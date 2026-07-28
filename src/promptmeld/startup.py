from __future__ import annotations

import os
import sys
import winreg
from pathlib import Path

from .branding import (
    APP_ID,
    LEGACY_APP_ID,
    LEGACY_STARTUP_LINK_NAME,
)


class StartupManager:
    VALUE_NAME = APP_ID
    LEGACY_VALUE_NAME = LEGACY_APP_ID
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    LEGACY_LINK_NAME = LEGACY_STARTUP_LINK_NAME

    @property
    def legacy_link_path(self) -> Path:
        app_data = Path(
            os.environ.get(
                "APPDATA",
                str(Path.home() / "AppData" / "Roaming"),
            )
        )
        return (
            app_data
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / self.LEGACY_LINK_NAME
        )

    def is_enabled(self) -> bool:
        return (
            self._registry_value_exists(self.VALUE_NAME)
            or self._registry_value_exists(self.LEGACY_VALUE_NAME)
            or self.legacy_link_path.exists()
        )

    def migrate_legacy_registration(self) -> None:
        if self._registry_value_exists(self.VALUE_NAME):
            return
        if (
            not self._registry_value_exists(self.LEGACY_VALUE_NAME)
            and not self.legacy_link_path.exists()
        ):
            return
        self._write_registry_value()
        self._delete_registry_value(self.LEGACY_VALUE_NAME)
        if self.legacy_link_path.exists():
            self.legacy_link_path.unlink()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._write_registry_value()
        else:
            self._delete_registry_value(self.VALUE_NAME)
        self._delete_registry_value(self.LEGACY_VALUE_NAME)
        if self.legacy_link_path.exists():
            self.legacy_link_path.unlink()

    def _write_registry_value(self) -> None:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            self.RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                self.VALUE_NAME,
                0,
                winreg.REG_SZ,
                self._launch_command(),
            )

    def _delete_registry_value(self, value_name: str) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, value_name)
        except FileNotFoundError:
            pass

    def _registry_value_exists(self, value_name: str) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.RUN_KEY,
                0,
                winreg.KEY_READ,
            ) as key:
                winreg.QueryValueEx(key, value_name)
                return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _launch_command() -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else Path(sys.executable)
        return f'"{executable}" -m promptmeld'
