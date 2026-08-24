from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import replace

from .automation_protocol import (
    AutomationCheckpoint,
    SubmissionDisposition,
    checkpoint_for_stage,
    disposition_for_checkpoint,
    recovery_actions_for,
)
from .chatgpt_selectors import (
    CHATGPT_MODE,
    CHAT_HOME,
    CHAT_MODE_TAB,
    COMPOSER,
    GENERATION_STOP,
    MODE_SWITCH,
    PROJECT_NEW_CHAT,
    PROJECT_ADD,
    PROJECT_CREATE,
    PROJECT_DESTINATION,
    PROJECT_INDEX_SEARCH,
    PROJECT_NAME,
    PROJECT_ROW,
    PROJECT_SHOW_MORE,
    PROJECT_STORAGE,
    PROJECT_TYPE_NEXT,
    PROJECTS_SECTION,
    RESPONSE_COPY,
    SEND,
    TEMPORARY_CHAT,
    TEMPORARY_CHAT_DIALOG,
    USER_MESSAGE_COPY,
)
from .clipboard import ClipboardSnapshot, read_clipboard_text, write_clipboard_text
from .models import (
    DEFAULT_CHATGPT_URI,
    ResponseAnchor,
    SubmissionResult,
    normalize_chatgpt_uri,
)
from .privacy import restore_placeholders

LOGGER = logging.getLogger(__name__)
DEFAULT_RESPONSE_TIMEOUT_SECONDS = 300.0
DEFAULT_CHATGPT_LAUNCH_TIMEOUT_SECONDS = 60.0


def _foreground_window_handle() -> int | None:
    try:
        import win32gui

        handle = int(win32gui.GetForegroundWindow())
        return handle or None
    except Exception:
        LOGGER.debug("Could not read the foreground window", exc_info=True)
        return None


def _restore_foreground_window(handle: int) -> bool:
    """Restore a previously focused native window when it still exists."""

    try:
        import win32gui

        if not handle or not win32gui.IsWindow(handle):
            return False
        win32gui.SetForegroundWindow(handle)
        return int(win32gui.GetForegroundWindow()) == int(handle)
    except Exception:
        LOGGER.debug(
            "Could not restore the previous foreground window",
            exc_info=True,
        )
        return False


def _clipboard_sequence_number() -> int | None:
    try:
        import win32clipboard

        return int(win32clipboard.GetClipboardSequenceNumber())
    except Exception:
        LOGGER.debug("Could not read the clipboard sequence number", exc_info=True)
        return None


class ChatGPTAutomationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "automation_failed",
        retry_mode: str = "delivery",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_mode = retry_mode


class ChatGPTAutomationCancelled(RuntimeError):
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

    MODE_SWITCH_PREFIX = MODE_SWITCH.names[0]
    CHATGPT_MODE_ITEM_PREFIX = CHATGPT_MODE.names[0]
    COMPOSER_NAMES = COMPOSER.names
    COMPOSER_CLASSES = COMPOSER.class_names
    SEND_BUTTON_NAMES = SEND.names
    CHAT_MODE_NAME = CHAT_MODE_TAB.names[0]
    TEMPORARY_CHAT_ON_NAME = TEMPORARY_CHAT.names[0]
    TEMPORARY_CHAT_OFF_NAME = TEMPORARY_CHAT.names[1]
    TEMPORARY_CHAT_DIALOG_NAME = TEMPORARY_CHAT_DIALOG.names[0]
    TEMPORARY_CHAT_CONFIRMATION_SECONDS = 60.0
    RESPONSE_COPY_NAMES = frozenset(name.casefold() for name in RESPONSE_COPY.names)
    USER_MESSAGE_COPY_NAMES = frozenset(
        name.casefold() for name in USER_MESSAGE_COPY.names
    )
    GENERATION_STOP_NAMES = frozenset(
        name.casefold() for name in GENERATION_STOP.names
    )
    PROJECT_NAME_AUTOMATION_ID = PROJECT_NAME.automation_ids[0]
    PROJECT_NAME_CONTROL_NAME = PROJECT_NAME.names[0]
    PROJECT_INDEX_SEARCH_AUTOMATION_ID = PROJECT_INDEX_SEARCH.automation_ids[0]
    PROJECTS_SECTION_NAME = PROJECTS_SECTION.names[0]
    PROJECT_SHOW_MORE_NAME = PROJECT_SHOW_MORE.names[0]
    PROJECT_ADD_NAME = PROJECT_ADD.names[0]
    PROJECT_CREATE_NAME = PROJECT_CREATE.names[0]
    PROJECT_STORAGE_CHOICES = frozenset(
        name.casefold() for name in PROJECT_STORAGE.names
    )
    PROJECT_TYPE_NEXT_NAME = PROJECT_TYPE_NEXT.names[0]
    PROJECT_CHANGE_PREFIX = PROJECT_DESTINATION.names[0]
    PROJECT_NEW_CHAT_PREFIX = PROJECT_DESTINATION.names[1]
    PROJECT_START_CHAT_PREFIX = PROJECT_DESTINATION.names[2]

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        launch_timeout_seconds: float = DEFAULT_CHATGPT_LAUNCH_TIMEOUT_SECONDS,
        chatgpt_uri: str = DEFAULT_CHATGPT_URI,
        project_uri: str = "",
        desktop_factory: Callable[..., object] | None = None,
        startfile: Callable[[str], None] = os.startfile,
        clipboard_writer: Callable[[str], None] = write_clipboard_text,
        clipboard_reader: Callable[[], str | None] = read_clipboard_text,
        clipboard_snapshot_factory: Callable[[], ClipboardSnapshot] = (
            ClipboardSnapshot.capture
        ),
        send_keys: Callable[..., None] | None = None,
        mouse_clicker: Callable[[object], None] | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
        response_timeout_seconds: float | None = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
        foreground_window_reader: Callable[[], int | None] | None = None,
        process_path_reader: Callable[[int], str | None] | None = None,
        clipboard_sequence_reader: Callable[[], int | None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        activity_callback: Callable[[], None] | None = None,
        response_callback: (
            Callable[[str, ResponseAnchor | None], None] | None
        ) = None,
        run_id: str = "",
    ):
        self.timeout_seconds = timeout_seconds
        self.launch_timeout_seconds = max(
            self.timeout_seconds,
            float(launch_timeout_seconds),
        )
        self.chatgpt_uri = normalize_chatgpt_uri(chatgpt_uri)
        self.project_uri = project_uri
        self.desktop_factory = desktop_factory
        self.startfile = startfile
        self.clipboard_writer = clipboard_writer
        self.clipboard_reader = clipboard_reader
        self.clipboard_snapshot_factory = clipboard_snapshot_factory
        self.send_keys = send_keys
        self.mouse_clicker = mouse_clicker
        self.progress_callback = progress_callback
        self.response_timeout_seconds = (
            None
            if response_timeout_seconds is None
            else max(0.01, float(response_timeout_seconds))
        )
        self.foreground_window_reader = (
            foreground_window_reader or _foreground_window_handle
        )
        self.process_path_reader = process_path_reader or self._process_path
        self.clipboard_sequence_reader = (
            clipboard_sequence_reader or _clipboard_sequence_number
        )
        self.enforce_clipboard_sequence = bool(
            clipboard_sequence_reader is None
            and clipboard_writer is write_clipboard_text
            and clipboard_reader is read_clipboard_text
        )
        self.is_cancelled = is_cancelled
        self.activity_callback = activity_callback
        self.response_callback = response_callback
        self.clipboard_owned_sequence: int | None = None
        self.clipboard_write_owned = False
        self.run_id = run_id or str(uuid.uuid4())
        self.timings: list[dict[str, float | str]] = []
        self.navigation_failure: str | None = None
        self.navigation_failure_code = ""
        self.navigation_retry_mode = "delivery"
        self.project_step = ""
        self.project_step_started_at: float | None = None
        self.project_step_attempts: dict[str, int] = {}
        self.current_stage = "preparing"
        self.checkpoint = AutomationCheckpoint.PREPARING
        self.submission_disposition = SubmissionDisposition.NOT_ATTEMPTED
        self.send_started = False
        self.submission_confirmed = False
        self.response_baseline: tuple[str, ...] = ()
        self.response_anchor: ResponseAnchor | None = None
        self.selector_ids: set[str] = set()
        self.chatgpt_hwnd = 0
        self.stage_started_at = time.perf_counter()
        self.stage_attempts: dict[str, int] = {}

    def _mark_selector(self, identifier: str) -> None:
        if identifier:
            self.selector_ids.add(identifier)

    def _retain_captured_response(self, value: str) -> None:
        """Cross a verified response into the main process immediately."""

        if self.response_callback is not None:
            self.response_callback(value, self.response_anchor)

    def _pulse(self) -> None:
        if self.activity_callback is not None:
            self.activity_callback()

    def _check_cancelled(self) -> None:
        self._pulse()
        if self.is_cancelled is None or not self.is_cancelled():
            return
        # Once Send has started, finish the short confirmation probe so the
        # caller can distinguish confirmed submission from an ambiguous one.
        if self.send_started and not self.submission_confirmed:
            return
        raise ChatGPTAutomationCancelled("Automation cancelled by the user.")

    def _sleep(self, seconds: float, *, honour_cancel: bool = True) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if honour_cancel:
                self._check_cancelled()
            else:
                self._pulse()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def submit(
        self,
        prompt: str,
        project_name: str,
        *,
        auto_submit: bool = True,
        temporary_chat: bool = False,
        copy_generated_text: bool = False,
        capture_generated_text: bool = False,
        redaction_replacements: dict[str, str] | None = None,
    ) -> SubmissionResult:
        import pythoncom

        submission_started = time.perf_counter()
        self.navigation_failure = None
        self.navigation_failure_code = ""
        self.navigation_retry_mode = "delivery"
        self.project_step = ""
        self.project_step_started_at = None
        self.project_step_attempts.clear()
        self.checkpoint = AutomationCheckpoint.PREPARING
        self.submission_disposition = SubmissionDisposition.NOT_ATTEMPTED
        self.send_started = False
        self.submission_confirmed = False
        self.response_anchor = None
        self.selector_ids.clear()
        self.chatgpt_hwnd = 0
        self.clipboard_owned_sequence = None
        self._ensure_automation_dependencies()
        previous_clipboard: str | None = None
        previous_clipboard_snapshot: ClipboardSnapshot | None = None
        input_method = ""
        pythoncom.CoInitialize()
        try:
            stage_started = time.perf_counter()
            self._report_progress(
                "locating-chatgpt",
                "Opening or focusing ChatGPT",
            )
            self._check_cancelled()
            window = self._get_or_launch_window()
            self.chatgpt_hwnd = self._native_window_handle(window) or 0
            window.set_focus()
            self._log_timing("find or launch ChatGPT", stage_started)

            stage_started = time.perf_counter()
            navigated = (
                self._navigate_to_temporary_chat(window)
                if temporary_chat
                else self._navigate_to_project_chat(window, project_name)
            )
            if not navigated:
                failed_operation = (
                    self.navigation_failure
                    or (
                        "turn on Temporary Chat"
                        if temporary_chat
                        else "open the requested ChatGPT Project"
                    )
                )
                recovery = (
                    "Review any Temporary Chat explanation in ChatGPT, turn "
                    "Temporary Chat on, and paste the copied prompt."
                    if temporary_chat
                    else (
                        f"Open the '{project_name}' Project, start a Chat, "
                        "and paste the copied prompt."
                    )
                )
                return self._fallback(
                    prompt,
                    f"ChatGPT opened, but PromptMeld could not {failed_operation}. "
                    f"The prompt has been copied. {recovery}",
                    failure_code=(
                        self.navigation_failure_code or "navigation_failed"
                    ),
                    retry_mode=self.navigation_retry_mode,
                )
            self._log_timing(
                (
                    "open temporary chat"
                    if temporary_chat
                    else "open project chat"
                ),
                stage_started,
            )
            window = self._refresh_chatgpt_window() or window
            self._report_progress(
                "destination-verified",
                "Verified the requested ChatGPT destination",
            )

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
                    failure_code="composer_unavailable",
                )
            self._mark_selector(COMPOSER.identifier)
            self._report_progress(
                "composer-verified",
                "Verified the ChatGPT message box",
            )

            self._report_progress(
                "inserting-prompt",
                "Inserting the generated prompt",
            )
            # Capture immediately before the temporary prompt clipboard write;
            # navigation may have taken long enough for an earlier value to be
            # stale.
            (
                previous_clipboard,
                previous_clipboard_snapshot,
            ) = self._capture_clipboard_state()
            input_method = self._set_composer_prompt(
                composer,
                prompt,
                window=window,
                project_name=project_name,
                temporary_chat=temporary_chat,
            )
            window = self._refresh_chatgpt_window() or window
            if not self._destination_is_ready_in(
                window,
                project_name,
                temporary_chat=temporary_chat,
            ):
                raise ChatGPTAutomationError(
                    "The ChatGPT destination changed while inserting the prompt."
                )
            if auto_submit:
                self._report_progress(
                    "finishing",
                    "Submitting the verified prompt",
                )
                self.response_anchor = self._build_response_anchor(window, prompt)
                self.response_baseline = self.response_anchor.baseline_tokens
                composer = self._find_composer(window) or composer
                self._check_cancelled()
                self._report_progress(
                    "send-started",
                    "Activating ChatGPT's verified Send control",
                )
                self.send_started = True
                self._submit_verified_prompt(window, composer)
                if not self._confirm_submission(
                    window,
                    composer,
                    prompt,
                    self.response_baseline,
                ):
                    return self._fallback(
                        prompt,
                        "PromptMeld activated ChatGPT's submit control but could "
                        "not prove that this prompt was accepted. Inspect ChatGPT "
                        "before trying again to avoid a duplicate submission.",
                        failure_code="submission_unconfirmed",
                        retry_mode="inspect",
                    )
                self.submission_confirmed = True
                self.response_anchor = self._anchor_submitted_message(
                    self._refresh_chatgpt_window() or window,
                    self.response_anchor,
                )
                self._report_progress(
                    "submitted",
                    "ChatGPT accepted the verified prompt",
                )
                self._check_cancelled()
            else:
                self._report_progress(
                    "finishing",
                    "Leaving the verified prompt ready for review",
                )
            if (
                previous_clipboard is not None
                or previous_clipboard_snapshot is not None
            ):
                if input_method == "clipboard":
                    self._sleep(0.08)
                self._restore_clipboard_if_unchanged(
                    previous_clipboard,
                    snapshot=previous_clipboard_snapshot,
                    expected=(prompt if input_method == "clipboard" else previous_clipboard),
                )
                previous_clipboard_snapshot = None
                previous_clipboard = None
            self._log_timing("insert and submit", stage_started)
            if not auto_submit:
                destination = (
                    "Temporary Chat"
                    if temporary_chat
                    else f"the '{project_name}' project"
                )
                LOGGER.info(
                    "Prepared writing prompt in ChatGPT %s",
                    destination,
                )
                return SubmissionResult(
                    submitted=False,
                    prepared=True,
                    message=(
                        f"Prompt inserted into {destination}. "
                        "Choose the model or reasoning level in ChatGPT, then "
                        "press Enter to submit."
                    ),
                    run_id=self.run_id,
                    checkpoint=AutomationCheckpoint.COMPOSER_VERIFIED,
                    submission_disposition=SubmissionDisposition.NOT_ATTEMPTED,
                )

            generated_text = None
            generated_text_copied = False
            wants_generated_text = capture_generated_text or copy_generated_text
            if wants_generated_text:
                self._report_progress(
                    "waiting-for-response",
                    "Waiting for ChatGPT to finish the response. You can "
                    "continue working in another window.",
                )
                response_clipboard: str | None = None
                response_clipboard_snapshot: ClipboardSnapshot | None = None
                try:
                    (
                        response_clipboard,
                        response_clipboard_snapshot,
                    ) = self._capture_clipboard_state()
                    generated_text = self._copy_latest_response(
                        window,
                        prompt,
                        anchor=self.response_anchor,
                    )
                    generated_text = restore_placeholders(
                        generated_text,
                        redaction_replacements or {},
                    )
                    self._retain_captured_response(generated_text)
                    self._report_progress(
                        "response-captured",
                        "Captured the response that belongs to this request",
                    )
                    if not copy_generated_text:
                        self._restore_clipboard_if_unchanged(
                            response_clipboard,
                            snapshot=response_clipboard_snapshot,
                            expected=generated_text,
                        )
                        response_clipboard_snapshot = None
                except ChatGPTAutomationCancelled:
                    self._restore_clipboard_if_unchanged(
                        response_clipboard,
                        snapshot=response_clipboard_snapshot,
                    )
                    response_clipboard_snapshot = None
                    raise
                except Exception as exc:
                    LOGGER.exception("ChatGPT response could not be retrieved")
                    self._restore_clipboard_if_unchanged(
                        response_clipboard,
                        snapshot=response_clipboard_snapshot,
                    )
                    response_clipboard_snapshot = None
                    return SubmissionResult(
                        submitted=True,
                        output_failed=True,
                        message=(
                            "The prompt was submitted, but ChatGPT did not expose "
                            "a complete generated response that PromptMeld could "
                            "verify. The original text was not replaced. "
                            f"Details: {exc}"
                        ),
                        run_id=self.run_id,
                        failed_stage="waiting-for-response",
                        failure_code=getattr(
                            exc,
                            "code",
                            "response_unavailable",
                        ),
                        submission_confirmed=True,
                        retry_mode=getattr(exc, "retry_mode", "response"),
                        recoverable=True,
                        response_baseline=self.response_baseline,
                        checkpoint=AutomationCheckpoint.SUBMISSION_CONFIRMED,
                        submission_disposition=SubmissionDisposition.CONFIRMED,
                        recovery_actions=recovery_actions_for(
                            SubmissionDisposition.CONFIRMED
                        ),
                        response_anchor=self.response_anchor,
                    )

                if copy_generated_text:
                    self._discard_clipboard_snapshot(
                        response_clipboard_snapshot
                    )
                    response_clipboard_snapshot = None
                    self._write_clipboard(generated_text)
                    generated_text_copied = True

            if temporary_chat:
                LOGGER.info("Submitted writing prompt to ChatGPT Temporary Chat")
                destination_message = "Submitted to Temporary Chat."
            else:
                LOGGER.info(
                    "Submitted writing prompt to the verified ChatGPT Project"
                )
                destination_message = (
                    f"Submitted to the '{project_name}' project."
                )
            return SubmissionResult(
                submitted=True,
                generated_text_copied=generated_text_copied,
                generated_text=generated_text or "",
                message=(
                    destination_message
                    + (
                        " The generated text is on the clipboard."
                        if generated_text_copied
                        else ""
                    )
                ),
                run_id=self.run_id,
                submission_confirmed=True,
                response_baseline=self.response_baseline,
                checkpoint=(
                    AutomationCheckpoint.RESPONSE_CAPTURED
                    if generated_text
                    else AutomationCheckpoint.SUBMISSION_CONFIRMED
                ),
                submission_disposition=SubmissionDisposition.CONFIRMED,
                recovery_actions=recovery_actions_for(
                    SubmissionDisposition.CONFIRMED,
                    has_result=bool(generated_text),
                ),
                response_anchor=self.response_anchor,
            )
        except ChatGPTAutomationCancelled:
            if (
                previous_clipboard is not None
                or previous_clipboard_snapshot is not None
            ):
                self._restore_clipboard_if_unchanged(
                    previous_clipboard,
                    snapshot=previous_clipboard_snapshot,
                )
                previous_clipboard_snapshot = None
                previous_clipboard = None
            disposition = (
                SubmissionDisposition.CONFIRMED
                if self.submission_confirmed
                else (
                    SubmissionDisposition.MAYBE_SUBMITTED
                    if self.send_started
                    else SubmissionDisposition.NOT_ATTEMPTED
                )
            )
            checkpoint = (
                AutomationCheckpoint.SUBMISSION_CONFIRMED
                if self.submission_confirmed
                else (
                    AutomationCheckpoint.SEND_STARTED
                    if self.send_started
                    else self.checkpoint
                )
            )
            self._report_progress(
                "cancelled",
                "Stopped at the last safely acknowledged checkpoint",
            )
            return SubmissionResult(
                submitted=self.submission_confirmed,
                cancelled=True,
                message=(
                    "Automation stopped after ChatGPT accepted the request; "
                    "ChatGPT may continue generating."
                    if self.submission_confirmed
                    else "Automation stopped before submission was confirmed."
                ),
                run_id=self.run_id,
                failed_stage=self.current_stage,
                failure_code="cancelled",
                submission_confirmed=self.submission_confirmed,
                retry_mode="response" if self.submission_confirmed else "",
                recoverable=self.submission_confirmed,
                response_baseline=self.response_baseline,
                checkpoint=checkpoint,
                submission_disposition=disposition,
                recovery_actions=recovery_actions_for(disposition),
                response_anchor=self.response_anchor,
            )
        except Exception as exc:
            LOGGER.exception("ChatGPT submission failed")
            failure_code = getattr(exc, "code", "automation_failed")
            retry_mode = getattr(exc, "retry_mode", "delivery")
            if (
                previous_clipboard is not None
                or previous_clipboard_snapshot is not None
            ):
                self._restore_clipboard_if_unchanged(
                    previous_clipboard,
                    snapshot=previous_clipboard_snapshot,
                )
                previous_clipboard_snapshot = None
                previous_clipboard = None
            if self.send_started:
                disposition = (
                    SubmissionDisposition.CONFIRMED
                    if self.submission_confirmed
                    else SubmissionDisposition.MAYBE_SUBMITTED
                )
                return SubmissionResult(
                    submitted=self.submission_confirmed,
                    output_failed=self.submission_confirmed,
                    message=(
                        "The prompt was submitted, but response handling stopped. "
                        "Retry response retrieval; PromptMeld will not send it again."
                        if self.submission_confirmed
                        else (
                            "PromptMeld activated Send but could not prove the outcome. "
                            "Inspect ChatGPT before retrying to avoid a duplicate request."
                        )
                    ),
                    run_id=self.run_id,
                    failed_stage=self.current_stage,
                    failure_code=failure_code,
                    submission_confirmed=self.submission_confirmed,
                    retry_mode="response" if self.submission_confirmed else "inspect",
                    recoverable=True,
                    response_baseline=self.response_baseline,
                    checkpoint=(
                        AutomationCheckpoint.SUBMISSION_CONFIRMED
                        if self.submission_confirmed
                        else AutomationCheckpoint.SEND_STARTED
                    ),
                    submission_disposition=disposition,
                    recovery_actions=recovery_actions_for(disposition),
                    response_anchor=self.response_anchor,
                )
            return self._fallback(
                prompt,
                "ChatGPT automation failed. The complete prompt has been copied to "
                f"the clipboard. Details: {exc}",
                failure_code=failure_code,
                retry_mode=retry_mode,
            )
        finally:
            if (
                previous_clipboard is not None
                or previous_clipboard_snapshot is not None
            ):
                self._restore_clipboard_if_unchanged(
                    previous_clipboard,
                    snapshot=previous_clipboard_snapshot,
                )
            self._log_timing("total submission", submission_started)
            pythoncom.CoUninitialize()

    def _ensure_automation_dependencies(self) -> None:
        if self.desktop_factory is None:
            from pywinauto import Desktop

            self.desktop_factory = Desktop
        if self.send_keys is None:
            from pywinauto.keyboard import send_keys

            self.send_keys = send_keys

    def retrieve_response(
        self,
        prompt: str,
        *,
        response_baseline: tuple[str, ...] = (),
        response_anchor: ResponseAnchor | None = None,
        redaction_replacements: dict[str, str] | None = None,
    ) -> SubmissionResult:
        """Retry response retrieval without ever submitting the prompt again."""

        import pythoncom

        self.response_baseline = tuple(response_baseline)
        self.response_anchor = response_anchor or ResponseAnchor(
            baseline_tokens=self.response_baseline,
            prompt_digest=self._text_digest(prompt),
        )
        self.checkpoint = AutomationCheckpoint.SUBMISSION_CONFIRMED
        self.submission_disposition = SubmissionDisposition.CONFIRMED
        self.send_started = True
        self.submission_confirmed = True
        self._ensure_automation_dependencies()
        before: str | None = None
        before_snapshot: ClipboardSnapshot | None = None
        pythoncom.CoInitialize()
        try:
            self._report_progress(
                "waiting-for-response",
                "Retrying retrieval of the existing ChatGPT response",
            )
            window = self._get_or_launch_window()
            self.chatgpt_hwnd = self._native_window_handle(window) or 0
            before, before_snapshot = self._capture_clipboard_state()
            generated = self._copy_latest_response(
                window,
                prompt,
                baseline=self.response_baseline,
                anchor=self.response_anchor,
            )
            generated = restore_placeholders(
                generated,
                redaction_replacements or {},
            )
            self._retain_captured_response(generated)
            self._report_progress(
                "response-captured",
                "Captured the response that belongs to this request",
            )
            self._restore_clipboard_if_unchanged(
                before,
                snapshot=before_snapshot,
                expected=generated,
            )
            before_snapshot = None
            before = None
            return SubmissionResult(
                submitted=True,
                generated_text=generated,
                message="The existing ChatGPT response was retrieved.",
                run_id=self.run_id,
                submission_confirmed=True,
                response_baseline=self.response_baseline,
                checkpoint=AutomationCheckpoint.RESPONSE_CAPTURED,
                submission_disposition=SubmissionDisposition.CONFIRMED,
                recovery_actions=recovery_actions_for(
                    SubmissionDisposition.CONFIRMED,
                    has_result=True,
                ),
                response_anchor=self.response_anchor,
            )
        except ChatGPTAutomationCancelled:
            return SubmissionResult(
                submitted=True,
                cancelled=True,
                message=(
                    "Response retrieval stopped. The existing ChatGPT request "
                    "was not sent again."
                ),
                run_id=self.run_id,
                failed_stage=self.current_stage,
                failure_code="cancelled",
                submission_confirmed=True,
                retry_mode="response",
                recoverable=True,
                response_baseline=self.response_baseline,
                checkpoint=AutomationCheckpoint.SUBMISSION_CONFIRMED,
                submission_disposition=SubmissionDisposition.CONFIRMED,
                recovery_actions=recovery_actions_for(
                    SubmissionDisposition.CONFIRMED
                ),
                response_anchor=self.response_anchor,
            )
        except Exception as exc:
            LOGGER.exception("Existing ChatGPT response could not be retrieved")
            return SubmissionResult(
                submitted=True,
                output_failed=True,
                message=f"The existing response is not ready: {exc}",
                run_id=self.run_id,
                failed_stage=self.current_stage,
                failure_code=getattr(exc, "code", "response_unavailable"),
                submission_confirmed=True,
                retry_mode="response",
                recoverable=True,
                response_baseline=self.response_baseline,
                checkpoint=AutomationCheckpoint.SUBMISSION_CONFIRMED,
                submission_disposition=SubmissionDisposition.CONFIRMED,
                recovery_actions=recovery_actions_for(
                    SubmissionDisposition.CONFIRMED
                ),
                response_anchor=self.response_anchor,
            )
        finally:
            if before is not None or before_snapshot is not None:
                self._restore_clipboard_if_unchanged(
                    before,
                    snapshot=before_snapshot,
                )
            pythoncom.CoUninitialize()

    def check_connection(self) -> SubmissionResult:
        """Check current-app readiness without navigating or inserting text."""

        import pythoncom

        self._ensure_automation_dependencies()
        pythoncom.CoInitialize()
        try:
            self._report_progress(
                "locating-chatgpt",
                "Checking the current ChatGPT app",
            )
            window = self._get_or_launch_window()
            blocked = self._blocked_window_state(window)
            if blocked:
                return SubmissionResult(
                    submitted=False,
                    message=(
                        "ChatGPT needs attention before PromptMeld can use it."
                    ),
                    run_id=self.run_id,
                    failed_stage="locating-chatgpt",
                    failure_code=blocked,
                    retry_mode="connection",
                    recoverable=True,
                )
            controls = self._descendants(window) or []
            usable = any(
                getattr(control.element_info, "control_type", "")
                in {"Button", "Edit", "Document"}
                for control in controls
            )
            if not usable:
                raise ChatGPTAutomationError(
                    "ChatGPT did not expose its accessibility controls.",
                    code="accessibility_unavailable",
                )
            return SubmissionResult(
                submitted=False,
                prepared=True,
                message="The current ChatGPT app and accessibility controls are ready.",
                run_id=self.run_id,
            )
        except Exception as exc:
            return SubmissionResult(
                submitted=False,
                message=str(exc),
                run_id=self.run_id,
                failed_stage=self.current_stage,
                failure_code=getattr(exc, "code", "connection_failed"),
                retry_mode="connection",
                recoverable=True,
            )
        finally:
            pythoncom.CoUninitialize()

    def _get_or_launch_window(self):
        window = self._find_window()
        if window is not None and self._window_accessibility_ready(window):
            return window
        launched = window is None
        if window is None:
            self.startfile(self.project_uri or self.chatgpt_uri)
        readiness_timeout = (
            self.launch_timeout_seconds
            if launched
            else max(20.0, self.timeout_seconds)
        )
        deadline = time.monotonic() + readiness_timeout
        stable_handle = None
        stable_checks = 0
        while time.monotonic() < deadline:
            window = self._find_window()
            if window is not None:
                handle = self._native_window_handle(window)
                ready = self._window_accessibility_ready(window)
                if ready and handle == stable_handle:
                    stable_checks += 1
                elif ready:
                    stable_handle = handle
                    stable_checks = 1
                else:
                    stable_handle = None
                    stable_checks = 0
                if stable_checks >= 2:
                    return window
            self._sleep(0.2)
        blocked = self._blocked_window_state(window) if window is not None else ""
        messages = {
            "sign_in_required": "ChatGPT is open but requires sign-in.",
            "introductory_dialog": (
                "ChatGPT is waiting for an introductory dialog to be completed."
            ),
            "update_required": "ChatGPT is waiting for an application update.",
        }
        raise ChatGPTAutomationError(
            messages.get(
                blocked,
                "The current ChatGPT app did not become ready before the timeout.",
            ),
            code=blocked or "chatgpt_not_ready",
        )

    def _find_window(self):
        desktop = self.desktop_factory(backend="uia")
        candidates = desktop.windows(
            title="ChatGPT",
            control_type="Window",
            visible_only=True,
            enabled_only=True,
        )
        verified = [
            candidate for candidate in candidates if self._is_current_window(candidate)
        ]
        foreground = self.foreground_window_reader()
        verified.sort(
            key=lambda candidate: (
                self._native_window_handle(candidate) != foreground,
                not self._window_accessibility_ready(candidate),
                self._native_window_handle(candidate) or 0,
            )
        )
        return verified[0] if verified else None

    def _is_current_window(self, window) -> bool:
        try:
            process_id = int(window.process_id())
            process_path = self.process_path_reader(process_id) or ""
        except Exception:
            LOGGER.debug(
                "Could not verify the ChatGPT window process",
                exc_info=True,
            )
            # UIA test doubles do not expose native handles. A real top-level
            # Windows candidate must always be process-verifiable.
            return self._native_window_handle(window) is None
        normalized = process_path.replace("/", "\\").casefold()
        accepted = (
            "\\openai.codex_" in normalized
            and normalized.endswith("\\app\\chatgpt.exe")
        )
        if not accepted:
            LOGGER.info(
                "Ignoring unverified ChatGPT window process_id=%s",
                process_id,
            )
        else:
            LOGGER.info(
                "Verified current ChatGPT window process_id=%s handle=%s "
                "package=OpenAI.Codex",
                process_id,
                self._native_window_handle(window),
            )
        return accepted

    def _window_accessibility_ready(self, window) -> bool:
        controls = self._descendants(window)
        if controls is None:
            return False
        if not controls and self._native_window_handle(window) is None:
            return True
        return bool(
            controls
            and any(
                getattr(control.element_info, "control_type", "")
                in {"Button", "Edit", "Document"}
                for control in controls
            )
        )

    def _blocked_window_state(self, window) -> str:
        controls = self._descendants(window) or []
        names = {
            str(getattr(control.element_info, "name", "") or "").strip().casefold()
            for control in controls
        }
        if names.intersection({"log in", "sign in", "continue with google"}):
            return "sign_in_required"
        if any("update" in name and "chatgpt" in name for name in names):
            return "update_required"
        if names.intersection({"get started", "continue", "next"}) and not self._find_composer(window):
            return "introductory_dialog"
        return ""

    @staticmethod
    def _process_path(process_id: int) -> str | None:
        import win32api
        import win32con
        import win32process

        handle = None
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION
                | win32con.PROCESS_VM_READ,
                False,
                process_id,
            )
            return str(win32process.GetModuleFileNameEx(handle, 0))
        except Exception:
            LOGGER.debug(
                "Could not read ChatGPT window process %s",
                process_id,
                exc_info=True,
            )
            return None
        finally:
            if handle is not None:
                win32api.CloseHandle(handle)

    def _navigate_to_temporary_chat(self, window) -> bool:
        self._report_progress(
            "selecting-mode",
            "Switching from Codex to ChatGPT when needed",
        )
        if not self._select_chatgpt_mode(window):
            self._report_progress(
                "selecting-mode",
                "Retrying the switch from Codex to ChatGPT",
            )
            self._prepare_navigation_retry(window)
            if not self._select_chatgpt_mode(window):
                return self._navigation_failed(
                    "switch from Codex to ChatGPT after two attempts"
                )

        self._report_progress(
            "opening-temporary-chat",
            "Opening a top-level ChatGPT chat outside Projects",
        )
        if not self._open_chat_home(window):
            self._report_progress(
                "opening-temporary-chat",
                "Retrying top-level ChatGPT navigation",
            )
            self._prepare_navigation_retry(window)
            if (
                not self._select_chatgpt_mode(window)
                or not self._open_chat_home(window)
            ):
                return self._navigation_failed(
                    "open a top-level ChatGPT chat for Temporary Chat"
                )

        if self._temporary_chat_is_ready(window):
            return True

        current = self._refresh_chatgpt_window() or window
        turn_on = self._find_control(
            current,
            lambda control: (
                control.element_info.control_type == "Button"
                and (control.element_info.name or "").strip()
                == self.TEMPORARY_CHAT_ON_NAME
            ),
        )
        if turn_on is None:
            return self._navigation_failed(
                "find ChatGPT's Temporary Chat control"
            )

        self._report_progress(
            "opening-temporary-chat",
            "Turning on Temporary Chat",
        )
        self._mark_selector(TEMPORARY_CHAT.identifier)
        self._activate_control(turn_on)

        deadline = (
            time.monotonic() + self.TEMPORARY_CHAT_CONFIRMATION_SECONDS
        )
        first_activation = time.monotonic()
        retried_activation = False
        confirmation_seen = False
        while time.monotonic() < deadline:
            current = self._refresh_chatgpt_window() or window
            if self._temporary_chat_is_ready_in(current):
                return True

            dialog = self._find_control(
                current,
                lambda control: (
                    control.element_info.control_type == "Window"
                    and (control.element_info.name or "").strip()
                    == self.TEMPORARY_CHAT_DIALOG_NAME
                ),
            )
            if dialog is not None:
                self._mark_selector(TEMPORARY_CHAT_DIALOG.identifier)
                if not confirmation_seen:
                    confirmation_seen = True
                    self._report_progress(
                        "temporary-chat-confirmation",
                        "Waiting for you to review and confirm Temporary Chat in ChatGPT",
                    )
                    try:
                        current.set_focus()
                    except Exception:
                        LOGGER.debug(
                            "Could not focus the Temporary Chat explanation",
                            exc_info=True,
                        )
            else:
                turn_on = self._find_control(
                    current,
                    lambda control: (
                        control.element_info.control_type == "Button"
                        and (control.element_info.name or "").strip()
                        == self.TEMPORARY_CHAT_ON_NAME
                    ),
                )
                if confirmation_seen and turn_on is not None:
                    return self._navigation_failed(
                        "turn on Temporary Chat because its confirmation "
                        "was dismissed"
                    )
                if (
                    not confirmation_seen
                    and not retried_activation
                    and turn_on is not None
                    and time.monotonic() - first_activation >= 1.0
                ):
                    retried_activation = True
                    self._report_progress(
                        "opening-temporary-chat",
                        "Retrying the Temporary Chat control",
                    )
                    self._mark_selector(TEMPORARY_CHAT.identifier)
                    self._activate_control(turn_on)
            self._sleep(0.1)

        if confirmation_seen:
            return self._navigation_failed(
                "complete the one-time Temporary Chat confirmation"
            )
        return self._navigation_failed("confirm Temporary Chat")

    def _temporary_chat_is_ready(self, window) -> bool:
        if self._temporary_chat_is_ready_in(window):
            return True
        refreshed = self._refresh_chatgpt_window()
        return bool(
            refreshed is not None
            and self._temporary_chat_is_ready_in(refreshed)
        )

    def _temporary_chat_is_ready_in(self, window) -> bool:
        controls = self._descendants(window)
        if controls is None:
            return False
        temporary_chat_is_on = any(
            control.element_info.control_type == "Button"
            and (control.element_info.name or "").strip()
            == self.TEMPORARY_CHAT_OFF_NAME
            for control in controls
        )
        project_is_active = any(
            control.element_info.control_type == "Button"
            and (control.element_info.name or "").strip().startswith(
                self.PROJECT_CHANGE_PREFIX
            )
            for control in controls
        )
        ready = bool(
            temporary_chat_is_on
            and not project_is_active
            and self._find_composer_in(controls) is not None
        )
        if ready:
            self._mark_selector(TEMPORARY_CHAT.identifier)
        return ready

    def _navigate_to_project_chat(self, window, project_name: str) -> bool:
        self._report_progress(
            "selecting-mode",
            "Switching from Codex to ChatGPT when needed",
        )
        if not self._select_chatgpt_mode(window):
            LOGGER.warning(
                "ChatGPT mode selection did not complete; retrying once"
            )
            self._report_progress(
                "selecting-mode",
                "Retrying the switch from Codex to ChatGPT",
            )
            self._prepare_navigation_retry(window)
            if not self._select_chatgpt_mode(window):
                return self._navigation_failed(
                    "switch from Codex to ChatGPT after two attempts"
                )
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
        if project_action is None:
            # Mode changes replace Chromium's sidebar subtree. Reacquire the
            # window when the existing wrapper does not expose the Project's
            # exact new-chat button, before falling back to a generic row.
            window = self._refresh_chatgpt_window() or window
            project_action = self._find_project_new_chat_control(
                window,
                project_name,
            )
        if project_action is not None:
            LOGGER.info("Using the verified Project new-chat fast path")
            return self._activate_project_new_chat(
                window,
                project_action,
                project_name,
            )

        if not self._open_chat_home(window):
            LOGGER.warning(
                "ChatGPT chat navigation did not complete; retrying once"
            )
            self._report_progress(
                "opening-project",
                "Retrying ChatGPT navigation before opening the Project",
            )
            self._prepare_navigation_retry(window)
            if (
                not self._select_chatgpt_mode(window)
                or not self._open_chat_home(window)
            ):
                return self._navigation_failed(
                    "open Chat mode after two attempts"
                )

        if self.project_uri:
            try:
                self.startfile(self.project_uri)
                self._sleep(0.8)
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
            activated = self._activate_project_new_chat(
                window,
                project_action,
                project_name,
            )
            if not activated:
                return self._navigation_failed(
                    f"confirm the '{project_name}' Project chat"
                )
            return True

        project_was_created = False
        if project is None:
            if not self._create_project(window, project_name):
                return False
            project_was_created = True
            if self._project_context_is_active(window, project_name):
                return True
            # Empty projects are hidden from the shortened sidebar until
            # Projects > Show more is activated. Return to Chat and locate the
            # exact project's own new-chat action rather than creating again.
            if not self._open_chat_home(window):
                return self._navigation_failed(
                    "return to Chat mode after creating the Project",
                    code="project_created_not_found",
                    retry_mode="inspect",
                )
            self._expand_project_list(window)
            project_action = self._wait_for_control(
                window,
                lambda control: self._is_project_new_chat_control(
                    control,
                    project_name,
                ),
            )
            if project_action is not None:
                activated = self._activate_project_new_chat(
                    window,
                    project_action,
                    project_name,
                )
                if not activated:
                    return self._navigation_failed(
                        f"confirm the '{project_name}' Project chat",
                        code="project_created_not_found",
                        retry_mode="inspect",
                    )
                return True
            project = self._find_project_control(window, project_name)
        if project is None:
            return self._navigation_failed(
                f"locate the '{project_name}' Project after creating it",
                code="project_created_not_found",
                retry_mode="inspect",
            )

        activated = self._activate_project_control(
            window,
            project,
            project_name,
        )
        if not activated:
            return self._navigation_failed(
                f"confirm the '{project_name}' Project chat",
                code=(
                    "project_created_not_found"
                    if project_was_created
                    else "navigation_failed"
                ),
                retry_mode=(
                    "inspect" if project_was_created else "delivery"
                ),
            )
        return True

    def _prepare_navigation_retry(self, window) -> None:
        """Reset a transient menu or stale mode surface before one retry."""

        try:
            window.set_focus()
            if self.send_keys is None:
                self._ensure_automation_dependencies()
            self.send_keys("{ESC}", pause=0.02)
        except Exception:
            LOGGER.debug(
                "Could not dismiss the stale ChatGPT navigation surface",
                exc_info=True,
            )
        deadline = time.monotonic() + min(max(self.timeout_seconds, 0.25), 1.0)
        while time.monotonic() < deadline:
            refreshed = self._refresh_chatgpt_window()
            if refreshed is not None and self._window_accessibility_ready(refreshed):
                return
            self._sleep(0.05)

    def _navigation_failed(
        self,
        operation: str,
        *,
        code: str = "navigation_failed",
        retry_mode: str = "delivery",
    ) -> bool:
        self.navigation_failure = operation
        self.navigation_failure_code = code
        self.navigation_retry_mode = retry_mode
        LOGGER.warning(
            "Automation run=%s stage=opening-project failure_code=%s "
            "retry_mode=%s",
            self.run_id,
            code,
            retry_mode,
        )
        return False

    def _start_project_step(self, step: str, message: str, window) -> None:
        self._finish_project_step()
        self.project_step = step
        self.project_step_started_at = time.perf_counter()
        attempt = self.project_step_attempts.get(step, 0) + 1
        self.project_step_attempts[step] = attempt
        LOGGER.info(
            "Automation run=%s stage=opening-project project_step=%s "
            "attempt=%s window_handle=%s",
            self.run_id,
            step,
            attempt,
            self._native_window_handle(window) or "unknown",
        )
        self._report_progress("opening-project", message)

    def _finish_project_step(
        self,
        *,
        outcome: str = "completed",
        failure_code: str = "",
    ) -> None:
        if not self.project_step or self.project_step_started_at is None:
            return
        elapsed_ms = (
            time.perf_counter() - self.project_step_started_at
        ) * 1000
        timing_name = f"opening-project:{self.project_step}"
        self.timings.append(
            {
                "stage": timing_name,
                "milliseconds": round(elapsed_ms, 1),
            }
        )
        LOGGER.info(
            "Automation run=%s stage=opening-project project_step=%s "
            "outcome=%s failure_code=%s completed_ms=%.1f",
            self.run_id,
            self.project_step,
            outcome,
            failure_code or "none",
            elapsed_ms,
        )
        self.project_step = ""
        self.project_step_started_at = None

    def _project_creation_failed(
        self,
        operation: str,
        code: str,
        *,
        retry_mode: str = "delivery",
    ) -> bool:
        self._finish_project_step(
            outcome="failed",
            failure_code=code,
        )
        return self._navigation_failed(
            operation,
            code=code,
            retry_mode=retry_mode,
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
        self._mark_selector(MODE_SWITCH.identifier)
        if switcher.element_info.name.endswith("ChatGPT"):
            return True

        self._activate_control(switcher)
        mode_item = self._wait_for_refreshed_control(
            window,
            lambda control: (
                control.element_info.control_type == "MenuItem"
                and (control.element_info.name or "").startswith(
                    self.CHATGPT_MODE_ITEM_PREFIX
                )
            ),
            timeout_seconds=min(self.timeout_seconds, 2.0),
        )
        if mode_item is None:
            return False
        self._mark_selector(CHATGPT_MODE.identifier)
        self._activate_control(mode_item)
        return self._wait_for_condition(
            lambda: self._chatgpt_mode_is_active(window),
            timeout_seconds=min(self.timeout_seconds, 4.0),
        )

    def _chatgpt_mode_is_active(self, window) -> bool:
        def is_active_in(candidate_window) -> bool:
            switcher = self._find_control(
                candidate_window,
                lambda control: (
                    control.element_info.control_type == "Button"
                    and (control.element_info.name or "").startswith(
                        self.MODE_SWITCH_PREFIX
                    )
                ),
            )
            return bool(
                switcher is not None
                and switcher.element_info.name.endswith("ChatGPT")
            )

        if is_active_in(window):
            return True
        refreshed = self._refresh_chatgpt_window()
        return bool(refreshed is not None and is_active_in(refreshed))

    def _open_chat_home(self, window) -> bool:
        # The global mode switch can leave an existing Codex page visible.
        # Starting a top-level new chat gives us the ChatGPT Projects view.
        # Older desktop builds then expose a Chat/Work toggle; newer builds go
        # straight to a ChatGPT composer and do not expose that toggle at all.
        new_chat = self._find_control(
            window,
            self._is_top_new_chat_control,
        )
        if new_chat is not None:
            self._mark_selector(CHAT_HOME.identifier)
            self._activate_control(new_chat)

        deadline = time.monotonic() + self.timeout_seconds
        chat_activated = False
        while time.monotonic() < deadline:
            current_window = self._refresh_chatgpt_window() or window
            chat = self._find_control(
                current_window,
                self._is_chat_mode_control,
            )
            if chat is None:
                if self._top_level_chat_is_ready_in(current_window):
                    return True
            else:
                if not chat_activated:
                    self._mark_selector(CHAT_MODE_TAB.identifier)
                    self._activate_control(chat)
                    chat_activated = True
                current_chat = self._find_control(
                    current_window,
                    self._is_chat_mode_control,
                )
                if (
                    current_chat is not None
                    and "text-token-text-primary"
                    in (current_chat.element_info.class_name or "")
                    and self._find_composer(current_window) is not None
                ):
                    return True
            self._sleep(0.1)
        return False

    @staticmethod
    def _is_top_new_chat_control(control) -> bool:
        info = control.element_info
        class_tokens = (info.class_name or "").split()
        return (
            info.control_type == "Button"
            and (info.name or "") == CHAT_HOME.names[0]
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

    def _top_level_chat_is_ready_in(self, window) -> bool:
        controls = self._descendants(window)
        if controls is None:
            return False
        chatgpt_mode_is_active = self._find_control(
            window,
            lambda control: (
                self._control_is_available(control)
                and control.element_info.control_type == "Button"
                and (control.element_info.name or "").startswith(
                    self.MODE_SWITCH_PREFIX
                )
                and (control.element_info.name or "").endswith("ChatGPT")
            ),
        ) is not None
        project_is_active = self._find_control(
            window,
            lambda control: (
                self._control_is_available(control)
                and control.element_info.control_type == "Button"
                and (control.element_info.name or "").strip().startswith(
                self.PROJECT_CHANGE_PREFIX
                )
            ),
        ) is not None
        return bool(
            chatgpt_mode_is_active
            and not project_is_active
            and self._find_composer_in(controls) is not None
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

    @classmethod
    def _is_project_new_chat_control(
        cls,
        control,
        project_name: str,
    ) -> bool:
        name = (control.element_info.name or "").strip()
        return (
            control.element_info.control_type == "Button"
            and name
            in {
                f"{cls.PROJECT_NEW_CHAT_PREFIX}{project_name}",
                f"{cls.PROJECT_START_CHAT_PREFIX}{project_name}",
            }
        )

    def _activate_project_new_chat(
        self,
        window,
        control,
        project_name: str,
    ) -> bool:
        previous_composer = self._composer_signature(window)
        self._report_progress(
            "opening-project",
            f"Starting a new chat in the '{project_name}' Project",
        )
        self._mark_selector(PROJECT_NEW_CHAT.identifier)
        self._activate_control(control)
        self._report_progress(
            "opening-project",
            "Waiting for ChatGPT to confirm the Project chat",
        )
        if self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name),
            timeout_seconds=self.timeout_seconds,
        ):
            return True

        if self._project_composer_transition_is_ready(
            window,
            previous_composer,
        ):
            LOGGER.info(
                "The exact project new-chat control produced a verified "
                "ChatGPT composer before its project label was exposed"
            )
            self._report_progress(
                "opening-project",
                "The Project label is delayed; continuing with its verified message box",
            )
            return True

        LOGGER.info(
            "Project new-chat confirmation is taking longer; "
            "refreshing the ChatGPT accessibility window"
        )
        self._report_progress(
            "opening-project",
            "Project confirmation is taking longer; refreshing ChatGPT controls",
        )
        if self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name),
            timeout_seconds=min(self.timeout_seconds, 2.0),
        ):
            return True

        if self._project_composer_transition_is_ready(
            window,
            previous_composer,
        ):
            LOGGER.info(
                "The exact project new-chat control produced a verified "
                "ChatGPT composer during the refreshed grace period"
            )
            self._report_progress(
                "opening-project",
                "The Project label is delayed; continuing with its verified message box",
            )
            return True

        LOGGER.warning(
            "The project new-chat activation was not confirmed after a "
            "refreshed grace period; reacquiring the control"
        )
        self._report_progress(
            "opening-project",
            "Reacquiring the Project control and retrying once",
        )
        self._prepare_navigation_retry(window)
        if not self._select_chatgpt_mode(window):
            return False

        replacement = self._wait_for_control(
            window,
            lambda candidate: self._is_project_new_chat_control(
                candidate,
                project_name,
            ),
            timeout_seconds=min(self.timeout_seconds, 2.0),
        )
        if replacement is None:
            if not self._open_chat_home(window):
                return False
            self._expand_project_list(window)
            replacement = self._wait_for_control(
                window,
                lambda candidate: self._is_project_new_chat_control(
                    candidate,
                    project_name,
                ),
                timeout_seconds=min(self.timeout_seconds, 2.0),
            )
        if replacement is None:
            return False

        self._report_progress(
            "opening-project",
            f"Retrying the '{project_name}' Project chat",
        )
        self._mark_selector(PROJECT_NEW_CHAT.identifier)
        self._activate_control(replacement)
        if self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name),
            timeout_seconds=min(self.timeout_seconds, 4.0),
        ):
            return True
        return self._project_composer_transition_is_ready(
            window,
            previous_composer,
        )

    def _activate_project_control(
        self,
        window,
        control,
        project_name: str,
    ) -> bool:
        previous_composer = self._composer_signature(window)
        self._report_progress(
            "opening-project",
            f"Opening the '{project_name}' Project",
        )
        self._mark_selector(PROJECT_ROW.identifier)
        self._activate_control(control)
        if self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name),
            timeout_seconds=self.timeout_seconds,
        ):
            return True

        if self._project_composer_transition_is_ready(
            window,
            previous_composer,
        ):
            LOGGER.info(
                "The exact project control produced a verified ChatGPT "
                "composer before its project label was exposed"
            )
            self._report_progress(
                "opening-project",
                "The Project label is delayed; continuing with its verified message box",
            )
            return True

        LOGGER.info(
            "Project confirmation is taking longer; refreshing the ChatGPT "
            "accessibility window"
        )
        self._report_progress(
            "opening-project",
            "Project confirmation is taking longer; refreshing ChatGPT controls",
        )
        if self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name),
            timeout_seconds=min(self.timeout_seconds, 2.0),
        ):
            return True

        if self._project_composer_transition_is_ready(
            window,
            previous_composer,
        ):
            LOGGER.info(
                "The exact project control produced a verified ChatGPT "
                "composer during the refreshed grace period"
            )
            self._report_progress(
                "opening-project",
                "The Project label is delayed; continuing with its verified message box",
            )
            return True

        LOGGER.warning(
            "The project activation was not confirmed after a refreshed grace "
            "period; reacquiring the control"
        )
        self._report_progress(
            "opening-project",
            "Reacquiring the Project control and retrying once",
        )
        self._prepare_navigation_retry(window)
        replacement = self._find_project_control(window, project_name)
        if replacement is None:
            return False
        self._mark_selector(PROJECT_ROW.identifier)
        self._activate_control(replacement)
        if self._wait_for_condition(
            lambda: self._project_chat_is_ready(window, project_name),
            timeout_seconds=min(self.timeout_seconds, 4.0),
        ):
            return True
        return self._project_composer_transition_is_ready(
            window,
            previous_composer,
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
        self._mark_selector(PROJECT_SHOW_MORE.identifier)
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
                and (control.element_info.name or "")
                == self.PROJECTS_SECTION_NAME
            ),
            None,
        )
        candidates = [
            control
            for control in controls
            if control.element_info.control_type == "Button"
            and (control.element_info.name or "") == self.PROJECT_SHOW_MORE_NAME
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
        window = self._refresh_chatgpt_window() or window
        self._start_project_step(
            "find-add-control",
            "Finding ChatGPT's new Project control",
            window,
        )
        add_project = self._wait_for_refreshed_control(
            window,
            lambda control: (
                control.element_info.control_type == "Button"
                and (control.element_info.name or "") == self.PROJECT_ADD_NAME
            ),
            timeout_seconds=min(self.timeout_seconds, 2.0),
        )
        if add_project is None:
            return self._project_creation_failed(
                "find ChatGPT's Add new project control",
                "project_add_control_missing",
            )
        self._start_project_step(
            "open-creation-surface",
            "Opening ChatGPT's new Project form",
            window,
        )
        self._mark_selector(PROJECT_ADD.identifier)
        try:
            activated = self._activate_control(add_project)
        except Exception:
            activated = False
            LOGGER.debug(
                "The new Project control could not be activated",
                exc_info=True,
            )
        if not activated:
            return self._project_creation_failed(
                "open ChatGPT's new Project form",
                "project_add_activation_failed",
            )

        name_edit = self._wait_for_refreshed_control(
            window,
            lambda control: (
                self._is_project_name_control(control)
                or self._is_project_index_search(control)
                or self._is_project_storage_choice(control)
            ),
        )
        if name_edit is None:
            return self._project_creation_failed(
                "find the Project creation form after opening it",
                "project_creation_surface_missing",
            )
        if name_edit is not None and self._is_project_storage_choice(name_edit):
            if not self._choose_cloud_project_storage(window):
                return False
            name_edit = self._wait_for_refreshed_control(
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
            window = self._refresh_chatgpt_window() or window
            self._start_project_step(
                "advance-from-project-index",
                "Opening the new Project form from Projects",
                window,
            )
            add_project = self._wait_for_refreshed_control(
                window,
                lambda control: (
                    control.element_info.control_type == "Button"
                    and (control.element_info.name or "")
                    == self.PROJECT_ADD_NAME
                ),
                timeout_seconds=min(self.timeout_seconds, 2.0),
            )
            if add_project is None:
                return self._project_creation_failed(
                    "advance from the Projects index to the creation form",
                    "project_index_transition_failed",
                )
            self._mark_selector(PROJECT_ADD.identifier)
            try:
                activated = self._activate_control(add_project)
            except Exception:
                activated = False
                LOGGER.debug(
                    "The Projects index creation control could not be activated",
                    exc_info=True,
                )
            if not activated:
                return self._project_creation_failed(
                    "advance from the Projects index to the creation form",
                    "project_index_transition_failed",
                )
            name_edit = self._wait_for_refreshed_control(
                window,
                lambda control: (
                    self._is_project_name_control(control)
                    or self._is_project_storage_choice(control)
                ),
            )
            if (
                name_edit is not None
                and self._is_project_storage_choice(name_edit)
            ):
                if not self._choose_cloud_project_storage(window):
                    return False
                name_edit = self._wait_for_refreshed_control(
                    window,
                    self._is_project_name_control,
                )
        if name_edit is None:
            return self._project_creation_failed(
                "find the new Project name field",
                "project_name_control_missing",
            )
        current_window = self._refresh_chatgpt_window() or window
        if self._project_storage_controls(current_window) is not None:
            if not self._choose_cloud_project_storage(current_window):
                return False
            name_edit = self._wait_for_refreshed_control(
                current_window,
                self._is_project_name_control,
            )
            if name_edit is None:
                return self._project_creation_failed(
                    "find the new Project name field after choosing Cloud",
                    "project_name_control_missing",
                )
        self._start_project_step(
            "enter-project-name",
            "Entering the new Cloud Project name",
            current_window,
        )
        name_edit = self._wait_for_refreshed_control(
            current_window,
            self._is_project_name_control,
            timeout_seconds=min(self.timeout_seconds, 2.0),
        )
        if name_edit is None:
            return self._project_creation_failed(
                "reacquire the new Project name field",
                "project_name_control_missing",
            )
        (
            project_clipboard,
            project_clipboard_snapshot,
        ) = self._capture_clipboard_state()
        self._mark_selector(PROJECT_NAME.identifier)
        try:
            self._write_clipboard(project_name)
            name_edit.set_focus()
            self.send_keys("^a", pause=0.02)
            self.send_keys("^v", pause=0.02)
        except Exception:
            LOGGER.debug(
                "The new Project name could not be entered",
                exc_info=True,
            )
            return self._project_creation_failed(
                "enter the new Project name",
                "project_name_entry_failed",
            )
        finally:
            self._restore_clipboard_if_unchanged(
                project_clipboard,
                snapshot=project_clipboard_snapshot,
                expected=project_name,
            )

        self._start_project_step(
            "find-create-control",
            "Finding the Cloud Project creation control",
            current_window,
        )
        create = self._wait_for_refreshed_control(
            current_window,
            lambda control: (
                control.element_info.control_type in {"Button", "Text"}
                and (control.element_info.name or "") == self.PROJECT_CREATE_NAME
                and bool(getattr(control.element_info, "enabled", True))
                and bool(getattr(control.element_info, "visible", True))
            ),
        )
        if create is None or not bool(
            getattr(create.element_info, "enabled", True)
        ):
            return self._project_creation_failed(
                "use the enabled Create project control",
                "project_create_unavailable",
            )

        # Creating a Cloud Project is not idempotent. Activate this exact,
        # freshly acquired control once, then require positive evidence of the
        # requested Project rather than treating a dismissed form as success.
        self._start_project_step(
            "activate-create-control",
            "Creating the Cloud Project",
            current_window,
        )
        self._mark_selector(PROJECT_CREATE.identifier)
        try:
            activated = self._activate_control(create)
        except Exception:
            activated = False
            LOGGER.debug(
                "The Create project activation outcome is ambiguous",
                exc_info=True,
            )
        if not activated:
            return self._project_creation_failed(
                "confirm whether ChatGPT created the Cloud Project",
                "project_create_activation_unconfirmed",
                retry_mode="inspect",
            )

        self._start_project_step(
            "confirm-project-created",
            "Waiting for ChatGPT to confirm the new Cloud Project",
            current_window,
        )
        if not self._wait_for_condition(
            lambda: self._created_project_is_exposed(
                current_window,
                project_name,
            )
        ):
            return self._project_creation_failed(
                "confirm whether ChatGPT created the Cloud Project",
                "project_create_activation_unconfirmed",
                retry_mode="inspect",
            )
        self._finish_project_step()
        return True

    def _is_project_name_control(self, control) -> bool:
        info = control.element_info
        return (
            info.control_type == "Edit"
            and (
                (getattr(info, "automation_id", "") or "")
                == self.PROJECT_NAME_AUTOMATION_ID
                or (info.name or "").strip() == self.PROJECT_NAME_CONTROL_NAME
            )
        )

    def _is_project_index_search(self, control) -> bool:
        info = control.element_info
        return (
            info.control_type == "Edit"
            and (getattr(info, "automation_id", "") or "")
            == self.PROJECT_INDEX_SEARCH_AUTOMATION_ID
        )

    @classmethod
    def _is_project_storage_choice(cls, control) -> bool:
        info = control.element_info
        return (
            info.control_type in {"Button", "RadioButton", "ListItem"}
            and cls._project_storage_choice_key(control) is not None
            and bool(getattr(info, "enabled", True))
            and bool(getattr(info, "visible", True))
        )

    @classmethod
    def _project_storage_choice_key(cls, control) -> str | None:
        names = [control.element_info.name or ""]
        try:
            names.extend(
                descendant.element_info.name or ""
                for descendant in control.descendants()
            )
        except Exception:
            pass
        for name in names:
            normalized = " ".join(name.strip().casefold().split())
            match = next(
                (
                    choice
                    for choice in cls.PROJECT_STORAGE_CHOICES
                    if normalized == choice
                    or normalized.startswith(f"{choice} ")
                ),
                None,
            )
            if match is not None:
                return match
        return None

    def _choose_cloud_project_storage(self, window) -> bool:
        """Choose Cloud only when the complete Cloud/Local prompt is visible."""

        self._start_project_step(
            "select-cloud-storage",
            "Choosing Cloud storage for the new Project",
            window,
        )
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            current_window = self._refresh_chatgpt_window() or window
            choices = self._project_storage_controls(current_window)
            if choices is not None:
                self._mark_selector(PROJECT_STORAGE.identifier)
                cloud_is_selected = (
                    self._project_storage_choice_is_selected(
                        choices["cloud"]
                    )
                    and (
                        "local" not in choices
                        or not self._project_storage_choice_is_selected(
                            choices["local"]
                        )
                    )
                )
                if cloud_is_selected:
                    LOGGER.info(
                        "Verified Cloud as the selected new Project type"
                    )
                else:
                    LOGGER.info(
                        "Selecting Cloud storage for new ChatGPT project"
                    )
                    try:
                        activated = self._activate_control(choices["cloud"])
                    except Exception:
                        activated = False
                        LOGGER.debug(
                            "Cloud storage activation could not be confirmed",
                            exc_info=True,
                        )
                    if not activated:
                        return self._project_creation_failed(
                            "choose Cloud storage for the new Project",
                            "project_cloud_activation_unconfirmed",
                        )
                if self._wait_for_condition(
                    lambda: self._cloud_project_storage_is_confirmed(
                        current_window,
                    )
                ):
                    current_window = (
                        self._refresh_chatgpt_window() or current_window
                    )
                    name_edit = self._find_control(
                        current_window,
                        self._is_project_name_control,
                    )
                    if name_edit is not None:
                        self._finish_project_step()
                        return True
                    next_control = self._wait_for_refreshed_control(
                        current_window,
                        lambda control: (
                            self._is_project_name_control(control)
                            or self._is_project_type_next_control(control)
                        ),
                        timeout_seconds=min(self.timeout_seconds, 2.0),
                    )
                    if (
                        next_control is not None
                        and self._is_project_name_control(next_control)
                    ):
                        self._finish_project_step()
                        return True
                    if next_control is None:
                        return self._project_creation_failed(
                            "advance from Cloud selection to Project naming",
                            "project_cloud_activation_unconfirmed",
                        )
                    self._start_project_step(
                        "advance-cloud-storage",
                        "Continuing with the verified Cloud Project type",
                        current_window,
                    )
                    self._mark_selector(PROJECT_TYPE_NEXT.identifier)
                    try:
                        advanced = self._activate_control(next_control)
                    except Exception:
                        advanced = False
                        LOGGER.debug(
                            "Cloud Project type confirmation could not advance",
                            exc_info=True,
                        )
                    if not advanced:
                        return self._project_creation_failed(
                            "advance from Cloud selection to Project naming",
                            "project_cloud_activation_unconfirmed",
                        )
                    if self._wait_for_refreshed_control(
                        current_window,
                        self._is_project_name_control,
                    ) is None:
                        return self._project_creation_failed(
                            "find the Project name field after choosing Cloud",
                            "project_name_control_missing",
                        )
                    self._finish_project_step()
                    return True
                return self._project_creation_failed(
                    "confirm Cloud storage for the new Project",
                    "project_cloud_activation_unconfirmed",
                )
            self._sleep(0.1)
        return self._project_creation_failed(
            "find the Cloud storage choice",
            "project_storage_choice_missing",
        )

    def _cloud_project_storage_is_confirmed(
        self,
        window,
    ) -> bool:
        current_window = self._refresh_chatgpt_window() or window
        choices = self._project_storage_controls(current_window)
        if choices is not None:
            if (
                self._project_storage_choice_is_selected(choices["cloud"])
                and (
                    "local" not in choices
                    or not self._project_storage_choice_is_selected(
                        choices["local"]
                    )
                )
            ):
                return True
            if "local" in choices:
                return False
            return self._find_control(
                current_window,
                self._is_project_type_next_control,
            ) is not None
        return self._find_control(
            current_window,
            lambda control: (
                self._is_project_name_control(control)
                or self._is_project_type_next_control(control)
            ),
        ) is not None

    @classmethod
    def _is_project_type_next_control(cls, control) -> bool:
        info = control.element_info
        return (
            info.control_type in {"Button", "Text"}
            and (info.name or "").strip() == cls.PROJECT_TYPE_NEXT_NAME
            and bool(getattr(info, "enabled", True))
            and bool(getattr(info, "visible", True))
        )

    @staticmethod
    def _project_storage_choice_is_selected(control) -> bool:
        for method_name in ("is_selected", "get_toggle_state"):
            method = getattr(control, method_name, None)
            if not callable(method):
                continue
            try:
                return bool(method())
            except Exception:
                continue
        try:
            return bool(control.iface_selection_item.CurrentIsSelected)
        except Exception:
            return False

    def _created_project_is_exposed(
        self,
        window,
        project_name: str,
    ) -> bool:
        current_window = self._refresh_chatgpt_window() or window
        project_action, project = self._find_project_targets(
            current_window,
            project_name,
        )
        return bool(
            self._project_context_is_active(current_window, project_name)
            or project_action is not None
            or project is not None
        )

    def _project_storage_controls(self, window):
        choices = {}
        controls = self._descendants(window) or []
        for control in controls:
            try:
                if not self._is_project_storage_choice(control):
                    continue
                key = self._project_storage_choice_key(control)
                if key is not None:
                    choices[key] = control
            except Exception:
                continue
        # Current ChatGPT builds can expose a single enabled Cloud ListItem
        # whose exact label lives in a Text child. Local may be omitted when it
        # is unavailable, but only accept that layout when its explicit Next
        # control is also exposed. This path never infers or activates Local.
        if "cloud" not in choices:
            return None
        if "local" in choices or any(
            self._is_project_type_next_control(control)
            for control in controls
        ):
            return choices
        return None

    def _project_context_is_active(
        self,
        window,
        project_name: str,
    ) -> bool:
        expected = f"{self.PROJECT_CHANGE_PREFIX} {project_name}"
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
        if self._project_chat_is_ready_in(window, project_name):
            return True
        refreshed = self._refresh_chatgpt_window()
        return bool(
            refreshed is not None
            and self._project_chat_is_ready_in(refreshed, project_name)
        )

    def _refresh_chatgpt_window(self):
        if self.desktop_factory is None:
            return None
        try:
            return self._find_window()
        except Exception:
            LOGGER.debug(
                "Could not refresh the ChatGPT accessibility window",
                exc_info=True,
            )
            return None

    def _project_chat_is_ready_in(
        self,
        window,
        project_name: str,
    ) -> bool:
        controls = self._descendants(window)
        if controls is None:
            return False
        expected = f"{self.PROJECT_CHANGE_PREFIX} {project_name}"
        project_is_active = any(
            self._control_is_available(control)
            and control.element_info.control_type == "Button"
            and (control.element_info.name or "").strip() == expected
            for control in controls
        )
        if not project_is_active:
            return False
        return self._find_composer_in(controls) is not None

    def _destination_is_ready_in(
        self,
        window,
        project_name: str,
        *,
        temporary_chat: bool,
    ) -> bool:
        return (
            self._temporary_chat_is_ready_in(window)
            if temporary_chat
            else self._project_chat_is_ready_in(window, project_name)
        )

    def _project_composer_transition_is_ready(
        self,
        window,
        previous_composer,
    ) -> bool:
        refreshed = self._refresh_chatgpt_window() or window
        controls = self._descendants(refreshed)
        if controls is None:
            return False
        chatgpt_mode_is_active = any(
            control.element_info.control_type == "Button"
            and (control.element_info.name or "").startswith(
                self.MODE_SWITCH_PREFIX
            )
            and (control.element_info.name or "").endswith("ChatGPT")
            for control in controls
        )
        if not chatgpt_mode_is_active:
            return False
        composer = self._find_composer_in(controls)
        if composer is None:
            return False
        info = composer.element_info
        if not (
            bool(getattr(info, "enabled", True))
            and bool(getattr(info, "visible", True))
        ):
            return False
        return self._composer_signature_for_control(composer) != previous_composer

    def _composer_signature(self, window):
        controls = self._descendants(window)
        if controls is None:
            return None
        composer = self._find_composer_in(controls)
        if composer is None:
            return None
        return self._composer_signature_for_control(composer)

    @staticmethod
    def _composer_signature_for_control(composer):
        info = composer.element_info
        runtime_id = tuple(getattr(info, "runtime_id", ()) or ())
        try:
            rectangle = composer.rectangle()
            bounds = (
                int(rectangle.left),
                int(rectangle.top),
                int(rectangle.right),
                int(rectangle.bottom),
            )
        except Exception:
            bounds = None
        identity = runtime_id or ("object", id(composer))
        return (
            identity,
            info.control_type or "",
            (info.name or "").strip(),
            info.class_name or "",
            bounds,
        )

    def _find_composer(self, window):
        controls = self._descendants(window)
        if controls is None:
            return None
        return self._find_composer_in(controls)

    def _find_composer_in(self, controls):
        available_controls = []
        for control in controls:
            try:
                if control.element_info.control_type not in ("Edit", "Document"):
                    continue
            except Exception:
                continue
            if self._control_is_available(control):
                available_controls.append(control)
        named = self._find_named_control_in(
            available_controls,
            names=self.COMPOSER_NAMES,
            control_types=("Edit", "Document"),
        )
        if named is not None:
            return named

        # The current ChatGPT desktop app exposes its contenteditable message
        # composer as an Edit control with class "ProseMirror". Keep this
        # fallback deliberately narrow so search boxes and other edits are never
        # treated as the message composer.
        for control in available_controls:
            if self._is_prosemirror_composer(control):
                return control
        return None

    @staticmethod
    def _control_is_available(control) -> bool:
        try:
            return bool(
                getattr(control.element_info, "enabled", True)
            ) and bool(
                getattr(control.element_info, "visible", True)
            )
        except Exception:
            # Chromium replaces UIA nodes while navigating. A wrapper can go
            # stale between descendants() and reading its state; skip it and
            # allow the freshly enumerated composer to win instead.
            return False

    def _is_prosemirror_composer(self, composer) -> bool:
        if composer.element_info.control_type != "Edit":
            return False
        class_tokens = {
            token.casefold()
            for token in (composer.element_info.class_name or "").split()
        }
        return bool(class_tokens.intersection(self.COMPOSER_CLASSES))

    def _submit_verified_prompt(self, window, composer) -> None:
        if not self._is_prosemirror_composer(composer):
            composer.set_focus()
            self.send_keys("{ENTER}", pause=0.02)
            return
        send_button = self._wait_for_send_button(window, 1.25)
        if send_button is None:
            # Electron can render a keyboard paste before React updates the
            # composer state. A no-op edit emits the missing input event.
            composer.set_focus()
            composer.type_keys(
                "{SPACE}{BACKSPACE}",
                pause=0.02,
                set_foreground=True,
            )
            send_button = self._wait_for_send_button(window, 1.25)
        if send_button is not None:
            self._mark_selector(SEND.identifier)
            self._activate_control(send_button)
            return
        composer.set_focus()
        self.send_keys("{ENTER}", pause=0.02)

    def _confirm_submission(
        self,
        window,
        composer,
        prompt: str,
        baseline: tuple[str, ...],
    ) -> bool:
        if self._native_window_handle(window) is None:
            return True
        deadline = time.monotonic() + min(max(self.timeout_seconds, 1.0), 5.0)
        while time.monotonic() < deadline:
            current = self._refresh_chatgpt_window() or window
            controls = self._descendants(current) or []
            if self._response_is_generating(controls):
                return True
            if set(self._response_control_tokens(current)) - set(baseline):
                return True
            refreshed_composer = self._find_composer(current) or composer
            value = self._read_composer_text(refreshed_composer)
            if value is not None and (
                not value.strip()
                or self._normalise_composer_text(value)
                != self._normalise_composer_text(prompt)
            ):
                return True
            self._sleep(0.1, honour_cancel=False)
        return False

    def _response_control_tokens(self, window) -> tuple[str, ...]:
        controls = self._descendants(window) or []
        tokens: list[str] = []
        copy_index = 0
        for control in controls:
            info = getattr(control, "element_info", None)
            if (
                info is None
                or getattr(info, "control_type", "") != "Button"
                or str(getattr(info, "name", "") or "").strip().casefold()
                not in self.RESPONSE_COPY_NAMES
            ):
                continue
            tokens.append(self._response_control_token(control, copy_index))
            copy_index += 1
        return tuple(tokens)

    def _user_message_control_tokens(self, window) -> tuple[str, ...]:
        controls = self._descendants(window) or []
        tokens: list[str] = []
        for index, control in enumerate(controls):
            info = getattr(control, "element_info", None)
            name = " ".join(
                str(getattr(info, "name", "") or "").strip().casefold().split()
            )
            if (
                str(getattr(info, "control_type", "")) != "Button"
                or name not in self.USER_MESSAGE_COPY_NAMES
            ):
                continue
            tokens.append(self._stable_control_token(control, index))
        return tuple(tokens)

    def _build_response_anchor(self, window, prompt: str) -> ResponseAnchor:
        controls = self._descendants(window) or []
        destination_kind, destination_name = self._destination_semantic_state(
            controls
        )
        # Test doubles and other non-native wrappers cannot provide stable UIA
        # identity. Preserve the legacy empty baseline for those objects while
        # requiring identity-based correlation for a real ChatGPT window.
        baseline = (
            self._response_control_tokens(window)
            if self._native_window_handle(window) is not None
            else ()
        )
        return ResponseAnchor(
            destination_token=self._destination_token(window, controls),
            destination_kind=destination_kind,
            destination_name=destination_name,
            destination_hwnd=self._native_window_handle(window) or 0,
            baseline_tokens=baseline,
            user_message_baseline_tokens=(
                self._user_message_control_tokens(window)
                if self._native_window_handle(window) is not None
                else ()
            ),
            prompt_digest=self._text_digest(prompt),
            submitted_message_token="",
        )

    def _destination_token(self, window, controls=None) -> str:
        controls = list(controls if controls is not None else self._descendants(window) or [])
        context: list[str] = [str(self._native_window_handle(window) or 0)]
        semantic_context: set[str] = set()
        for control in controls:
            try:
                info = control.element_info
                name = " ".join(str(info.name or "").strip().split())
                lowered = name.casefold()
                project_context = lowered.startswith(
                    self.PROJECT_CHANGE_PREFIX.casefold()
                ) or lowered.startswith(
                    self.PROJECT_NEW_CHAT_PREFIX.casefold()
                )
                temporary_context = (
                    lowered == self.TEMPORARY_CHAT_OFF_NAME.casefold()
                )
                if project_context or temporary_context:
                    if project_context:
                        self._mark_selector(PROJECT_DESTINATION.identifier)
                    else:
                        self._mark_selector(TEMPORARY_CHAT.identifier)
                    semantic_context.add(
                        ("project:" if project_context else "temporary:")
                        + lowered
                    )
            except Exception:
                continue
        composer = self._find_composer_in(controls)
        if composer is not None:
            semantic_context.add("composer:" + COMPOSER.identifier)
        context.extend(sorted(semantic_context))
        return hashlib.sha256("\x1f".join(context).encode("utf-8")).hexdigest()

    def _destination_semantic_state(self, controls) -> tuple[str, str]:
        for control in controls:
            info = getattr(control, "element_info", None)
            name = " ".join(str(getattr(info, "name", "") or "").split())
            lowered = name.casefold()
            for prefix in (
                self.PROJECT_CHANGE_PREFIX,
                self.PROJECT_NEW_CHAT_PREFIX,
                self.PROJECT_START_CHAT_PREFIX,
            ):
                if lowered.startswith(prefix.casefold()):
                    return "project", name[len(prefix) :].strip().casefold()
        if any(
            " ".join(
                str(getattr(getattr(control, "element_info", None), "name", "") or "")
                .strip()
                .casefold()
                .split()
            )
            == self.TEMPORARY_CHAT_OFF_NAME.casefold()
            for control in controls
        ):
            return "temporary", ""
        return "chat", ""

    def _destination_conflicts(
        self,
        window,
        controls,
        anchor: ResponseAnchor,
    ) -> bool:
        current_hwnd = self._native_window_handle(window) or 0
        if (
            anchor.destination_hwnd
            and current_hwnd
            and current_hwnd != anchor.destination_hwnd
        ):
            return True
        if not anchor.destination_kind:
            return bool(
                anchor.destination_token
                and self._destination_token(window, controls)
                != anchor.destination_token
            )
        current_kind, current_name = self._destination_semantic_state(controls)
        names = {
            " ".join(
                str(getattr(getattr(control, "element_info", None), "name", "") or "")
                .strip()
                .casefold()
                .split()
            )
            for control in controls
        }
        temporary_explicitly_off = (
            self.TEMPORARY_CHAT_ON_NAME.casefold() in names
        )
        if anchor.destination_kind == "temporary":
            return bool(
                current_kind == "project" or temporary_explicitly_off
            )
        if anchor.destination_kind == "project":
            return bool(
                current_kind == "temporary"
                or (
                    current_kind == "project"
                    and current_name != anchor.destination_name
                )
            )
        return current_kind in {"temporary", "project"}

    @staticmethod
    def _text_digest(value: str) -> str:
        normalised = ChatGPTDesktop._normalise_composer_text(value).strip()
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    @classmethod
    def _control_text(cls, control) -> str:
        info = getattr(control, "element_info", None)
        candidates = [str(getattr(info, "name", "") or "")]
        for method_name in ("window_text", "text_block", "get_value"):
            method = getattr(control, method_name, None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception:
                continue
            if isinstance(value, str):
                candidates.append(value)
        return max(candidates, key=len, default="")

    def _submitted_message_index(
        self,
        controls,
        anchor: ResponseAnchor,
    ) -> int | None:
        match = self._submitted_message_match(controls, anchor)
        return match[0] if match is not None else None

    def _submitted_message_match(
        self,
        controls,
        anchor: ResponseAnchor,
    ) -> tuple[int, object] | None:
        if anchor.submitted_message_token:
            for index, control in enumerate(controls):
                try:
                    if (
                        self._stable_control_token(control, index)
                        == anchor.submitted_message_token
                    ):
                        return index, control
                except Exception:
                    continue
            return None
        if not anchor.prompt_digest:
            return None
        found: tuple[int, object] | None = None
        for index, control in enumerate(controls):
            info = getattr(control, "element_info", None)
            if str(getattr(info, "control_type", "")) in {"Edit", "Button"}:
                continue
            try:
                if self._text_digest(self._control_text(control)) != anchor.prompt_digest:
                    continue
                found = (index, control)
            except Exception:
                continue
        return found

    @staticmethod
    def _control_parent(control):
        parent = getattr(control, "parent", None)
        if not callable(parent):
            return None
        try:
            return parent()
        except Exception:
            return None

    def _control_ancestor_tokens(self, control) -> tuple[str, ...]:
        tokens: list[str] = []
        current = control
        for index in range(12):
            current = self._control_parent(current)
            if current is None:
                break
            info = getattr(current, "element_info", None)
            control_type = str(getattr(info, "control_type", ""))
            if control_type == "Window":
                break
            token = self._stable_control_token(current, -(index + 2))
            if token in tokens:
                break
            tokens.append(token)
        return tuple(tokens)

    def _anchor_submitted_message(
        self,
        window,
        anchor: ResponseAnchor | None,
    ) -> ResponseAnchor | None:
        if anchor is None or anchor.submitted_message_token:
            return anchor
        controls = self._descendants(window) or []
        match = self._submitted_message_match(controls, anchor)
        owner_index = -1
        owner_control = None
        if match is not None:
            index, control = match
            owner_index = index
            owner_control = control
            for candidate_index in range(index + 1, len(controls)):
                candidate = controls[candidate_index]
                info = getattr(candidate, "element_info", None)
                candidate_name = " ".join(
                    str(getattr(info, "name", "") or "")
                    .strip()
                    .casefold()
                    .split()
                )
                if (
                    str(getattr(info, "control_type", "")) == "Button"
                    and candidate_name in self.USER_MESSAGE_COPY_NAMES
                ):
                    owner_index = candidate_index
                    owner_control = candidate
                    self._mark_selector(USER_MESSAGE_COPY.identifier)
                    break
        else:
            baseline = set(anchor.user_message_baseline_tokens)
            new_user_controls: list[tuple[int, object]] = []
            for candidate_index, candidate in enumerate(controls):
                info = getattr(candidate, "element_info", None)
                candidate_name = " ".join(
                    str(getattr(info, "name", "") or "")
                    .strip()
                    .casefold()
                    .split()
                )
                if (
                    str(getattr(info, "control_type", "")) != "Button"
                    or candidate_name not in self.USER_MESSAGE_COPY_NAMES
                ):
                    continue
                token = self._stable_control_token(candidate, candidate_index)
                if token not in baseline:
                    new_user_controls.append((candidate_index, candidate))
            if len(new_user_controls) == 1:
                owner_index, owner_control = new_user_controls[0]
                self._mark_selector(USER_MESSAGE_COPY.identifier)
        if owner_control is None:
            return anchor
        ancestors = self._control_ancestor_tokens(owner_control)
        return replace(
            anchor,
            submitted_message_token=self._stable_control_token(
                owner_control,
                owner_index,
            ),
            # The outermost non-window ancestor is the narrowest stable
            # conversation container that can also own the following assistant
            # response. The submitted message token remains the primary anchor.
            conversation_container_token=(ancestors[-1] if ancestors else ""),
        )

    def _copy_shares_response_container(
        self,
        control,
        anchor: ResponseAnchor,
    ) -> bool:
        if not anchor.conversation_container_token:
            return True
        return anchor.conversation_container_token in self._control_ancestor_tokens(
            control
        )

    def _capture_clipboard_state(
        self,
    ) -> tuple[str | None, ClipboardSnapshot | None]:
        self.clipboard_owned_sequence = None
        self.clipboard_write_owned = False
        snapshot = None
        if self.enforce_clipboard_sequence:
            try:
                snapshot = self.clipboard_snapshot_factory()
            except Exception:
                LOGGER.warning(
                    "Could not retain the complete clipboard before automation",
                    exc_info=True,
                )
        return self.clipboard_reader(), snapshot

    @staticmethod
    def _discard_clipboard_snapshot(
        snapshot: ClipboardSnapshot | None,
    ) -> None:
        if snapshot is None:
            return
        try:
            snapshot.close()
        except Exception:
            LOGGER.debug("Could not release clipboard snapshot", exc_info=True)

    def _restore_clipboard_if_unchanged(
        self,
        value: str | None,
        *,
        snapshot: ClipboardSnapshot | None = None,
        expected: str | None = None,
    ) -> bool:
        owned_sequence = self.clipboard_owned_sequence
        if owned_sequence is None:
            if (
                snapshot is not None
                or self.enforce_clipboard_sequence
                or not self.clipboard_write_owned
            ):
                self._discard_clipboard_snapshot(snapshot)
                return False
        read_deadline = time.monotonic() + 1.0
        while True:
            sequence_before = self._read_clipboard_sequence()
            if owned_sequence is not None and (
                sequence_before is None
                or sequence_before != owned_sequence
            ):
                self._discard_clipboard_snapshot(snapshot)
                return False
            try:
                current = self.clipboard_reader()
            except Exception:
                current = None
            sequence_after = self._read_clipboard_sequence()
            if owned_sequence is not None and (
                sequence_after is None
                or sequence_after != owned_sequence
            ):
                self._discard_clipboard_snapshot(snapshot)
                return False
            if expected is None or current == expected:
                break
            # read_clipboard_text returns None both for a temporarily busy
            # clipboard and for a clipboard without Unicode text. Retry only
            # while PromptMeld's exact sequence remains current. A different
            # non-empty value or any sequence change belongs to someone else.
            if current is not None or time.monotonic() >= read_deadline:
                self._discard_clipboard_snapshot(snapshot)
                return False
            self._pulse()
            time.sleep(0.025)
        if snapshot is not None:
            snapshot.mark_owned(owned_sequence)
            return snapshot.restore_if_owned()
        if value is None:
            return False
        self._write_clipboard(value)
        return True

    def _read_clipboard_sequence(self) -> int | None:
        try:
            value = self.clipboard_sequence_reader()
            return None if value is None else int(value)
        except Exception:
            return None

    def _write_clipboard(self, value: str) -> None:
        self.clipboard_writer(value)
        self.clipboard_write_owned = True
        self.clipboard_owned_sequence = self._read_clipboard_sequence()

    def _claim_current_clipboard(self, expected: str) -> bool:
        sequence_before = self._read_clipboard_sequence()
        try:
            current = self.clipboard_reader()
        except Exception:
            return False
        sequence_after = self._read_clipboard_sequence()
        if current != expected:
            return False
        if (
            sequence_before is not None
            and sequence_after is not None
            and sequence_before != sequence_after
        ):
            return False
        self.clipboard_write_owned = True
        self.clipboard_owned_sequence = sequence_after
        return True

    def _wait_for_send_button(self, window, timeout_seconds: float):
        names = {name.casefold() for name in self.SEND_BUTTON_NAMES}
        return self._wait_for_refreshed_control(
            window,
            lambda control: (
                control.element_info.control_type == "Button"
                and (control.element_info.name or "").strip().casefold()
                in names
                and self._control_is_available(control)
            ),
            timeout_seconds=timeout_seconds,
        )

    def _find_chat_composer(self, window):
        controls = self._descendants(window)
        if controls is None:
            return None
        return self._find_named_control_in(
            controls,
            names=self.COMPOSER_NAMES,
            control_types=("Edit", "Document"),
        )

    def _set_composer_prompt(
        self,
        composer,
        prompt: str,
        *,
        window=None,
        project_name: str | None = None,
        temporary_chat: bool = False,
    ) -> str:
        """Insert and verify a prompt without trusting a blind global paste."""

        # Chromium exposes ChatGPT's contenteditable ProseMirror composer as an
        # Edit control, but its synchronous UIA ValuePattern.SetValue call can
        # stop responding indefinitely. Paste through that verified control
        # instead. Ordinary native Edit controls may still use direct UIA text.
        if not self._is_prosemirror_composer(composer):
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
                    if self._wait_for_composer_prompt(
                        composer,
                        prompt,
                        window=window,
                    ):
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

        self._write_clipboard(prompt)
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
                if self._composer_prompt_is_verified(
                    composer, prompt, window=window
                ):
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
            if window is not None:
                current_window = self._refresh_chatgpt_window() or window
                if (
                    (project_name is not None or temporary_chat)
                    and not self._destination_is_ready_in(
                        current_window,
                        project_name or "",
                        temporary_chat=temporary_chat,
                    )
                ):
                    raise ChatGPTAutomationError(
                        "The ChatGPT destination changed before the paste retry."
                    )
                current_window.set_focus()
                composer = self._find_composer(current_window) or composer
            composer.set_focus()
            self.send_keys("^a", pause=0.02)
            self.send_keys("^v", pause=0.02)
            self._report_progress(
                "inserting-prompt",
                "Verifying the complete prompt in ChatGPT",
            )
            if self._composer_prompt_is_verified(
                composer, prompt, window=window
            ):
                LOGGER.info(
                    "Pasted and verified prompt through focused keyboard input"
                )
                return "clipboard"
        except ChatGPTAutomationError:
            raise
        except Exception:
            LOGGER.debug(
                "Focused ChatGPT composer paste was unavailable",
                exc_info=True,
            )

        raise ChatGPTAutomationError(
            "The verified ChatGPT composer did not accept the generated prompt."
        )

    def _composer_prompt_is_verified(
        self,
        composer,
        prompt: str,
        *,
        window=None,
    ) -> bool:
        if self._is_prosemirror_composer(composer):
            return self._verify_prosemirror_prompt_via_clipboard(
                composer,
                prompt,
            )
        return self._wait_for_composer_prompt(
            composer,
            prompt,
            window=window,
        )

    def _verify_prosemirror_prompt_via_clipboard(
        self,
        composer,
        prompt: str,
    ) -> bool:
        """Verify Chromium's editor without its unreliable UIA value read."""

        type_keys = getattr(composer, "type_keys", None)
        if not callable(type_keys):
            return False
        marker = f"PromptMeld clipboard verification {time.monotonic_ns()}"
        try:
            self._write_clipboard(marker)
            type_keys(
                "^a^c",
                pause=0.02,
                set_foreground=True,
            )
            deadline = time.monotonic() + min(
                max(self.timeout_seconds, 0.2),
                0.75,
            )
            copied = self.clipboard_reader()
            while copied == marker and time.monotonic() < deadline:
                self._sleep(0.02)
                copied = self.clipboard_reader()
            verified = (
                isinstance(copied, str)
                and self._normalise_composer_text(copied)
                == self._normalise_composer_text(prompt)
            )
            if verified:
                self._claim_current_clipboard(copied)
                # Copy leaves the whole editor selected. Collapse the selection
                # so Enter submits rather than replacing the verified prompt.
                type_keys(
                    "{END}",
                    pause=0.02,
                    set_foreground=True,
                )
                return True
        except Exception:
            LOGGER.debug(
                "ChatGPT ProseMirror clipboard verification was unavailable",
                exc_info=True,
            )

        # Leave the known prompt in the editor for the existing retry path.
        try:
            self._write_clipboard(prompt)
            type_keys(
                "^v",
                pause=0.02,
                set_foreground=True,
            )
        except Exception:
            LOGGER.debug(
                "Could not restore the prompt after clipboard verification",
                exc_info=True,
            )
        return False

    def _wait_for_composer_prompt(
        self,
        composer,
        prompt: str,
        *,
        window=None,
    ) -> bool:
        deadline = time.monotonic() + min(self.timeout_seconds, 2.0)
        current = composer
        while time.monotonic() < deadline:
            value = self._read_composer_text(current)
            if (
                value is not None
                and self._normalise_composer_text(value)
                == self._normalise_composer_text(prompt)
            ):
                return True
            if window is not None:
                refreshed = self._refresh_chatgpt_window() or window
                current = self._find_composer(refreshed) or current
            self._sleep(0.05)
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

    def _copy_latest_response(
        self,
        window,
        prompt: str,
        *,
        baseline: tuple[str, ...] = (),
        anchor: ResponseAnchor | None = None,
    ) -> str:
        """Use ChatGPT's verified response Copy control to get plain text."""

        started = time.monotonic()
        deadline = (
            None
            if self.response_timeout_seconds is None
            else started
            + max(self.timeout_seconds, self.response_timeout_seconds)
        )
        next_status_update = started + 30.0
        sentinel = f"__PROMPTMELD_OUTPUT_NOT_READY_{self.run_id}__"
        generation_seen = False
        generation_active = False
        completed_checks = 0
        attempted_tokens: set[str] = set()
        active_anchor = anchor or ResponseAnchor(
            destination_token=self._destination_token(window),
            baseline_tokens=tuple(baseline),
            prompt_digest=self._text_digest(prompt),
        )
        baseline_tokens = set(active_anchor.baseline_tokens)
        legacy_baseline_count = (
            len(active_anchor.baseline_tokens)
            if active_anchor.baseline_tokens
            and all(
                str(token).partition(":")[0].isdigit()
                for token in active_anchor.baseline_tokens
            )
            else 0
        )
        while deadline is None or time.monotonic() < deadline:
            self._check_cancelled()
            now = time.monotonic()
            if now >= next_status_update:
                elapsed = int(now - started)
                self._report_progress(
                    "waiting-for-response",
                    f"Still waiting for ChatGPT ({elapsed} seconds). You can "
                    "continue working in another window.",
                )
                next_status_update = now + 30.0
            current = self._refresh_chatgpt_window() or window
            controls = self._descendants(current) or []
            if self._destination_conflicts(
                current,
                controls,
                active_anchor,
            ):
                raise ChatGPTAutomationError(
                    "The active ChatGPT conversation changed while waiting for the response.",
                    code="response_destination_changed",
                    retry_mode="inspect",
                )
            refreshed_anchor = self._anchor_submitted_message(
                current,
                active_anchor,
            )
            if refreshed_anchor is not None:
                active_anchor = refreshed_anchor
                self.response_anchor = refreshed_anchor
            submitted_match = self._submitted_message_match(
                controls,
                active_anchor,
            )
            copy_controls = [
                control
                for control in controls
                if (
                    control.element_info.control_type == "Button"
                    and (control.element_info.name or "").strip().casefold()
                    in self.RESPONSE_COPY_NAMES
                )
            ]
            eligible = []
            if active_anchor.response_control_token:
                for index, control in enumerate(copy_controls):
                    token = self._response_control_token(control, index)
                    if (
                        token == active_anchor.response_control_token
                        and token not in attempted_tokens
                    ):
                        eligible.append((token, control))
                        break
            submitted_message_index = (
                submitted_match[0] if submitted_match is not None else None
            )
            if (
                not active_anchor.response_control_token
                and submitted_message_index is not None
            ):
                next_user_message_index = len(controls)
                for control_index in range(
                    submitted_message_index + 1,
                    len(controls),
                ):
                    info = getattr(controls[control_index], "element_info", None)
                    name = " ".join(
                        str(getattr(info, "name", "") or "")
                        .strip()
                        .casefold()
                        .split()
                    )
                    if (
                        str(getattr(info, "control_type", "")) == "Button"
                        and name in self.USER_MESSAGE_COPY_NAMES
                    ):
                        next_user_message_index = control_index
                        break
                for index, control in enumerate(copy_controls):
                    token = self._response_control_token(control, index)
                    if (
                        token in attempted_tokens
                        or token in baseline_tokens
                        or index < legacy_baseline_count
                    ):
                        continue
                    try:
                        control_index = controls.index(control)
                    except ValueError:
                        continue
                    if not (
                        submitted_message_index < control_index < next_user_message_index
                    ):
                        continue
                    if not self._copy_shares_response_container(
                        control,
                        active_anchor,
                    ):
                        continue
                    active_anchor = replace(
                        active_anchor,
                        response_control_token=token,
                    )
                    self.response_anchor = active_anchor
                    self._mark_selector(RESPONSE_COPY.identifier)
                    eligible = [(token, control)]
                    break
            elif (
                not active_anchor.response_control_token
                and self._native_window_handle(current) is None
            ):
                # Non-native test doubles and legacy wrappers cannot expose a
                # stable submitted-message identity. Retain the baseline-only
                # behavior for those objects; real ChatGPT windows always use
                # the ownership path above.
                eligible = [
                    (self._response_control_token(control, index), control)
                    for index, control in enumerate(copy_controls)
                    if (
                        self._response_control_token(control, index)
                        not in attempted_tokens
                        and self._response_control_token(control, index)
                        not in baseline_tokens
                        and index >= legacy_baseline_count
                    )
                ]
            if self._native_window_handle(current) is not None and (
                submitted_match is None
                and not active_anchor.response_control_token
            ):
                if (
                    active_anchor.submitted_message_token
                    and "|Button|" not in active_anchor.submitted_message_token
                    and self._submitted_message_match(
                        controls,
                        replace(active_anchor, submitted_message_token=""),
                    )
                    is not None
                ):
                    raise ChatGPTAutomationError(
                        "The submitted ChatGPT message is no longer present with "
                        "its verified identity inside the conversation.",
                        code="response_owner_changed",
                        retry_mode="inspect",
                    )
                # Chromium virtualizes off-screen message text and controls.
                # Absence alone is not an ownership change; keep waiting for
                # the anchored user-message control to re-enter the UIA tree.
                self._sleep(0.15)
                continue
            if self._response_is_generating(controls):
                generation_seen = True
                generation_active = True
                completed_checks = 0
                self._sleep(0.15)
                continue
            generation_active = False
            if generation_seen:
                completed_checks += 1
                if completed_checks < 2:
                    self._sleep(0.15)
                    continue
            for token, control in eligible:
                attempted_tokens.add(token)
                first = self._read_verified_copy_control(
                    control,
                    sentinel + "_1",
                    prompt,
                    window=current,
                )
                if first is None or not self._clipboard_is_still_owned():
                    continue
                second = self._read_verified_copy_control(
                    control,
                    sentinel + "_2",
                    prompt,
                    window=current,
                )
                if second is not None and self._normalise_composer_text(
                    second
                ) == self._normalise_composer_text(first):
                    self._mark_selector(RESPONSE_COPY.identifier)
                    return second
            if (
                self._native_window_handle(current) is not None
                and active_anchor.response_control_token
                and active_anchor.response_control_token in attempted_tokens
            ):
                raise ChatGPTAutomationError(
                    "ChatGPT exposed the verified response Copy control, but "
                    "its clipboard action could not be completed.",
                    code="response_copy_failed",
                    retry_mode="response",
                )
            self._sleep(0.15)
        if generation_active:
            raise ChatGPTAutomationError(
                "ChatGPT still exposed an active generation control when the "
                "configured response timeout ended.",
                code="response_still_generating",
                retry_mode="response",
            )
        if active_anchor.response_control_token and attempted_tokens:
            raise ChatGPTAutomationError(
                "ChatGPT exposed the verified response Copy control, but it did "
                "not produce two matching clipboard reads.",
                code="response_copy_failed",
                retry_mode="response",
            )
        if (
            active_anchor.submitted_message_token
            and not active_anchor.response_control_token
        ):
            raise ChatGPTAutomationError(
                "The submitted ChatGPT message is no longer present with a "
                "response Copy control that PromptMeld can verify.",
                code="response_owner_changed",
                retry_mode="inspect",
            )
        raise ChatGPTAutomationError(
            "ChatGPT did not expose a completed response Copy control before "
            "the configured response timeout.",
            code="response_unavailable",
            retry_mode="response",
        )

    def _read_verified_copy_control(
        self,
        control,
        sentinel: str,
        prompt: str,
        *,
        window=None,
    ) -> str | None:
        self._write_clipboard(sentinel)
        sentinel_sequence = self.clipboard_owned_sequence
        if not self._activate_control(control, allow_focus=False):
            LOGGER.info(
                "Response Copy activation unavailable selector=%s",
                RESPONSE_COPY.identifier,
            )
            return None
        # ChatGPT handles Copy through Chromium's asynchronous clipboard API.
        # UIA Invoke can return well before that write reaches the Windows
        # clipboard, especially while the response view is still settling.
        # Keep this bounded so a broken control cannot stall cancellation or
        # the helper watchdog.
        copied = self._wait_for_clipboard_sequence_change(
            sentinel_sequence,
            timeout_seconds=1.5,
        )
        if (
            not copied
            and window is not None
            and self._native_window_handle(window) is not None
        ):
            # Chromium can animate UIA Invoke as a successful button press but
            # still decline its asynchronous clipboard write when ChatGPT is
            # not foreground. Retrying Copy is idempotent. Use real keyboard
            # input only after proving that this is the same verified top-level
            # ChatGPT window, and keep it foreground until the clipboard write
            # has crossed the browser boundary.
            previous_foreground = self.foreground_window_reader()
            target_handle = self._native_window_handle(window)
            try:
                self._report_progress(
                    "waiting-for-response",
                    "Retrying the verified response Copy control with keyboard input",
                )
                if self._activate_response_copy_with_keyboard(window, control):
                    copied = self._wait_for_clipboard_sequence_change(
                        sentinel_sequence,
                        timeout_seconds=2.0,
                    )
                if not copied:
                    self._report_progress(
                        "waiting-for-response",
                        "Retrying the same verified response Copy control with a pointer click",
                    )
                    if self._activate_response_copy_with_pointer(window):
                        copied = self._wait_for_clipboard_sequence_change(
                            sentinel_sequence,
                            timeout_seconds=2.0,
                        )
            finally:
                self._restore_previous_foreground(
                    previous_foreground,
                    target_handle,
                )
        if not copied:
            self._report_progress(
                "waiting-for-response",
                "The verified response Copy control did not update the clipboard",
            )
            LOGGER.info(
                "Response Copy produced no clipboard change selector=%s",
                RESPONSE_COPY.identifier,
            )
            return None
        value = self._wait_for_copied_response_value(sentinel, prompt)
        if (
            not isinstance(value, str)
            or not value.strip()
            or value == sentinel
            or self._normalise_composer_text(value)
            == self._normalise_composer_text(prompt)
        ):
            self._report_progress(
                "waiting-for-response",
                "The clipboard changed, but the verified response text could not be read",
            )
            LOGGER.info(
                "Response Copy clipboard value rejected selector=%s",
                RESPONSE_COPY.identifier,
            )
            return None
        self._claim_current_clipboard(value)
        LOGGER.info(
            "Response Copy clipboard value verified selector=%s",
            RESPONSE_COPY.identifier,
        )
        return value

    def _wait_for_copied_response_value(
        self,
        sentinel: str,
        prompt: str,
    ) -> str | None:
        """Wait for Chromium's Unicode clipboard value and sequence to settle."""

        if not self.enforce_clipboard_sequence:
            value = self.clipboard_reader()
            return value if isinstance(value, str) else None

        deadline = time.monotonic() + 2.0
        stable_since: float | None = None
        stable_sequence: int | None = None
        stable_value: str | None = None
        while True:
            sequence_before = self._read_clipboard_sequence()
            value = self.clipboard_reader()
            sequence_after = self._read_clipboard_sequence()
            now = time.monotonic()
            valid = bool(
                isinstance(value, str)
                and value.strip()
                and value != sentinel
                and self._normalise_composer_text(value)
                != self._normalise_composer_text(prompt)
                and sequence_before is not None
                and sequence_before == sequence_after
            )
            if valid:
                if (
                    sequence_after == stable_sequence
                    and value == stable_value
                    and stable_since is not None
                ):
                    if now - stable_since >= 0.35:
                        return value
                else:
                    stable_sequence = sequence_after
                    stable_value = value
                    stable_since = now
            else:
                stable_sequence = None
                stable_value = None
                stable_since = None
            if now >= deadline:
                return None
            self._sleep(0.05)

    def _wait_for_clipboard_sequence_change(
        self,
        before: int | None,
        *,
        timeout_seconds: float,
    ) -> bool:
        if not self.enforce_clipboard_sequence:
            return True
        if before is None:
            return False
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        current = self._read_clipboard_sequence()
        while (
            current is not None
            and current == before
            and time.monotonic() < deadline
        ):
            self._sleep(0.05)
            current = self._read_clipboard_sequence()
        return current is not None and current != before

    def _activate_response_copy_with_keyboard(self, window, control) -> bool:
        """Use a verified foreground keyboard gesture for response Copy."""

        target_handle = self._native_window_handle(window)
        if (
            target_handle is None
            or not self.chatgpt_hwnd
            or target_handle != self.chatgpt_hwnd
        ):
            LOGGER.info(
                "Foreground response Copy rejected for an unverified window "
                "selector=%s",
                RESPONSE_COPY.identifier,
            )
            return False
        try:
            window.set_focus()
            control.set_focus()
            focus_deadline = time.monotonic() + 0.75
            foreground = self.foreground_window_reader()
            while (
                foreground != target_handle
                and time.monotonic() < focus_deadline
            ):
                self._sleep(0.05)
                foreground = self.foreground_window_reader()
            if foreground != target_handle:
                LOGGER.info(
                    "Foreground response Copy could not verify focus selector=%s",
                    RESPONSE_COPY.identifier,
                )
                return False
            if self.send_keys is None:
                self._ensure_automation_dependencies()
            self.send_keys("{ENTER}", pause=0.02)
            LOGGER.info(
                "Foreground response Copy activated selector=%s",
                RESPONSE_COPY.identifier,
            )
            return True
        except Exception:
            LOGGER.debug(
                "Foreground response Copy activation failed selector=%s",
                RESPONSE_COPY.identifier,
                exc_info=True,
            )
            return False

    def _activate_response_copy_with_pointer(self, window) -> bool:
        """Physically click only the response control retained by its anchor."""

        anchor = self.response_anchor
        expected_token = (
            anchor.response_control_token if anchor is not None else ""
        )
        target_handle = self._native_window_handle(window)
        if (
            not expected_token
            or target_handle is None
            or not self.chatgpt_hwnd
            or target_handle != self.chatgpt_hwnd
        ):
            LOGGER.info(
                "Pointer response Copy rejected for an unverified window "
                "selector=%s",
                RESPONSE_COPY.identifier,
            )
            return False
        try:
            current = self._refresh_chatgpt_window() or window
            if self._native_window_handle(current) != target_handle:
                return False
            current.set_focus()
            focus_deadline = time.monotonic() + 0.75
            foreground = self.foreground_window_reader()
            while (
                foreground != target_handle
                and time.monotonic() < focus_deadline
            ):
                self._sleep(0.05)
                foreground = self.foreground_window_reader()
            if foreground != target_handle:
                LOGGER.info(
                    "Pointer response Copy could not verify focus selector=%s",
                    RESPONSE_COPY.identifier,
                )
                return False
            controls = self._descendants(current) or []
            copy_index = 0
            owned_control = None
            for candidate in controls:
                info = getattr(candidate, "element_info", None)
                if (
                    info is None
                    or getattr(info, "control_type", "") != "Button"
                    or str(getattr(info, "name", "") or "").strip().casefold()
                    not in self.RESPONSE_COPY_NAMES
                ):
                    continue
                token = self._response_control_token(candidate, copy_index)
                copy_index += 1
                if token == expected_token:
                    owned_control = candidate
                    break
            if owned_control is None:
                LOGGER.info(
                    "Pointer response Copy could not revalidate ownership "
                    "selector=%s",
                    RESPONSE_COPY.identifier,
                )
                return False
            (self.mouse_clicker or _click_control_on_virtual_desktop)(
                owned_control
            )
            LOGGER.info(
                "Pointer response Copy activated selector=%s",
                RESPONSE_COPY.identifier,
            )
            return True
        except Exception:
            LOGGER.debug(
                "Pointer response Copy activation failed selector=%s",
                RESPONSE_COPY.identifier,
                exc_info=True,
            )
            return False

    def _restore_previous_foreground(
        self,
        previous_handle: int | None,
        target_handle: int | None,
    ) -> None:
        if (
            previous_handle is None
            or target_handle is None
            or previous_handle == target_handle
            or self.foreground_window_reader() != target_handle
        ):
            return
        _restore_foreground_window(previous_handle)

    def _clipboard_is_still_owned(self) -> bool:
        if not self.enforce_clipboard_sequence:
            return True
        owned = self.clipboard_owned_sequence
        current = self._read_clipboard_sequence()
        return owned is not None and current is not None and owned == current

    @staticmethod
    def _response_control_token(control, index: int) -> str:
        return ChatGPTDesktop._stable_control_token(control, index)

    @staticmethod
    def _stable_control_token(
        control,
        index: int,
        *,
        include_name: bool = False,
    ) -> str:
        info = getattr(control, "element_info", None)
        runtime_id = getattr(info, "runtime_id", None)
        automation_id = str(getattr(info, "automation_id", "") or "")
        handle = getattr(info, "handle", None) or getattr(control, "handle", None)
        identity = runtime_id or automation_id or handle
        if not identity:
            try:
                rectangle = control.rectangle()
                identity = (
                    int(rectangle.left),
                    int(rectangle.top),
                    int(rectangle.right),
                    int(rectangle.bottom),
                )
            except Exception:
                identity = f"fallback-{index}"
        name = str(getattr(info, "name", "") or "") if include_name else ""
        control_type = str(getattr(info, "control_type", "") or "")
        class_name = str(getattr(info, "class_name", "") or "")
        return f"{identity!s}|{control_type}|{class_name}|{name}"

    @staticmethod
    def _response_is_generating(controls) -> bool:
        """Detect response controls that ChatGPT exposes while streaming."""

        exact_names = ChatGPTDesktop.GENERATION_STOP_NAMES
        for control in controls:
            info = getattr(control, "element_info", None)
            if info is None or getattr(info, "control_type", "") != "Button":
                continue
            if not bool(getattr(info, "enabled", True)):
                continue
            if not bool(getattr(info, "visible", True)):
                continue
            name = " ".join(
                str(getattr(info, "name", "") or "")
                .strip()
                .casefold()
                .split()
            )
            if name in exact_names or (
                name.startswith("stop ")
                and any(
                    marker in name
                    for marker in ("generat", "response", "stream")
                )
            ):
                return True
        return False

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
    def _native_window_handle(window) -> int | None:
        """Read a top-level UIA wrapper's native handle when it exposes one."""

        for candidate in (
            getattr(window, "handle", None),
            getattr(getattr(window, "element_info", None), "handle", None),
        ):
            try:
                handle = int(candidate or 0)
            except (TypeError, ValueError):
                continue
            if handle:
                return handle
        return None

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
        for control in controls:
            try:
                if predicate(control):
                    return control
            except Exception:
                # Electron can invalidate individual UIA wrappers while a new
                # page is rendering. Ignore that stale candidate and continue
                # through the current accessibility snapshot.
                continue
        return None

    def _wait_for_control(
        self,
        window,
        predicate,
        timeout_seconds: float | None = None,
    ):
        timeout = (
            self.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            control = self._find_control(window, predicate)
            if control is not None:
                return control
            self._sleep(0.1)
        return None

    def _wait_for_refreshed_control(
        self,
        window,
        predicate,
        timeout_seconds: float | None = None,
    ):
        timeout = (
            self.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current_window = self._refresh_chatgpt_window() or window
            control = self._find_control(current_window, predicate)
            if control is not None:
                return control
            self._sleep(0.1)
        return None

    def _wait_for_condition(
        self,
        predicate,
        timeout_seconds: float | None = None,
    ) -> bool:
        timeout = (
            self.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            self._sleep(0.1)
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

    def _activate_control(
        self,
        control,
        *,
        allow_focus: bool = True,
    ) -> bool:
        """Activate a UIA control, keeping physical input as the last resort."""

        control_type = getattr(
            control.element_info,
            "control_type",
            "unknown",
        )
        invoke = getattr(control, "invoke", None)
        if callable(invoke):
            try:
                invoke()
                return True
            except Exception:
                LOGGER.debug(
                    "UIA Invoke unavailable for %s control",
                    control_type,
                    exc_info=True,
                )

        # UIA ButtonWrapper.click() is not a physical click: it tries the
        # Invoke pattern and then SelectionItem. Other UIA wrappers expose
        # select() directly, so retain that as a separate fallback.
        pattern_click = getattr(control, "click", None)
        if callable(pattern_click):
            try:
                pattern_click()
                return True
            except Exception:
                LOGGER.debug(
                    "UIA pattern click unavailable for %s control",
                    control_type,
                    exc_info=True,
                )

        select = getattr(control, "select", None)
        if callable(select):
            try:
                select()
                return True
            except Exception:
                LOGGER.debug(
                    "UIA SelectionItem unavailable for %s control",
                    control_type,
                    exc_info=True,
                )

        if not allow_focus:
            LOGGER.debug(
                "No background-safe activation pattern for %s control",
                control_type,
            )
            return False

        set_focus = getattr(control, "set_focus", None)
        if callable(set_focus):
            try:
                set_focus()
                if self.send_keys is None:
                    self._ensure_automation_dependencies()
                self.send_keys("{ENTER}", pause=0.02)
                return True
            except Exception:
                LOGGER.debug(
                    "Keyboard activation unavailable for %s control",
                    control_type,
                    exc_info=True,
                )

        LOGGER.warning(
            "Using physical-click fallback for verified %s control",
            control_type,
        )
        (self.mouse_clicker or _click_control_on_virtual_desktop)(control)
        return True

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
        self._pulse()
        next_stage = stage.strip() or self.current_stage
        next_checkpoint = checkpoint_for_stage(next_stage)
        if next_checkpoint != AutomationCheckpoint.PREPARING:
            self.checkpoint = next_checkpoint
            if next_checkpoint not in {
                AutomationCheckpoint.COMPLETE,
                AutomationCheckpoint.CANCELLED,
            }:
                self.submission_disposition = disposition_for_checkpoint(
                    next_checkpoint
                )
        now = time.perf_counter()
        if self.current_stage and next_stage != self.current_stage:
            elapsed_ms = (now - self.stage_started_at) * 1000
            self.timings.append(
                {
                    "stage": self.current_stage,
                    "milliseconds": round(elapsed_ms, 1),
                }
            )
            LOGGER.info(
                "Automation run=%s stage=%s completed_ms=%.1f",
                self.run_id,
                self.current_stage,
                elapsed_ms,
            )
            self.stage_started_at = now
        self.current_stage = next_stage
        if self.current_stage not in self.stage_attempts:
            self.stage_attempts[self.current_stage] = 1
        elif message.casefold().startswith("retry"):
            self.stage_attempts[self.current_stage] += 1
        LOGGER.info(
            "Automation run=%s stage=%s attempt=%s",
            self.run_id,
            self.current_stage,
            self.stage_attempts[self.current_stage],
        )
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(stage, message)
        except Exception:
            LOGGER.debug(
                "Automation progress callback failed",
                exc_info=True,
            )

    def _fallback(
        self,
        prompt: str,
        message: str,
        *,
        failure_code: str = "automation_failed",
        retry_mode: str = "delivery",
    ) -> SubmissionResult:
        disposition = (
            SubmissionDisposition.CONFIRMED
            if self.submission_confirmed
            else (
                SubmissionDisposition.MAYBE_SUBMITTED
                if self.send_started
                else SubmissionDisposition.NOT_ATTEMPTED
            )
        )
        fallback_copied = False
        if disposition == SubmissionDisposition.NOT_ATTEMPTED:
            self._write_clipboard(prompt)
            fallback_copied = True
        LOGGER.warning(
            "Automation run=%s failed_stage=%s failure_code=%s "
            "submission_confirmed=%s elapsed_ms=%.1f",
            self.run_id,
            self.current_stage,
            failure_code,
            self.submission_confirmed,
            (time.perf_counter() - self.stage_started_at) * 1000,
        )
        return SubmissionResult(
            submitted=False,
            prepared=False,
            fallback_copied=fallback_copied,
            message=message,
            run_id=self.run_id,
            failed_stage=self.current_stage,
            failure_code=failure_code,
            submission_confirmed=self.submission_confirmed,
            retry_mode=retry_mode,
            recoverable=True,
            response_baseline=self.response_baseline,
            checkpoint=(
                AutomationCheckpoint.SEND_STARTED
                if disposition == SubmissionDisposition.MAYBE_SUBMITTED
                else self.checkpoint
            ),
            submission_disposition=disposition,
            recovery_actions=recovery_actions_for(disposition),
            response_anchor=self.response_anchor,
        )
