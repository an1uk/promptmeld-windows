from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from dataclasses import replace
from importlib.resources import files
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSystemTrayIcon,
)

from . import display_version
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
from .updates import (
    RELEASES_URL,
    DownloadResult,
    ReleaseInfo,
    UpdateCheckResult,
    UpdateState,
    check_is_due,
    check_latest_release,
    cleanup_update_downloads,
    download_installer,
    is_newer_version,
    load_update_state,
    save_update_state,
    verify_installer_file,
)
from .windows import (
    GlobalHotkeyManager,
    SelectionCapture,
    SelectionCaptureError,
    is_hotkey_released,
)
from .worker import FunctionWorker

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .automation_progress import AutomationProgressWindow
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
    def __init__(
        self,
        qt_app: QApplication,
        paths: AppPaths,
        single_instance: SingleInstance | None = None,
    ):
        self.qt_app = qt_app
        self.paths = paths
        self.single_instance = single_instance
        self.settings = None
        self.registry = None
        self.capture = None
        self.popup: LauncherPopup | None = None
        self.automation_progress: AutomationProgressWindow | None = None
        self.icons: ActionIconProvider | None = None
        self.current_selection: CapturedSelection | None = None
        self.prompt_builder = PromptBuilder()
        self.usage = UsageTracker(paths.usage_file)
        self.thread_pool = QThreadPool.globalInstance()
        self.startup = StartupManager()
        self.startup.migrate_legacy_registration()
        self.settings_dialog: ActionSettingsDialog | None = None
        self.update_state_path = paths.data_dir / "update-state.json"
        self.update_downloads_dir = paths.data_dir / "updates"
        self.update_state = load_update_state(self.update_state_path)
        self.available_update: ReleaseInfo | None = None
        self.update_check_in_progress = False
        self.update_download_in_progress = False
        self.update_last_error = ""
        self.update_current_confirmed = False
        self.update_cancel_event: threading.Event | None = None
        self.update_progress_dialog: QProgressDialog | None = None
        cleanup_update_downloads(self.update_downloads_dir)
        cached_release = self.update_state.cached_release
        if cached_release is not None:
            try:
                if is_newer_version(cached_release.version, display_version()):
                    self.available_update = cached_release
            except ValueError:
                LOGGER.warning("Ignored invalid cached update version")

        app_icon = make_tray_icon()
        qt_app.setWindowIcon(app_icon)
        self.tray = QSystemTrayIcon(app_icon, qt_app)
        self.tray.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.configuration_action = self.menu.addAction("Configuration…")
        self.configuration_action.triggered.connect(
            lambda: QTimer.singleShot(0, self.open_action_settings)
        )
        self.menu.setDefaultAction(self.configuration_action)
        self.open_launcher_action = self.menu.addAction("Launcher hotkey")
        self.open_launcher_action.triggered.connect(
            self.show_launcher_shortcut_help
        )
        self.update_action = self.menu.addAction("Check for updates...")
        self.update_action.triggered.connect(
            lambda: self.check_for_updates(manual=True)
        )
        self.menu.addSeparator()
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
        self._refresh_update_surfaces()
        if getattr(sys, "frozen", False):
            QTimer.singleShot(10_000, self._scheduled_update_check)

    def _load_components(self, first_load: bool = False) -> None:
        self.settings = load_settings(self.paths.settings_file)
        self.actions = load_actions(self.paths.actions_file)
        self.registry = ActionRegistry(self.actions, self.usage)
        self.capture = SelectionCapture(self.settings.capture_timeout_ms)
        self._update_tray_shortcut_action()
        if self.popup is not None:
            self.popup.set_registry(
                self.registry,
                self.settings.home_most_used_count,
                self.settings.folder_icons,
                self.settings.natural_voice_enabled,
                self.settings.auto_submit_enabled,
                self.settings.temporary_chat_enabled,
                self.settings.guided_drafting_enabled,
                self.settings.resulting_text_length,
                self.settings.writing_block_enabled,
                self.settings.resulting_text_formatting,
                self.settings.replace_selected_text_enabled,
            )
            self.popup.set_theme(self.settings.theme)

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
                self.settings.temporary_chat_enabled,
                self.settings.theme,
                self.settings.guided_drafting_enabled,
                self.settings.resulting_text_length,
                self.settings.writing_block_enabled,
                self.settings.resulting_text_formatting,
                self.settings.replace_selected_text_enabled,
            )
            self.popup.action_requested.connect(self.run_action)
            self.popup.custom_requested.connect(self.run_custom)
            self.popup.natural_voice_changed.connect(
                self.set_natural_voice_enabled
            )
            self.popup.auto_submit_changed.connect(
                self.set_auto_submit_enabled
            )
            self.popup.replace_selected_text_changed.connect(
                self.set_replace_selected_text_enabled
            )
            self.popup.temporary_chat_changed.connect(
                self.set_temporary_chat_enabled
            )
            self.popup.guided_drafting_changed.connect(
                self.set_guided_drafting_enabled
            )
            self.popup.resulting_text_length_changed.connect(
                self.set_resulting_text_length
            )
            self.popup.writing_block_changed.connect(
                self.set_writing_block_enabled
            )
            self.popup.resulting_text_formatting_changed.connect(
                self.set_resulting_text_formatting
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
        popup = self._ensure_popup()
        popup.set_source_is_editable(self.current_selection.source_is_editable)
        popup.show_at_cursor()

    def capture_and_submit(self, action: WritingAction) -> None:
        try:
            selection = self.capture.capture()
        except SelectionCaptureError as exc:
            self.notify(APP_NAME, str(exc), QSystemTrayIcon.MessageIcon.Warning)
            return
        self._submit_action(action, selection)

    def run_action(
        self,
        action_id: str,
        additional_information: str = "",
        editing_strength: str = "default",
        preserve_facts: bool = True,
        recipient_audience: str = "unspecified",
    ) -> None:
        action = self.registry.get(action_id)
        if action is None or self.current_selection is None:
            self.notify(
                APP_NAME,
                "The selected action or captured text is no longer available.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self._submit_action(
            action,
            self.current_selection,
            additional_information=additional_information,
            editing_strength=editing_strength,
            preserve_facts=preserve_facts,
            recipient_audience=recipient_audience,
        )

    def run_custom(
        self,
        instruction: str,
        additional_information: str = "",
        editing_strength: str = "default",
        preserve_facts: bool = True,
        recipient_audience: str = "unspecified",
    ) -> None:
        if self.current_selection is None:
            self.notify(
                APP_NAME,
                "The captured text is no longer available.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        if not self._confirm_automatic_replacement(self.current_selection):
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
                resulting_text_length=self.settings.resulting_text_length,
                writing_block_enabled=self.settings.writing_block_enabled,
                resulting_text_formatting=(
                    self.settings.resulting_text_formatting
                ),
                additional_information=additional_information,
                editing_strength=editing_strength,
                preserve_facts=preserve_facts,
                recipient_audience=recipient_audience,
            )
        except ValueError as exc:
            self.notify(APP_NAME, str(exc), QSystemTrayIcon.MessageIcon.Warning)
            return
        self.usage.record("__custom__")
        self._submit_prompt(prompt, selection=self.current_selection)

    def _submit_action(
        self,
        action: WritingAction,
        selection: CapturedSelection,
        *,
        additional_information: str = "",
        editing_strength: str = "default",
        preserve_facts: bool = True,
        recipient_audience: str = "unspecified",
    ) -> None:
        if not self._confirm_automatic_replacement(selection):
            return
        prompt = self.prompt_builder.build(
            action,
            selection,
            natural_voice_enabled=self.settings.natural_voice_enabled,
            natural_voice_instruction=self.settings.natural_voice_instruction,
            primary_language=self.settings.primary_language,
            guided_drafting_enabled=(
                self.settings.guided_drafting_enabled
            ),
            resulting_text_length=self.settings.resulting_text_length,
            writing_block_enabled=self.settings.writing_block_enabled,
            resulting_text_formatting=(
                self.settings.resulting_text_formatting
            ),
            additional_information=additional_information,
            editing_strength=editing_strength,
            preserve_facts=preserve_facts,
            recipient_audience=recipient_audience,
        )
        self.usage.record(action.id)
        self._submit_prompt(
            prompt,
            project_name=project_name_for_action(
                self.settings.project_name,
                action,
            ),
            selection=selection,
        )

    def _confirm_automatic_replacement(
        self,
        selection: CapturedSelection,
    ) -> bool:
        if not (
            self.settings.replace_selected_text_enabled
            and self.settings.auto_submit_enabled
            and selection.source_is_editable
        ):
            return True
        chat_mode = (
            "Temporary Chat is enabled, so the original text will not be saved "
            "in ChatGPT."
            if self.settings.temporary_chat_enabled
            else "The original may not be recoverable if the replacement goes wrong."
        )
        response = QMessageBox.warning(
            self.popup,
            "Confirm automatic text replacement",
            "PromptMeld will automatically replace the selected text after "
            "ChatGPT generates a response. The generated text may be wrong, "
            "and the existing text may be lost. "
            f"{chat_mode}\n\n"
            "Before using this, consider enabling Windows Clipboard History "
            "(Win+V) or a clipboard manager such as CopyQ. This may preserve "
            "the original selection for recovery, but clipboard history can "
            "retain sensitive text.\n\nDo you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

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

    def set_replace_selected_text_enabled(self, enabled: bool) -> None:
        if enabled == self.settings.replace_selected_text_enabled:
            return
        previous = self.settings
        updated = replace(previous, replace_selected_text_enabled=enabled)
        try:
            save_settings(self.paths.settings_file, updated)
        except OSError as exc:
            LOGGER.exception("Could not save automatic replacement setting")
            if self.popup is not None:
                self.popup.set_replace_selected_text_enabled(
                    previous.replace_selected_text_enabled
                )
            self.notify(
                "Setting could not be saved",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def set_guided_drafting_enabled(self, enabled: bool) -> None:
        if enabled == self.settings.guided_drafting_enabled:
            return
        previous = self.settings
        updated = replace(previous, guided_drafting_enabled=enabled)
        try:
            save_settings(self.paths.settings_file, updated)
        except OSError as exc:
            LOGGER.exception("Could not save guided drafting setting")
            if self.popup is not None:
                self.popup.set_guided_drafting_enabled(
                    previous.guided_drafting_enabled
                )
            self.notify(
                "Setting could not be saved",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def set_temporary_chat_enabled(self, enabled: bool) -> None:
        if enabled == self.settings.temporary_chat_enabled:
            return
        previous = self.settings
        updated = replace(previous, temporary_chat_enabled=enabled)
        try:
            save_settings(self.paths.settings_file, updated)
        except OSError as exc:
            LOGGER.exception("Could not save temporary chat setting")
            if self.popup is not None:
                self.popup.set_temporary_chat_enabled(
                    previous.temporary_chat_enabled
                )
            self.notify(
                "Setting could not be saved",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def set_resulting_text_length(self, value: str) -> None:
        if value == self.settings.resulting_text_length:
            return
        previous = self.settings
        updated = replace(previous, resulting_text_length=value)
        try:
            save_settings(self.paths.settings_file, updated)
        except (OSError, ValueError) as exc:
            LOGGER.exception("Could not save resulting text length setting")
            if self.popup is not None:
                self.popup.set_resulting_text_length(
                    previous.resulting_text_length
                )
            self.notify(
                "Setting could not be saved",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def set_writing_block_enabled(self, enabled: bool) -> None:
        if enabled == self.settings.writing_block_enabled:
            return
        previous = self.settings
        updated = replace(previous, writing_block_enabled=enabled)
        try:
            save_settings(self.paths.settings_file, updated)
        except OSError as exc:
            LOGGER.exception("Could not save writing block setting")
            if self.popup is not None:
                self.popup.set_writing_block_enabled(
                    previous.writing_block_enabled
                )
            self.notify(
                "Setting could not be saved",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def set_resulting_text_formatting(self, value: str) -> None:
        if value == self.settings.resulting_text_formatting:
            return
        previous = self.settings
        updated = replace(previous, resulting_text_formatting=value)
        try:
            save_settings(self.paths.settings_file, updated)
        except (OSError, ValueError) as exc:
            LOGGER.exception("Could not save resulting text formatting setting")
            if self.popup is not None:
                self.popup.set_resulting_text_formatting(
                    previous.resulting_text_formatting
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
        selection: CapturedSelection | None = None,
    ) -> None:
        project_name = project_name or self.settings.project_name
        settings = self.settings
        selection = selection or self.current_selection
        progress_window = self._show_automation_progress(
            project_name,
            temporary_chat=settings.temporary_chat_enabled,
        )
        worker = FunctionWorker(
            lambda report_progress: submit_via_worker(
                prompt,
                project_name,
                settings,
                source_hwnd=(selection.source_hwnd if selection else None),
                source_is_editable=(
                    selection.source_is_editable if selection else False
                ),
                progress_callback=report_progress,
            ),
            with_progress=True,
        )
        worker.signals.progress.connect(progress_window.update_stage)
        worker.signals.finished.connect(
            lambda result, window=progress_window: self._submission_finished(
                result,
                window,
            )
        )
        self.thread_pool.start(worker)

    def _show_automation_progress(
        self,
        project_name: str,
        *,
        temporary_chat: bool = False,
    ) -> AutomationProgressWindow:
        from .automation_progress import AutomationProgressWindow

        if (
            self.automation_progress is None
            or self.automation_progress.theme != self.settings.theme
        ):
            if self.automation_progress is not None:
                self.automation_progress.close()
            self.automation_progress = AutomationProgressWindow(
                self.settings.theme
            )
        self.automation_progress.begin(
            project_name,
            temporary_chat=temporary_chat,
        )
        return self.automation_progress

    def _submission_finished(
        self,
        result: SubmissionResult,
        progress_window: AutomationProgressWindow | None = None,
    ) -> None:
        if progress_window is not None:
            progress_window.finish(result)
        if result.prepared:
            self.notify(
                "Prompt ready in ChatGPT",
                result.message,
                QSystemTrayIcon.MessageIcon.Information,
                6500,
            )
            return
        if result.selection_replaced:
            self.notify(
                "Text replaced",
                result.message,
                QSystemTrayIcon.MessageIcon.Information,
                6500,
            )
            return
        if result.generated_text_copied:
            self.notify(
                "Generated text copied",
                result.message,
                QSystemTrayIcon.MessageIcon.Information,
                6500,
            )
            return
        if result.output_failed:
            self.notify(
                "Generated text could not be returned",
                result.message,
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )
            return
        if not result.submitted:
            self.notify(
                "ChatGPT needs attention",
                result.message,
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )

    def reload_configuration_after_save(self) -> None:
        if self.icons is not None:
            self.icons.clear_cache()
        self._reload_configuration(register_hotkeys=False)
        self._apply_startup_preference()
        self._refresh_update_surfaces()
        if (
            getattr(sys, "frozen", False)
            and self.settings.check_for_updates_enabled
        ):
            QTimer.singleShot(0, self._scheduled_update_check)

    def _reload_configuration(self, register_hotkeys: bool = True) -> None:
        try:
            self.hotkeys.unregister_all()
            self.usage.load()
            self._load_components()
            if register_hotkeys:
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

    def _save_update_state(self) -> None:
        try:
            save_update_state(self.update_state_path, self.update_state)
        except OSError:
            LOGGER.exception("Update state could not be saved")

    def _scheduled_update_check(self) -> None:
        if (
            not getattr(sys, "frozen", False)
            or not self.settings.check_for_updates_enabled
            or self.update_check_in_progress
            or self.update_download_in_progress
            or not check_is_due(self.update_state)
        ):
            return
        self.check_for_updates(manual=False)

    def check_for_updates(self, *, manual: bool = True) -> None:
        if self.update_check_in_progress or self.update_download_in_progress:
            if manual:
                self._sync_settings_update_status(self.settings_dialog)
            return
        self.update_check_in_progress = True
        self.update_last_error = ""
        self.update_state = self.update_state.with_attempt()
        self._save_update_state()
        self._refresh_update_surfaces()
        current_version = display_version()
        worker = FunctionWorker(
            lambda: check_latest_release(current_version)
        )
        worker.signals.finished.connect(
            lambda result, requested_manually=manual: (
                self._update_check_finished(result, requested_manually)
            )
        )
        self.thread_pool.start(worker)

    def _update_check_finished(
        self,
        result: object,
        manual: bool,
    ) -> None:
        self.update_check_in_progress = False
        if not isinstance(result, UpdateCheckResult):
            result = UpdateCheckResult(
                status="error",
                error="GitHub returned an unexpected update result.",
            )

        if result.status == "available" and result.release is not None:
            self.available_update = result.release
            self.update_last_error = ""
            self.update_current_confirmed = False
            should_notify = (
                self.update_state.last_notified_version
                != result.release.version
            )
            self.update_state = replace(
                self.update_state,
                cached_release=result.release,
                last_notified_version=(
                    result.release.version
                    if should_notify
                    else self.update_state.last_notified_version
                ),
            )
            self._save_update_state()
            if manual:
                self._show_update_available(result.release)
            elif should_notify:
                next_step = (
                    "install it"
                    if result.release.installable
                    else "view the release"
                )
                self.notify(
                    "PromptMeld update available",
                    f"Version {result.release.version} is available. Open the "
                    f"PromptMeld tray menu or Configuration to {next_step}.",
                    QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
        elif result.status == "current":
            self.available_update = None
            self.update_last_error = ""
            self.update_current_confirmed = True
            self.update_state = replace(
                self.update_state,
                cached_release=None,
            )
            self._save_update_state()
            if manual:
                QMessageBox.information(
                    self.settings_dialog,
                    "PromptMeld is up to date",
                    f"Version {display_version()} is the latest stable version.",
                )
        else:
            self.update_last_error = result.error or "The update check failed."
            self.update_current_confirmed = False
            LOGGER.warning("Update check failed: %s", self.update_last_error)
            if manual:
                QMessageBox.warning(
                    self.settings_dialog,
                    "Could not check for updates",
                    self.update_last_error,
                )
        self._refresh_update_surfaces()

    def _show_update_available(self, release: ReleaseInfo) -> None:
        message = QMessageBox(self.settings_dialog)
        message.setWindowTitle("PromptMeld update available")
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(
            f"PromptMeld {release.version} is available.\n\n"
            f"You are using version {display_version()}."
        )
        install_button = None
        if release.installable and getattr(sys, "frozen", False):
            install_button = message.addButton(
                "Download and install",
                QMessageBox.ButtonRole.AcceptRole,
            )
        release_button = message.addButton(
            "View release notes",
            QMessageBox.ButtonRole.ActionRole,
        )
        message.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        if not release.installable:
            message.setInformativeText(
                release.install_error
                or "This release can only be downloaded from GitHub."
            )
        elif not getattr(sys, "frozen", False):
            message.setInformativeText(
                "Installer updates are disabled while PromptMeld is running "
                "from a development source tree."
            )
        message.exec()
        clicked = message.clickedButton()
        if install_button is not None and clicked is install_button:
            self.download_update()
        elif clicked is release_button:
            self.open_update_release()

    def _refresh_update_surfaces(self) -> None:
        if self.update_download_in_progress:
            self.update_action.setText("Downloading update...")
            self.update_action.setEnabled(False)
        elif self.update_check_in_progress:
            self.update_action.setText("Checking for updates...")
            self.update_action.setEnabled(False)
        elif self.available_update is not None:
            self.update_action.setText(
                f"Update available: v{self.available_update.version}..."
            )
            self.update_action.setEnabled(True)
        else:
            self.update_action.setText("Check for updates...")
            self.update_action.setEnabled(not self.update_download_in_progress)
        self._sync_settings_update_status(self.settings_dialog)

    def _sync_settings_update_status(self, dialog) -> None:
        if dialog is None or not hasattr(dialog, "set_update_status"):
            return
        try:
            if self.update_download_in_progress:
                dialog.set_update_status(
                    "Downloading and verifying the PromptMeld installer...",
                    checking=True,
                    release_available=self.available_update is not None,
                )
                return
            if self.update_check_in_progress:
                dialog.set_update_status(
                    "Checking the latest stable GitHub release...",
                    checking=True,
                    release_available=self.available_update is not None,
                )
                return
            release = self.available_update
            if release is not None:
                installable = (
                    release.installable and getattr(sys, "frozen", False)
                )
                status = f"PromptMeld {release.version} is available."
                if release.install_error:
                    status = f"{status} {release.install_error}"
                dialog.set_update_status(
                    status,
                    release_available=True,
                    install_available=installable,
                    version=release.version,
                )
                return
            if self.update_last_error:
                dialog.set_update_status(
                    f"Last check failed: {self.update_last_error}"
                )
                return
            if self.update_current_confirmed:
                status = (
                    f"PromptMeld {display_version()} is the latest stable "
                    "version found."
                )
            elif self.update_state.last_attempt_utc:
                status = (
                    "An update check was attempted earlier. Choose Check now "
                    "to refresh the result."
                )
            else:
                status = "Updates have not been checked yet."
            dialog.set_update_status(status)
        except RuntimeError:
            LOGGER.debug("Configuration closed while update status changed")

    def open_update_release(self) -> None:
        url = (
            self.available_update.release_url
            if self.available_update is not None
            else RELEASES_URL
        )
        if not QDesktopServices.openUrl(QUrl(url)):
            self.notify(
                "Could not open GitHub",
                url,
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def download_update(self) -> None:
        release = self.available_update
        if self.update_download_in_progress:
            return
        if release is None:
            self.check_for_updates(manual=True)
            return
        if not release.installable or not getattr(sys, "frozen", False):
            self.open_update_release()
            return

        self.update_download_in_progress = True
        self.update_cancel_event = threading.Event()
        progress = QProgressDialog(
            f"Downloading PromptMeld {release.version}...",
            "Cancel",
            0,
            int(release.installer_size or 0),
            self.settings_dialog,
        )
        progress.setWindowTitle("PromptMeld update")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self.update_cancel_event.set)
        self.update_progress_dialog = progress
        progress.show()

        current_version = display_version()
        cancel_event = self.update_cancel_event
        worker = FunctionWorker(
            lambda report: download_installer(
                release,
                self.update_downloads_dir,
                current_version=current_version,
                report_progress=lambda downloaded, total: report(
                    downloaded,
                    total,
                ),
                is_cancelled=cancel_event.is_set,
            ),
            with_progress=True,
        )
        worker.signals.progress.connect(self._update_download_progress)
        worker.signals.finished.connect(
            lambda result, current=release: self._update_download_finished(
                result,
                current,
            )
        )
        self.thread_pool.start(worker)
        self._refresh_update_surfaces()

    def _update_download_progress(self, downloaded: object, total: object) -> None:
        progress = self.update_progress_dialog
        if progress is None:
            return
        try:
            downloaded_bytes = int(downloaded)
            total_bytes = int(total)
        except (TypeError, ValueError):
            return
        progress.setMaximum(max(1, total_bytes))
        progress.setValue(min(downloaded_bytes, total_bytes))
        progress.setLabelText(
            f"Downloading PromptMeld... "
            f"{downloaded_bytes / 1_048_576:.1f} of "
            f"{total_bytes / 1_048_576:.1f} MB"
        )

    def _update_download_finished(
        self,
        result: object,
        release: ReleaseInfo,
    ) -> None:
        self.update_download_in_progress = False
        self.update_cancel_event = None
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
            self.update_progress_dialog.deleteLater()
            self.update_progress_dialog = None
        self._refresh_update_surfaces()

        if not isinstance(result, DownloadResult):
            result = DownloadResult(error="The updater returned an invalid result.")
        if result.cancelled:
            return
        if not result.succeeded or result.path is None:
            QMessageBox.warning(
                self.settings_dialog,
                "Update download failed",
                result.error or "The installer could not be downloaded.",
            )
            return
        self._confirm_install_update(result.path, release)

    def _confirm_install_update(self, installer_path, release: ReleaseInfo) -> None:
        response = QMessageBox.question(
            self.settings_dialog,
            "Install PromptMeld update",
            f"PromptMeld {release.version} has been downloaded and verified.\n\n"
            "PromptMeld will close and the normal installer will open. Your "
            "configuration and writing actions will be kept.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if response != QMessageBox.StandardButton.Ok:
            return
        if not self._resolve_unsaved_settings_before_update():
            return
        self._launch_update_installer(installer_path, release)

    def _resolve_unsaved_settings_before_update(self) -> bool:
        dialog = self.settings_dialog
        if dialog is None or not dialog.has_unsaved_changes():
            return True
        message = QMessageBox(dialog)
        message.setWindowTitle("Unsaved Configuration changes")
        message.setIcon(QMessageBox.Icon.Warning)
        message.setText(
            "Configuration contains unsaved changes. Save them before "
            "installing the update?"
        )
        save_button = message.addButton(
            "Save changes and install",
            QMessageBox.ButtonRole.AcceptRole,
        )
        discard_button = message.addButton(
            "Discard changes and install",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        message.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        message.exec()
        clicked = message.clickedButton()
        if clicked is save_button:
            return bool(dialog.save_changes())
        return clicked is discard_button

    def _launch_update_installer(
        self,
        installer_path,
        release: ReleaseInfo,
    ) -> None:
        try:
            resolved_installer = installer_path.resolve(strict=True)
            resolved_directory = self.update_downloads_dir.resolve(strict=True)
            if (
                resolved_installer.parent != resolved_directory
                or resolved_installer.name != release.installer_name
            ):
                raise OSError("The verified installer path was not recognised.")
            verification_error = verify_installer_file(
                release,
                resolved_installer,
            )
            if verification_error:
                raise OSError(verification_error)
        except OSError as exc:
            QMessageBox.warning(
                self.settings_dialog,
                "Update could not be installed",
                str(exc),
            )
            return

        self.hotkeys.unregister_all()
        shutdown_automation_helper()
        if self.single_instance is not None:
            self.single_instance.release()
        try:
            subprocess.Popen(
                [str(resolved_installer)],
                cwd=str(resolved_directory),
                close_fds=True,
            )
        except OSError as exc:
            LOGGER.exception("Verified update installer could not be started")
            mutex_restored = (
                self.single_instance is None
                or self.single_instance.reacquire_mutex()
            )
            if mutex_restored and self.settings_dialog is None:
                self.register_hotkeys()
            QMessageBox.critical(
                self.settings_dialog,
                "Update installer could not start",
                f"{exc}\n\nThe verified installer remains at:\n"
                f"{resolved_installer}",
            )
            if not mutex_restored:
                self.qt_app.quit()
            return

        LOGGER.info("Starting verified PromptMeld %s installer", release.version)
        self.tray.hide()
        self.qt_app.quit()

    def open_action_settings(self) -> None:
        # Tool windows can remain topmost while hidden or while an automation
        # worker is finishing. Clear them before presenting Configuration so it
        # cannot open behind a manually closed launcher/progress window.
        LOGGER.info(
            "Configuration open requested (existing_dialog=%s)",
            self.settings_dialog is not None,
        )
        if self.popup is not None:
            self.popup.hide()
        if self.automation_progress is not None:
            self.automation_progress.hide()
        if self.settings_dialog is not None:
            existing_dialog = self.settings_dialog
            try:
                self._sync_settings_update_status(existing_dialog)
                self._present_settings_dialog(existing_dialog)
                LOGGER.info("Existing Configuration window presented")
                return
            except Exception:
                # A Qt wrapper can occasionally outlive its native dialog after
                # a close during another window transition. Do not let that
                # stale reference make every later tray request a no-op.
                LOGGER.exception(
                    "Existing Configuration window was unusable; recreating it"
                )
                self._discard_settings_dialog(existing_dialog)

        self.hotkeys.unregister_all()
        dialog = None
        try:
            dialog = self._create_settings_dialog()
            dialog.actions_saved.connect(self.reload_configuration_after_save)
            update_signals = (
                (
                    "update_check_requested",
                    lambda: self.check_for_updates(manual=True),
                ),
                ("update_release_requested", self.open_update_release),
                ("update_install_requested", self.download_update),
            )
            for signal_name, callback in update_signals:
                signal = getattr(dialog, signal_name, None)
                if signal is not None:
                    signal.connect(callback)
            dialog.finished.connect(
                lambda result, current=dialog: self._settings_dialog_closed(
                    current,
                    result,
                )
            )
            self.settings_dialog = dialog
            self._sync_settings_update_status(dialog)
            self._present_settings_dialog(dialog)
        except Exception as exc:
            LOGGER.exception("Configuration window could not be created")
            if dialog is not None:
                self._discard_settings_dialog(dialog)
            try:
                self.register_hotkeys()
            except Exception:
                LOGGER.exception(
                    "Hotkeys could not be restored after Configuration failed"
                )
            self.notify(
                "Configuration could not be opened",
                str(exc),
                QSystemTrayIcon.MessageIcon.Critical,
                8000,
            )
            return
        LOGGER.info("New Configuration window presented")

    def _create_settings_dialog(self):
        from .settings_ui import ActionSettingsDialog

        return ActionSettingsDialog(
            self.actions,
            self.paths,
            self._ensure_icons(),
            self.settings.popup_hotkey,
            replace(
                self.settings,
                startup_enabled=self.startup.is_enabled(),
            ),
            hotkey_availability=self.hotkeys.is_available,
        )

    def _present_settings_dialog(self, dialog) -> None:
        # Reversing the minimized state before showNormal avoids a Qt/Windows
        # edge case where the dialog is technically visible but remains only on
        # the taskbar. Widget, window-handle, and native activation requests
        # cover the different stages of the Windows window lifecycle.
        state = dialog.windowState()
        dialog.setWindowState(
            (state & ~Qt.WindowState.WindowMinimized)
            | Qt.WindowState.WindowActive
        )
        dialog.showNormal()
        self._activate_settings_dialog(dialog)
        # The tray menu and topmost tool window finish closing asynchronously
        # on Windows. Retry across that native transition rather than relying on
        # one timing-sensitive activation attempt.
        for delay_ms in (75, 250):
            QTimer.singleShot(
                delay_ms,
                lambda current=dialog, delay=delay_ms: (
                    self._reactivate_settings_dialog(current, delay)
                ),
            )

    @staticmethod
    def _activate_settings_dialog(dialog) -> None:
        dialog.raise_()
        dialog.activateWindow()
        window_handle = dialog.windowHandle()
        if window_handle is not None:
            window_handle.requestActivate()
        if sys.platform != "win32":
            return
        try:
            import win32con
            import win32gui

            window_id = int(dialog.winId())
            if window_id and win32gui.IsWindow(window_id):
                win32gui.ShowWindow(window_id, win32con.SW_RESTORE)
                win32gui.BringWindowToTop(window_id)
                win32gui.SetForegroundWindow(window_id)
        except Exception:
            # Windows can refuse SetForegroundWindow under its focus-stealing
            # rules. The Qt requests and the later retry still remain valid.
            LOGGER.debug(
                "Native Configuration activation request was refused",
                exc_info=True,
            )

    def _reactivate_settings_dialog(self, dialog, delay_ms: int = 0) -> None:
        if self.settings_dialog is not dialog:
            return
        try:
            if not dialog.isVisible() or dialog.isMinimized():
                dialog.showNormal()
            self._activate_settings_dialog(dialog)
            if delay_ms >= 250 and not dialog.isActiveWindow():
                QApplication.alert(dialog, 1500)
            LOGGER.info(
                "Configuration activation checked after %d ms "
                "(visible=%s minimized=%s active=%s)",
                delay_ms,
                dialog.isVisible(),
                dialog.isMinimized(),
                dialog.isActiveWindow(),
            )
        except Exception:
            LOGGER.exception(
                "Configuration activation retry failed after %d ms",
                delay_ms,
            )
            self._discard_settings_dialog(dialog)
            try:
                self.register_hotkeys()
            except Exception:
                LOGGER.exception(
                    "Hotkeys could not be restored after Configuration was lost"
                )

    def _discard_settings_dialog(self, dialog) -> None:
        if self.settings_dialog is dialog:
            self.settings_dialog = None
        try:
            dialog.hide()
            dialog.close()
        except Exception:
            LOGGER.debug(
                "Unusable Configuration window could not be closed",
                exc_info=True,
            )

    def _settings_dialog_closed(self, dialog, result: int) -> None:
        if self.settings_dialog is not dialog:
            LOGGER.info("Ignored close signal from an old Configuration window")
            return
        LOGGER.info("Configuration window closed (result=%s)", result)
        self.settings_dialog = None
        if self.icons is not None:
            self.icons.clear_cache()
        self.hotkeys.unregister_all()
        self.register_hotkeys()

    def toggle_startup(self, enabled: bool) -> None:
        previous_registration = self.startup.is_enabled()
        updated = replace(self.settings, startup_enabled=enabled)
        try:
            self.startup.set_enabled(enabled)
            save_settings(self.paths.settings_file, updated)
        except Exception as exc:
            LOGGER.exception("Could not update startup setting")
            try:
                self.startup.set_enabled(previous_registration)
            except Exception:
                LOGGER.exception("Could not restore previous startup setting")
            self.startup_action.blockSignals(True)
            self.startup_action.setChecked(self.startup.is_enabled())
            self.startup_action.blockSignals(False)
            self.notify(
                "Startup setting failed",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        self.settings = updated

    def _apply_startup_preference(self) -> None:
        enabled = self.settings.startup_enabled
        try:
            self.startup.set_enabled(enabled)
        except Exception as exc:
            LOGGER.exception("Could not apply startup setting")
            self.notify(
                "Startup setting failed",
                str(exc),
                QSystemTrayIcon.MessageIcon.Warning,
            )
            enabled = self.startup.is_enabled()
        self.startup_action.blockSignals(True)
        self.startup_action.setChecked(enabled)
        self.startup_action.blockSignals(False)

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

    def _update_tray_shortcut_action(self) -> None:
        self.open_launcher_action.setText(
            f"Launcher hotkey: {self.settings.popup_hotkey}"
        )

    def show_launcher_shortcut_help(self) -> None:
        self.notify(
            "Open the PromptMeld launcher",
            "Select text in an editable application, then press "
            f"{self.settings.popup_hotkey}. Double-click the tray icon to open "
            "Configuration.",
            QSystemTrayIcon.MessageIcon.Information,
            6500,
        )

    def _tray_activated(self, reason) -> None:
        LOGGER.info("Tray icon activated (reason=%s)", reason)
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            QTimer.singleShot(0, self.open_action_settings)

    def quit(self) -> None:
        if self.update_cancel_event is not None:
            self.update_cancel_event.set()
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
        self.hotkeys.unregister_all()
        shutdown_automation_helper()
        if self.automation_progress is not None:
            self.automation_progress.close()
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
        launcher = PromptMeld(qt_app, paths, instance)
    except (ConfigurationError, OSError) as exc:
        LOGGER.exception("%s failed to start", APP_NAME)
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    qt_app.aboutToQuit.connect(launcher.hotkeys.unregister_all)
    qt_app.aboutToQuit.connect(instance.release)
    return qt_app.exec()
