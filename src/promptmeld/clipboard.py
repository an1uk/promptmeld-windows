from __future__ import annotations

import time
from dataclasses import dataclass

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
        was_empty: bool = False,
        registered_formats: dict[int, bytes] | None = None,
    ):
        self.data_object = data_object
        self.text = text
        self.sequence = sequence
        self.owned_sequence: int | None = None
        self.com_initialized = com_initialized
        self.was_empty = was_empty
        self.registered_formats = dict(registered_formats or {})

    @classmethod
    def capture(cls) -> "ClipboardSnapshot":
        data_object = None
        com_initialized = False
        was_empty = False
        registered_formats: dict[int, bytes] = {}
        if pythoncom is not None:
            try:
                # OleGetClipboard can appear to work after CoInitialize alone,
                # but the matching OleSetClipboard used for restoration then
                # fails with CO_E_NOTINITIALIZED. Clipboard ownership is an OLE
                # service, so initialise the full OLE apartment here.
                pythoncom.OleInitialize()
                com_initialized = True
                data_object = pythoncom.OleGetClipboard()
            except Exception:
                data_object = None
        try:
            win32clipboard.OpenClipboard()
            try:
                was_empty = win32clipboard.CountClipboardFormats() == 0
                previous_format = 0
                while True:
                    format_id = int(
                        win32clipboard.EnumClipboardFormats(previous_format)
                    )
                    if not format_id:
                        break
                    previous_format = format_id
                    # Registered formats carry application-defined byte
                    # payloads. OLE clipboard proxies can restore their text
                    # representation across a process boundary while silently
                    # dropping these bytes, so retain an in-memory supplement.
                    if format_id < 0xC000:
                        continue
                    try:
                        payload = win32clipboard.GetClipboardData(format_id)
                    except Exception:
                        continue
                    if isinstance(payload, (bytes, bytearray, memoryview)):
                        registered_formats[format_id] = bytes(payload)
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            was_empty = False
        return cls(
            data_object,
            read_clipboard_text(),
            int(win32clipboard.GetClipboardSequenceNumber()),
            com_initialized,
            was_empty,
            registered_formats,
        )

    def mark_owned(self, sequence: int | None = None) -> None:
        self.owned_sequence = (
            int(win32clipboard.GetClipboardSequenceNumber())
            if sequence is None
            else int(sequence)
        )

    def close(self) -> None:
        """Release the OLE snapshot without changing the clipboard."""

        if self.com_initialized and pythoncom is not None:
            pythoncom.CoUninitialize()
            self.com_initialized = False

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
                    # Materialise delayed-rendered formats before a short-lived
                    # automation companion can exit.
                    pythoncom.OleFlushClipboard()
                    restored_sequence = int(
                        win32clipboard.GetClipboardSequenceNumber()
                    )
                    return self._restore_registered_formats(
                        restored_sequence
                    )
                except Exception:
                    pass
            if self.text is not None:
                write_clipboard_text(self.text)
                restored_sequence = int(
                    win32clipboard.GetClipboardSequenceNumber()
                )
                return self._restore_registered_formats(restored_sequence)
            if self.was_empty:
                empty_clipboard()
                return True
            return False
        finally:
            self.close()

    def _restore_registered_formats(self, expected_sequence: int) -> bool:
        """Reattach byte formats omitted by a cross-process OLE proxy."""

        if not self.registered_formats:
            return True
        for attempt in range(10):
            if (
                int(win32clipboard.GetClipboardSequenceNumber())
                != expected_sequence
            ):
                return False
            try:
                win32clipboard.OpenClipboard()
                break
            except Exception:
                if attempt == 9:
                    return False
                time.sleep(0.02)
        try:
            if (
                int(win32clipboard.GetClipboardSequenceNumber())
                != expected_sequence
            ):
                return False
            for format_id, expected_payload in self.registered_formats.items():
                current_payload = None
                if win32clipboard.IsClipboardFormatAvailable(format_id):
                    try:
                        current_payload = win32clipboard.GetClipboardData(
                            format_id
                        )
                    except Exception:
                        current_payload = None
                if isinstance(
                    current_payload,
                    (bytes, bytearray, memoryview),
                ) and bytes(current_payload) == expected_payload:
                    continue
                win32clipboard.SetClipboardData(format_id, expected_payload)
                restored_payload = win32clipboard.GetClipboardData(format_id)
                if (
                    not isinstance(
                        restored_payload,
                        (bytes, bytearray, memoryview),
                    )
                    or bytes(restored_payload) != expected_payload
                ):
                    return False
            return True
        except Exception:
            return False
        finally:
            win32clipboard.CloseClipboard()


CANARY_CLIPBOARD_FORMAT = "PromptMeld.AutomationCanary.v1"


@dataclass(slots=True)
class ClipboardCanaryProbe:
    """Verify full-format clipboard round-tripping without losing user data."""

    snapshot: ClipboardSnapshot
    marker_text: str
    marker_format: int
    marker_payload: bytes

    @classmethod
    def begin(cls, marker: str) -> "ClipboardCanaryProbe":
        snapshot = ClipboardSnapshot.capture()
        marker_text = f"PromptMeld clipboard canary {marker}"
        marker_payload = marker.encode("ascii", errors="strict")
        marker_format = int(
            win32clipboard.RegisterClipboardFormat(CANARY_CLIPBOARD_FORMAT)
        )
        try:
            deadline = time.monotonic() + 2.0
            attempt = 0
            while True:
                try:
                    win32clipboard.OpenClipboard()
                    try:
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardData(
                            win32con.CF_UNICODETEXT,
                            marker_text,
                        )
                        win32clipboard.SetClipboardData(
                            marker_format,
                            marker_payload,
                        )
                    finally:
                        win32clipboard.CloseClipboard()
                    return cls(
                        snapshot,
                        marker_text,
                        marker_format,
                        marker_payload,
                    )
                except Exception as exc:
                    attempt += 1
                    if time.monotonic() >= deadline:
                        raise ClipboardBusyError(
                            "The clipboard stayed busy for two seconds. Close "
                            "Clipboard history or any clipboard manager and try "
                            "the test again."
                        ) from exc
                    time.sleep(min(0.025 * attempt, 0.15))
        except Exception:
            snapshot.close()
            raise

    def finish(self) -> bool:
        """Restore the original only when the complete marker survived."""

        stable_sequence = None
        marker_preserved = False
        deadline = time.monotonic() + 2.0
        attempt = 0
        while True:
            try:
                sequence_before = int(
                    win32clipboard.GetClipboardSequenceNumber()
                )
                win32clipboard.OpenClipboard()
                try:
                    text = (
                        win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        if win32clipboard.IsClipboardFormatAvailable(
                            win32con.CF_UNICODETEXT
                        )
                        else None
                    )
                    payload = (
                        win32clipboard.GetClipboardData(self.marker_format)
                        if win32clipboard.IsClipboardFormatAvailable(
                            self.marker_format
                        )
                        else None
                    )
                finally:
                    win32clipboard.CloseClipboard()
                sequence_after = int(
                    win32clipboard.GetClipboardSequenceNumber()
                )
                stable_sequence = sequence_after
                marker_preserved = bool(
                    sequence_before == sequence_after
                    and text == self.marker_text
                    and payload == self.marker_payload
                )
                break
            except Exception:
                attempt += 1
                if time.monotonic() >= deadline:
                    marker_preserved = False
                    break
                time.sleep(min(0.025 * attempt, 0.15))
        if not marker_preserved or stable_sequence is None:
            self.snapshot.close()
            return False
        self.snapshot.mark_owned(stable_sequence)
        try:
            return self.snapshot.restore_if_owned()
        except Exception:
            self.snapshot.close()
            return False


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
