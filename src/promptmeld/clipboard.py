from __future__ import annotations

import time

import win32clipboard
import win32con


class ClipboardBusyError(RuntimeError):
    pass


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
