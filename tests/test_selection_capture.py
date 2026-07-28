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
