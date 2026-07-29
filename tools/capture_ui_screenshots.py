from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from promptmeld.actions import ActionRegistry
from promptmeld.config import ensure_user_configuration, load_actions, load_settings
from promptmeld.icons import ActionIconProvider
from promptmeld.paths import AppPaths
from promptmeld.settings_ui import ActionSettingsDialog
from promptmeld.ui import LauncherPopup
from promptmeld.usage import UsageTracker


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    docs = project_root / "docs"
    docs.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)

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
        )
        popup.show()
        app.processEvents()
        popup.grab().save(str(docs / "launcher-popup.png"))
        popup.close()

        dialog = ActionSettingsDialog(
            actions,
            paths,
            icons,
            settings.popup_hotkey,
            settings,
        )
        dialog.show()
        app.processEvents()
        dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-actions.png"))
        dialog.tabs.setCurrentIndex(2)
        app.processEvents()
        dialog.grab().save(str(docs / "manage-defaults.png"))
        dialog.tabs.setCurrentIndex(1)
        first_folder = dialog.action_list.topLevelItem(0)
        if first_folder is not None:
            dialog.action_list.setCurrentItem(first_folder)
            app.processEvents()
            dialog.grab().save(str(docs / "manage-folders.png"))
        dialog.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
