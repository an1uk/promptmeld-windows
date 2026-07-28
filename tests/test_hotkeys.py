import pytest
import win32con

from promptmeld import windows
from promptmeld.windows import (
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
