import pytest
import win32con
from PySide6.QtWidgets import QApplication

from promptmeld import windows
from promptmeld.windows import (
    GlobalHotkeyManager,
    HotkeyParseError,
    is_hotkey_released,
    parse_hotkey,
)


def test_parse_hotkey():
    parsed = parse_hotkey("Ctrl+Alt+Space")

    assert parsed.modifiers & win32con.MOD_CONTROL
    assert parsed.modifiers & win32con.MOD_ALT
    assert parsed.virtual_key == win32con.VK_SPACE


def test_invalid_hotkey_is_rejected():
    with pytest.raises(HotkeyParseError):
        parse_hotkey("Space")


def test_hotkey_release_checks_trigger_key_and_modifiers(monkeypatch):
    pressed: set[int] = set()
    monkeypatch.setattr(
        windows,
        "_key_is_down",
        lambda virtual_key: virtual_key in pressed,
    )

    assert is_hotkey_released("Ctrl+Alt+Space") is True

    pressed.add(win32con.VK_CONTROL)
    assert is_hotkey_released("Ctrl+Alt+Space") is False

    pressed.clear()
    pressed.add(win32con.VK_MENU)
    assert is_hotkey_released("Ctrl+Alt+Space") is False

    pressed.clear()
    pressed.add(win32con.VK_SPACE)
    assert is_hotkey_released("Ctrl+Alt+Space") is False


def test_hotkey_availability_temporarily_registers_with_windows(
    qtbot,
    monkeypatch,
):
    calls: list[tuple[str, int]] = []

    class FakeUser32:
        @staticmethod
        def RegisterHotKey(hwnd, registration_id, modifiers, virtual_key):
            calls.append(("register", registration_id))
            return virtual_key != ord("9")

        @staticmethod
        def UnregisterHotKey(hwnd, registration_id):
            calls.append(("unregister", registration_id))
            return True

    monkeypatch.setattr(windows, "_USER32", FakeUser32())
    manager = GlobalHotkeyManager(QApplication.instance())

    assert manager.is_available("Ctrl+Alt+8") is True
    assert [name for name, _ in calls] == ["register", "unregister"]

    calls.clear()
    assert manager.is_available("Ctrl+Alt+9") is False
    assert [name for name, _ in calls] == ["register"]
