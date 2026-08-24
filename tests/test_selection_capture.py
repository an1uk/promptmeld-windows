import win32con

from promptmeld import clipboard, windows
from promptmeld.windows import SelectionCapture


def test_clipboard_snapshot_initialises_ole_for_full_format_restore(
    monkeypatch,
):
    events = []
    data_object = object()

    class PythonCom:
        @staticmethod
        def OleInitialize():
            events.append("ole-initialise")

        @staticmethod
        def OleGetClipboard():
            events.append("ole-get")
            return data_object

        @staticmethod
        def CoUninitialize():
            events.append("com-uninitialise")

    monkeypatch.setattr(clipboard, "pythoncom", PythonCom)
    monkeypatch.setattr(clipboard, "read_clipboard_text", lambda: None)
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "OpenClipboard",
        lambda: None,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "CloseClipboard",
        lambda: None,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "CountClipboardFormats",
        lambda: 1,
    )
    formats = iter([0xC123, 0])
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "EnumClipboardFormats",
        lambda previous: next(formats),
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardData",
        lambda format_id: b"custom payload",
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardSequenceNumber",
        lambda: 7,
    )

    snapshot = clipboard.ClipboardSnapshot.capture()

    assert snapshot.data_object is data_object
    assert snapshot.registered_formats == {0xC123: b"custom payload"}
    assert events == ["ole-initialise", "ole-get"]
    snapshot.close()
    assert events[-1] == "com-uninitialise"


def test_clipboard_snapshot_reattaches_missing_registered_byte_format(
    monkeypatch,
):
    state = {
        "sequence": 10,
        "open": False,
        "formats": {},
    }

    class PythonCom:
        @staticmethod
        def OleSetClipboard(data_object):
            state["sequence"] += 1

        @staticmethod
        def OleFlushClipboard():
            return None

    monkeypatch.setattr(clipboard, "pythoncom", PythonCom)
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardSequenceNumber",
        lambda: state["sequence"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "OpenClipboard",
        lambda: state.update(open=True),
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "CloseClipboard",
        lambda: state.update(open=False),
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "IsClipboardFormatAvailable",
        lambda format_id: format_id in state["formats"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardData",
        lambda format_id: state["formats"][format_id],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "SetClipboardData",
        lambda format_id, payload: state["formats"].update(
            {format_id: payload}
        ),
    )
    snapshot = clipboard.ClipboardSnapshot(
        object(),
        "marker text",
        1,
        registered_formats={0xC123: b"custom payload"},
    )
    snapshot.mark_owned(state["sequence"])

    assert snapshot.restore_if_owned() is True
    assert state["formats"] == {0xC123: b"custom payload"}
    assert state["open"] is False


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
        def mark_owned(self, sequence=None):
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


def test_selection_capture_does_not_restore_after_newer_clipboard_change(
    monkeypatch,
):
    state = {"sequence": 10}
    events: list[str] = []

    class Snapshot:
        owned_sequence = None

        def mark_owned(self, sequence=None):
            self.owned_sequence = state["sequence"] if sequence is None else sequence
            if sequence is not None:
                # Simulate the user copying immediately after PromptMeld read
                # the stable selection but before restoration.
                state["sequence"] += 1

        def restore_if_owned(self):
            if state["sequence"] == self.owned_sequence:
                events.append("restore")
                return True
            events.append("preserve-newer")
            return False

    monkeypatch.setattr(
        windows.ClipboardSnapshot,
        "capture",
        lambda: Snapshot(),
    )
    monkeypatch.setattr(
        windows.win32clipboard,
        "GetClipboardSequenceNumber",
        lambda: state["sequence"],
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
    assert events == ["preserve-newer"]


def test_word_editor_window_class_is_treated_as_editable():
    assert SelectionCapture._looks_like_editable_class("_WwG") is True


def test_generic_browser_document_class_is_not_assumed_editable():
    assert (
        SelectionCapture._looks_like_editable_class(
            "Chrome_RenderWidgetHostHWND"
        )
        is False
    )


def test_clipboard_canary_verifies_full_marker_and_restores_original(
    monkeypatch,
):
    state = {"sequence": 1, "formats": {}}

    class Snapshot:
        def __init__(self):
            self.owned = None
            self.restored = False

        def mark_owned(self, sequence):
            self.owned = sequence

        def restore_if_owned(self):
            self.restored = state["sequence"] == self.owned
            return self.restored

        def close(self):
            pass

    snapshot = Snapshot()
    monkeypatch.setattr(
        clipboard.ClipboardSnapshot,
        "capture",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "RegisterClipboardFormat",
        lambda name: 500,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "OpenClipboard",
        lambda: None,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "CloseClipboard",
        lambda: None,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "EmptyClipboard",
        lambda: state["formats"].clear(),
    )

    def set_data(format_id, value):
        state["formats"][format_id] = value
        state["sequence"] += 1

    monkeypatch.setattr(
        clipboard.win32clipboard,
        "SetClipboardData",
        set_data,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardSequenceNumber",
        lambda: state["sequence"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "IsClipboardFormatAvailable",
        lambda format_id: format_id in state["formats"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardData",
        lambda format_id: state["formats"][format_id],
    )

    probe = clipboard.ClipboardCanaryProbe.begin("TOKEN")
    state["sequence"] += 1  # Simulate helper restoration of both formats.

    assert state["formats"][win32con.CF_UNICODETEXT].endswith("TOKEN")
    assert state["formats"][500] == b"TOKEN"
    assert probe.finish() is True
    assert snapshot.restored is True


def test_clipboard_canary_never_overwrites_newer_user_content(monkeypatch):
    state = {"sequence": 1, "formats": {}}

    class Snapshot:
        def __init__(self):
            self.closed = False

        def mark_owned(self, sequence):
            raise AssertionError("newer clipboard must not be claimed")

        def restore_if_owned(self):
            raise AssertionError("newer clipboard must not be restored over")

        def close(self):
            self.closed = True

    snapshot = Snapshot()
    monkeypatch.setattr(
        clipboard.ClipboardSnapshot,
        "capture",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "RegisterClipboardFormat",
        lambda name: 500,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "OpenClipboard",
        lambda: None,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "CloseClipboard",
        lambda: None,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "EmptyClipboard",
        lambda: state["formats"].clear(),
    )

    def set_data(format_id, value):
        state["formats"][format_id] = value
        state["sequence"] += 1

    monkeypatch.setattr(
        clipboard.win32clipboard,
        "SetClipboardData",
        set_data,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardSequenceNumber",
        lambda: state["sequence"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "IsClipboardFormatAvailable",
        lambda format_id: format_id in state["formats"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardData",
        lambda format_id: state["formats"][format_id],
    )

    probe = clipboard.ClipboardCanaryProbe.begin("TOKEN")
    state["formats"] = {win32con.CF_UNICODETEXT: "newer user copy"}
    state["sequence"] += 1

    assert probe.finish() is False
    assert state["formats"] == {
        win32con.CF_UNICODETEXT: "newer user copy"
    }
    assert snapshot.closed is True


def test_clipboard_canary_retries_transient_busy_read(monkeypatch):
    state = {"sequence": 1, "formats": {}, "open_attempts": 0}

    class Snapshot:
        def __init__(self):
            self.owned = None
            self.restored = False

        def mark_owned(self, sequence):
            self.owned = sequence

        def restore_if_owned(self):
            self.restored = state["sequence"] == self.owned
            return self.restored

        def close(self):
            pass

    snapshot = Snapshot()
    monkeypatch.setattr(
        clipboard.ClipboardSnapshot,
        "capture",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "RegisterClipboardFormat",
        lambda name: 500,
    )

    def open_clipboard():
        state["open_attempts"] += 1
        # The first call belongs to begin(). The first two finish() reads
        # reproduce Qt briefly retaining clipboard ownership.
        if state["open_attempts"] in {2, 3}:
            raise OSError("clipboard busy")

    monkeypatch.setattr(
        clipboard.win32clipboard,
        "OpenClipboard",
        open_clipboard,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "CloseClipboard",
        lambda: None,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "EmptyClipboard",
        lambda: state["formats"].clear(),
    )

    def set_data(format_id, value):
        state["formats"][format_id] = value
        state["sequence"] += 1

    monkeypatch.setattr(
        clipboard.win32clipboard,
        "SetClipboardData",
        set_data,
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardSequenceNumber",
        lambda: state["sequence"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "IsClipboardFormatAvailable",
        lambda format_id: format_id in state["formats"],
    )
    monkeypatch.setattr(
        clipboard.win32clipboard,
        "GetClipboardData",
        lambda format_id: state["formats"][format_id],
    )

    probe = clipboard.ClipboardCanaryProbe.begin("TOKEN")

    assert probe.finish() is True
    assert state["open_attempts"] == 4
    assert snapshot.restored is True
