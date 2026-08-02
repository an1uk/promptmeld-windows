from __future__ import annotations

from dataclasses import dataclass

from promptmeld.chatgpt import (
    ChatGPTAutomationError,
    ChatGPTDesktop,
    _click_control_on_virtual_desktop,
)


@dataclass
class ElementInfo:
    name: str
    control_type: str
    class_name: str = ""
    enabled: bool = True
    visible: bool = True
    automation_id: str = ""


class FakeControl:
    def __init__(
        self,
        name: str,
        control_type: str,
        events: list[str],
        class_name: str = "",
        enabled: bool = True,
        visible: bool = True,
        automation_id: str = "",
        on_click=None,
    ):
        self.element_info = ElementInfo(
            name,
            control_type,
            class_name,
            enabled,
            visible,
            automation_id,
        )
        self.events = events
        self.on_click = on_click

    def click_input(self):
        self.events.append(f"mouse:{self.element_info.name}")
        if self.on_click is not None:
            self.on_click()

    def click(self):
        self.events.append(f"click:{self.element_info.name}")
        if self.on_click is not None:
            self.on_click()

    def set_focus(self):
        self.events.append(f"focus:{self.element_info.name}")


class FakeComposer(FakeControl):
    def __init__(self, events: list[str]):
        super().__init__("Message ChatGPT", "Edit", events)
        self.value = ""

    def set_edit_text(self, text: str):
        self.events.append("set-text:Message ChatGPT")
        self.value = text

    def get_value(self):
        return self.value


class FakeWindow(FakeControl):
    def __init__(self, controls, events):
        super().__init__("ChatGPT", "Window", events)
        self.controls = controls

    def descendants(self):
        return self.controls


class FakeDesktop:
    def __init__(self, window):
        self.window = window

    def windows(self, **kwargs):
        return [self.window]


def test_submit_navigates_project_and_restores_clipboard():
    events: list[str] = []
    clipboard: list[str] = []
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events == [
        "focus:ChatGPT",
        "click:New chat",
        "click:Chat",
        "click:WritingLauncher",
        "set-text:Message ChatGPT",
        "focus:Message ChatGPT",
        "keys:{ENTER}",
    ]
    assert clipboard == ["selected source"]


def test_submit_copies_generated_response_to_clipboard():
    events: list[str] = []
    clipboard = {"text": "selected source"}
    copy_button = FakeControl("Copy", "Button", events)
    copy_button.on_click = lambda: clipboard.update(text="Generated answer")
    controls = [
        FakeControl("Switch mode, current mode: ChatGPT", "Button", events),
        FakeControl("New chat", "Button", events, class_name="sidebar-item"),
        FakeControl("Chat", "Button", events, class_name="text-token-text-primary"),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl("Change project: WritingLauncher", "Button", events),
        FakeComposer(events),
        copy_button,
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "complete prompt",
        "WritingLauncher",
        copy_generated_text=True,
    )

    assert result.submitted is True
    assert result.generated_text_copied is True
    assert clipboard["text"] == "Generated answer"
    assert "The generated text is on the clipboard." in result.message


def test_prepare_only_inserts_prompt_without_pressing_enter():
    events: list[str] = []
    clipboard: list[str] = []
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "complete prompt",
        "WritingLauncher",
        auto_submit=False,
    )

    assert result.submitted is False
    assert result.prepared is True
    assert result.fallback_copied is False
    assert "model or reasoning level" in result.message
    assert "set-text:Message ChatGPT" in events
    assert "keys:{ENTER}" not in events
    assert clipboard == ["selected source"]


def test_temporary_chat_skips_project_and_prepares_prompt():
    events: list[str] = []
    clipboard: list[str] = []
    composer = FakeComposer(events)
    temporary_toggle = FakeControl(
        "Turn on temporary chat",
        "Button",
        events,
    )

    def enable_temporary_chat():
        temporary_toggle.element_info.name = "Turn off temporary chat"

    temporary_toggle.on_click = enable_temporary_chat
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("PromptMeld", "Button", events),
        temporary_toggle,
        composer,
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "complete prompt",
        "PromptMeld",
        auto_submit=False,
        temporary_chat=True,
    )

    assert result.prepared is True
    assert "Temporary Chat" in result.message
    assert "click:PromptMeld" not in events
    assert "click:Turn on temporary chat" in events
    assert composer.value == "complete prompt"
    assert clipboard == ["selected source"]


def test_one_time_temporary_chat_continue_is_left_to_the_user():
    events: list[str] = []
    progress: list[tuple[str, str]] = []
    composer = FakeComposer(events)
    continue_button = FakeControl("Continue", "Button", events)
    dialog = FakeWindow([continue_button], events)
    dialog.element_info.name = "Temporary Chat"
    temporary_toggle = FakeControl(
        "Turn on temporary chat",
        "Button",
        events,
    )
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        temporary_toggle,
        composer,
    ]

    def show_explanation():
        controls.append(dialog)

    temporary_toggle.on_click = show_explanation

    class UserConfirmationWindow(FakeWindow):
        def __init__(self):
            super().__init__(controls, events)
            self.dialog_reads = 0

        def descendants(self):
            if dialog in self.controls:
                self.dialog_reads += 1
                if self.dialog_reads >= 4:
                    # This state change represents the user pressing Continue
                    # in ChatGPT. PromptMeld must never activate that button.
                    self.controls.remove(dialog)
                    temporary_toggle.element_info.name = (
                        "Turn off temporary chat"
                    )
            return self.controls

    window = UserConfirmationWindow()
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        progress_callback=lambda stage, message: progress.append(
            (stage, message)
        ),
    )

    result = adapter.submit(
        "complete prompt",
        "PromptMeld",
        auto_submit=False,
        temporary_chat=True,
    )

    assert result.prepared is True
    assert "click:Continue" not in events
    assert "mouse:Continue" not in events
    assert (
        "temporary-chat-confirmation",
        "Waiting for you to review and confirm Temporary Chat in ChatGPT",
    ) in progress
    assert composer.value == "complete prompt"


def test_composer_uses_targeted_clipboard_paste_when_uia_input_fails():
    clipboard = {"text": "selected source"}
    events: list[str] = []

    class ClipboardComposer(FakeComposer):
        def set_edit_text(self, text: str):
            raise RuntimeError("ValuePattern unavailable")

        def type_keys(self, keys: str, **kwargs):
            self.events.append(f"type-keys:{keys}")
            self.value = clipboard["text"]

    composer = ClipboardComposer(events)
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: clipboard.update(text=text),
        clipboard_reader=lambda: clipboard["text"],
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    method = adapter._set_composer_prompt(composer, "complete prompt")

    assert method == "clipboard"
    assert composer.value == "complete prompt"
    assert events == ["type-keys:^a^v"]


def test_prosemirror_composer_skips_blocking_uia_text_input():
    clipboard = {"text": "selected source"}
    events: list[str] = []

    class ProseMirrorComposer(FakeComposer):
        def __init__(self):
            super().__init__(events)
            self.element_info.class_name = "ProseMirror ProseMirror-focused"

        def set_edit_text(self, text: str):
            raise AssertionError("ProseMirror must not use UIA SetValue")

        def get_value(self):
            raise AssertionError("ProseMirror must not use UIA value read-back")

        def type_keys(self, keys: str, **kwargs):
            self.events.append(f"type-keys:{keys}")
            if keys in ("^a^v", "^v"):
                self.value = clipboard["text"]
            elif keys == "^a^c":
                clipboard["text"] = self.value

    composer = ProseMirrorComposer()
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: clipboard.update(text=text),
        clipboard_reader=lambda: clipboard["text"],
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    method = adapter._set_composer_prompt(composer, "complete prompt")

    assert method == "clipboard"
    assert composer.value == "complete prompt"
    assert events == [
        "type-keys:^a^v",
        "type-keys:^a^c",
        "type-keys:{END}",
    ]


def test_submit_verifies_prosemirror_via_clipboard_before_enter():
    clipboard = {"text": "selected source"}
    events: list[str] = []

    class ProseMirrorComposer(FakeComposer):
        def __init__(self):
            super().__init__(events)
            self.element_info.class_name = "ProseMirror ProseMirror-focused"

        def get_value(self):
            raise AssertionError("ProseMirror UIA value read must not be used")

        def type_keys(self, keys: str, **kwargs):
            self.events.append(f"type-keys:{keys}")
            if keys == "^a^v":
                self.value = clipboard["text"]
            elif keys == "^a^c":
                clipboard["text"] = self.value

    composer = ProseMirrorComposer()
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        composer,
        FakeControl("Send", "Button", events),
    ]
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events[-1] == "click:Send"
    assert "keys:{ENTER}" not in events
    assert "type-keys:^a^c" in events


def test_paste_retry_refuses_composer_in_a_different_project():
    clipboard = {"text": "selected source"}
    events: list[str] = []

    class RejectingComposer(FakeComposer):
        def __init__(self):
            super().__init__(events)
            self.element_info.class_name = "ProseMirror"

        def type_keys(self, keys: str, **kwargs):
            self.events.append(f"type-keys:{keys}")

    original = RejectingComposer()
    different_project = FakeControl(
        "Change project: PromptMeld - Technical help",
        "Button",
        events,
    )
    replacement = FakeControl(
        "Message ChatGPT",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    window = FakeWindow([different_project, replacement], events)
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: clipboard.update(text=text),
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.1,
    )

    error = None
    try:
        adapter._set_composer_prompt(
            original,
            "complete prompt",
            window=window,
            project_name="PromptMeld - Editing",
        )
    except ChatGPTAutomationError as exc:
        error = exc

    assert error is not None
    assert "destination changed" in str(error)
    assert events == [
        "type-keys:^a^v",
        "type-keys:^a^c",
        "type-keys:^v",
    ]


def test_composer_verification_reacquires_fresh_chatgpt_control():
    events: list[str] = []
    fresh_composer = FakeComposer(events)

    class StaleComposer(FakeComposer):
        def set_edit_text(self, text: str):
            self.events.append("set-text:stale-composer")
            fresh_composer.value = text

    stale_composer = StaleComposer(events)
    stale_window = FakeWindow([stale_composer], events)
    fresh_window = FakeWindow([fresh_composer], events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(fresh_window),
        timeout_seconds=0.2,
    )

    method = adapter._set_composer_prompt(
        stale_composer,
        "complete prompt",
        window=stale_window,
    )

    assert method == "uia"
    assert fresh_composer.value == "complete prompt"
    assert events == ["set-text:stale-composer"]


def test_submit_does_not_press_enter_when_composer_rejects_prompt():
    events: list[str] = []
    clipboard: list[str] = []

    class RejectingComposer(FakeComposer):
        def set_edit_text(self, text: str):
            self.events.append("reject-uia")

        def type_keys(self, keys: str, **kwargs):
            self.events.append(f"reject-type-keys:{keys}")

    composer = RejectingComposer(events)
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        composer,
    ]
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.1,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is False
    assert result.fallback_copied is True
    assert "keys:{ENTER}" not in events
    assert clipboard[-1] == "complete prompt"


def test_submit_copies_prompt_when_project_controls_are_missing():
    events: list[str] = []
    clipboard: list[str] = []
    window = FakeWindow([], events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda *args, **kwargs: None,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is False
    assert result.fallback_copied is True
    assert clipboard == ["complete prompt"]
    assert "switch from Codex to ChatGPT after two attempts" in result.message
    assert "project controls are not exposed" not in result.message


def test_submit_switches_from_codex_to_chatgpt_before_selecting_project():
    events: list[str] = []
    mode_switch = FakeControl(
        "Switch mode, current mode: Codex",
        "Button",
        events,
    )
    mode_item = FakeControl(
        "ChatGPT Create, learn, and explore",
        "MenuItem",
        events,
        on_click=lambda: setattr(
            mode_switch.element_info,
            "name",
            "Switch mode, current mode: ChatGPT",
        ),
    )
    controls = [
        mode_switch,
        mode_item,
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events.index("click:Switch mode, current mode: Codex") < events.index(
        "click:ChatGPT Create, learn, and explore"
    )
    assert events.index(
        "click:ChatGPT Create, learn, and explore"
    ) < events.index("click:Chat")
    assert events.index("click:Chat") < events.index("click:WritingLauncher")


def test_submit_retries_transient_codex_mode_switch():
    events: list[str] = []
    progress: list[tuple[str, str]] = []
    controls: list[FakeControl] = []
    attempts = 0
    mode_switch = FakeControl(
        "Switch mode, current mode: Codex",
        "Button",
        events,
    )

    def reveal_mode_item_on_second_attempt():
        nonlocal attempts
        attempts += 1
        if attempts != 2:
            return
        controls.append(
            FakeControl(
                "ChatGPT Create, learn, and explore",
                "MenuItem",
                events,
                on_click=lambda: setattr(
                    mode_switch.element_info,
                    "name",
                    "Switch mode, current mode: ChatGPT",
                ),
            )
        )

    mode_switch.on_click = reveal_mode_item_on_second_attempt
    controls.extend(
        [
            mode_switch,
            FakeControl(
                "New chat",
                "Button",
                events,
                class_name="sidebar-item",
            ),
            FakeControl(
                "Chat",
                "Button",
                events,
                class_name="text-token-text-primary",
            ),
            FakeControl("WritingLauncher", "Button", events),
            FakeControl(
                "Change project: WritingLauncher",
                "Button",
                events,
            ),
            FakeComposer(events),
        ]
    )
    adapter = ChatGPTDesktop(
        timeout_seconds=0.02,
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        progress_callback=lambda stage, message: progress.append(
            (stage, message)
        ),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert attempts == 2
    assert (
        "selecting-mode",
        "Retrying the switch from Codex to ChatGPT",
    ) in progress


def test_mode_switch_confirmation_uses_refreshed_chatgpt_window():
    events: list[str] = []
    stale_switcher = FakeControl(
        "Switch mode, current mode: Codex",
        "Button",
        events,
    )
    fresh_switcher = FakeControl(
        "Switch mode, current mode: Codex",
        "Button",
        events,
    )
    mode_item = FakeControl(
        "ChatGPT Create, learn, and explore",
        "MenuItem",
        events,
        on_click=lambda: setattr(
            fresh_switcher.element_info,
            "name",
            "Switch mode, current mode: ChatGPT",
        ),
    )
    stale_window = FakeWindow([stale_switcher], events)
    fresh_window = FakeWindow([fresh_switcher, mode_item], events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(fresh_window),
        timeout_seconds=0.2,
    )

    assert adapter._select_chatgpt_mode(stale_window) is True
    assert events == [
        "click:Switch mode, current mode: Codex",
        "click:ChatGPT Create, learn, and explore",
    ]


def test_project_lookup_refreshes_after_mode_switch():
    events: list[str] = []
    project_name = "PromptMeld - Editing"
    stale_project_row = FakeControl(
        project_name,
        "Button",
        events,
        class_name="sidebar-item group/folder-row",
    )
    stale_window = FakeWindow(
        [
            FakeControl(
                "Switch mode, current mode: ChatGPT",
                "Button",
                events,
            ),
            stale_project_row,
        ],
        events,
    )
    fresh_controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]

    def confirm_project():
        fresh_controls.append(
            FakeControl(
                f"Change project: {project_name}",
                "Button",
                events,
            )
        )

    fresh_controls.append(
        FakeControl(
            f"New chat in {project_name}",
            "Button",
            events,
            on_click=confirm_project,
        )
    )
    fresh_window = FakeWindow(fresh_controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(fresh_window),
        timeout_seconds=0.2,
    )

    assert adapter._navigate_to_project_chat(stale_window, project_name) is True
    assert f"click:New chat in {project_name}" in events
    assert f"click:{project_name}" not in events


def test_submit_retries_transient_chat_home_transition():
    events: list[str] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
    ]

    def send_keys(keys, **kwargs):
        events.append(f"keys:{keys}")
        if keys != "{ESC}" or any(
            control.element_info.name == "Chat"
            for control in controls
        ):
            return
        controls.extend(
            [
                FakeControl(
                    "Chat",
                    "Button",
                    events,
                    class_name="text-token-text-primary",
                ),
                FakeControl("WritingLauncher", "Button", events),
                FakeControl(
                    "Change project: WritingLauncher",
                    "Button",
                    events,
                ),
                FakeComposer(events),
            ]
        )

    adapter = ChatGPTDesktop(
        timeout_seconds=0.02,
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=send_keys,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events.count("click:New chat") == 2
    assert "keys:{ESC}" in events


def test_chat_home_supports_current_ui_without_chat_work_toggle():
    events: list[str] = []
    composer = FakeControl(
        "Current placeholder",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item focus-visible:outline",
        ),
        FakeControl(
            "Change project: Previous Project",
            "Button",
            events,
            visible=False,
        ),
        composer,
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        timeout_seconds=0.2,
    )

    assert adapter._open_chat_home(window) is True
    assert events == ["click:New chat"]


def test_submit_creates_missing_writinglauncher_project():
    events: list[str] = []
    clipboard: list[str] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeComposer(events),
        FakeControl("Add new project", "Button", events),
        FakeControl(
            "Project name",
            "Edit",
            events,
            automation_id="chatgpt-project-name",
        ),
    ]

    def finish_creation():
        controls.extend(
            [
                FakeControl(
                    "Change project: WritingLauncher",
                    "Button",
                    events,
                ),
            ]
        )

    controls.append(
        FakeControl(
            "Create project",
            "Button",
            events,
            on_click=finish_creation,
        )
    )
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert "click:Add new project" in events
    assert "focus:Project name" in events
    assert "click:Create project" in events
    assert clipboard == [
        "WritingLauncher",
        "selected source",
    ]


def test_existing_empty_project_is_selected_after_show_more():
    events: list[str] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item focus-visible:outline",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeComposer(events),
        FakeControl("Projects", "Button", events),
    ]

    def reveal_projects():
        for _ in range(3):
            new_chat = FakeControl(
                "New chat in WritingLauncher",
                "Button",
                events,
            )
            new_chat.on_click = lambda: controls.append(
                FakeControl(
                    "Change project: WritingLauncher",
                    "Button",
                    events,
                )
            )
            controls.append(new_chat)

    controls.append(
        FakeControl(
            "Show more",
            "Button",
            events,
            on_click=reveal_projects,
        )
    )
    controls.append(FakeControl("Add new project", "Button", events))
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events.count("click:Show more") == 1
    assert events.count("click:New chat in WritingLauncher") == 1
    assert "click:Add new project" not in events


def test_project_creation_supports_two_stage_projects_index():
    events: list[str] = []
    controls: list[FakeControl] = []
    add_project = FakeControl("Add new project", "Button", events)
    search = FakeControl(
        "Search projects",
        "Edit",
        events,
        automation_id="projects-index-search",
    )
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Button", events)
    controls.append(add_project)
    activations = 0

    def advance_creation():
        nonlocal activations
        activations += 1
        if activations == 1:
            controls.append(search)
        else:
            controls.remove(search)
            controls.extend([name_edit, create])

    add_project.on_click = advance_creation
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )

    assert adapter._create_project(window, "WritingLauncher") is True
    assert events.count("click:Add new project") == 2
    assert "focus:Project name" in events


def test_project_lookup_rejects_same_named_chat_sidebar_row():
    events: list[str] = []
    chat_row = FakeControl(
        "WritingLauncher",
        "Button",
        events,
        class_name="sidebar-item",
    )
    project = FakeControl(
        "WritingLauncher",
        "Button",
        events,
        class_name="sidebar-item group/folder-row",
    )
    adapter = ChatGPTDesktop()

    assert (
        adapter._find_project_control(
            FakeWindow([chat_row, project], events),
            "WritingLauncher",
        )
        is project
    )


def test_top_new_chat_lookup_rejects_same_named_history_row():
    events: list[str] = []
    top_new_chat = FakeControl(
        "New chat",
        "Button",
        events,
        class_name="sidebar-item focus-visible:outline",
    )
    history_row = FakeControl(
        "New chat",
        "Button",
        events,
        class_name="group relative sidebar-item",
    )

    assert ChatGPTDesktop._is_top_new_chat_control(top_new_chat) is True
    assert ChatGPTDesktop._is_top_new_chat_control(history_row) is False


def test_current_do_anything_composer_is_recognised():
    events: list[str] = []
    composer = FakeControl(
        "Do anything",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    adapter = ChatGPTDesktop()

    assert adapter._find_composer(FakeWindow([composer], events)) is composer


def test_prosemirror_class_is_a_constrained_composer_fallback():
    events: list[str] = []
    search = FakeControl("Search", "Edit", events, class_name="SearchBox")
    renamed_composer = FakeControl(
        "Current placeholder",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    adapter = ChatGPTDesktop()

    assert (
        adapter._find_composer(
            FakeWindow([search, renamed_composer], events)
        )
        is renamed_composer
    )


def test_project_ready_accepts_renamed_prosemirror_composer():
    events: list[str] = []
    project_name = "PromptMeld - Editing"
    project_marker = FakeControl(
        f"Change project: {project_name}",
        "Button",
        events,
    )
    renamed_composer = FakeControl(
        "Current placeholder",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    adapter = ChatGPTDesktop()

    assert adapter._project_chat_is_ready_in(
        FakeWindow([project_marker, renamed_composer], events),
        project_name,
    ) is True


def test_hidden_named_composer_does_not_mask_visible_prosemirror():
    events: list[str] = []
    hidden_named = FakeControl(
        "Message ChatGPT",
        "Edit",
        events,
        visible=False,
    )
    visible_composer = FakeControl(
        "Current placeholder",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    adapter = ChatGPTDesktop()

    assert (
        adapter._find_composer(
            FakeWindow([hidden_named, visible_composer], events)
        )
        is visible_composer
    )


def test_stale_composer_does_not_mask_visible_prosemirror():
    events: list[str] = []

    class StaleElementInfo:
        name = "Message ChatGPT"
        control_type = "Edit"
        class_name = ""

        @property
        def enabled(self):
            raise RuntimeError("stale UIA wrapper")

    stale = FakeControl("stale", "Edit", events)
    stale.element_info = StaleElementInfo()
    visible_composer = FakeControl(
        "Current placeholder",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    adapter = ChatGPTDesktop()

    assert (
        adapter._find_composer(
            FakeWindow([stale, visible_composer], events)
        )
        is visible_composer
    )


def test_unknown_edit_control_is_not_treated_as_composer():
    events: list[str] = []
    search = FakeControl("Search", "Edit", events, class_name="SearchBox")
    adapter = ChatGPTDesktop()

    assert adapter._find_composer(FakeWindow([search], events)) is None


def test_control_activation_prefers_uia_invoke_without_moving_mouse():
    events: list[str] = []

    class InvokableControl(FakeControl):
        def invoke(self):
            self.events.append(f"invoke:{self.element_info.name}")

    control = InvokableControl("Chat", "Button", events)
    adapter = ChatGPTDesktop()

    adapter._activate_control(control)

    assert events == ["invoke:Chat"]


def test_control_activation_uses_pattern_click_when_invoke_fails():
    events: list[str] = []

    class FailingInvokableControl(FakeControl):
        def invoke(self):
            raise RuntimeError("Invoke pattern unavailable")

    control = FailingInvokableControl("Chat", "Button", events)
    adapter = ChatGPTDesktop()

    adapter._activate_control(control)

    assert events == ["click:Chat"]


def test_control_activation_uses_keyboard_before_physical_mouse():
    events: list[str] = []

    class KeyboardControl(FakeControl):
        def invoke(self):
            raise RuntimeError("Invoke pattern unavailable")

        def click(self):
            raise RuntimeError("Pattern click unavailable")

        def select(self):
            raise RuntimeError("SelectionItem unavailable")

    control = KeyboardControl("Chat", "Button", events)
    adapter = ChatGPTDesktop(
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        mouse_clicker=lambda item: events.append(
            f"mouse:{item.element_info.name}"
        ),
    )

    adapter._activate_control(control)

    assert events == ["focus:Chat", "keys:{ENTER}"]


def test_control_activation_uses_physical_mouse_only_as_last_resort():
    events: list[str] = []

    class MouseOnlyControl(FakeControl):
        def invoke(self):
            raise RuntimeError("Invoke pattern unavailable")

        def click(self):
            raise RuntimeError("Pattern click unavailable")

        def select(self):
            raise RuntimeError("SelectionItem unavailable")

        def set_focus(self):
            raise RuntimeError("Keyboard focus unavailable")

    control = MouseOnlyControl("Chat", "Button", events)
    adapter = ChatGPTDesktop(
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        mouse_clicker=lambda item: events.append(
            f"mouse:{item.element_info.name}"
        ),
    )

    adapter._activate_control(control)

    assert events == ["mouse:Chat"]


def test_physical_fallback_supports_negative_virtual_desktop_coordinates():
    @dataclass
    class Rectangle:
        left: int
        top: int
        right: int
        bottom: int

    class RectangleControl:
        @staticmethod
        def rectangle():
            return Rectangle(-2200, 100, -1800, 500)

    class FakeWin32Api:
        metrics = {
            76: -2520,
            77: 0,
            78: 8280,
            79: 1728,
        }

        def __init__(self):
            self.cursor = (400, 200)
            self.positions = []
            self.events = []

        def GetSystemMetrics(self, index):
            return self.metrics[index]

        def GetCursorPos(self):
            return self.cursor

        def SetCursorPos(self, position):
            self.cursor = position
            self.positions.append(position)

        def mouse_event(self, flags, dx, dy, data, extra):
            self.events.append((flags, dx, dy, data, extra))

    win32api = FakeWin32Api()

    _click_control_on_virtual_desktop(
        RectangleControl(),
        win32api_module=win32api,
    )

    assert win32api.positions == [(-2000, 300), (400, 200)]
    assert win32api.events == [
        (0x0002, 0, 0, 0, 0),
        (0x0004, 0, 0, 0, 0),
    ]


def test_visible_project_new_chat_uses_fast_path():
    events: list[str] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeComposer(events),
    ]
    project_action = FakeControl(
        "New chat in PromptMeld - Editing",
        "Button",
        events,
        on_click=lambda: controls.append(
            FakeControl(
                "Change project: PromptMeld - Editing",
                "Button",
                events,
            )
        ),
    )
    controls.append(project_action)
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "complete prompt",
        "PromptMeld - Editing",
    )

    assert result.submitted is True
    assert "click:New chat in PromptMeld - Editing" in events
    assert "click:New chat" not in events
    assert "click:Chat" not in events


def test_project_new_chat_is_reacquired_after_unconfirmed_activation():
    events: list[str] = []
    progress: list[tuple[str, str]] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    attempts = 0

    def activate_on_second_attempt():
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            controls.append(
                FakeControl(
                    "Change project: PromptMeld - Editing",
                    "Button",
                    events,
                )
            )

    project_action = FakeControl(
        "New chat in PromptMeld - Editing",
        "Button",
        events,
        on_click=activate_on_second_attempt,
    )
    controls.append(project_action)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.02,
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        progress_callback=lambda stage, message: progress.append(
            (stage, message)
        ),
    )

    result = adapter.submit(
        "complete prompt",
        "PromptMeld - Editing",
    )

    assert result.submitted is True
    assert attempts == 2
    assert events.count("click:New chat in PromptMeld - Editing") == 2
    assert (
        "opening-project",
        "Project confirmation is taking longer; refreshing ChatGPT controls",
    ) in progress
    assert (
        "opening-project",
        "Reacquiring the Project control and retrying once",
    ) in progress


def test_project_confirmation_refreshes_stale_chatgpt_window():
    events: list[str] = []
    progress: list[tuple[str, str]] = []
    project_name = "PromptMeld - Editing"
    stale_controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            f"New chat in {project_name}",
            "Button",
            events,
        ),
    ]
    fresh_controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            f"Change project: {project_name}",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    stale_window = FakeWindow(stale_controls, events)
    fresh_window = FakeWindow(fresh_controls, events)
    desktop_calls = 0

    def desktop_factory(**kwargs):
        nonlocal desktop_calls
        desktop_calls += 1
        return FakeDesktop(
            stale_window if desktop_calls == 1 else fresh_window
        )

    adapter = ChatGPTDesktop(
        timeout_seconds=0.02,
        desktop_factory=desktop_factory,
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        progress_callback=lambda stage, message: progress.append(
            (stage, message)
        ),
    )

    result = adapter.submit("complete prompt", project_name)

    assert result.submitted is True
    assert events.count(f"click:New chat in {project_name}") == 1
    assert "set-text:Message ChatGPT" in events
    assert (
        "opening-project",
        "Reacquiring the Project control and retrying once",
    ) not in progress


def test_project_composer_transition_allows_delayed_context_label():
    events: list[str] = []
    progress: list[tuple[str, str]] = []
    project_name = "PromptMeld - Editing"
    previous_composer = FakeComposer(events)
    controls: list[FakeControl] = []

    class DelayedMarkerComposer(FakeComposer):
        def set_edit_text(self, text: str):
            super().set_edit_text(text)
            controls.append(
                FakeControl(
                    f"Change project: {project_name}",
                    "Button",
                    events,
                )
            )

    project_composer = DelayedMarkerComposer(events)
    controls.extend(
        [
            FakeControl(
                "Switch mode, current mode: ChatGPT",
                "Button",
                events,
            ),
            previous_composer,
        ]
    )

    def open_project_chat():
        controls.remove(previous_composer)
        controls.append(project_composer)

    project_action = FakeControl(
        f"New chat in {project_name}",
        "Button",
        events,
        on_click=open_project_chat,
    )
    controls.append(project_action)
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.02,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        progress_callback=lambda stage, message: progress.append(
            (stage, message)
        ),
    )

    result = adapter.submit("complete prompt", project_name)

    assert result.submitted is True
    assert events.count(f"click:New chat in {project_name}") == 1
    assert project_composer.value == "complete prompt"
    assert (
        "opening-project",
        "The Project label is delayed; continuing with its verified message box",
    ) in progress
    assert (
        "opening-project",
        "Reacquiring the Project control and retrying once",
    ) not in progress
