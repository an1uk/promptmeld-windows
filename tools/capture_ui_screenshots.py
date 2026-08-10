from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from promptmeld.actions import ActionRegistry
from promptmeld.automation_progress import AutomationProgressWindow
from promptmeld.config import ensure_user_configuration, load_actions, load_settings
from promptmeld.icons import ActionIconProvider
from promptmeld.models import ApplicationProfile, SubmissionResult
from promptmeld.paths import AppPaths
from promptmeld.privacy import detect_sensitive_text
from promptmeld.privacy_preview import PrivacyPreviewDialog
from promptmeld.returning import ReturnDecision
from promptmeld.result_review import ResultReviewDialog
from promptmeld.settings_ui import (
    ActionSettingsDialog,
    ApplicationProfileDialog,
    StarterPackCatalogueDialog,
)
from promptmeld.action_packs import load_builtin_action_packs
from promptmeld.ui import LauncherPopup
from promptmeld.usage import UsageTracker


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    docs = Path(
        os.environ.get(
            "PROMPTMELD_SCREENSHOT_DIR",
            str(project_root / "docs"),
        )
    )
    docs.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    windows_fonts = Path(
        os.environ.get("WINDIR", r"C:\Windows")
    ) / "Fonts"
    segoe_ui = windows_fonts / "segoeui.ttf"
    for font_file in (segoe_ui, windows_fonts / "seguisym.ttf"):
        if font_file.exists():
            QFontDatabase.addApplicationFont(str(font_file))
    if segoe_ui.exists():
        app.setFont(QFont("Segoe UI", 9))

    with tempfile.TemporaryDirectory(prefix="promptmeld-screenshots-") as data:
        paths = AppPaths.discover(Path(data))
        ensure_user_configuration(paths)
        actions = load_actions(paths.actions_file)
        settings = load_settings(paths.settings_file)
        icons = ActionIconProvider(paths.data_dir)

        popup = LauncherPopup(
            ActionRegistry(actions, UsageTracker(paths.usage_file)),
            icons,
            settings.home_most_used_count,
            settings.folder_icons,
            settings.natural_voice_enabled,
            settings.auto_submit_enabled,
            settings.temporary_chat_enabled,
            "dark",
            settings.guided_drafting_enabled,
            settings.resulting_text_length,
            settings.writing_block_enabled,
            settings.resulting_text_formatting,
        )
        popup.set_source_context(
            "outlook.exe",
            ReturnDecision(copy_result=True),
            selected_text=(
                "From: Taylor Morgan\nSubject: Friday meeting\n"
                "Could you confirm whether Friday afternoon still works?"
            ),
        )
        popup.refresh()
        popup.show()
        app.processEvents()
        popup_image = popup.grab().toImage()
        popup_image.save(str(docs / "launcher-popup.png"))
        popup.close()

        progress = AutomationProgressWindow("dark")
        progress.begin("PromptMeld - Editing")
        for stage, message in (
            ("locating-chatgpt", "Opening or focusing ChatGPT"),
            (
                "selecting-mode",
                "Switching from Codex to ChatGPT when needed",
            ),
            (
                "opening-project",
                "Opening the 'PromptMeld - Editing' Project",
            ),
            ("finding-composer", "Finding the ChatGPT message box"),
            ("inserting-prompt", "Inserting the generated prompt"),
        ):
            progress.update_stage(stage, message)
        QTest.qWait(750)
        progress_image = progress.grab().toImage()
        progress.finish(
            SubmissionResult(
                submitted=True,
                generated_text="Generated response retained in memory",
            ),
            can_apply=True,
        )
        app.processEvents()
        progress.grab().toImage().save(
            str(docs / "completion-notification.png")
        )
        progress.close()

        review = ResultReviewDialog("dark")
        review.set_results(
            [
                "Thank you for your message. I can confirm that Friday works.",
                "Thanks for getting in touch. Friday would suit me well.",
                "I appreciate the message. I am available on Friday.",
            ],
            requested_count=3,
            can_apply=True,
        )
        review.show()
        app.processEvents()
        review.grab().toImage().save(
            str(docs / "alternative-review.png")
        )
        review.close()

        privacy_text = (
            "Please reply to Jane Smith at jane@example.com or call "
            "+44 7700 900123. Account number: 1234-5678-9012."
        )
        privacy = PrivacyPreviewDialog(
            privacy_text,
            detect_sensitive_text(privacy_text),
            theme="dark",
        )
        privacy.show()
        app.processEvents()
        privacy.grab().save(str(docs / "privacy-preview.png"))
        privacy.close()

        gap = 32
        overview = QImage(
            popup_image.width() + gap + progress_image.width(),
            max(popup_image.height(), progress_image.height()),
            QImage.Format.Format_ARGB32,
        )
        overview.fill(QColor("#0f1117"))
        painter = QPainter(overview)
        painter.drawImage(0, 0, popup_image)
        painter.drawImage(
            popup_image.width() + gap,
            (overview.height() - progress_image.height()) // 2,
            progress_image,
        )
        painter.end()
        overview.save(str(docs / "promptmeld-overview.png"))

        dialog = ActionSettingsDialog(
            actions,
            paths,
            icons,
            settings.popup_hotkey,
            settings,
        )
        dialog.show()
        app.processEvents()
        dialog.tabs.setCurrentIndex(0)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-general.png"))
        dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-applications.png"))
        profile_dialog = ApplicationProfileDialog(
            "outlook.exe",
            ApplicationProfile(
                return_mode="copy",
                recipient_audience="colleague_peer",
                resulting_text_formatting="plain",
                title_subject="subject",
                natural_voice="on",
                project_name="Client correspondence",
            ),
            settings,
            dialog,
        )
        def capture_profile_dialog() -> None:
            profile_dialog.grab().save(
                str(docs / "configure-application.png")
            )
            profile_dialog.reject()

        QTimer.singleShot(100, capture_profile_dialog)
        profile_dialog.exec()
        dialog.tabs.setCurrentIndex(2)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-actions.png"))
        catalogue = StarterPackCatalogueDialog(
            load_builtin_action_packs(),
            actions,
            icons,
            theme="dark",
        )
        catalogue.refresh("reports")
        catalogue.show()
        app.processEvents()
        catalogue.grab().save(
            str(docs / "starter-pack-catalogue.png")
        )
        catalogue.close()
        dialog.tabs.setCurrentIndex(3)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-hotkeys.png"))
        dialog.tabs.setCurrentIndex(4)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-defaults.png"))
        dialog.tabs.setCurrentIndex(5)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-backup-recovery.png"))
        dialog.tabs.setCurrentIndex(2)
        first_folder = dialog.action_list.topLevelItem(0)
        if first_folder is not None:
            dialog.action_list.setCurrentItem(first_folder)
            app.processEvents()
            dialog.grab().save(str(docs / "manage-folders.png"))
        dialog.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
