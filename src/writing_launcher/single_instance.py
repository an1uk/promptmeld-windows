from __future__ import annotations

import ctypes
from ctypes import wintypes

from .branding import (
    HOTKEY_RECEIVER_TITLE,
    LEGACY_HOTKEY_RECEIVER_TITLE,
    SINGLE_INSTANCE_NAME,
)
from .windows import ACTIVATE_EXISTING_MESSAGE

_ERROR_ALREADY_EXISTS = 183
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_KERNEL32.CreateMutexW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
_KERNEL32.CreateMutexW.restype = wintypes.HANDLE
_KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL32.CloseHandle.restype = wintypes.BOOL
_USER32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_USER32.FindWindowW.restype = wintypes.HWND
_USER32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_USER32.PostMessageW.restype = wintypes.BOOL


class SingleInstance:
    """Low-overhead Windows mutex with activation signalling."""

    def __init__(self, name: str = SINGLE_INSTANCE_NAME):
        self.name = name
        self.handle: int | None = None

    def acquire(self) -> bool:
        for title in (
            HOTKEY_RECEIVER_TITLE,
            LEGACY_HOTKEY_RECEIVER_TITLE,
        ):
            existing_window = _USER32.FindWindowW(None, title)
            if existing_window:
                _USER32.PostMessageW(
                    existing_window,
                    ACTIVATE_EXISTING_MESSAGE,
                    0,
                    0,
                )
                return False

        handle = _KERNEL32.CreateMutexW(None, False, self.name)
        if not handle:
            return False
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            _KERNEL32.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle:
            _KERNEL32.CloseHandle(self.handle)
            self.handle = None

    def __del__(self) -> None:
        self.release()
