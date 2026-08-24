from __future__ import annotations

import ctypes
import logging
import os
import time
import weakref
from ctypes import wintypes
from dataclasses import dataclass

import win32api
import win32clipboard
import win32con
import win32gui
import win32process
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from .clipboard import (
    ClipboardSnapshot,
    ClipboardBusyError,
    empty_clipboard,
    read_clipboard_text,
)
from .branding import HOTKEY_RECEIVER_TITLE
from .models import ApplyReceipt, CapturedSelection, SourceFingerprint

LOGGER = logging.getLogger(__name__)
_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_SEND_MESSAGE = _USER32.SendMessageW
_SEND_MESSAGE.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_SEND_MESSAGE.restype = wintypes.LPARAM
_GET_CURRENT_PROCESS = _KERNEL32.GetCurrentProcess
_GET_CURRENT_PROCESS.argtypes = []
_GET_CURRENT_PROCESS.restype = wintypes.HANDLE
_GET_PROCESS_TIMES = _KERNEL32.GetProcessTimes
_GET_PROCESS_TIMES.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
]
_GET_PROCESS_TIMES.restype = wintypes.BOOL
ACTIVATE_EXISTING_MESSAGE = win32con.WM_APP + 0x214
VERIFIED_EDIT_ADAPTER = "win32-edit-v1"
PROMPTMELD_SCRATCH_ADAPTER = "promptmeld-scratch-v1"
_PROMPTMELD_SCRATCH_WIDGETS: weakref.WeakValueDictionary[
    int,
    QPlainTextEdit,
] = weakref.WeakValueDictionary()
EM_GETSEL = 0x00B0
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2


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
        process_id, process_started = self._source_process_identity(source_hwnd)
        focused_hwnd = self._focused_hwnd() or source_hwnd
        focused_class = self._window_class(focused_hwnd)
        source_is_editable = self._source_is_editable(source_hwnd, source_class)
        LOGGER.info(
            "Capturing selection from application=%r class=%r hwnd=%s",
            source_app,
            source_class,
            source_hwnd,
        )
        snapshot = ClipboardSnapshot.capture()
        try:
            self._empty_clipboard()
            snapshot.mark_owned()
            self._send_copy()

            started = time.monotonic()
            deadline = started + (self.timeout_ms / 1000)
            retry_at = started + min(0.35, (self.timeout_ms / 1000) / 2)
            copy_retried = False
            text: str | None = None
            captured_sequence: int | None = None
            while time.monotonic() < deadline:
                sequence_before = int(
                    win32clipboard.GetClipboardSequenceNumber()
                )
                text = self._read_text()
                sequence_after = int(
                    win32clipboard.GetClipboardSequenceNumber()
                )
                if text and sequence_before == sequence_after:
                    captured_sequence = sequence_after
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

            if not text or not text.strip() or captured_sequence is None:
                LOGGER.warning(
                    "No text selection detected from window class=%r hwnd=%s",
                    source_class,
                    source_hwnd,
                )
                raise SelectionCaptureError(
                    "No selected text was detected. Select text in another "
                    "application and try again."
                )
            snapshot.mark_owned(captured_sequence)
        finally:
            snapshot.restore_if_owned()
        adapter_id = self._verified_adapter_for(focused_class)
        selection_start = -1
        selection_end = -1
        if adapter_id:
            try:
                selection_start, selection_end = _edit_selection_range(focused_hwnd)
                if (
                    selection_end <= selection_start
                    or not process_id
                    or not process_started
                    or not source_hwnd
                    or not source_class
                    or not focused_class
                ):
                    adapter_id = ""
            except SourceRecoveryError:
                adapter_id = ""
        return CapturedSelection(
            text=text,
            source_hwnd=source_hwnd,
            source_title=source_title,
            source_is_editable=source_is_editable,
            source_app=source_app,
            source_fingerprint=SourceFingerprint(
                process_id=process_id,
                process_started=process_started,
                top_level_hwnd=source_hwnd,
                top_level_class=source_class,
                focused_hwnd=focused_hwnd,
                focused_class=focused_class,
                adapter_id=adapter_id,
                selection_start=selection_start,
                selection_end=selection_end,
            ),
        )

    @staticmethod
    def _source_process_identity(source_hwnd: int) -> tuple[int, int]:
        handle = None
        try:
            _thread_id, process_id = win32process.GetWindowThreadProcessId(
                source_hwnd
            )
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION,
                False,
                process_id,
            )
            times = win32process.GetProcessTimes(handle)
            creation = (
                times.get("CreationTime")
                if isinstance(times, dict)
                else times[0]
            )
            timestamp = getattr(creation, "timestamp", None)
            started = int(timestamp() * 1_000_000) if callable(timestamp) else 0
            return int(process_id), started
        except Exception:
            LOGGER.debug("Could not fingerprint the source process", exc_info=True)
            try:
                return int(
                    win32process.GetWindowThreadProcessId(source_hwnd)[1]
                ), 0
            except Exception:
                return 0, 0
        finally:
            if handle is not None:
                try:
                    handle.Close()
                except Exception:
                    pass

    @staticmethod
    def _current_process_identity() -> tuple[int, int]:
        """Read PromptMeld's own identity without reopening its frozen process."""

        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if not _GET_PROCESS_TIMES(
                _GET_CURRENT_PROCESS(),
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            started = (int(creation.dwHighDateTime) << 32) | int(
                creation.dwLowDateTime
            )
            return int(os.getpid()), started
        except Exception:
            LOGGER.debug("Could not inspect current process identity", exc_info=True)
            return 0, 0

    @staticmethod
    def _verified_adapter_for(class_name: str) -> str:
        folded = (class_name or "").strip().casefold()
        if folded == "edit" or folded.startswith("richedit"):
            return VERIFIED_EDIT_ADAPTER
        return ""

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
    def __init__(
        self,
        message: str,
        *,
        original_preserved: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.original_preserved = original_preserved


def _normalise_selected_text(value: str) -> str:
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
    )


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _utf16_offset_to_python_index(value: str, offset: int) -> int:
    """Translate a Win32 Edit UTF-16 code-unit offset to a Python index."""

    if offset < 0:
        raise SourceRecoveryError("The captured editor returned a negative range.")
    units = 0
    for index, character in enumerate(value):
        if units == offset:
            return index
        units += _utf16_units(character)
        if units > offset:
            raise SourceRecoveryError(
                "The captured editor range split a Unicode character."
            )
    if units == offset:
        return len(value)
    raise SourceRecoveryError("The captured editor range is outside its text.")


def _edit_selection_range(hwnd: int) -> tuple[int, int]:
    if not hwnd or not win32gui.IsWindow(hwnd):
        raise SourceRecoveryError("The captured editor is no longer available.")
    start = wintypes.DWORD()
    end = wintypes.DWORD()
    _SEND_MESSAGE(
        hwnd,
        EM_GETSEL,
        ctypes.addressof(start),
        ctypes.addressof(end),
    )
    return int(start.value), int(end.value)


def _edit_text(hwnd: int) -> str:
    if not hwnd or not win32gui.IsWindow(hwnd):
        raise SourceRecoveryError("The captured editor is no longer available.")
    length = int(_SEND_MESSAGE(hwnd, win32con.WM_GETTEXTLENGTH, 0, 0))
    if length < 0 or length > 16_777_216:
        raise SourceRecoveryError("The captured editor returned an invalid length.")
    buffer = ctypes.create_unicode_buffer(length + 1)
    copied = int(
        _SEND_MESSAGE(
            hwnd,
            win32con.WM_GETTEXT,
            length + 1,
            ctypes.addressof(buffer),
        )
    )
    if copied < 0:
        raise SourceRecoveryError("The captured editor text could not be read.")
    return buffer.value


def _set_edit_selection(hwnd: int, start: int, end: int) -> None:
    _SEND_MESSAGE(hwnd, EM_SETSEL, int(start), int(end))


def _replace_edit_selection(hwnd: int, value: str) -> None:
    try:
        win32gui.SendMessage(hwnd, EM_REPLACESEL, 1, value)
    except Exception as exc:
        raise SourceRecoveryError(
            "The verified editor rejected the replacement."
        ) from exc


def source_supports_verified_apply(selection: CapturedSelection | None) -> bool:
    fingerprint = selection.source_fingerprint if selection is not None else None
    return bool(
        selection is not None
        and selection.source_is_editable
        and fingerprint is not None
        and fingerprint.adapter_id
        in {VERIFIED_EDIT_ADAPTER, PROMPTMELD_SCRATCH_ADAPTER}
        and fingerprint.process_id
        and fingerprint.process_started
        and fingerprint.top_level_hwnd == selection.source_hwnd
        and fingerprint.top_level_class
        and fingerprint.focused_hwnd
        and fingerprint.focused_class
        and fingerprint.selection_start >= 0
        and fingerprint.selection_end > fingerprint.selection_start
    )


def capture_promptmeld_scratch_selection(
    editor: QPlainTextEdit,
) -> CapturedSelection:
    """Fingerprint a PromptMeld-owned editor for the diagnostics canary."""

    editor.setProperty("promptmeldVerifiedScratch", True)
    # A parentless widget can have a lazy or transient native handle in a
    # frozen, tray-only Qt process. Create its hidden native window and let Qt
    # finish the Windows registration before asking Win32 for process/class
    # identity. The scratch editor never becomes visible to the user.
    editor.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    editor.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    editor.selectAll()
    editor.show()
    QApplication.processEvents()
    hwnd = int(editor.winId())
    process_id, process_started = SelectionCapture._current_process_identity()
    class_name = editor.metaObject().className()
    cursor = editor.textCursor()
    start = int(cursor.selectionStart())
    end = int(cursor.selectionEnd())
    LOGGER.info(
        "Canary scratch fingerprint hwnd=%s pid=%s process_started=%s "
        "class_present=%s selection=%s:%s",
        hwnd,
        process_id,
        bool(process_started),
        bool(class_name),
        start,
        end,
    )
    if (
        not hwnd
        or not process_id
        or not process_started
        or not class_name
        or end <= start
    ):
        raise SourceRecoveryError(
            "PromptMeld could not fingerprint its canary scratch editor."
        )
    _PROMPTMELD_SCRATCH_WIDGETS[hwnd] = editor
    return CapturedSelection(
        text=cursor.selectedText().replace("\u2029", "\n"),
        source_hwnd=hwnd,
        source_title="PromptMeld diagnostics scratch",
        source_is_editable=True,
        source_app="promptmeld.exe",
        source_fingerprint=SourceFingerprint(
            process_id=process_id,
            process_started=process_started,
            top_level_hwnd=hwnd,
            top_level_class=class_name,
            focused_hwnd=hwnd,
            focused_class=class_name,
            adapter_id=PROMPTMELD_SCRATCH_ADAPTER,
            selection_start=start,
            selection_end=end,
        ),
    )


def release_promptmeld_scratch_selection(
    selection: CapturedSelection | None,
) -> None:
    fingerprint = selection.source_fingerprint if selection is not None else None
    if fingerprint is not None:
        _PROMPTMELD_SCRATCH_WIDGETS.pop(fingerprint.focused_hwnd, None)


def _promptmeld_scratch_widget(
    fingerprint: SourceFingerprint,
) -> QPlainTextEdit:
    editor = _PROMPTMELD_SCRATCH_WIDGETS.get(fingerprint.focused_hwnd)
    if (
        editor is None
        or int(editor.winId()) != fingerprint.focused_hwnd
        or not bool(editor.property("promptmeldVerifiedScratch"))
    ):
        raise SourceRecoveryError(
            "The PromptMeld canary scratch editor identity changed."
        )
    process_id, process_started = SelectionCapture._current_process_identity()
    try:
        _thread_id, window_process_id = win32process.GetWindowThreadProcessId(
            fingerprint.top_level_hwnd
        )
    except Exception as exc:
        raise SourceRecoveryError(
            "The PromptMeld canary scratch window is no longer available."
        ) from exc
    if (
        not win32gui.IsWindow(fingerprint.top_level_hwnd)
        or int(window_process_id) != fingerprint.process_id
        or process_id != fingerprint.process_id
        or process_started != fingerprint.process_started
        or editor.metaObject().className() != fingerprint.focused_class
    ):
        raise SourceRecoveryError(
            "The PromptMeld canary scratch editor identity changed."
        )
    return editor


def _apply_promptmeld_scratch_selection(
    selection: CapturedSelection,
    generated_text: str,
) -> ApplyReceipt:
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    editor = _promptmeld_scratch_widget(fingerprint)
    cursor = editor.textCursor()
    if (
        cursor.selectionStart(),
        cursor.selectionEnd(),
    ) != (fingerprint.selection_start, fingerprint.selection_end):
        raise SourceRecoveryError(
            "The PromptMeld canary scratch selection range changed."
        )
    selected = cursor.selectedText().replace("\u2029", "\n")
    if _normalise_selected_text(selected) != _normalise_selected_text(
        selection.text
    ):
        raise SourceRecoveryError(
            "The PromptMeld canary scratch selection changed."
        )
    cursor.insertText(generated_text)
    after = editor.toPlainText()
    start = fingerprint.selection_start
    end = start + len(generated_text)
    if after[start:end] != generated_text:
        raise SourceRecoveryError(
            "The PromptMeld canary scratch editor failed read-back verification."
        )
    return ApplyReceipt(
        adapter_id=PROMPTMELD_SCRATCH_ADAPTER,
        source_fingerprint=fingerprint,
        original_text=selection.text,
        generated_text=generated_text,
        replacement_start=start,
        replacement_end=end,
    )


def _reverse_promptmeld_scratch_replacement(receipt: ApplyReceipt) -> None:
    editor = _promptmeld_scratch_widget(receipt.source_fingerprint)
    current = editor.toPlainText()
    if current[receipt.replacement_start : receipt.replacement_end] != (
        receipt.generated_text
    ):
        raise SourceRecoveryError(
            "The PromptMeld canary scratch result changed before cleanup."
        )
    cursor = editor.textCursor()
    cursor.setPosition(receipt.replacement_start)
    cursor.setPosition(
        receipt.replacement_end,
        QTextCursor.MoveMode.KeepAnchor,
    )
    cursor.insertText(receipt.original_text)
    restored = editor.toPlainText()
    restored_end = receipt.replacement_start + len(receipt.original_text)
    if restored[receipt.replacement_start : restored_end] != receipt.original_text:
        raise SourceRecoveryError(
            "The PromptMeld canary scratch cleanup could not be verified."
        )


def automatic_source_return_is_allowed(
    selection: CapturedSelection,
    chatgpt_hwnd: int = 0,
) -> bool:
    """Do not interrupt a third application being used during response wait."""

    try:
        current = int(win32gui.GetForegroundWindow() or 0)
    except Exception:
        return False
    return bool(
        current
        and current
        in {
            int(selection.source_hwnd or 0),
            int(chatgpt_hwnd or 0),
        }
    )


def _validate_source_fingerprint(
    source_hwnd: int,
    fingerprint: SourceFingerprint,
) -> None:
    if (
        not fingerprint.top_level_hwnd
        or source_hwnd != fingerprint.top_level_hwnd
    ):
        raise SourceRecoveryError("The captured top-level window identity changed.")
    if not win32gui.IsWindow(source_hwnd):
        raise SourceRecoveryError(
            "The original editable window is no longer available."
        )
    if not win32gui.IsWindow(fingerprint.focused_hwnd):
        raise SourceRecoveryError(
            "The original editor control is no longer available."
        )
    if (
        fingerprint.focused_hwnd != source_hwnd
        and not win32gui.IsChild(source_hwnd, fingerprint.focused_hwnd)
    ):
        raise SourceRecoveryError(
            "The original editor no longer belongs to the captured window."
        )
    _thread_id, process_id = win32process.GetWindowThreadProcessId(source_hwnd)
    if fingerprint.process_id and int(process_id) != fingerprint.process_id:
        raise SourceRecoveryError(
            "Windows reused the original window handle for another process."
        )
    if fingerprint.process_started:
        _pid, process_started = SelectionCapture._source_process_identity(source_hwnd)
        if not process_started:
            raise SourceRecoveryError(
                "The original application process identity could not be revalidated."
            )
        if process_started != fingerprint.process_started:
            raise SourceRecoveryError(
                "The original application process has been replaced."
            )
    if (
        fingerprint.top_level_class
        and SelectionCapture._window_class(source_hwnd)
        != fingerprint.top_level_class
    ):
        raise SourceRecoveryError("The original window identity changed.")
    if (
        fingerprint.focused_class
        and SelectionCapture._window_class(fingerprint.focused_hwnd)
        != fingerprint.focused_class
    ):
        raise SourceRecoveryError("The original editor identity changed.")


def _activate_verified_source(
    source_hwnd: int,
    fingerprint: SourceFingerprint,
) -> None:
    _validate_source_fingerprint(source_hwnd, fingerprint)
    if win32gui.IsIconic(source_hwnd):
        win32gui.ShowWindow(source_hwnd, 9)  # SW_RESTORE
    try:
        win32gui.BringWindowToTop(source_hwnd)
    except Exception:
        LOGGER.debug("Could not bring verified source to top", exc_info=True)
    try:
        win32gui.SetForegroundWindow(source_hwnd)
    except Exception as exc:
        raise SourceRecoveryError(
            "Windows did not allow PromptMeld to return to the original application."
        ) from exc
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if (
            win32gui.GetForegroundWindow() == source_hwnd
            and SelectionCapture._focused_hwnd() == fingerprint.focused_hwnd
        ):
            _validate_source_fingerprint(source_hwnd, fingerprint)
            return
        time.sleep(0.03)
    raise SourceRecoveryError(
        "The original editor did not regain the exact captured focus."
    )


def apply_verified_source_selection(
    selection: CapturedSelection,
    generated_text: str,
) -> ApplyReceipt:
    """Replace and read back a native Edit/RichEdit selection transactionally."""

    if not source_supports_verified_apply(selection):
        raise SourceRecoveryError(
            "This source does not expose a verifiable replacement adapter."
        )
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    if fingerprint.adapter_id == PROMPTMELD_SCRATCH_ADAPTER:
        return _apply_promptmeld_scratch_selection(selection, generated_text)
    _activate_verified_source(selection.source_hwnd, fingerprint)
    current_start, current_end = _edit_selection_range(fingerprint.focused_hwnd)
    if (current_start, current_end) != (
        fingerprint.selection_start,
        fingerprint.selection_end,
    ):
        raise SourceRecoveryError(
            "The exact original selection range changed while ChatGPT was responding."
        )
    before = _edit_text(fingerprint.focused_hwnd)
    start_index = _utf16_offset_to_python_index(before, current_start)
    end_index = _utf16_offset_to_python_index(before, current_end)
    selected = before[start_index:end_index]
    if _normalise_selected_text(selected) != _normalise_selected_text(selection.text):
        raise SourceRecoveryError(
            "The original selection changed while ChatGPT was responding."
        )
    prefix = before[:start_index]
    suffix = before[end_index:]
    _replace_edit_selection(fingerprint.focused_hwnd, generated_text)
    after = _edit_text(fingerprint.focused_hwnd)
    middle_end = len(after) - len(suffix) if suffix else len(after)
    middle = after[len(prefix):middle_end]
    verified = (
        after.startswith(prefix)
        and (not suffix or after.endswith(suffix))
        and _normalise_selected_text(middle)
        == _normalise_selected_text(generated_text)
    )
    if not verified:
        restored = False
        if after.startswith(prefix) and (not suffix or after.endswith(suffix)):
            _set_edit_selection(
                fingerprint.focused_hwnd,
                _utf16_units(prefix),
                _utf16_units(after[:middle_end]),
            )
            _replace_edit_selection(fingerprint.focused_hwnd, selected)
            restored = _edit_text(fingerprint.focused_hwnd) == before
        raise SourceRecoveryError(
            "The editor did not verify the generated text after replacement; "
            + (
                "the exact original was restored."
                if restored
                else "PromptMeld could not prove that the original was restored."
            ),
            original_preserved=restored,
        )
    replacement_start = _utf16_units(prefix)
    replacement_end = replacement_start + _utf16_units(middle)
    return ApplyReceipt(
        adapter_id=VERIFIED_EDIT_ADAPTER,
        source_fingerprint=fingerprint,
        original_text=selected,
        generated_text=middle,
        replacement_start=replacement_start,
        replacement_end=replacement_end,
    )


def reverse_verified_source_replacement(receipt: ApplyReceipt) -> None:
    """Reverse only the exact verified range produced by PromptMeld."""

    if receipt.adapter_id == PROMPTMELD_SCRATCH_ADAPTER:
        _reverse_promptmeld_scratch_replacement(receipt)
        return
    if receipt.adapter_id != VERIFIED_EDIT_ADAPTER:
        raise SourceRecoveryError("No verified reversal adapter is available.")
    fingerprint = receipt.source_fingerprint
    source_hwnd = fingerprint.top_level_hwnd
    if not source_hwnd:
        raise SourceRecoveryError("The original application is no longer available.")
    _activate_verified_source(int(source_hwnd), fingerprint)
    current = _edit_text(fingerprint.focused_hwnd)
    replacement_start = _utf16_offset_to_python_index(
        current,
        receipt.replacement_start,
    )
    replacement_end = _utf16_offset_to_python_index(
        current,
        receipt.replacement_end,
    )
    current_value = current[replacement_start:replacement_end]
    if _normalise_selected_text(current_value) != _normalise_selected_text(
        receipt.generated_text
    ):
        raise SourceRecoveryError(
            "The applied text changed after PromptMeld inserted it, so automatic "
            "reversal was disabled."
        )
    _set_edit_selection(
        fingerprint.focused_hwnd,
        receipt.replacement_start,
        receipt.replacement_end,
    )
    _replace_edit_selection(fingerprint.focused_hwnd, receipt.original_text)
    restored = _edit_text(fingerprint.focused_hwnd)
    restored_start = _utf16_offset_to_python_index(
        restored,
        receipt.replacement_start,
    )
    restored_end = restored_start + len(receipt.original_text)
    if _normalise_selected_text(
        restored[restored_start:restored_end]
    ) != _normalise_selected_text(receipt.original_text):
        raise SourceRecoveryError(
            "The editor did not verify restoration of the original text."
        )


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
