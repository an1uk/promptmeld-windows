from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

import win32api
import win32con
import win32gui
import win32process
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QWidget

from .clipboard import (
    ClipboardBusyError,
    empty_clipboard,
    read_clipboard_text,
    write_clipboard_text,
)
from .branding import HOTKEY_RECEIVER_TITLE
from .models import CapturedSelection

LOGGER = logging.getLogger(__name__)
_USER32 = ctypes.WinDLL("user32", use_last_error=True)
ACTIVATE_EXISTING_MESSAGE = win32con.WM_APP + 0x214


class SelectionCaptureError(RuntimeError):
    pass


class SelectionCapture:
    def __init__(self, timeout_ms: int = 1000):
        self.timeout_ms = timeout_ms

    def capture(self) -> CapturedSelection:
        source_hwnd = win32gui.GetForegroundWindow()
        source_title = win32gui.GetWindowText(source_hwnd)
        source_class = win32gui.GetClassName(source_hwnd)
        source_app = self._source_executable(source_hwnd)
        source_is_editable = self._source_is_editable(source_hwnd, source_class)
        LOGGER.info(
            "Capturing selection from application=%r class=%r hwnd=%s",
            source_app,
            source_class,
            source_hwnd,
        )
        self._empty_clipboard()
        self._send_copy()

        started = time.monotonic()
        deadline = started + (self.timeout_ms / 1000)
        retry_at = started + min(0.35, (self.timeout_ms / 1000) / 2)
        copy_retried = False
        text: str | None = None
        while time.monotonic() < deadline:
            text = self._read_text()
            if text:
                break
            if not copy_retried and time.monotonic() >= retry_at:
                copy_retried = True
                if win32gui.GetForegroundWindow() == source_hwnd:
                    LOGGER.info(
                        "Retrying selection copy for window class=%r hwnd=%s",
                        source_class,
                        source_hwnd,
                    )
                    self._send_copy()
                else:
                    LOGGER.warning(
                        "Source window lost focus before copy retry; hwnd=%s",
                        source_hwnd,
                    )
            time.sleep(0.025)

        if not text or not text.strip():
            LOGGER.warning(
                "No text selection detected from window class=%r hwnd=%s",
                source_class,
                source_hwnd,
            )
            raise SelectionCaptureError(
                "No selected text was detected. Select text in another "
                "application and try again."
            )
        return CapturedSelection(
            text=text,
            source_hwnd=source_hwnd,
            source_title=source_title,
            source_is_editable=source_is_editable,
            source_app=source_app,
        )

    @staticmethod
    def _source_executable(source_hwnd: int) -> str:
        """Identify the source executable without retaining its full path."""

        handle = None
        try:
            _thread_id, process_id = win32process.GetWindowThreadProcessId(
                source_hwnd
            )
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION
                | win32con.PROCESS_VM_READ,
                False,
                process_id,
            )
            path = win32process.GetModuleFileNameEx(handle, 0)
            return str(path).replace("\\", "/").rsplit("/", 1)[-1].casefold()
        except Exception:
            LOGGER.debug(
                "Could not identify the selected text's source executable",
                exc_info=True,
            )
            return ""
        finally:
            if handle is not None:
                try:
                    handle.Close()
                except Exception:
                    pass

    @classmethod
    def _source_is_editable(cls, source_hwnd: int, source_class: str) -> bool:
        """Determine whether the captured selection came from an editable UI."""

        focused_hwnd = cls._focused_hwnd() or source_hwnd
        focused_class = cls._window_class(focused_hwnd)
        if cls._looks_like_editable_class(
            focused_class
        ) or cls._looks_like_editable_class(source_class):
            return True

        # Web editors and custom controls often expose their editability only
        # through UI Automation rather than a useful Win32 class name.
        try:
            import pythoncom
            from pywinauto.uia_defines import IUIA

            pythoncom.CoInitialize()
            try:
                iuia = IUIA()
                element = iuia.get_focused_element()
                control_type = iuia.known_control_type_ids.get(
                    int(element.CurrentControlType),
                    "",
                )
                if control_type == "Edit":
                    try:
                        from pywinauto.uia_defines import get_elem_interface

                        value_pattern = get_elem_interface(element, "Value")
                        return not bool(value_pattern.CurrentIsReadOnly)
                    except Exception:
                        # Some editable web and custom controls expose the Edit
                        # control type without a Value pattern. Treating only
                        # Edit as writable is still safer than accepting a
                        # generic Document, which can be an ordinary web page.
                        return True
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            LOGGER.debug(
                "Could not inspect the focused UI Automation element",
                exc_info=True,
            )
        return False

    @staticmethod
    def _focused_hwnd() -> int | None:
        try:
            info = win32gui.GetGUIThreadInfo(0)
            if isinstance(info, tuple) and len(info) >= 3:
                return int(info[2]) or None
            if isinstance(info, dict):
                return int(info.get("hwndFocus", 0)) or None
        except Exception:
            LOGGER.debug("Could not read the focused Win32 control", exc_info=True)
        return None

    @staticmethod
    def _window_class(hwnd: int) -> str:
        try:
            return win32gui.GetClassName(hwnd)
        except Exception:
            return ""

    @staticmethod
    def _looks_like_editable_class(class_name: str) -> bool:
        folded = (class_name or "").strip().casefold()
        return folded in {
            "edit",
            "richedit20a",
            "richedit20w",
            "richedit50w",
            "richeditd2dpt",
            "scintilla",
            "tedit",
            "wxwindowclassnr",
            "_wwg",
        } or folded.startswith("richedit")

    @staticmethod
    def _send_copy() -> None:
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        try:
            win32api.keybd_event(ord("C"), 0, 0, 0)
            win32api.keybd_event(
                ord("C"),
                0,
                win32con.KEYEVENTF_KEYUP,
                0,
            )
        finally:
            win32api.keybd_event(
                win32con.VK_CONTROL,
                0,
                win32con.KEYEVENTF_KEYUP,
                0,
            )
        time.sleep(0.01)

    @staticmethod
    def _empty_clipboard() -> None:
        try:
            empty_clipboard()
        except ClipboardBusyError as exc:
            raise SelectionCaptureError(str(exc)) from exc

    @staticmethod
    def _read_text() -> str | None:
        return read_clipboard_text()


class SourceRecoveryError(RuntimeError):
    pass


def _send_control_shortcut(key: str, pause: float = 0.03) -> None:
    virtual_key = ord(key.upper())
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    try:
        win32api.keybd_event(virtual_key, 0, 0, 0)
        win32api.keybd_event(
            virtual_key,
            0,
            win32con.KEYEVENTF_KEYUP,
            0,
        )
    finally:
        win32api.keybd_event(
            win32con.VK_CONTROL,
            0,
            win32con.KEYEVENTF_KEYUP,
            0,
        )
    time.sleep(pause)


def _normalise_selected_text(value: str) -> str:
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
        .rstrip("\n")
    )


def replace_source_selection(
    source_hwnd: int | None,
    original_text: str,
    generated_text: str,
    source_app: str = "",
    *,
    clipboard_reader: Callable[[], str | None] = read_clipboard_text,
    clipboard_writer: Callable[[str], None] = write_clipboard_text,
    send_keys: Callable[..., None] | None = None,
) -> None:
    """Re-verify and replace a captured source selection."""

    if not source_hwnd:
        raise SourceRecoveryError(
            "The original editable window could not be identified."
        )
    try:
        if not win32gui.IsWindow(source_hwnd):
            raise SourceRecoveryError(
                "The original editable window is no longer available."
            )
        if win32gui.IsIconic(source_hwnd):
            win32gui.ShowWindow(source_hwnd, 9)  # SW_RESTORE
        try:
            win32gui.BringWindowToTop(source_hwnd)
        except Exception:
            LOGGER.debug("Could not bring source window to top", exc_info=True)
        win32gui.SetForegroundWindow(source_hwnd)
        focus_timeout = (
            2.5
            if source_app.casefold()
            in {
                "winword.exe",
                "outlook.exe",
                "olk.exe",
                "ms-teams.exe",
                "teams.exe",
                "chrome.exe",
                "msedge.exe",
                "firefox.exe",
            }
            else 1.5
        )
        deadline = time.monotonic() + focus_timeout
        while time.monotonic() < deadline:
            if win32gui.GetForegroundWindow() == source_hwnd:
                break
            time.sleep(0.03)
        if win32gui.GetForegroundWindow() != source_hwnd:
            raise SourceRecoveryError(
                "Windows did not return focus to the original application."
            )

        marker = f"PromptMeld source verification {time.monotonic_ns()}"
        clipboard_writer(marker)
        if send_keys is None:
            _send_control_shortcut("c")
        else:
            send_keys("^c", pause=0.03)
        verification_deadline = time.monotonic() + 0.55
        selected_text = clipboard_reader()
        while selected_text == marker and time.monotonic() < verification_deadline:
            time.sleep(0.03)
            selected_text = clipboard_reader()
        if _normalise_selected_text(
            str(selected_text or "")
        ) != _normalise_selected_text(original_text):
            raise SourceRecoveryError(
                "The original selection changed while ChatGPT was responding."
            )

        clipboard_writer(generated_text)
        if send_keys is None:
            _send_control_shortcut("v", pause=0.04)
        else:
            send_keys("^v", pause=0.04)
    except SourceRecoveryError:
        raise
    except Exception as exc:
        raise SourceRecoveryError(
            "Windows could not paste the generated text into the original "
            "application."
        ) from exc


def undo_source_replacement(source_hwnd: int | None) -> None:
    """Focus a preserved source window and invoke its native Undo command."""

    if not source_hwnd or not win32gui.IsWindow(source_hwnd):
        raise SourceRecoveryError(
            "The original application window is no longer available."
        )
    try:
        if win32gui.IsIconic(source_hwnd):
            win32gui.ShowWindow(source_hwnd, 9)  # SW_RESTORE
        try:
            win32gui.BringWindowToTop(source_hwnd)
        except Exception:
            LOGGER.debug(
                "Could not bring source window to top for Undo",
                exc_info=True,
            )
        win32gui.SetForegroundWindow(source_hwnd)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if win32gui.GetForegroundWindow() == source_hwnd:
                break
            time.sleep(0.03)
        if win32gui.GetForegroundWindow() != source_hwnd:
            raise SourceRecoveryError(
                "Windows did not return focus to the original application."
            )
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        try:
            win32api.keybd_event(ord("Z"), 0, 0, 0)
            win32api.keybd_event(
                ord("Z"),
                0,
                win32con.KEYEVENTF_KEYUP,
                0,
            )
        finally:
            win32api.keybd_event(
                win32con.VK_CONTROL,
                0,
                win32con.KEYEVENTF_KEYUP,
                0,
            )
    except SourceRecoveryError:
        raise
    except Exception as exc:
        raise SourceRecoveryError(
            "The original application did not accept the Undo command."
        ) from exc


@dataclass(frozen=True, slots=True)
class ParsedHotkey:
    modifiers: int
    virtual_key: int


class HotkeyParseError(ValueError):
    pass


_MODIFIERS = {
    "alt": win32con.MOD_ALT,
    "ctrl": win32con.MOD_CONTROL,
    "control": win32con.MOD_CONTROL,
    "shift": win32con.MOD_SHIFT,
    "win": win32con.MOD_WIN,
    "windows": win32con.MOD_WIN,
}

_KEYS = {
    "space": win32con.VK_SPACE,
    "enter": win32con.VK_RETURN,
    "tab": win32con.VK_TAB,
    "escape": win32con.VK_ESCAPE,
    "esc": win32con.VK_ESCAPE,
    **{str(number): ord(str(number)) for number in range(10)},
    **{chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)},
    **{f"f{number}": win32con.VK_F1 + number - 1 for number in range(1, 25)},
}


def parse_hotkey(value: str) -> ParsedHotkey:
    parts = [part.strip().casefold() for part in value.split("+") if part.strip()]
    if len(parts) < 2:
        raise HotkeyParseError(
            f"Hotkey '{value}' must include a modifier and a key."
        )
    modifiers = win32con.MOD_NOREPEAT
    key: int | None = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
        elif part in _KEYS and key is None:
            key = _KEYS[part]
        else:
            raise HotkeyParseError(f"Unsupported hotkey component: {part}")
    if key is None:
        raise HotkeyParseError(f"Hotkey '{value}' has no key.")
    return ParsedHotkey(modifiers=modifiers, virtual_key=key)


def _key_is_down(virtual_key: int) -> bool:
    return bool(_USER32.GetAsyncKeyState(virtual_key) & 0x8000)


def is_hotkey_released(value: str) -> bool:
    """Return true only after the trigger key and its modifiers are all up."""

    parsed = parse_hotkey(value)
    keys = [parsed.virtual_key]
    if parsed.modifiers & win32con.MOD_CONTROL:
        keys.append(win32con.VK_CONTROL)
    if parsed.modifiers & win32con.MOD_ALT:
        keys.append(win32con.VK_MENU)
    if parsed.modifiers & win32con.MOD_SHIFT:
        keys.append(win32con.VK_SHIFT)
    if parsed.modifiers & win32con.MOD_WIN:
        keys.extend((win32con.VK_LWIN, win32con.VK_RWIN))
    return not any(_key_is_down(key) for key in keys)


class _HotkeyReceiver(QWidget):
    hotkey_received = Signal(int)
    activation_requested = Signal()

    def nativeEvent(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == win32con.WM_HOTKEY:
                self.hotkey_received.emit(int(msg.wParam))
                return True, 0
            if msg.message == ACTIVATE_EXISTING_MESSAGE:
                self.activation_requested.emit()
                return True, 0
        except (TypeError, ValueError):
            LOGGER.exception("Failed to process native hotkey event")
        return super().nativeEvent(event_type, message)


class GlobalHotkeyManager(QObject):
    activated = Signal(str)
    activation_requested = Signal()

    def __init__(self, qt_application):
        super().__init__()
        self._application = qt_application
        self._receiver = _HotkeyReceiver()
        self._receiver.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._receiver.setWindowTitle(HOTKEY_RECEIVER_TITLE)
        self._receiver.hide()
        self._receiver_hwnd = int(self._receiver.winId())
        self._registered: dict[int, tuple[str, str]] = {}
        self._next_id = 0xB000
        self._receiver.hotkey_received.connect(self._dispatch)
        self._receiver.activation_requested.connect(self.activation_requested)

    def register(self, command_id: str, hotkey: str) -> None:
        parsed = parse_hotkey(hotkey)
        registration_id = self._next_id
        self._next_id += 1
        if not _USER32.RegisterHotKey(
            self._receiver_hwnd,
            registration_id,
            parsed.modifiers,
            parsed.virtual_key,
        ):
            error_code = ctypes.get_last_error()
            raise RuntimeError(
                f"Could not register {hotkey} for '{command_id}' "
                f"(Windows error {error_code}). It may already be in use."
            )
        self._registered[registration_id] = (command_id, hotkey)
        LOGGER.info("Registered hotkey %s for %s", hotkey, command_id)

    def unregister_all(self) -> None:
        for registration_id in tuple(self._registered):
            _USER32.UnregisterHotKey(self._receiver_hwnd, registration_id)
        self._registered.clear()

    def is_available(self, hotkey: str) -> bool:
        """Ask Windows whether a hotkey can currently be registered."""
        parsed = parse_hotkey(hotkey)
        candidate = (parsed.modifiers, parsed.virtual_key)
        for _, registered_hotkey in self._registered.values():
            registered = parse_hotkey(registered_hotkey)
            if (registered.modifiers, registered.virtual_key) == candidate:
                return True

        registration_id = self._next_id
        self._next_id += 1
        if not _USER32.RegisterHotKey(
            self._receiver_hwnd,
            registration_id,
            parsed.modifiers,
            parsed.virtual_key,
        ):
            return False
        _USER32.UnregisterHotKey(self._receiver_hwnd, registration_id)
        return True

    def _dispatch(self, registration_id: int) -> None:
        item = self._registered.get(registration_id)
        if item:
            LOGGER.info("Hotkey activated for %s", item[0])
            self.activated.emit(item[0])
