from __future__ import annotations

import time

import win32clipboard
import win32con

try:
    import pythoncom
except ImportError:  # pragma: no cover - Windows builds include pywin32.
    pythoncom = None


class ClipboardBusyError(RuntimeError):
    pass


class ClipboardSnapshot:
    """Restore a clipboard only while PromptMeld still owns its last change."""

    def __init__(
        self,
        data_object,
        text: str | None,
        sequence: int,
        com_initialized: bool = False,
    ):
        self.data_object = data_object
        self.text = text
        self.sequence = sequence
        self.owned_sequence: int | None = None
        self.com_initialized = com_initialized

    @classmethod
    def capture(cls) -> "ClipboardSnapshot":
        data_object = None
        com_initialized = False
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
                com_initialized = True
                data_object = pythoncom.OleGetClipboard()
            except Exception:
                data_object = None
        return cls(
            data_object,
            read_clipboard_text(),
            int(win32clipboard.GetClipboardSequenceNumber()),
            com_initialized,
        )

    def mark_owned(self) -> None:
        self.owned_sequence = int(win32clipboard.GetClipboardSequenceNumber())

    def restore_if_owned(self) -> bool:
        try:
            if self.owned_sequence is None:
                return False
            if (
                int(win32clipboard.GetClipboardSequenceNumber())
                != self.owned_sequence
            ):
                return False
            if self.data_object is not None and pythoncom is not None:
                try:
                    pythoncom.OleSetClipboard(self.data_object)
                    return True
                except Exception:
                    pass
            if self.text is not None:
                write_clipboard_text(self.text)
                return True
            return False
        finally:
            if self.com_initialized and pythoncom is not None:
                pythoncom.CoUninitialize()
                self.com_initialized = False


def empty_clipboard() -> None:
    for attempt in range(10):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception as exc:
            if attempt == 9:
                raise ClipboardBusyError(
                    "The clipboard is busy. Close any clipboard popup and try again."
                ) from exc
            time.sleep(0.02)


def read_clipboard_text() -> str | None:
    try:
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(
                win32con.CF_UNICODETEXT
            ):
                return None
            value = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return value if isinstance(value, str) else None
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return None


def write_clipboard_text(text: str) -> None:
    for attempt in range(15):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception:
            if attempt == 14:
                raise
            time.sleep(0.025)
