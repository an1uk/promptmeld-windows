from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import replace
from importlib.resources import files
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from .actions import ActionRegistry
from .automation_client import (
    shutdown_automation_helper,
    submit_via_worker,
)
from .branding import APP_ID, APP_NAME
from .config import (
    ConfigurationError,
    ensure_user_configuration,
    load_actions,
    load_settings,
    save_settings,
)
from .models import CapturedSelection, SubmissionResult, WritingAction
from .paths import AppPaths
from .prompting import PromptBuilder
from .single_instance import SingleInstance
from .startup import StartupManager
from .usage import UsageTracker
from .windows import (
    GlobalHotkeyManager,
    SelectionCapture,
    SelectionCaptureError,
    is_hotkey_released,
)
from .worker import FunctionWorker

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .icons import ActionIconProvider
    from .settings_ui import ActionSettingsDialog
    from .ui import LauncherPopup


def project_name_for_action(
    base_project_name: str,
    action: WritingAction,
) -> str:
    """Return the dedicated ChatGPT project for an action's configured folder."""

    folder_parts = [
        part.strip()
        for part in action.folder.replace("\\", "/").split("/")
        if part.strip()
    ]
    if not folder_parts:
        return base_project_name
    return " - ".join((base_project_name, *folder_parts))


def configure_logging(paths: AppPaths) -> None:
    paths.ensure()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        return
    handler = RotatingFileHandler(
        paths.log_file,
        maxBytes=512_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)


def make_tray_icon() -> QIcon:
    icon_path = files("promptmeld").joinpath(
        "resources",
        "branding",
        "promptmeld.png",
    )
    icon = QIcon(str(icon_path))
    if not icon.isNull():
        return icon

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#315ecb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(26)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "P")
    painter.end()
    return QIcon(pixmap)


class PromptMeld:
    def __init__(self, qt_app: QApplication, paths: AppPaths):
        self.qt_app = qt_app
        self.paths = paths
        self.settings = None
        self.registry = None
        self.capture = None
        self.popup: LauncherPopup | None = None
        self.icons: ActionIconProvider | None = None
        self.current_selection: CapturedSelection | None = None
        self.prompt_builder = PromptBuilder()
        self.usage = UsageTracker(paths.usage_file)
        self.thread_pool = QThreadPool.globalInstance()
        self.startup = StartupManager()
        self.startup.migrate_legacy_registration()
        self.settings_dialog: ActionSettingsDialog | None = None

        app_icon = make_tray_icon()
        qt_app.setWindowIcon(app_icon)
        self.tray = QSystemTrayIcon(app_icon, qt_app)
        self.tray.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.open_launcher_action = self.menu.addAction("Open launcher")
        self.open_launcher_action.triggered.connect(self.capture_and_show)
        self.menu.addSeparator()
        self.manage_actions_action = self.menu.addAction("Manage writing actions…")
        self.manage_actions_action.triggered.connect(self.open_action_settings)
        self.open_config_action = self.menu.addAction("Open configuration folder")
        self.open_config_action.triggered.connect(self.open_config_folder)
        self.reload_action = self.menu.addAction("Reload configuration")
        self.reload_action.triggered.connect(self.reload_configuration)
        self.startup_action = self.menu.addAction("Start with Windows")
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(self.startup.is_enabled())
        self.startup_action.toggled.connect(self.toggle_startup)
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction("Exit")
        self.exit_action.triggered.connect(self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)

        ensure_user_configuration(paths)
        self._load_components(first_load=True)

        self.hotkeys = GlobalHotkeyManager(qt_app)
        self.hotkeys.activated.connect(self.handle_hotkey)
        self.hotkeys.activation_requested.connect(
            lambda: self.activate_existing("activate")
        )
        self.register_hotkeys()
        self.tray.show()

    def _load_components(self, first_load: bool = False) -> None:
        self.settings = load_settings(self.paths.settings_file)
        self.actions = load_actions(self.paths.actions_file)
        self.registry = ActionRegistry(self.actions, self.usage)
        self.capture = SelectionCapture(self.settings.capture_timeout_ms)
        if self.popup is not None:
            self.popup.set_registry(
                self.registry,
                self.settings.home_most_used_count,
                self.settings.folder_icons,
                self.settings.natural_voice_enabled,
                self.settings.auto_submit_enabled,
            )

    def _ensure_icons(self):
        if self.icons is None:
            from .icons import ActionIconProvider

            self.icons = ActionIconProvider(self.paths.data_dir)
        return self.icons

    def _ensure_popup(self):
        if self.popup is None:
            from .ui import LauncherPopup

            self.popup = LauncherPopup(
                self.registry,
                self._ensure_icons(),
                self.settings.home_most_used_count,
                self.settings.folder_icons,
                self.settings.natural_voice_enabled,
                self.settings.auto_submit_enabled,
            )
            self.popup.action_requested.connect(self.run_action)
            self.popup.custom_requested.connect(self.run_custom)
            self.popup.natural_voice_changed.connect(
                self.set_natural_voice_enabled
            )
            self.popup.auto_submit_changed.connect(
                self.set_auto_submit_enabled
            )
        return self.popup

    def register_hotkeys(self) -> None:
        failures: list[str] = []
        try:
            self.hotkeys.register("__popup__", self.settings.popup_hotkey)
        except Exception as exc:
            failures.append(str(exc))
        for action in self.registry.all():
            if not action.hotkey:
                continue
            try:
                self.hotkeys.register(action.id, action.hotkey)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            self.notify(
                "Some hotkeys are unavailable",
                "\n".join(failures[:3]),
                QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

    def handle_hotkey(self, command_id: str) -> None:
        # WM_HOTKEY is delivered on key-down. A fixed delay is unreliable for
        # manually held shortcuts and Logitech Smart Actions, so wait until the
        # complete trigger chord is physically released before sending Ctrl+C.
        hotkey = (
            self.settings.popup_hotkey
            if command_id == "__popup__"
            else (
                action.hotkey
                if (action := self.registry.get(command_id)) is not None
                else None
            )
        )
        if not hotkey:
            self._execute_hotkey(command_id)
            return
        self._execute_after_hotkey_release(
            command_id,
            hotkey,
            time.monotonic() + 2.0,
        )

    def _execute_after_hotkey_release(
        self,
        command_id: str,
        hotkey: str,
        deadline: float,
    ) -> None:
        if is_hotkey_released(hotkey):
            # Give the source application one event-loop turn to process key-up
            # and allow an Actions Ring overlay to finish dismissing.
            QTimer.singleShot(45, lambda: self._execute_hotkey(command_id))
            return
        if time.monotonic() < deadline:
            QTimer.singleShot(
                25,
                lambda: self._execute_after_hotkey_release(
                    command_id,
                    hotkey,
                    deadline,
                ),
            )
            return
        LOGGER.warning(
            "Hotkey %s remained pressed; selection capture was cancelled",
            hotkey,
        )
        self.notify(
            APP_NAME,
            "The shortcut remained held. Release the shortcut keys and try again.",
            QSystemTrayIcon.MessageIcon.Warning,
        )

    def _execute_hotkey(self, command_id: str) -> None:
        if command_id == "__popup__":
            self.capture_and_show()
            return
        action = self.registry.get(command_id)
        if action is not None:
            self.capture_and_submit(action)

    def capture_and_show(self) -> None:
        try:
            self.current_selection = self.capture.capture()
        except SelectionCaptureError as exc:
            self.notify(APP_NAME, str(exc), QSystemTrayIcon.MessageIcon.Warning)
            return
        self._ensure_popup().show_at_cursor()

    def capture_and_submit(self, action: WritingAction) -> None:
        try:
            selection = self.capture.capture()
        except SelectionCaptureError as exc:
            self.notify(APP_NAME, str(exc), QSystemTrayIcon.MessageIcon.Warning)
            return
        self._submit_action(action, selection)

    def run_action(self, action_id: str) -> None:
        action = self.registry.get(action_id)
        if action is None or self.current_selection is None:
            self.notify(
                APP_NAME,
                "The selected action or captured text is no longer available.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self._submit_action(action, self.current_selection)

    def run_custom(self, instruction: str) -> None:
        if self.current_selection is None:
            self.notify(
                APP_NAME,
                "The captured text is no longer available.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        try:
            prompt = self.prompt_builder.build_custom(
                instruction,
                self.current_selection,
                natural_voice_enabled=self.settings.natural_voice_enabled,
                natural_voice_instruction=(
                    self.settings.natural_voice_instruction
                ),
                primary_language=self.settings.primary_language,
            )
        except ValueError as exc:
            self.notify(APP_NAME, str(exc), QSystemTrayIcon.MessageIcon.Warning)
            return
        self.usage.record("__custom__")
        self._submit_prompt(prompt)

    def _submit_action(
        self,
        action: WritingAction,
        selection: CapturedSelection,
    ) -> None:
        prompt = self.prompt_builder.build(
            action,
            selection,
            natural_voice_enabled=self.settings.natural_voice_enabled,
            natural_voice_instruction=self.settings.natural_voice_instruction,
            primary_language=self.settings.primary_language,
            guided_drafting_enabled=(
                self.settings.guided_drafting_enabled
            ),
        )
        self.usage.record(action.id)
        self._submit_prompt(
            prompt,
            project_name=project_name_for_action(
                self.settings.project_name,
                action,
            ),
        )

    def set_natural_voice_enabled(self, enabled: bool) -> None:
        if enabled == self.settings.natural_voice_enabled:
            return
        previous = self.settings
        updated = replace(previous, natural_voice_enabled=enabled)
        try:
            save_settings(self.paths.settings_file, updated)
        except OSError as exc:
            LOGGER.exception("Could not save natural voice setting")
            if self.popup is not None:
                self.popup.set_natural_voice_enabled(
                    previous.natural_voice_enabled
                )
            self.notify(
                "Setting could not be saved",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def set_auto_submit_enabled(self, enabled: bool) -> None:
        if enabled == self.settings.auto_submit_enabled:
            return
        previous = self.settings
        updated = replace(previous, auto_submit_enabled=enabled)
        try:
            save_settings(self.paths.settings_file, updated)
        except OSError as exc:
            LOGGER.exception("Could not save automatic submission setting")
            if self.popup is not None:
                self.popup.set_auto_submit_enabled(
                    previous.auto_submit_enabled
                )
            self.notify(
                "Setting could not be saved",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def _submit_prompt(
        self,
        prompt: str,
        project_name: str | None = None,
    ) -> None:
        project_name = project_name or self.settings.project_name
        settings = self.settings
        worker = FunctionWorker(
            lambda: submit_via_worker(prompt, project_name, settings)
        )
        worker.signals.finished.connect(self._submission_finished)
        self.thread_pool.start(worker)

    def _submission_finished(self, result: SubmissionResult) -> None:
        if result.prepared:
            self.notify(
                "Prompt ready in ChatGPT",
                result.message,
                QSystemTrayIcon.MessageIcon.Information,
                6500,
            )
            return
        if not result.submitted:
            self.notify(
                "ChatGPT needs attention",
                result.message,
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )

    def reload_configuration(self) -> None:
        self._reload_configuration()

    def reload_configuration_after_save(self) -> None:
        if self.icons is not None:
            self.icons.clear_cache()
        self._reload_configuration()

    def _reload_configuration(self) -> None:
        try:
            self.hotkeys.unregister_all()
            self.usage.load()
            self._load_components()
            self.register_hotkeys()
            LOGGER.info("Configuration reloaded")
        except ConfigurationError as exc:
            LOGGER.exception("Configuration reload failed")
            self.notify(
                "Configuration error",
                str(exc),
                QSystemTrayIcon.MessageIcon.Critical,
                8000,
            )

    def open_config_folder(self) -> None:
        self.paths.ensure()
        os.startfile(self.paths.data_dir)

    def open_action_settings(self) -> None:
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        from .settings_ui import ActionSettingsDialog

        self.settings_dialog = ActionSettingsDialog(
            self.actions,
            self.paths,
            self._ensure_icons(),
            self.settings.popup_hotkey,
            self.settings,
        )
        self.settings_dialog.actions_saved.connect(
            self.reload_configuration_after_save
        )
        self.settings_dialog.finished.connect(self._settings_dialog_closed)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _settings_dialog_closed(self, result: int) -> None:
        self.settings_dialog = None
        if self.icons is not None:
            self.icons.clear_cache()

    def toggle_startup(self, enabled: bool) -> None:
        try:
            self.startup.set_enabled(enabled)
        except Exception as exc:
            LOGGER.exception("Could not update startup setting")
            self.startup_action.blockSignals(True)
            self.startup_action.setChecked(self.startup.is_enabled())
            self.startup_action.blockSignals(False)
            self.notify(
                "Startup setting failed",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def notify(
        self,
        title: str,
        message: str,
        icon=QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 4500,
    ) -> None:
        self.tray.showMessage(title, message, icon, duration_ms)

    def activate_existing(self, message: str) -> None:
        self.notify(
            f"{APP_NAME} is already running",
            f"Use {self.settings.popup_hotkey} or the Actions Ring to open it.",
        )

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.capture_and_show()

    def quit(self) -> None:
        self.hotkeys.unregister_all()
        shutdown_automation_helper()
        self.tray.hide()
        self.qt_app.quit()


def run() -> int:
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(APP_NAME)
    qt_app.setOrganizationName(APP_ID)
    qt_app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            APP_NAME,
            "The Windows notification area is unavailable.",
        )
        return 1

    paths = AppPaths.discover()
    configure_logging(paths)
    instance = SingleInstance()
    if not instance.acquire():
        return 0

    try:
        launcher = PromptMeld(qt_app, paths)
    except (ConfigurationError, OSError) as exc:
        LOGGER.exception("%s failed to start", APP_NAME)
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    qt_app.aboutToQuit.connect(launcher.hotkeys.unregister_all)
    qt_app.aboutToQuit.connect(instance.release)
    return qt_app.exec()
