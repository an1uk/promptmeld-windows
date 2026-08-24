from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest
import win32gui

from promptmeld import chatgpt as chatgpt_module
from promptmeld.chatgpt import (
    ChatGPTAutomationCancelled,
    ChatGPTAutomationError,
    ChatGPTDesktop,
    _click_control_on_virtual_desktop,
)
from promptmeld.models import ResponseAnchor
from promptmeld.automation_protocol import (
    AutomationCheckpoint,
    RecoveryAction,
    SubmissionDisposition,
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
    def __init__(self, controls, events, process_id=None, handle=None):
        super().__init__("ChatGPT", "Window", events)
        self.controls = controls
        self._process_id = process_id
        self.handle = handle

    def descendants(self):
        return self.controls

    def process_id(self):
        if self._process_id is None:
            raise RuntimeError("No fake process id")
        return self._process_id


class FakeDesktop:
    def __init__(self, window):
        self.window = window

    def windows(self, **kwargs):
        return [self.window]


def test_get_or_launch_window_opens_current_chatgpt_app():
    events: list[str] = []
    window = FakeWindow([], events, process_id=42)
    searches = iter([[], [window], [window]])
    launched: list[str] = []

    class SequencedDesktop:
        def windows(self, **kwargs):
            return next(searches)

    adapter = ChatGPTDesktop(
        timeout_seconds=0.2,
        desktop_factory=lambda **kwargs: SequencedDesktop(),
        startfile=launched.append,
        process_path_reader=lambda process_id: (
            r"C:\Program Files\WindowsApps\OpenAI.Codex_1\app\ChatGPT.exe"
        ),
    )

    assert adapter._get_or_launch_window() is window
    assert launched == ["codex:"]


def test_cold_launch_uses_dedicated_readiness_timeout(monkeypatch):
    clock = {"now": 0.0}
    launched = []
    adapter = ChatGPTDesktop(
        timeout_seconds=0.2,
        launch_timeout_seconds=45.0,
        desktop_factory=lambda **kwargs: FakeDesktop(None),
        startfile=launched.append,
    )
    monkeypatch.setattr(adapter, "_find_window", lambda: None)
    monkeypatch.setattr(
        chatgpt_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        adapter,
        "_sleep",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )

    with pytest.raises(ChatGPTAutomationError, match="did not become ready"):
        adapter._get_or_launch_window()

    assert launched == ["codex:"]
    assert clock["now"] >= 45.0


def test_find_window_ignores_chatgpt_classic():
    events: list[str] = []
    classic = FakeWindow([], events, process_id=1)
    current = FakeWindow([], events, process_id=2)

    class CandidateDesktop:
        def windows(self, **kwargs):
            return [classic, current]

    paths = {
        1: r"C:\Program Files\WindowsApps\OpenAI.ChatGPT-Desktop_1\app\ChatGPT Classic.exe",
        2: r"C:\Program Files\WindowsApps\OpenAI.Codex_1\app\ChatGPT.exe",
    }
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: CandidateDesktop(),
        process_path_reader=paths.get,
    )

    assert adapter._find_window() is current


def test_find_window_prefers_foreground_verified_current_app():
    events: list[str] = []
    first = FakeWindow([FakeComposer(events)], events, process_id=1)
    second = FakeWindow([FakeComposer(events)], events, process_id=2)
    first.handle = 100
    second.handle = 200

    class CandidateDesktop:
        def windows(self, **kwargs):
            return [first, second]

    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: CandidateDesktop(),
        foreground_window_reader=lambda: 200,
        process_path_reader=lambda process_id: (
            rf"C:\Program Files\WindowsApps\OpenAI.Codex_{process_id}"
            r"\app\ChatGPT.exe"
        ),
    )

    assert adapter._find_window() is second


def test_submission_confirmation_rejects_unchanged_composer():
    events: list[str] = []
    composer = FakeComposer(events)
    composer.value = "complete prompt"
    window = FakeWindow([composer], events, process_id=42)
    window.handle = 900
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        process_path_reader=lambda process_id: (
            r"C:\Program Files\WindowsApps\OpenAI.Codex_1\app\ChatGPT.exe"
        ),
    )

    assert adapter._confirm_submission(window, composer, "complete prompt", ()) is False


def test_unconfirmed_send_never_copies_or_retries_prompt(monkeypatch):
    events: list[str] = []
    clipboard_writes: list[str] = []
    controls = [
        FakeControl("Switch mode, current mode: ChatGPT", "Button", events),
        FakeControl("New chat", "Button", events, class_name="sidebar-item"),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl("Change project: WritingLauncher", "Button", events),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "user clipboard",
        clipboard_writer=clipboard_writes.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )
    monkeypatch.setattr(adapter, "_confirm_submission", lambda *args: False)

    result = adapter.submit("private prompt", "WritingLauncher")

    assert result.submitted is False
    assert result.fallback_copied is False
    assert result.checkpoint == AutomationCheckpoint.SEND_STARTED
    assert result.submission_disposition == SubmissionDisposition.MAYBE_SUBMITTED
    assert result.retry_mode == "inspect"
    assert RecoveryAction.RETRY_DELIVERY not in result.recovery_actions
    assert clipboard_writes == []


def test_cancellation_during_response_wait_remains_confirmed_and_never_resends(
    monkeypatch,
):
    events: list[str] = []
    clipboard_writes: list[str] = []
    controls = [
        FakeControl("Switch mode, current mode: ChatGPT", "Button", events),
        FakeControl("New chat", "Button", events, class_name="sidebar-item"),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl("Change project: WritingLauncher", "Button", events),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "user clipboard",
        clipboard_writer=clipboard_writes.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )
    monkeypatch.setattr(adapter, "_confirm_submission", lambda *args: True)
    monkeypatch.setattr(
        adapter,
        "_copy_latest_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ChatGPTAutomationCancelled("cancelled")
        ),
    )

    result = adapter.submit(
        "private prompt",
        "WritingLauncher",
        capture_generated_text=True,
    )

    assert result.cancelled is True
    assert result.submitted is True
    assert result.submission_disposition == SubmissionDisposition.CONFIRMED
    assert result.retry_mode == "response"
    assert RecoveryAction.RETRY_DELIVERY not in result.recovery_actions
    assert "private prompt" not in clipboard_writes


def test_response_wait_never_copies_a_preexisting_response():
    events: list[str] = []
    copied: list[str] = []
    copy_button = FakeControl(
        "Copy",
        "Button",
        events,
        on_click=lambda: copied.append("old response"),
    )
    window = FakeWindow([copy_button], events)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.01,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: copied[-1] if copied else "unchanged",
        clipboard_writer=lambda text: copied.append(text),
    )
    baseline = adapter._response_control_tokens(window)

    with pytest.raises(ChatGPTAutomationError, match="completed response"):
        adapter._copy_latest_response(
            window,
            "new prompt",
            baseline=baseline,
        )

    assert "click:Copy" not in events


def test_response_wait_never_copies_baseline_after_generation_stops(
    monkeypatch,
):
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    copy_button = FakeControl(
        "Copy",
        "Button",
        events,
        on_click=lambda: clipboard.update(text="old response"),
    )
    stop = FakeControl("Stop generating", "Button", events)

    class CompletedWithoutNewResponse(FakeWindow):
        def __init__(self):
            super().__init__([copy_button], events)
            self.reads = 0

        def descendants(self):
            self.reads += 1
            return [stop, copy_button] if self.reads == 1 else [copy_button]

    window = CompletedWithoutNewResponse()
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.01,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )

    with pytest.raises(ChatGPTAutomationError, match="completed response"):
        adapter._copy_latest_response(
            window,
            "new prompt",
            baseline=("0:old",),
        )

    assert "click:Copy" not in events


def test_clipboard_restore_preserves_a_newer_user_copy():
    state = {"text": "original", "sequence": 1}

    def write(value: str) -> None:
        state["text"] = value
        state["sequence"] += 1

    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: state["text"],
        clipboard_writer=write,
        clipboard_sequence_reader=lambda: state["sequence"],
    )
    adapter._write_clipboard("temporary")
    state.update(text="user copy", sequence=state["sequence"] + 1)

    assert adapter._restore_clipboard_if_unchanged(
        "original",
        expected="temporary",
    ) is False
    assert state["text"] == "user copy"


def test_full_clipboard_snapshot_restores_rich_formats_when_still_owned():
    state = {
        "text": "user text",
        "formats": {"html": b"<b>user text</b>", "image": b"pixels"},
        "sequence": 10,
    }

    class Snapshot:
        def __init__(self):
            self.text = state["text"]
            self.formats = dict(state["formats"])
            self.owned_sequence = None
            self.closed = False

        def mark_owned(self, sequence):
            self.owned_sequence = sequence

        def restore_if_owned(self):
            if state["sequence"] != self.owned_sequence:
                self.closed = True
                return False
            state["text"] = self.text
            state["formats"] = dict(self.formats)
            state["sequence"] += 1
            self.closed = True
            return True

        def close(self):
            self.closed = True

    snapshots = []

    def capture_snapshot():
        value = Snapshot()
        snapshots.append(value)
        return value

    def write(value):
        state["text"] = value
        state["formats"] = {"unicode": value.encode()}
        state["sequence"] += 1

    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: state["text"],
        clipboard_writer=write,
        clipboard_sequence_reader=lambda: state["sequence"],
        clipboard_snapshot_factory=capture_snapshot,
    )
    adapter.enforce_clipboard_sequence = True
    before, snapshot = adapter._capture_clipboard_state()
    adapter._write_clipboard("temporary prompt")

    assert adapter._restore_clipboard_if_unchanged(
        before,
        snapshot=snapshot,
        expected="temporary prompt",
    ) is True
    assert state["text"] == "user text"
    assert state["formats"] == {
        "html": b"<b>user text</b>",
        "image": b"pixels",
    }
    assert snapshots[0].closed is True


def test_clipboard_restore_retries_transient_empty_read_while_owned():
    state = {
        "text": "response",
        "sequence": 10,
        "reads": 0,
        "restored": False,
    }

    class Snapshot:
        def __init__(self):
            self.owned_sequence = None

        def mark_owned(self, sequence):
            self.owned_sequence = sequence

        def restore_if_owned(self):
            assert self.owned_sequence == state["sequence"]
            state["restored"] = True
            return True

        def close(self):
            raise AssertionError("An owned snapshot must not be discarded")

    def read_clipboard():
        state["reads"] += 1
        return None if state["reads"] == 1 else state["text"]

    adapter = ChatGPTDesktop(
        clipboard_reader=read_clipboard,
        clipboard_writer=lambda value: state.update(
            text=value,
            sequence=state["sequence"] + 1,
        ),
        clipboard_sequence_reader=lambda: state["sequence"],
    )
    adapter.enforce_clipboard_sequence = True
    adapter.clipboard_owned_sequence = state["sequence"]

    assert adapter._restore_clipboard_if_unchanged(
        "marker",
        snapshot=Snapshot(),
        expected="response",
    ) is True
    assert state["reads"] == 2
    assert state["restored"] is True


def test_clipboard_restore_aborts_if_sequence_changes_during_busy_read():
    state = {"sequence": 10, "closed": False}

    class Snapshot:
        def close(self):
            state["closed"] = True

    def read_clipboard():
        state["sequence"] += 1
        return None

    adapter = ChatGPTDesktop(
        clipboard_reader=read_clipboard,
        clipboard_sequence_reader=lambda: state["sequence"],
    )
    adapter.enforce_clipboard_sequence = True
    adapter.clipboard_owned_sequence = state["sequence"]

    assert adapter._restore_clipboard_if_unchanged(
        "marker",
        snapshot=Snapshot(),
        expected="response",
    ) is False
    assert state["closed"] is True


def test_response_copy_attempts_each_new_control_only_once(monkeypatch):
    events: list[str] = []
    writes: list[str] = []
    copy_button = FakeControl("Copy", "Button", events)
    window = FakeWindow([copy_button], events)
    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.01,
        clipboard_reader=lambda: writes[-1] if writes else "unchanged",
        clipboard_writer=writes.append,
    )

    with pytest.raises(ChatGPTAutomationError, match="completed response"):
        adapter._copy_latest_response(window, "new prompt")

    assert events.count("click:Copy") == 1
    assert len(writes) == 1
    assert writes[0].startswith("__PROMPTMELD_OUTPUT_NOT_READY_")


def test_response_copy_rejects_clipboard_contention_between_probes(
    monkeypatch,
):
    events: list[str] = []
    clipboard = {"text": "unchanged", "copy_count": 0}

    def replace_clipboard() -> None:
        clipboard["copy_count"] += 1
        clipboard["text"] = (
            "owned response"
            if clipboard["copy_count"] == 1
            else "newer user copy"
        )

    copy_button = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="response-copy-1",
        on_click=replace_clipboard,
    )
    window = FakeWindow([copy_button], events)
    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.01,
        clipboard_reader=lambda: str(clipboard["text"]),
        clipboard_writer=lambda text: clipboard.update(text=text),
    )

    with pytest.raises(ChatGPTAutomationError, match="completed response"):
        adapter._copy_latest_response(window, "new prompt")

    assert events == ["click:Copy", "click:Copy"]
    assert clipboard["text"] == "newer user copy"


def test_response_copy_is_anchored_to_submitted_message_and_container(
    monkeypatch,
):
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    prompt = "request owned by this conversation"
    window = FakeWindow([], events)
    window.handle = 900
    conversation = FakeControl(
        "Conversation",
        "Pane",
        events,
        automation_id="conversation-1",
    )
    conversation.parent = lambda: window
    submitted = FakeControl(
        prompt,
        "Text",
        events,
        automation_id="user-message-1",
    )
    submitted.parent = lambda: conversation
    response_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="response-copy-1",
        on_click=lambda: clipboard.update(text="owned response"),
    )
    response_copy.parent = lambda: conversation
    window.controls = [submitted, response_copy]
    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.5,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )
    anchor = adapter._anchor_submitted_message(
        window,
        ResponseAnchor(
            destination_token=adapter._destination_token(window),
            prompt_digest=adapter._text_digest(prompt),
        ),
    )
    assert anchor is not None
    assert anchor.submitted_message_token
    assert anchor.conversation_container_token

    assert adapter._copy_latest_response(window, prompt, anchor=anchor) == (
        "owned response"
    )
    assert events.count("click:Copy") == 2


def test_unrelated_chat_copy_is_rejected_even_if_globally_new(monkeypatch):
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    prompt = "request owned by prior chat"
    window = FakeWindow([], events)
    window.handle = 900
    unrelated_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="globally-new-copy",
        on_click=lambda: clipboard.update(text="unrelated response"),
    )
    window.controls = [unrelated_copy]
    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.5,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )
    anchor = ResponseAnchor(
        destination_token=adapter._destination_token(window),
        prompt_digest=adapter._text_digest(prompt),
        submitted_message_token="user-message-from-prior-chat|Text||",
    )

    with pytest.raises(ChatGPTAutomationError, match="no longer present"):
        adapter._copy_latest_response(window, prompt, anchor=anchor)

    assert "click:Copy" not in events


def test_response_copy_uses_stable_identity_not_global_copy_order(monkeypatch):
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    prompt = "current prompt"
    window = FakeWindow([], events)
    submitted = FakeControl(
        prompt,
        "Text",
        events,
        automation_id="user-message-1",
    )
    new_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="new-copy",
        on_click=lambda: clipboard.update(text="current response"),
    )
    old_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="old-copy",
        on_click=lambda: clipboard.update(text="old response"),
    )
    # The new control appears before the old one in the global Copy ordering.
    window.controls = [submitted, new_copy, old_copy]
    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.05,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )
    old_token = adapter._response_control_token(old_copy, 1)
    anchor = ResponseAnchor(
        destination_token=adapter._destination_token(window),
        baseline_tokens=(old_token,),
        prompt_digest=adapter._text_digest(prompt),
        submitted_message_token=adapter._stable_control_token(submitted, 0),
    )

    assert adapter._copy_latest_response(window, prompt, anchor=anchor) == (
        "current response"
    )
    assert events == ["click:Copy", "click:Copy"]


def test_stale_submitted_message_wrapper_cannot_own_response(monkeypatch):
    events: list[str] = []
    prompt = "current prompt"
    window = FakeWindow([], events)
    window.handle = 900
    stale_message = FakeControl(
        prompt,
        "Text",
        events,
        automation_id="replacement-wrapper",
    )
    response_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="new-copy",
    )
    window.controls = [stale_message, response_copy]
    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        timeout_seconds=0.01,
        response_timeout_seconds=0.5,
        desktop_factory=lambda **kwargs: FakeDesktop(window),
    )
    anchor = ResponseAnchor(
        destination_token=adapter._destination_token(window),
        prompt_digest=adapter._text_digest(prompt),
        submitted_message_token="original-wrapper|Text||",
    )

    with pytest.raises(ChatGPTAutomationError, match="no longer present"):
        adapter._copy_latest_response(window, prompt, anchor=anchor)

    assert "click:Copy" not in events


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
    assert clipboard == []


def test_submit_copies_generated_response_to_clipboard():
    events: list[str] = []
    progress: list[tuple[str, str]] = []
    boundary_events: list[tuple[str, str]] = []
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
        progress_callback=lambda stage, message: progress.append(
            (stage, message)
        ) or boundary_events.append(("progress", stage)),
        response_callback=lambda text, anchor: boundary_events.append(
            ("response", text)
        ),
    )

    result = adapter.submit(
        "complete prompt",
        "WritingLauncher",
        copy_generated_text=True,
    )

    assert result.submitted is True
    assert result.generated_text_copied is True
    assert result.generated_text == "Generated answer"
    assert clipboard["text"] == "Generated answer"
    assert "The generated text is on the clipboard." in result.message
    assert any(
        stage == "waiting-for-response"
        and "continue working in another window" in message
        for stage, message in progress
    )
    assert boundary_events.index(("response", "Generated answer")) < (
        boundary_events.index(("progress", "response-captured"))
    )


def test_generated_response_restores_redacted_values_before_copying():
    events: list[str] = []
    clipboard = {"text": "selected source"}
    copy_button = FakeControl("Copy", "Button", events)
    copy_button.on_click = lambda: clipboard.update(
        text="Hello [NAME_1], email [EMAIL_1]."
    )
    controls = [
        FakeControl("Switch mode, current mode: ChatGPT", "Button", events),
        FakeControl("New chat", "Button", events, class_name="sidebar-item"),
        FakeControl("Chat", "Button", events, class_name="text-token-text-primary"),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl("Change project: WritingLauncher", "Button", events),
        FakeComposer(events),
        copy_button,
    ]
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "Hello [NAME_1].",
        "WritingLauncher",
        copy_generated_text=True,
        redaction_replacements={
            "[NAME_1]": "Jane Smith",
            "[EMAIL_1]": "jane@example.com",
        },
    )

    expected = "Hello Jane Smith, email jane@example.com."
    assert result.generated_text == expected
    assert clipboard["text"] == expected


def test_response_copy_uses_background_safe_control_activation():
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    copy_button = FakeControl("Copy", "Button", events)
    copy_button.on_click = lambda: clipboard.update(text="Generated answer")
    window = FakeWindow([copy_button], events)
    adapter = ChatGPTDesktop(
        response_timeout_seconds=0.1,
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )

    result = adapter._copy_latest_response(window, "Complete prompt")

    assert result == "Generated answer"
    assert events == ["click:Copy", "click:Copy"]


def test_response_copy_waits_for_delayed_chromium_clipboard_write():
    events: list[str] = []
    state = {
        "text": "unchanged",
        "sequence": 10,
        "pending": False,
        "sequence_reads": 0,
    }
    copy_button = FakeControl(
        "Copy",
        "Button",
        events,
        on_click=lambda: state.update(pending=True, sequence_reads=0),
    )

    def write_clipboard(value: str) -> None:
        state["text"] = value
        state["sequence"] += 1

    def read_sequence() -> int:
        if state["pending"]:
            state["sequence_reads"] += 1
            if state["sequence_reads"] >= 3:
                state["pending"] = False
                state["text"] = "Generated answer"
                state["sequence"] += 1
        return state["sequence"]

    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: state["text"],
        clipboard_writer=write_clipboard,
        clipboard_sequence_reader=read_sequence,
    )
    adapter.enforce_clipboard_sequence = True

    assert adapter._read_verified_copy_control(
        copy_button,
        "sentinel",
        "original prompt",
    ) == "Generated answer"
    assert state["sequence_reads"] >= 3


def test_response_copy_retries_with_verified_foreground_keyboard(
    monkeypatch,
):
    events: list[str] = []
    clock = {"now": 0.0}
    state = {
        "text": "unchanged",
        "sequence": 10,
        "foreground": 321,
    }
    restored: list[int] = []
    copy_button = FakeControl("Copy", "Button", events)

    class ForegroundWindow(FakeWindow):
        def set_focus(self):
            super().set_focus()
            state["foreground"] = self.handle

    window = ForegroundWindow([copy_button], events, handle=900)

    def write_clipboard(value: str) -> None:
        state["text"] = value
        state["sequence"] += 1

    def send_keys(keys: str, **_kwargs) -> None:
        events.append(f"keys:{keys}")
        assert state["foreground"] == 900
        state["text"] = "Generated answer"
        state["sequence"] += 1

    def restore_foreground(handle: int) -> bool:
        restored.append(handle)
        state["foreground"] = handle
        return True

    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: state["text"],
        clipboard_writer=write_clipboard,
        clipboard_sequence_reader=lambda: state["sequence"],
        foreground_window_reader=lambda: state["foreground"],
        send_keys=send_keys,
    )
    adapter.enforce_clipboard_sequence = True
    adapter.chatgpt_hwnd = 900
    monkeypatch.setattr(
        chatgpt_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        adapter,
        "_sleep",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )
    monkeypatch.setattr(
        chatgpt_module,
        "_restore_foreground_window",
        restore_foreground,
    )

    assert adapter._read_verified_copy_control(
        copy_button,
        "sentinel",
        "original prompt",
        window=window,
    ) == "Generated answer"
    assert events == [
        "click:Copy",
        "focus:ChatGPT",
        "focus:Copy",
        "keys:{ENTER}",
    ]
    assert restored == [321]
    assert state["foreground"] == 321


def test_response_copy_uses_owned_pointer_fallback_after_keyboard(
    monkeypatch,
):
    events: list[str] = []
    clock = {"now": 0.0}
    state = {
        "text": "unchanged",
        "sequence": 10,
        "foreground": 321,
    }
    restored: list[int] = []
    copy_button = FakeControl("Copy", "Button", events)

    class ForegroundWindow(FakeWindow):
        def set_focus(self):
            super().set_focus()
            state["foreground"] = self.handle

    window = ForegroundWindow([copy_button], events, handle=900)

    def write_clipboard(value: str) -> None:
        state["text"] = value
        state["sequence"] += 1

    def send_keys(keys: str, **_kwargs) -> None:
        events.append(f"keys:{keys}")

    def click_pointer(control) -> None:
        events.append(f"pointer:{control.element_info.name}")
        state["text"] = "Generated answer"
        state["sequence"] += 1

    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: state["text"],
        clipboard_writer=write_clipboard,
        clipboard_sequence_reader=lambda: state["sequence"],
        foreground_window_reader=lambda: state["foreground"],
        send_keys=send_keys,
        mouse_clicker=click_pointer,
    )
    adapter.enforce_clipboard_sequence = True
    adapter.chatgpt_hwnd = 900
    adapter.response_anchor = ResponseAnchor(
        response_control_token=adapter._response_control_token(copy_button, 0)
    )
    monkeypatch.setattr(
        chatgpt_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        adapter,
        "_sleep",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )
    monkeypatch.setattr(
        chatgpt_module,
        "_restore_foreground_window",
        lambda handle: restored.append(handle) or state.update(
            foreground=handle
        ) or True,
    )

    assert adapter._read_verified_copy_control(
        copy_button,
        "sentinel",
        "original prompt",
        window=window,
    ) == "Generated answer"
    assert events == [
        "click:Copy",
        "focus:ChatGPT",
        "focus:Copy",
        "keys:{ENTER}",
        "focus:ChatGPT",
        "pointer:Copy",
    ]
    assert restored == [321]
    assert state["foreground"] == 321


def test_response_copy_retries_clipboard_read_after_sequence_change(
    monkeypatch,
):
    events: list[str] = []
    clock = {"now": 0.0}
    state = {"text": "unchanged", "sequence": 10, "reads": 0}

    def copied() -> None:
        state["sequence"] += 1

    def read_clipboard():
        state["reads"] += 1
        return "Generated answer" if state["reads"] >= 3 else None

    copy_button = FakeControl(
        "Copy",
        "Button",
        events,
        on_click=copied,
    )
    adapter = ChatGPTDesktop(
        clipboard_reader=read_clipboard,
        clipboard_writer=lambda value: state.update(
            text=value,
            sequence=state["sequence"] + 1,
        ),
        clipboard_sequence_reader=lambda: state["sequence"],
    )
    adapter.enforce_clipboard_sequence = True
    monkeypatch.setattr(
        chatgpt_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        adapter,
        "_sleep",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )

    assert adapter._read_verified_copy_control(
        copy_button,
        "sentinel",
        "original prompt",
    ) == "Generated answer"
    assert state["reads"] >= 3


def test_response_copy_waits_for_clipboard_sequence_to_stabilise(
    monkeypatch,
):
    events: list[str] = []
    clock = {"now": 0.0}
    state = {
        "text": "unchanged",
        "sequence": 10,
        "sequence_reads": 0,
    }

    def copied() -> None:
        state["text"] = "Generated answer"
        state["sequence"] += 1
        state["sequence_reads"] = 0

    def read_sequence() -> int:
        state["sequence_reads"] += 1
        if state["sequence_reads"] == 4:
            state["sequence"] += 1
        return state["sequence"]

    copy_button = FakeControl(
        "Copy",
        "Button",
        events,
        on_click=copied,
    )
    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: state["text"],
        clipboard_writer=lambda value: state.update(
            text=value,
            sequence=state["sequence"] + 1,
        ),
        clipboard_sequence_reader=read_sequence,
    )
    adapter.enforce_clipboard_sequence = True
    monkeypatch.setattr(
        chatgpt_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        adapter,
        "_sleep",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )

    assert adapter._read_verified_copy_control(
        copy_button,
        "sentinel",
        "original prompt",
    ) == "Generated answer"
    assert clock["now"] >= 0.35
    assert adapter._restore_clipboard_if_unchanged(
        "canary marker",
        expected="Generated answer",
    ) is True
    assert state["text"] == "canary marker"


def test_response_copy_does_not_send_keys_to_changed_native_window(
    monkeypatch,
):
    events: list[str] = []
    clock = {"now": 0.0}
    state = {"text": "unchanged", "sequence": 10}
    copy_button = FakeControl("Copy", "Button", events)
    window = FakeWindow([copy_button], events, handle=901)
    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: state["text"],
        clipboard_writer=lambda value: state.update(
            text=value,
            sequence=state["sequence"] + 1,
        ),
        clipboard_sequence_reader=lambda: state["sequence"],
        foreground_window_reader=lambda: 777,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )
    adapter.enforce_clipboard_sequence = True
    adapter.chatgpt_hwnd = 900
    monkeypatch.setattr(
        chatgpt_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        adapter,
        "_sleep",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )

    assert adapter._read_verified_copy_control(
        copy_button,
        "sentinel",
        "original prompt",
        window=window,
    ) is None
    assert events == ["click:Copy"]


def test_native_owned_response_copy_failure_returns_immediately():
    events: list[str] = []
    writes: list[str] = []
    copy_button = FakeControl("Copy", "Button", events)
    window = FakeWindow([copy_button], events, handle=900)
    adapter = ChatGPTDesktop(
        response_timeout_seconds=120,
        clipboard_reader=lambda: writes[-1] if writes else "unchanged",
        clipboard_writer=writes.append,
    )
    anchor = ResponseAnchor(
        response_control_token=adapter._response_control_token(copy_button, 0)
    )

    with pytest.raises(ChatGPTAutomationError) as raised:
        adapter._copy_latest_response(
            window,
            "original prompt",
            anchor=anchor,
        )

    assert raised.value.code == "response_copy_failed"
    assert raised.value.retry_mode == "response"
    assert events == ["click:Copy"]


def test_response_copy_waits_until_generation_has_finished(monkeypatch):
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    stop_button = FakeControl("Stop generating", "Button", events)
    copy_button = FakeControl("Copy", "Button", events)

    class StreamingResponseWindow(FakeWindow):
        def __init__(self):
            super().__init__([], events)
            self.reads = 0

        def descendants(self):
            self.reads += 1
            if self.reads <= 2:
                copy_button.on_click = lambda: clipboard.update(
                    text="Truncated answer"
                )
                return [stop_button, copy_button]
            copy_button.on_click = lambda: clipboard.update(
                text="Complete generated answer"
            )
            return [copy_button]

    window = StreamingResponseWindow()
    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        response_timeout_seconds=1,
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )

    result = adapter._copy_latest_response(window, "Complete prompt")

    assert result == "Complete generated answer"
    assert clipboard["text"] == "Complete generated answer"
    assert events == ["click:Copy", "click:Copy"]
    assert window.reads >= 4


def test_plain_stop_button_is_treated_as_active_generation():
    events: list[str] = []

    assert ChatGPTDesktop._response_is_generating(
        [FakeControl("Stop", "Button", events)]
    ) is True


def test_response_anchor_uses_submitted_user_copy_control():
    events: list[str] = []
    prompt = "Reply with exactly this phrase"
    window = FakeWindow([], events)
    window.handle = 900
    submitted = FakeControl(
        prompt,
        "Text",
        events,
        automation_id="submitted-text",
    )
    user_copy = FakeControl(
        "Copy message",
        "Button",
        events,
        automation_id="submitted-user-copy",
    )
    response_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="owned-response-copy",
    )
    window.controls = [submitted, user_copy, response_copy]
    adapter = ChatGPTDesktop()

    anchor = adapter._anchor_submitted_message(
        window,
        ResponseAnchor(prompt_digest=adapter._text_digest(prompt)),
    )

    assert anchor is not None
    assert anchor.submitted_message_token == adapter._stable_control_token(
        user_copy,
        1,
    )
    assert "chatgpt.user-message-copy.v1" in adapter.selector_ids


def test_response_anchor_uses_new_user_copy_when_prompt_text_is_split():
    events: list[str] = []
    prompt = "Reply with exactly this phrase: PROMPTMELD_CANARY_123456789ABC"
    window = FakeWindow([], events)
    window.handle = 900
    old_user_copy = FakeControl(
        "Copy message",
        "Button",
        events,
        automation_id="old-user-copy",
    )
    window.controls = [old_user_copy]
    adapter = ChatGPTDesktop()
    anchor = adapter._build_response_anchor(window, prompt)
    split_prompt = FakeControl(
        "Reply with exactly this phrase: PROMPTMELD",
        "Text",
        events,
        automation_id="split-prompt-text",
    )
    submitted_user_copy = FakeControl(
        "Copy message",
        "Button",
        events,
        automation_id="submitted-user-copy",
    )
    response_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="owned-response-copy",
    )
    window.controls = [
        old_user_copy,
        split_prompt,
        submitted_user_copy,
        response_copy,
    ]

    anchored = adapter._anchor_submitted_message(window, anchor)

    assert anchored is not None
    assert anchored.submitted_message_token == adapter._stable_control_token(
        submitted_user_copy,
        2,
    )
    assert "chatgpt.user-message-copy.v1" in adapter.selector_ids


def test_destination_token_ignores_chromium_runtime_identity_churn():
    events: list[str] = []
    window = FakeWindow([], events)
    window.handle = 900
    window.controls = [
        FakeControl(
            "Turn off temporary chat",
            "Button",
            events,
            automation_id="temporary-toggle-before",
        ),
        FakeComposer(events),
    ]
    adapter = ChatGPTDesktop()
    before = adapter._destination_token(window)
    rerendered_composer = FakeComposer(events)
    rerendered_composer.element_info.automation_id = "composer-after"
    window.controls = [
        FakeControl(
            "Turn off temporary chat",
            "Button",
            events,
            automation_id="temporary-toggle-after",
        ),
        rerendered_composer,
    ]

    assert adapter._destination_token(window) == before


def test_destination_token_changes_when_temporary_chat_is_left():
    events: list[str] = []
    window = FakeWindow([], events)
    window.handle = 900
    adapter = ChatGPTDesktop()
    window.controls = [
        FakeControl("Turn off temporary chat", "Button", events),
        FakeComposer(events),
    ]
    temporary = adapter._destination_token(window)
    window.controls = [
        FakeControl("Turn on temporary chat", "Button", events),
        FakeComposer(events),
    ]

    assert adapter._destination_token(window) != temporary


def test_temporary_destination_tolerates_transiently_missing_controls():
    events: list[str] = []
    window = FakeWindow([], events)
    window.handle = 900
    adapter = ChatGPTDesktop()
    window.controls = [
        FakeControl("Turn off temporary chat", "Button", events),
        FakeComposer(events),
    ]
    anchor = adapter._build_response_anchor(window, "canary prompt")
    window.controls = [FakeControl("Stop", "Button", events)]

    assert adapter._destination_conflicts(
        window,
        window.controls,
        anchor,
    ) is False


def test_temporary_destination_rejects_explicit_exit():
    events: list[str] = []
    window = FakeWindow([], events)
    window.handle = 900
    adapter = ChatGPTDesktop()
    window.controls = [
        FakeControl("Turn off temporary chat", "Button", events),
        FakeComposer(events),
    ]
    anchor = adapter._build_response_anchor(window, "canary prompt")
    window.controls = [
        FakeControl("Turn on temporary chat", "Button", events),
        FakeComposer(events),
    ]

    assert adapter._destination_conflicts(
        window,
        window.controls,
        anchor,
    ) is True


def test_anchored_response_survives_submitted_prompt_virtualization():
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    window = FakeWindow([], events)
    window.handle = 900
    response_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="owned-response-copy",
        on_click=lambda: clipboard.update(text="owned response"),
    )
    window.controls = [response_copy]
    adapter = ChatGPTDesktop(
        response_timeout_seconds=0.1,
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )
    anchor = ResponseAnchor(
        destination_token=adapter._destination_token(window),
        prompt_digest=adapter._text_digest("virtualized prompt"),
        submitted_message_token="missing-user-message|Button||",
        response_control_token=adapter._response_control_token(response_copy, 0),
    )

    assert adapter._copy_latest_response(
        window,
        "virtualized prompt",
        anchor=anchor,
    ) == "owned response"


def test_response_anchor_stays_with_first_assistant_copy_before_next_user_turn():
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    prompt = "owned prompt"
    window = FakeWindow([], events)
    window.handle = 900
    submitted = FakeControl(
        prompt,
        "Text",
        events,
        automation_id="submitted-text",
    )
    user_copy = FakeControl(
        "Copy message",
        "Button",
        events,
        automation_id="owned-user-copy",
    )
    owned_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="owned-response-copy",
        on_click=lambda: clipboard.update(text="owned response"),
    )
    later_user_copy = FakeControl(
        "Copy message",
        "Button",
        events,
        automation_id="later-user-copy",
    )
    unrelated_copy = FakeControl(
        "Copy",
        "Button",
        events,
        automation_id="later-response-copy",
        on_click=lambda: clipboard.update(text="unrelated response"),
    )
    window.controls = [
        submitted,
        user_copy,
        owned_copy,
        later_user_copy,
        unrelated_copy,
    ]
    adapter = ChatGPTDesktop(
        response_timeout_seconds=0.1,
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )
    anchor = adapter._anchor_submitted_message(
        window,
        ResponseAnchor(
            destination_token=adapter._destination_token(window),
            prompt_digest=adapter._text_digest(prompt),
        ),
    )

    assert anchor is not None
    assert adapter._copy_latest_response(
        window,
        prompt,
        anchor=anchor,
    ) == "owned response"
    assert "click:Copy" in events
    assert clipboard["text"] == "owned response"


def test_indefinite_response_wait_continues_until_copy_is_available(
    monkeypatch,
):
    events: list[str] = []
    clipboard = {"text": "unchanged"}
    copy_button = FakeControl("Copy response", "Button", events)
    copy_button.on_click = lambda: clipboard.update(text="Late answer")

    class DelayedResponseWindow(FakeWindow):
        def __init__(self):
            super().__init__([], events)
            self.reads = 0

        def descendants(self):
            self.reads += 1
            return [copy_button] if self.reads >= 4 else []

    monkeypatch.setattr("promptmeld.chatgpt.time.sleep", lambda _delay: None)
    adapter = ChatGPTDesktop(
        response_timeout_seconds=None,
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
    )

    result = adapter._copy_latest_response(
        DelayedResponseWindow(),
        "Complete prompt",
    )

    assert result == "Late answer"
    assert adapter.response_timeout_seconds is None


def test_response_can_be_captured_for_review_without_remaining_on_clipboard():
    events: list[str] = []
    clipboard = {"text": "selected source"}
    copy_button = FakeControl("Copy", "Button", events)
    copy_button.on_click = lambda: clipboard.update(text="Marked alternatives")
    controls = [
        FakeControl("Switch mode, current mode: ChatGPT", "Button", events),
        FakeControl("New chat", "Button", events, class_name="sidebar-item"),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl("Change project: WritingLauncher", "Button", events),
        FakeComposer(events),
        copy_button,
    ]
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: clipboard["text"],
        clipboard_writer=lambda text: clipboard.update(text=text),
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "complete prompt",
        "WritingLauncher",
        capture_generated_text=True,
    )

    assert result.generated_text == "Marked alternatives"
    assert result.generated_text_copied is False
    assert clipboard["text"] == "selected source"


def test_background_activation_does_not_take_focus_as_a_fallback():
    events: list[str] = []

    class FocusOnlyControl:
        element_info = ElementInfo("Copy", "Button")

        def set_focus(self):
            events.append("focus")

    adapter = ChatGPTDesktop()

    activated = adapter._activate_control(
        FocusOnlyControl(),
        allow_focus=False,
    )

    assert activated is False
    assert events == []


def test_chatgpt_companion_adapter_has_no_source_application_interface():
    parameters = inspect.signature(ChatGPTDesktop.submit).parameters

    for forbidden in (
        "source_hwnd",
        "source_is_editable",
        "source_text",
        "source_app",
        "replace_selected_text",
    ):
        assert forbidden not in parameters


def test_response_wait_uses_the_chatgpt_native_window_handle():
    window = FakeWindow([], [])
    window.handle = 900

    assert ChatGPTDesktop._native_window_handle(window) == 900


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
    assert clipboard == []


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
    assert clipboard == []


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
    cloud = FakeControl("Cloud", "Button", events)
    local = FakeControl("Local", "Button", events)
    controls.append(add_project)
    activations = 0

    def advance_creation():
        nonlocal activations
        activations += 1
        if activations == 1:
            controls.append(search)
        else:
            controls.remove(search)
            controls.extend([cloud, local])

    add_project.on_click = advance_creation
    cloud.on_click = lambda: (
        controls.remove(cloud),
        controls.remove(local),
        controls.extend([name_edit, create]),
    )
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
    assert "click:Cloud" in events
    assert "click:Local" not in events
    assert "focus:Project name" in events


def test_project_creation_chooses_cloud_before_naming():
    events: list[str] = []
    controls: list[FakeControl] = []
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Button", events)
    cloud = FakeControl("Cloud", "Button", events)
    local = FakeControl("Local", "Button", events)

    def show_storage_choice():
        controls.extend([cloud, local])

    def choose_cloud():
        controls.remove(cloud)
        controls.remove(local)
        controls.extend([name_edit, create])

    add_project = FakeControl(
        "Add new project",
        "Button",
        events,
        on_click=show_storage_choice,
    )
    controls.append(add_project)
    cloud.on_click = choose_cloud
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is True
    assert events.index("click:Cloud") < events.index("focus:Project name")
    assert "click:Local" not in events


def test_project_creation_chooses_cloud_when_name_is_already_visible():
    events: list[str] = []
    controls: list[FakeControl] = []
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Button", events)
    cloud = FakeControl("Cloud", "RadioButton", events)
    local = FakeControl("Local", "RadioButton", events)

    def show_creation_form():
        controls.extend([name_edit, cloud, local, create])

    def choose_cloud():
        controls.remove(cloud)
        controls.remove(local)

    controls.append(
        FakeControl(
            "Add new project",
            "Button",
            events,
            on_click=show_creation_form,
        )
    )
    cloud.on_click = choose_cloud
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is True
    assert events.index("click:Cloud") < events.index("focus:Project name")
    assert "click:Local" not in events


def test_project_creation_advances_current_cloud_type_dialog():
    events: list[str] = []
    controls: list[FakeControl] = []
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Button", events)
    cloud = FakeControl(
        "Cloud Work through ideas and tasks without setup",
        "Button",
        events,
    )
    local = FakeControl(
        "Local Edit, run, and test files on your computer",
        "Button",
        events,
    )
    cloud.is_selected = lambda: True
    local.is_selected = lambda: False
    next_control = FakeControl("Next", "Button", events)

    def advance_to_name():
        controls.remove(cloud)
        controls.remove(local)
        controls.remove(next_control)
        controls.extend([name_edit, create])

    next_control.on_click = advance_to_name
    controls.extend(
        [
            FakeControl("Add new project", "Button", events),
            cloud,
            local,
            next_control,
        ]
    )
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is True
    assert "click:Cloud Work through ideas and tasks without setup" not in events
    assert "click:Local Edit, run, and test files on your computer" not in events
    assert "click:Next" in events
    assert events.index("click:Next") < events.index("focus:Project name")


def test_project_creation_handles_cloud_list_item_with_text_child():
    events: list[str] = []
    controls: list[FakeControl] = []
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Button", events)

    class StorageListItem(FakeControl):
        def descendants(self):
            return [FakeControl("Cloud", "Text", events)]

    cloud = StorageListItem(
        "Work through ideas and tasks without setup",
        "ListItem",
        events,
    )
    next_control = FakeControl("Next", "Text", events)

    def advance_to_name():
        controls.remove(cloud)
        controls.remove(next_control)
        controls.extend([name_edit, create])

    next_control.on_click = advance_to_name
    controls.extend(
        [
            FakeControl("Add new project", "Button", events),
            cloud,
            next_control,
        ]
    )
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is True
    assert "click:Work through ideas and tasks without setup" in events
    assert "click:Next" in events
    assert events.index("click:Next") < events.index("focus:Project name")
    assert not any("Local" in event for event in events)


def test_project_creation_accepts_enabled_create_text_control():
    events: list[str] = []
    controls: list[FakeControl] = []
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Text", events)
    controls.extend(
        [
            FakeControl("Add new project", "Button", events),
            name_edit,
            create,
        ]
    )
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )
    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: "original clipboard",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is True
    assert "click:Create project" in events


def test_project_creation_requires_positive_project_evidence():
    events: list[str] = []
    controls: list[FakeControl] = []
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Button", events)
    controls.extend(
        [
            FakeControl("Add new project", "Button", events),
            name_edit,
            create,
        ]
    )
    create.on_click = lambda: (
        controls.remove(name_edit),
        controls.remove(create),
    )
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.01,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is False
    assert events.count("click:Create project") == 1
    assert adapter.navigation_failure_code == (
        "project_create_activation_unconfirmed"
    )
    assert adapter.navigation_retry_mode == "inspect"


def test_project_creation_rejects_disabled_create_control():
    events: list[str] = []
    controls = [
        FakeControl("Add new project", "Button", events),
        FakeControl(
            "Project name",
            "Edit",
            events,
            automation_id="chatgpt-project-name",
        ),
        FakeControl(
            "Create project",
            "Button",
            events,
            enabled=False,
        ),
    ]
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.01,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is False
    assert "click:Create project" not in events
    assert adapter.navigation_failure_code == "project_create_unavailable"
    assert adapter.navigation_retry_mode == "delivery"


def test_project_creation_rejects_unconfirmed_cloud_choice():
    events: list[str] = []
    controls = [
        FakeControl("Add new project", "Button", events),
        FakeControl(
            "Project name",
            "Edit",
            events,
            automation_id="chatgpt-project-name",
        ),
        FakeControl("Cloud", "RadioButton", events),
        FakeControl("Local", "RadioButton", events),
        FakeControl("Create project", "Button", events),
    ]
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.01,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is False
    assert events.count("click:Cloud") == 1
    assert "click:Local" not in events
    assert "click:Create project" not in events
    assert adapter.navigation_failure_code == (
        "project_cloud_activation_unconfirmed"
    )


def test_project_creation_requires_paired_storage_choices():
    events: list[str] = []
    controls = [
        FakeControl("Add new project", "Button", events),
        FakeControl("Cloud", "Button", events),
    ]
    adapter = ChatGPTDesktop(timeout_seconds=0.01)

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is False
    assert "click:Cloud" not in events
    assert adapter.navigation_failure_code == (
        "project_storage_choice_missing"
    )


def test_project_creation_reacquires_stale_window_wrappers(monkeypatch):
    events: list[str] = []
    controls: list[FakeControl] = [
        FakeControl("Add new project", "Button", events),
        FakeControl(
            "Project name",
            "Edit",
            events,
            automation_id="chatgpt-project-name",
        ),
    ]
    create = FakeControl("Create project", "Button", events)
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )
    controls.append(create)
    fresh_window = FakeWindow(controls, events)

    class StaleWindow(FakeWindow):
        def descendants(self):
            raise RuntimeError("stale UIA wrapper")

    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.01,
    )
    monkeypatch.setattr(
        adapter,
        "_refresh_chatgpt_window",
        lambda: fresh_window,
    )

    assert adapter._create_project(
        StaleWindow([], events),
        "WritingLauncher",
    ) is True
    assert "click:Create project" in events


def test_project_creation_accepts_exact_project_row_as_evidence():
    events: list[str] = []
    controls: list[FakeControl] = [
        FakeControl("Add new project", "Button", events),
        FakeControl(
            "Project name",
            "Edit",
            events,
            automation_id="chatgpt-project-name",
        ),
    ]
    create = FakeControl("Create project", "Button", events)
    create.on_click = lambda: controls.append(
        FakeControl(
            "WritingLauncher",
            "Button",
            events,
            class_name="sidebar-item group/folder-row",
        )
    )
    controls.append(create)
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.01,
    )

    assert adapter._create_project(
        FakeWindow(controls, events),
        "WritingLauncher",
    ) is True


def test_project_creation_logs_exclude_project_name(caplog):
    events: list[str] = []
    private_project_name = "Private Customer Project"
    controls: list[FakeControl] = [
        FakeControl("Add new project", "Button", events),
        FakeControl(
            "Project name",
            "Edit",
            events,
            automation_id="chatgpt-project-name",
        ),
    ]
    create = FakeControl("Create project", "Button", events)
    create.on_click = lambda: controls.append(
        FakeControl(
            f"Change project: {private_project_name}",
            "Button",
            events,
        )
    )
    controls.append(create)
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.01,
    )
    caplog.set_level("INFO", logger="promptmeld.chatgpt")

    assert adapter._create_project(
        FakeWindow(controls, events),
        private_project_name,
    ) is True
    assert private_project_name not in caplog.text
    assert "project_step=confirm-project-created" in caplog.text


def test_submit_exposes_project_creation_failure_checkpoint(monkeypatch):
    events: list[str] = []
    clipboard: list[str] = []
    window = FakeWindow([], events)
    adapter = ChatGPTDesktop(
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
    )
    monkeypatch.setattr(adapter, "_get_or_launch_window", lambda: window)

    def fail_project_creation(window, project_name):
        adapter._report_progress(
            "opening-project",
            "Opening the requested Project",
        )
        return adapter._project_creation_failed(
            "confirm whether ChatGPT created the Cloud Project",
            "project_create_activation_unconfirmed",
            retry_mode="inspect",
        )

    monkeypatch.setattr(
        adapter,
        "_navigate_to_project_chat",
        fail_project_creation,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.failed_stage == "opening-project"
    assert result.failure_code == "project_create_activation_unconfirmed"
    assert result.retry_mode == "inspect"
    assert result.recoverable is True


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
