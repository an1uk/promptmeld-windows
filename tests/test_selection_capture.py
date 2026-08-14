from promptmeld import windows
from promptmeld.windows import SelectionCapture


def test_selection_capture_retries_copy_when_first_attempt_is_missed(
    monkeypatch,
):
    copy_attempts = 0

    def send_copy() -> None:
        nonlocal copy_attempts
        copy_attempts += 1

    monkeypatch.setattr(windows.win32gui, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(windows.win32gui, "GetWindowText", lambda hwnd: "Editor")
    monkeypatch.setattr(windows.win32gui, "GetClassName", lambda hwnd: "Edit")
    capture = SelectionCapture(timeout_ms=200)
    monkeypatch.setattr(
        capture,
        "_source_executable",
        lambda hwnd: "winword.exe",
    )
    monkeypatch.setattr(capture, "_empty_clipboard", lambda: None)
    monkeypatch.setattr(capture, "_send_copy", send_copy)
    monkeypatch.setattr(
        capture,
        "_read_text",
        lambda: "Selected text" if copy_attempts >= 2 else None,
    )

    selection = capture.capture()

    assert copy_attempts == 2
    assert selection.text == "Selected text"
    assert selection.source_hwnd == 123
    assert selection.source_is_editable is True
    assert selection.source_app == "winword.exe"


def test_selection_capture_restores_owned_clipboard(monkeypatch):
    events: list[str] = []

    class Snapshot:
        def mark_owned(self):
            events.append("owned")

        def restore_if_owned(self):
            events.append("restore")
            return True

    monkeypatch.setattr(
        windows.ClipboardSnapshot,
        "capture",
        lambda: Snapshot(),
    )
    monkeypatch.setattr(windows.win32gui, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(windows.win32gui, "GetWindowText", lambda hwnd: "Editor")
    monkeypatch.setattr(windows.win32gui, "GetClassName", lambda hwnd: "Edit")
    capture = SelectionCapture(timeout_ms=100)
    monkeypatch.setattr(capture, "_source_executable", lambda hwnd: "editor.exe")
    monkeypatch.setattr(capture, "_empty_clipboard", lambda: None)
    monkeypatch.setattr(capture, "_send_copy", lambda: None)
    monkeypatch.setattr(capture, "_read_text", lambda: "Selected text")

    assert capture.capture().text == "Selected text"
    assert events == ["owned", "owned", "restore"]


def test_word_editor_window_class_is_treated_as_editable():
    assert SelectionCapture._looks_like_editable_class("_WwG") is True


def test_generic_browser_document_class_is_not_assumed_editable():
    assert (
        SelectionCapture._looks_like_editable_class(
            "Chrome_RenderWidgetHostHWND"
        )
        is False
    )
