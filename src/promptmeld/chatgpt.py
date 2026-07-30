from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from .clipboard import read_clipboard_text, write_clipboard_text
from .models import SubmissionResult

LOGGER = logging.getLogger(__name__)


class ChatGPTAutomationError(RuntimeError):
    pass


def _click_control_on_virtual_desktop(
    control,
    *,
    win32api_module=None,
) -> None:
    """Click a verified UIA rectangle without primary-screen normalization."""

    if win32api_module is None:
        import win32api as win32api_module

    rectangle = control.rectangle()
    left = int(rectangle.left)
    top = int(rectangle.top)
    right = int(rectangle.right)
    bottom = int(rectangle.bottom)
    if right <= left or bottom <= top:
        raise ChatGPTAutomationError(
            "The destination control has no clickable screen area."
        )

    target = (
        left + ((right - left) // 2),
        top + ((bottom - top) // 2),
    )
    virtual_left = win32api_module.GetSystemMetrics(76)
    virtual_top = win32api_module.GetSystemMetrics(77)
    virtual_right = (
        virtual_left + win32api_module.GetSystemMetrics(78)
    )
    virtual_bottom = (
        virtual_top + win32api_module.GetSystemMetrics(79)
    )
    if not (
        virtual_left <= target[0] < virtual_right
        and virtual_top <= target[1] < virtual_bottom
    ):
        raise ChatGPTAutomationError(
            "The destination control is outside the Windows virtual desktop."
        )
    monitor_from_point = getattr(
        win32api_module,
        "MonitorFromPoint",
        None,
    )
    if callable(monitor_from_point) and not monitor_from_point(target, 0):
        raise ChatGPTAutomationError(
            "The destination control is not located on an active monitor."
        )

    original = win32api_module.GetCursorPos()
    win32api_module.SetCursorPos(target)
    if win32api_module.GetCursorPos() != target:
        raise ChatGPTAutomationError(
            "Windows could not position the pointer over the destination control."
        )
    try:
        # With no MOVE flag, button events occur at the SetCursorPos location.
        # This avoids pywinauto's primary-screen absolute-coordinate conversion,
        # which clamps negative virtual-desktop coordinates to a screen edge.
        win32api_module.mouse_event(0x0002, 0, 0, 0, 0)
        try:
            win32api_module.mouse_event(0x0004, 0, 0, 0, 0)
        except Exception:
            # Do not leave the primary button held if its first release fails.
            win32api_module.mouse_event(0x0004, 0, 0, 0, 0)
            raise
    finally:
        if win32api_module.GetCursorPos() == target:
            win32api_module.SetCursorPos(original)


class ChatGPTDesktop:
    """Narrow adapter around ChatGPT's Windows accessibility surface."""

    MODE_SWITCH_PREFIX = "Switch mode, current mode:"
    CHATGPT_MODE_ITEM_PREFIX = "ChatGPT Create, learn, and explore"
    COMPOSER_NAMES = (
        "Do anything",
        "Message ChatGPT",
        "Message",
        "Ask anything",
        "Send a message",
        "Type a message",
    )
    COMPOSER_CLASSES = ("prosemirror",)
    CHAT_MODE_NAME = "Chat"
    PROJECT_NAME_AUTOMATION_ID = "chatgpt-project-name"
    PROJECT_INDEX_SEARCH_AUTOMATION_ID = "projects-index-search"

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        chatgpt_uri: str = "chatgpt:",
        project_uri: str = "",
        desktop_factory: Callable[..., object] | None = None,
        startfile: Callable[[str], None] = os.startfile,
        clipboard_writer: Callable[[str], None] = write_clipboard_text,
        clipboard_reader: Callable[[], str | None] = read_clipboard_text,
        send_keys: Callable[..., None] | None = None,
        mouse_clicker: Callable[[object], None] | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.chatgpt_uri = chatgpt_uri
        self.project_uri = project_uri
        self.desktop_factory = desktop_factory
        self.startfile = startfile
        self.clipboard_writer = clipboard_writer
        self.clipboard_reader = clipboard_reader
        self.send_keys = send_keys
        self.mouse_clicker = mouse_clicker
        self.progress_callback = progress_callback
        self.timings: list[dict[str, float | str]] = []

    def submit(
        self,
        prompt: str,
        project_name: str,
        *,
        auto_submit: bool = True,
    ) -> SubmissionResult:
        import pythoncom

        submission_started = time.perf_counter()
        self._ensure_automation_dependencies()
        previous_clipboard = self.clipboard_reader()
        pythoncom.CoInitialize()
        try:
            stage_started = time.perf_counter()
            self._report_progress(
                "locating-chatgpt",
                "Opening or focusing ChatGPT",
            )
            window = self._get_or_launch_window()
            window.set_focus()
            self._log_timing("find or launch ChatGPT", stage_started)

            stage_started = time.perf_counter()
            if not self._navigate_to_project_chat(window, project_name):
                return self._fallback(
                    prompt,
                    "ChatGPT opened, but the project controls are not exposed through "
                    "Windows accessibility. The prompt has been copied; open the "
                    f"'{project_name}' project, start a Chat, and paste it.",
                )
            self._log_timing("open project chat", stage_started)

            stage_started = time.perf_counter()
            self._report_progress(
                "finding-composer",
                "Finding the ChatGPT message box",
            )
            composer = self._find_composer(window)
            if composer is None:
                return self._fallback(
                    prompt,
                    "The ChatGPT composer could not be verified. The prompt has been "
                    "copied instead of typing into an unknown control.",
                )

            self._report_progress(
                "inserting-prompt",
                "Inserting the generated prompt",
            )
            input_method = self._set_composer_prompt(composer, prompt)
            if auto_submit:
                self._report_progress(
                    "finishing",
                    "Submitting the verified prompt",
                )
                composer.set_focus()
                self.send_keys("{ENTER}", pause=0.02)
            else:
                self._report_progress(
                    "finishing",
                    "Leaving the verified prompt ready for review",
                )
            if previous_clipboard is not None:
                if input_method == "clipboard":
                    time.sleep(0.08)
                self.clipboard_writer(previous_clipboard)
            self._log_timing("insert and submit", stage_started)
            if not auto_submit:
                LOGGER.info(
                    "Prepared writing prompt in ChatGPT project '%s'",
                    project_name,
                )
                return SubmissionResult(
                    submitted=False,
                    prepared=True,
                    message=(
                        f"Prompt inserted into the '{project_name}' project. "
                        "Choose the model or reasoning level in ChatGPT, then "
                        "press Enter to submit."
                    ),
                )
            LOGGER.info("Submitted writing prompt to ChatGPT project '%s'", project_name)
            return SubmissionResult(
                submitted=True,
                message=f"Submitted to the '{project_name}' project.",
            )
        except Exception as exc:
            LOGGER.exception("ChatGPT submission failed")
            return self._fallback(
                prompt,
                "ChatGPT automation failed. The complete prompt has been copied to "
                f"the clipboard. Details: {exc}",
            )
        finally:
            self._log_timing("total submission", submission_started)
            pythoncom.CoUninitialize()

    def _ensure_automation_dependencies(self) -> None:
        if self.desktop_factory is None:
            from pywinauto import Desktop

            self.desktop_factory = Desktop
        if self.send_keys is None:
            from pywinauto.keyboard import send_keys

            self.send_keys = send_keys

    def _get_or_launch_window(self):
        window = self._find_window()
        if window is not None:
            return window
        self.startfile(self.project_uri or self.chatgpt_uri)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            window = self._find_window()
            if window is not None:
                return window
            time.sleep(0.2)
        raise ChatGPTAutomationError(
            "The ChatGPT desktop window did not appear before the timeout."
        )

    def _find_window(self):
        desktop = self.desktop_factory(backend="uia")
        candidates = desktop.windows(
            title="ChatGPT",
            control_type="Window",
            visible_only=True,
            enabled_only=True,
        )
        return candidates[0] if candidates else None

    def _navigate_to_project_chat(self, window, project_name: str) -> bool:
        self._report_progress(
            "selecting-mode",
            "Switching from Codex to ChatGPT when needed",
        )
        if not self._select_chatgpt_mode(window):
            return False
        self._report_progress(
            "opening-project",
            f"Opening the '{project_name}' Project",
        )

        # Fast path: the sidebar often already exposes the exact project's
        # dedicated new-chat action. It is safe to use directly and avoids a
        # top-level New chat -> Chat round trip.
        project_action = self._find_project_new_chat_control(
            window,
            project_name,
        )
        if project_action is not None:
            LOGGER.info(
                "Using visible project new-chat fast path for '%s'",
                project_name,
            )
            return self._activate_project_new_chat(
                window,
                project_action,
                project_name,
            )

        if not self._open_chat_home(window):
            return False

        if self.project_uri:
            try:
                self.startfile(self.project_uri)
                time.sleep(0.8)
                window.set_focus()
            except OSError:
                LOGGER.exception("Configured project URI could not be opened")

        project_action, project = self._find_project_targets(
            window,
            project_name,
        )
        if project_action is None and project is None:
            self._expand_project_list(window)
            project_action = self._wait_for_control(
                window,
                lambda control: (
                    self._is_project_new_chat_control(
                        control,
                        project_name,
                    )
                    or self._is_project_control(
                        control,
                        project_name,
                    )
                ),
            )
            if (
                project_action is not None
                and not self._is_project_new_chat_control(
                    project_action,
                    project_name,
                )
            ):
                project = project_action
                project_action = None

        if project_action is not None:
            return self._activate_project_new_chat(
                window,
                project_action,
                project_name,
            )

        if project is None:
            if not self._create_project(window, project_name):
                return False
            if self._project_context_is_active(window, project_name):
                return True
            # Empty projects are hidden from the shortened sidebar until
            # Projects > Show more is activated. Return to Chat and locate the
            # exact project's own new-chat action rather than creating again.
            if not self._open_chat_home(window):
                return False
            self._expand_project_list(window)
            project_action = self._wait_for_control(
                window,
                lambda control: self._is_project_new_chat_control(
                    control,
                    project_name,
                ),
            )
            if project_action is not None:
                return self._activate_project_new_chat(
                    window,
                    project_action,
                    project_name,
                )
            project = self._find_project_control(window, project_name)
        if project is None:
            return False

        self._activate_control(project)
        return self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name)
        )

    def _select_chatgpt_mode(self, window) -> bool:
        switcher = self._find_control(
            window,
            lambda control: (
                control.element_info.control_type == "Button"
                and (control.element_info.name or "").startswith(
                    self.MODE_SWITCH_PREFIX
                )
            ),
        )
        if switcher is None:
            return False
        if switcher.element_info.name.endswith("ChatGPT"):
            return True

        self._activate_control(switcher)
        mode_item = self._wait_for_control(
            window,
            lambda control: (
                control.element_info.control_type == "MenuItem"
                and (control.element_info.name or "").startswith(
                    self.CHATGPT_MODE_ITEM_PREFIX
                )
            ),
        )
        if mode_item is None:
            return False
        self._activate_control(mode_item)
        return self._wait_for_condition(
            lambda: bool(
                (
                    current := self._find_control(
                        window,
                        lambda control: (
                            control.element_info.control_type == "Button"
                            and (
                                control.element_info.name or ""
                            ).startswith(self.MODE_SWITCH_PREFIX)
                        ),
                    )
                )
                and current.element_info.name.endswith("ChatGPT")
            )
        )

    def _open_chat_home(self, window) -> bool:
        # The global mode switch can leave an existing Codex page visible.
        # Starting a top-level new chat exposes the Chat/Work toggle; choosing
        # Chat then gives us the ChatGPT Projects view.
        new_chat = self._find_control(
            window,
            self._is_top_new_chat_control,
        )
        if new_chat is not None:
            self._activate_control(new_chat)

        chat = self._wait_for_control(
            window,
            self._is_chat_mode_control,
        )
        if chat is None:
            return False
        self._activate_control(chat)
        return self._wait_for_condition(
            lambda: bool(
                (
                    current := self._find_control(
                        window,
                        self._is_chat_mode_control,
                    )
                )
                and "text-token-text-primary"
                in (current.element_info.class_name or "")
                and self._find_chat_composer(window) is not None
            )
        )

    @staticmethod
    def _is_top_new_chat_control(control) -> bool:
        info = control.element_info
        class_tokens = (info.class_name or "").split()
        return (
            info.control_type == "Button"
            and (info.name or "") == "New chat"
            and bool(class_tokens)
            and class_tokens[0] == "sidebar-item"
        )

    def _is_chat_mode_control(self, control) -> bool:
        info = control.element_info
        class_name = info.class_name or ""
        return (
            info.control_type == "Button"
            and (info.name or "") == self.CHAT_MODE_NAME
            and "text-token-text-" in class_name
        )

    def _find_project_control(self, window, project_name: str):
        return self._find_control(
            window,
            lambda control: self._is_project_control(
                control,
                project_name,
            ),
        )

    def _find_project_new_chat_control(
        self,
        window,
        project_name: str,
    ):
        return self._find_control(
            window,
            lambda control: self._is_project_new_chat_control(
                control,
                project_name,
            ),
        )

    def _find_project_targets(self, window, project_name: str):
        controls = self._descendants(window)
        if controls is None:
            return None, None
        project_action = next(
            (
                control
                for control in controls
                if self._is_project_new_chat_control(
                    control,
                    project_name,
                )
            ),
            None,
        )
        project = next(
            (
                control
                for control in controls
                if self._is_project_control(control, project_name)
            ),
            None,
        )
        return project_action, project

    @staticmethod
    def _is_project_new_chat_control(
        control,
        project_name: str,
    ) -> bool:
        name = (control.element_info.name or "").strip()
        return (
            control.element_info.control_type == "Button"
            and name
            in {
                f"New chat in {project_name}",
                f"Start new chat in {project_name}",
            }
        )

    def _activate_project_new_chat(
        self,
        window,
        control,
        project_name: str,
    ) -> bool:
        self._activate_control(control)
        return self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name)
        )

    @staticmethod
    def _is_project_control(control, project_name: str) -> bool:
        info = control.element_info
        class_name = info.class_name or ""
        is_project_row = "folder-row" in class_name
        is_project_card = "w-full shrink-0" in class_name
        return (
            info.control_type == "Button"
            and (info.name or "").strip() == project_name
            and "cursor-grab" not in class_name
            and (
                is_project_row
                or is_project_card
                or "sidebar-item" not in class_name
            )
        )

    def _expand_project_list(self, window) -> bool:
        show_more = self._find_projects_show_more(window)
        if show_more is None:
            return False
        self._activate_control(show_more)
        return True

    def _find_projects_show_more(self, window):
        controls = self._descendants(window)
        if controls is None:
            return None
        projects = next(
            (
                control
                for control in controls
                if control.element_info.control_type == "Button"
                and (control.element_info.name or "") == "Projects"
            ),
            None,
        )
        candidates = [
            control
            for control in controls
            if control.element_info.control_type == "Button"
            and (control.element_info.name or "") == "Show more"
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if projects is None:
            return None

        try:
            project_rect = projects.rectangle()
            below_projects = [
                control
                for control in candidates
                if (
                    (rect := control.rectangle()).left
                    >= project_rect.left
                    and rect.right <= project_rect.right
                    and rect.top > project_rect.bottom
                )
            ]
        except Exception:
            return None
        return (
            min(
                below_projects,
                key=lambda control: control.rectangle().top,
            )
            if below_projects
            else None
        )

    def _create_project(self, window, project_name: str) -> bool:
        add_project = self._find_control(
            window,
            lambda control: (
                control.element_info.control_type == "Button"
                and (control.element_info.name or "") == "Add new project"
            ),
        )
        if add_project is None:
            return False
        self._activate_control(add_project)

        name_edit = self._wait_for_control(
            window,
            lambda control: (
                self._is_project_name_control(control)
                or self._is_project_index_search(control)
            ),
        )
        if (
            name_edit is not None
            and self._is_project_index_search(name_edit)
        ):
            # Some desktop builds use the first activation to open the
            # Projects index. Activating Add new project again from that index
            # opens the naming dialog.
            add_project = self._find_control(
                window,
                lambda control: (
                    control.element_info.control_type == "Button"
                    and (control.element_info.name or "")
                    == "Add new project"
                ),
            )
            if add_project is None:
                return False
            self._activate_control(add_project)
            name_edit = self._wait_for_control(
                window,
                self._is_project_name_control,
            )
        if name_edit is None:
            return False
        self.clipboard_writer(project_name)
        name_edit.set_focus()
        self.send_keys("^a", pause=0.02)
        self.send_keys("^v", pause=0.02)

        create = self._wait_for_control(
            window,
            lambda control: (
                control.element_info.control_type == "Button"
                and (control.element_info.name or "") == "Create project"
                and bool(getattr(control.element_info, "enabled", True))
            ),
        )
        if create is None:
            return False
        self._activate_control(create)
        return self._wait_for_condition(
            lambda: (
                self._project_context_is_active(window, project_name)
                or self._find_project_control(window, project_name)
                is not None
                or self._find_control(
                    window,
                    self._is_project_name_control,
                )
                is None
            )
        )

    def _is_project_name_control(self, control) -> bool:
        info = control.element_info
        return (
            info.control_type == "Edit"
            and (
                (getattr(info, "automation_id", "") or "")
                == self.PROJECT_NAME_AUTOMATION_ID
                or (info.name or "").strip() == "Project name"
            )
        )

    def _is_project_index_search(self, control) -> bool:
        info = control.element_info
        return (
            info.control_type == "Edit"
            and (getattr(info, "automation_id", "") or "")
            == self.PROJECT_INDEX_SEARCH_AUTOMATION_ID
        )

    def _project_context_is_active(
        self,
        window,
        project_name: str,
    ) -> bool:
        expected = f"Change project: {project_name}"
        return (
            self._find_control(
                window,
                lambda control: (
                    control.element_info.control_type == "Button"
                    and (control.element_info.name or "").strip()
                    == expected
                ),
            )
            is not None
        )

    def _project_chat_is_ready(self, window, project_name: str) -> bool:
        controls = self._descendants(window)
        if controls is None:
            return False
        expected = f"Change project: {project_name}"
        project_is_active = any(
            control.element_info.control_type == "Button"
            and (control.element_info.name or "").strip() == expected
            for control in controls
        )
        if not project_is_active:
            return False
        return (
            self._find_named_control_in(
                controls,
                names=self.COMPOSER_NAMES,
                control_types=("Edit", "Document"),
            )
            is not None
        )

    def _find_composer(self, window):
        controls = self._descendants(window)
        if controls is None:
            return None
        named = self._find_named_control_in(
            controls,
            names=self.COMPOSER_NAMES,
            control_types=("Edit", "Document"),
        )
        if named is not None:
            return named

        # The current ChatGPT desktop app exposes its contenteditable message
        # composer as an Edit control with class "ProseMirror". Keep this
        # fallback deliberately narrow so search boxes and other edits are never
        # treated as the message composer.
        for control in controls:
            info = control.element_info
            if (
                info.control_type == "Edit"
                and (info.class_name or "").strip().casefold()
                in self.COMPOSER_CLASSES
                and bool(getattr(info, "enabled", True))
                and bool(getattr(info, "visible", True))
            ):
                return control
        return None

    def _find_chat_composer(self, window):
        controls = self._descendants(window)
        if controls is None:
            return None
        return self._find_named_control_in(
            controls,
            names=self.COMPOSER_NAMES,
            control_types=("Edit", "Document"),
        )

    def _set_composer_prompt(self, composer, prompt: str) -> str:
        """Insert and verify a prompt without trusting a blind global paste."""

        for method_name in ("set_edit_text", "set_text"):
            set_text = getattr(composer, method_name, None)
            if not callable(set_text):
                continue
            try:
                set_text(prompt)
                self._report_progress(
                    "inserting-prompt",
                    "Verifying the complete prompt in ChatGPT",
                )
                if self._wait_for_composer_prompt(composer, prompt):
                    LOGGER.info(
                        "Inserted prompt through ChatGPT composer UI Automation"
                    )
                    return "uia"
            except Exception:
                LOGGER.debug(
                    "ChatGPT composer UIA text input was unavailable",
                    exc_info=True,
                )
            break

        self.clipboard_writer(prompt)
        type_keys = getattr(composer, "type_keys", None)
        if callable(type_keys):
            try:
                type_keys(
                    "^a^v",
                    pause=0.02,
                    set_foreground=True,
                )
                self._report_progress(
                    "inserting-prompt",
                    "Verifying the complete prompt in ChatGPT",
                )
                if self._wait_for_composer_prompt(composer, prompt):
                    LOGGER.info(
                        "Pasted prompt through the targeted ChatGPT composer"
                    )
                    return "clipboard"
            except Exception:
                LOGGER.debug(
                    "Targeted ChatGPT composer paste was unavailable",
                    exc_info=True,
                )

        try:
            composer.set_focus()
            self.send_keys("^a", pause=0.02)
            self.send_keys("^v", pause=0.02)
            self._report_progress(
                "inserting-prompt",
                "Verifying the complete prompt in ChatGPT",
            )
            if self._wait_for_composer_prompt(composer, prompt):
                LOGGER.info(
                    "Pasted and verified prompt through focused keyboard input"
                )
                return "clipboard"
        except Exception:
            LOGGER.debug(
                "Focused ChatGPT composer paste was unavailable",
                exc_info=True,
            )

        raise ChatGPTAutomationError(
            "The verified ChatGPT composer did not accept the generated prompt."
        )

    def _wait_for_composer_prompt(
        self,
        composer,
        prompt: str,
    ) -> bool:
        deadline = time.monotonic() + min(self.timeout_seconds, 2.0)
        while time.monotonic() < deadline:
            value = self._read_composer_text(composer)
            if (
                value is not None
                and self._normalise_composer_text(value)
                == self._normalise_composer_text(prompt)
            ):
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def _read_composer_text(composer) -> str | None:
        for method_name in ("get_value", "window_text", "text_block"):
            read_text = getattr(composer, method_name, None)
            if not callable(read_text):
                continue
            try:
                value = read_text()
            except Exception:
                continue
            if isinstance(value, str):
                return value
        return None

    @staticmethod
    def _normalise_composer_text(value: str) -> str:
        return (
            value.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u2028", "\n")
            .replace("\u2029", "\n")
            .rstrip("\n")
        )

    @staticmethod
    def _descendants(window):
        try:
            return window.descendants()
        except Exception:
            return None

    @classmethod
    def _find_control(cls, window, predicate):
        controls = cls._descendants(window)
        if controls is None:
            return None
        return next(
            (control for control in controls if predicate(control)),
            None,
        )

    def _wait_for_control(self, window, predicate):
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            control = self._find_control(window, predicate)
            if control is not None:
                return control
            time.sleep(0.1)
        return None

    def _wait_for_condition(self, predicate) -> bool:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.1)
        return False

    @classmethod
    def _find_named_control(cls, window, names, control_types):
        controls = cls._descendants(window)
        if controls is None:
            return None
        return cls._find_named_control_in(
            controls,
            names,
            control_types,
        )

    @staticmethod
    def _find_named_control_in(controls, names, control_types):
        folded = {name.casefold() for name in names}
        exact = None
        partial = None
        for control in controls:
            info = control.element_info
            name = (info.name or "").strip()
            if info.control_type not in control_types or not name:
                continue
            lowered = name.casefold()
            if lowered in folded:
                exact = control
                break
            if any(candidate in lowered for candidate in folded):
                partial = partial or control
        return exact or partial

    def _activate_control(self, control) -> None:
        """Activate a UIA control, keeping physical input as the last resort."""

        name = getattr(control.element_info, "name", "")
        invoke = getattr(control, "invoke", None)
        if callable(invoke):
            try:
                invoke()
                return
            except Exception:
                LOGGER.debug(
                    "UIA Invoke unavailable for control '%s'",
                    name,
                    exc_info=True,
                )

        # UIA ButtonWrapper.click() is not a physical click: it tries the
        # Invoke pattern and then SelectionItem. Other UIA wrappers expose
        # select() directly, so retain that as a separate fallback.
        pattern_click = getattr(control, "click", None)
        if callable(pattern_click):
            try:
                pattern_click()
                return
            except Exception:
                LOGGER.debug(
                    "UIA pattern click unavailable for control '%s'",
                    name,
                    exc_info=True,
                )

        select = getattr(control, "select", None)
        if callable(select):
            try:
                select()
                return
            except Exception:
                LOGGER.debug(
                    "UIA SelectionItem unavailable for control '%s'",
                    name,
                    exc_info=True,
                )

        set_focus = getattr(control, "set_focus", None)
        if callable(set_focus):
            try:
                set_focus()
                if self.send_keys is None:
                    self._ensure_automation_dependencies()
                self.send_keys("{ENTER}", pause=0.02)
                return
            except Exception:
                LOGGER.debug(
                    "Keyboard activation unavailable for control '%s'",
                    name,
                    exc_info=True,
                )

        LOGGER.warning(
            "Using physical-click fallback for control '%s'",
            name,
        )
        (self.mouse_clicker or _click_control_on_virtual_desktop)(control)

    def _log_timing(self, stage: str, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.timings.append(
            {
                "stage": stage,
                "milliseconds": round(elapsed_ms, 1),
            }
        )
        LOGGER.info(
            "ChatGPT automation timing - %s: %.0f ms",
            stage,
            elapsed_ms,
        )

    def _report_progress(self, stage: str, message: str) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(stage, message)
        except Exception:
            LOGGER.debug(
                "Automation progress callback failed",
                exc_info=True,
            )

    def _fallback(self, prompt: str, message: str) -> SubmissionResult:
        self.clipboard_writer(prompt)
        LOGGER.warning(message)
        return SubmissionResult(
            submitted=False,
            prepared=False,
            fallback_copied=True,
            message=message,
        )
