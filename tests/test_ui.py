from __future__ import annotations

from promptmeld.actions import ActionRegistry
from promptmeld.app import make_tray_icon
from promptmeld.config import load_actions, load_settings
from promptmeld.icons import ActionIconProvider
from promptmeld.models import (
    AppSettings,
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    WritingAction,
)
from promptmeld.paths import AppPaths
from promptmeld.settings_ui import (
    ActionSettingsDialog,
    BranchArrowStyle,
    HotkeyCaptureEdit,
    NoWheelComboBox,
)
from promptmeld.ui import LauncherPopup
from promptmeld.usage import UsageTracker
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QLabel,
    QMessageBox,
)


def test_promptmeld_application_icon_is_available(qtbot):
    assert not make_tray_icon().isNull()


def test_promptmeld_tagline_is_shown_in_launcher_and_configuration(
    qtbot,
    tmp_path,
):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(popup)
    qtbot.addWidget(dialog)

    assert "Write well and prosper" in {
        label.text() for label in popup.findChildren(QLabel)
    }
    assert "Write well and prosper" in {
        label.text() for label in dialog.findChildren(QLabel)
    }
    popup.layout().activate()
    dialog.layout().activate()
    assert popup.tagline.geometry().top() == popup.title.geometry().top()
    heading = dialog.findChild(QLabel, "settingsTitle")
    assert heading is not None
    assert dialog.tagline.geometry().top() == heading.geometry().top()


def test_popup_filters_actions(qtbot, tmp_path):
    actions = [
        WritingAction("shorten", "Shorten", ("concise",), "Make it shorter."),
        WritingAction("friendly", "Friendly", ("warm",), "Make it warmer."),
    ]
    popup = LauncherPopup(
        ActionRegistry(actions, UsageTracker(tmp_path / "usage.json")),
        ActionIconProvider(tmp_path),
    )
    qtbot.addWidget(popup)

    popup.search.setText("warm")

    assert popup.list.count() == 1
    assert popup.list.item(0).data(256) == "friendly"
    assert not popup.list.item(0).icon().isNull()


def test_popup_exposes_remembered_natural_voice_toggle(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        natural_voice_enabled=True,
    )
    qtbot.addWidget(popup)

    with qtbot.waitSignal(popup.natural_voice_changed) as signal:
        popup.natural_voice.setChecked(False)

    assert signal.args == [False]
    assert popup.natural_voice_enabled is False


def test_popup_exposes_remembered_auto_submit_toggle(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        auto_submit_enabled=False,
    )
    qtbot.addWidget(popup)

    with qtbot.waitSignal(popup.auto_submit_changed) as signal:
        popup.auto_submit.setChecked(True)

    assert signal.args == [True]
    assert popup.auto_submit_enabled is True


def test_closed_dropdown_ignores_mouse_wheel(qtbot):
    combo = NoWheelComboBox()
    combo.addItems(["First", "Second"])
    qtbot.addWidget(combo)

    class WheelEvent:
        ignored = False

        def ignore(self):
            self.ignored = True

    event = WheelEvent()
    combo.wheelEvent(event)

    assert event.ignored is True
    assert combo.currentIndex() == 0


def test_popup_browses_folders_and_subfolders(qtbot, tmp_path):
    actions = [
        WritingAction(
            "edit",
            "Edit",
            (),
            "Edit it.",
            folder="Editing",
        ),
        WritingAction(
            "review",
            "Review",
            (),
            "Review it.",
            folder="Editing/Reviews",
        ),
        WritingAction(
            "technical",
            "Technical",
            (),
            "Explain it.",
            folder="Technical help",
        ),
    ]
    popup = LauncherPopup(
        ActionRegistry(actions, UsageTracker(tmp_path / "usage.json")),
        ActionIconProvider(tmp_path),
    )
    qtbot.addWidget(popup)

    assert [popup.list.item(row).text() for row in range(popup.list.count())] == [
        "FOLDERS",
        "Editing  ›",
        "Technical help  ›",
    ]

    popup._run_item(popup.list.item(1))
    assert popup.current_folder == "Editing"
    assert [popup.list.item(row).text() for row in range(popup.list.count())] == [
        "Back",
        "Reviews  ›",
        "Edit",
    ]

    popup._run_item(popup.list.item(1))
    assert popup.current_folder == "Editing/Reviews"
    assert popup.list.item(1).text() == "Review"


def test_popup_shows_direct_and_real_most_used_actions(qtbot, tmp_path):
    usage = UsageTracker(tmp_path / "usage.json")
    usage.record("used")
    actions = [
        WritingAction(
            "pinned",
            "Pinned",
            (),
            "Pinned instruction.",
            folder="Editing",
            show_on_home=True,
        ),
        WritingAction(
            "used",
            "Used",
            (),
            "Used instruction.",
            folder="Editing",
        ),
    ]
    popup = LauncherPopup(
        ActionRegistry(actions, usage),
        ActionIconProvider(tmp_path),
        home_most_used_count=1,
    )
    qtbot.addWidget(popup)

    assert [popup.list.item(row).text() for row in range(popup.list.count())] == [
        "DIRECT ACTIONS",
        "Pinned",
        "MOST USED",
        "Used",
        "FOLDERS",
        "Editing  ›",
    ]


def test_settings_tree_displays_nested_folders(qtbot, tmp_path):
    action = WritingAction(
        "review",
        "Review",
        (),
        "Review it.",
        folder="Editing/Reviews",
    )
    dialog = ActionSettingsDialog(
        [action],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    editing = dialog.action_list.topLevelItem(0)
    reviews = editing.child(0)
    review = reviews.child(0)

    assert editing.text(0) == "Editing"
    assert reviews.text(0) == "Reviews"
    assert review.text(0) == "Review"


def test_action_settings_edits_and_saves_an_action(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    provider = ActionIconProvider(tmp_path)
    action = WritingAction(
        "shorten",
        "Shorten",
        ("brief",),
        "Make it shorter.",
        "Ctrl+Alt+2",
        icon="lucide:scissors",
    )
    dialog = ActionSettingsDialog(
        [action],
        paths,
        provider,
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    dialog.name.setText("Make concise")
    dialog.instruction.setPlainText("Make the text concise.")
    dialog.folder_combo.setCurrentText("Editing / Quick actions")
    dialog.show_on_home.setChecked(True)
    dialog.icon_combo.setCurrentIndex(
        dialog.icon_combo.findData("lucide:shrink")
    )
    assert dialog.save_status.text() == "Unsaved changes"
    dialog._save()

    saved = paths.actions_file.read_text(encoding="utf-8")
    assert '"name": "Make concise"' in saved
    assert '"icon": "lucide:shrink"' in saved
    assert '"folder": "Editing/Quick actions"' in saved
    assert '"show_on_home": true' in saved
    assert dialog.save_status.text() == "Changes saved"


def test_action_instruction_editor_has_high_contrast_style(
    qtbot,
    tmp_path,
):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(theme="dark"),
    )
    qtbot.addWidget(dialog)

    assert dialog.instruction.objectName() == "actionInstruction"
    assert "QPlainTextEdit#actionInstruction" in dialog.styleSheet()
    assert "color: #ffffff" in dialog.styleSheet()


def test_light_and_dark_appearance_options_apply_to_both_windows(
    qtbot,
    tmp_path,
):
    registry = ActionRegistry(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        UsageTracker(tmp_path / "usage.json"),
    )
    light_popup = LauncherPopup(registry, theme="light")
    dark_popup = LauncherPopup(registry, theme="dark")
    light_dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(theme="light"),
    )
    dark_dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(theme="dark"),
    )
    for widget in (light_popup, dark_popup, light_dialog, dark_dialog):
        qtbot.addWidget(widget)

    assert "background: #ffffff" in light_popup.styleSheet()
    assert "background: #16181d" in dark_popup.styleSheet()
    assert "QCheckBox::indicator:checked" in light_popup.styleSheet()
    assert "check-white.svg" in light_popup.styleSheet()
    assert light_dialog.theme.currentData() == "light"
    assert "QDialog { background: #f5f7fa" in light_dialog.styleSheet()
    assert "QTabBar::tab" in light_dialog.styleSheet()
    assert "color: #202631" in light_dialog.styleSheet()
    assert "QCheckBox::indicator:checked" in light_dialog.styleSheet()
    assert "check-white.svg" in light_dialog.styleSheet()
    assert "QTreeWidget::item:hover:!selected" in light_dialog.styleSheet()
    assert "show-decoration-selected: 0" in light_dialog.styleSheet()
    assert isinstance(light_dialog.branch_arrow_style, BranchArrowStyle)
    assert "QTreeWidget::branch" not in light_dialog.styleSheet()
    assert "background: #20242b" not in light_dialog.styleSheet()
    assert "QCheckBox::indicator:checked" in dark_dialog.styleSheet()
    assert "check-white.svg" in dark_dialog.styleSheet()
    assert "border: 2px solid #ffffff" in dark_dialog.styleSheet()
    assert "background: #4f7cff" in dark_dialog.styleSheet()
    assert "show-decoration-selected: 0" in dark_dialog.styleSheet()
    assert isinstance(dark_dialog.branch_arrow_style, BranchArrowStyle)
    assert "QTreeWidget::branch" not in dark_dialog.styleSheet()
    assert "QTableWidget::item" in dark_dialog.styleSheet()
    assert "color: #f6f7fa" in dark_dialog.styleSheet()
    assert "background: #ffffff" not in dark_dialog.styleSheet()


def test_appearance_option_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text("{}", encoding="utf-8")
    settings = load_settings(paths.settings_file)
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        paths,
        ActionIconProvider(tmp_path),
        settings.popup_hotkey,
        settings,
    )
    qtbot.addWidget(dialog)

    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog._save()

    assert load_settings(paths.settings_file).theme == "dark"


def test_general_preferences_are_separate_from_writing_defaults(
    qtbot,
    tmp_path,
):
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    assert [
        dialog.tabs.tabText(index)
        for index in range(dialog.tabs.count())
    ] == ["General", "Writing actions", "Hotkeys", "Defaults & style"]
    general_page = dialog.tabs.widget(0)
    defaults_page = dialog.tabs.widget(3)
    for control in (
        dialog.theme,
        dialog.most_used_count,
        dialog.primary_language,
        dialog.start_with_windows,
    ):
        assert general_page.isAncestorOf(control)
        assert not defaults_page.isAncestorOf(control)


def test_general_tab_shows_about_version_and_github_link(qtbot, tmp_path):
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    assert dialog.tabs.currentIndex() == 0
    assert dialog.version_label.text().startswith("Version ")
    assert "github.com/an1uk/promptmeld-windows" in dialog.github_link.text()
    assert dialog.github_link.openExternalLinks()
    assert (
        dialog.buttons.button(QDialogButtonBox.StandardButton.Close).text()
        == "Close without saving"
    )


def test_unsaved_status_clears_when_changes_are_reverted(qtbot, tmp_path):
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    assert dialog.save_status.text() == ""
    dialog.start_with_windows.setChecked(True)
    assert dialog.save_status.text() == "Unsaved changes"
    dialog.start_with_windows.setChecked(False)
    assert dialog.save_status.text() == ""

    dialog.name.setText("Changed")
    assert dialog.save_status.text() == "Unsaved changes"
    dialog.name.setText("Edit")
    assert dialog.save_status.text() == ""


def test_start_with_windows_option_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text("{}", encoding="utf-8")
    settings = load_settings(paths.settings_file)
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        paths,
        ActionIconProvider(tmp_path),
        settings.popup_hotkey,
        settings,
    )
    qtbot.addWidget(dialog)

    dialog.start_with_windows.setChecked(True)
    dialog._save()

    assert load_settings(paths.settings_file).startup_enabled is True


def test_action_settings_saves_most_used_count(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        '{"home_most_used_count": 3}',
        encoding="utf-8",
    )
    settings = load_settings(paths.settings_file)
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        settings.popup_hotkey,
        settings,
    )
    qtbot.addWidget(dialog)

    dialog.most_used_count.setValue(6)
    dialog._save()

    assert load_settings(paths.settings_file).home_most_used_count == 6


def test_action_settings_saves_natural_voice_configuration(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text("{}", encoding="utf-8")
    settings = load_settings(paths.settings_file)
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        settings.popup_hotkey,
        settings,
    )
    qtbot.addWidget(dialog)

    dialog.natural_voice_default.setChecked(True)
    dialog.auto_submit_default.setChecked(True)
    dialog.natural_voice_instruction.setPlainText("Keep my own vocabulary.")
    dialog.primary_language.setCurrentText("English (US)")
    dialog.natural_voice_mode.setCurrentIndex(
        dialog.natural_voice_mode.findData("never")
    )
    dialog.guided_drafting_default.setChecked(True)
    dialog.guided_drafting.setChecked(True)
    dialog._save()

    saved_settings = load_settings(paths.settings_file)
    assert saved_settings.natural_voice_enabled is True
    assert saved_settings.auto_submit_enabled is True
    assert (
        saved_settings.natural_voice_instruction
        == "Keep my own vocabulary."
    )
    assert saved_settings.primary_language == "English (US)"
    assert saved_settings.guided_drafting_enabled is True
    assert load_actions(paths.actions_file)[0].natural_voice == "never"
    assert load_actions(paths.actions_file)[0].guided_drafting is True


def test_action_settings_restores_recommended_voice_wording(
    qtbot,
    tmp_path,
):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    dialog.natural_voice_instruction.setPlainText("Custom wording")

    dialog.reset_voice_button.click()

    assert (
        dialog.natural_voice_instruction.toPlainText()
        == DEFAULT_NATURAL_VOICE_INSTRUCTION
    )


def test_natural_voice_help_explains_ai_detection_limit(qtbot, tmp_path):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    help_text = dialog.voice_description.text()
    assert "AI-detection tools" in help_text
    assert "avoidance is far from guaranteed" in help_text


def test_submission_help_explains_model_selection(qtbot, tmp_path):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    assert dialog.auto_submit_default.isChecked() is False
    help_text = dialog.submission_description.text()
    assert "without pressing Enter" in help_text
    assert "model or reasoning level" in help_text


def test_action_settings_saves_a_badged_folder_icon(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        '{"folder_icons": {}}',
        encoding="utf-8",
    )
    settings = load_settings(paths.settings_file)
    dialog = ActionSettingsDialog(
        [
            WritingAction(
                "custom",
                "Custom",
                (),
                "Do it.",
                folder="Custom folder",
            )
        ],
        paths,
        ActionIconProvider(tmp_path),
        settings.popup_hotkey,
        settings,
    )
    qtbot.addWidget(dialog)

    folder_item = dialog.action_list.topLevelItem(0)
    dialog.action_list.setCurrentItem(folder_item)
    dialog.icon_combo.setCurrentIndex(
        dialog.icon_combo.findData("lucide:sparkles")
    )
    dialog._save()

    saved_settings = load_settings(paths.settings_file)
    assert saved_settings.folder_icons == {
        "Custom folder": "lucide:sparkles"
    }


def test_action_settings_rejects_duplicate_hotkeys(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    provider = ActionIconProvider(tmp_path)
    actions = [
        WritingAction("one", "One", (), "First.", "Ctrl+Alt+1"),
        WritingAction("two", "Two", (), "Second.", "Ctrl+Alt+1"),
    ]
    dialog = ActionSettingsDialog(
        actions,
        paths,
        provider,
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    try:
        dialog._validated_actions()
    except ValueError as exc:
        assert "same hotkey" in str(exc)
    else:
        raise AssertionError("Expected duplicate hotkeys to be rejected")


def test_hotkey_capture_uses_the_pressed_key_combination(qtbot):
    editor = HotkeyCaptureEdit()
    qtbot.addWidget(editor)
    editor.show()
    editor.setFocus()

    qtbot.keyClick(
        editor,
        Qt.Key.Key_7,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier,
    )

    assert editor.text() == "Ctrl+Alt+7"
    qtbot.keyClick(editor, Qt.Key.Key_8)
    assert editor.text() == "Ctrl+Alt+7"


def test_hotkeys_tab_edits_clears_and_reports_clashes(qtbot, tmp_path):
    actions = [
        WritingAction("one", "One", (), "First.", "Ctrl+Alt+1"),
        WritingAction("two", "Two", (), "Second."),
        WritingAction("three", "Three", (), "Third.", "Ctrl+Alt+3"),
    ]
    dialog = ActionSettingsDialog(
        actions,
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        hotkey_availability=lambda hotkey: hotkey != "Ctrl+Alt+9",
    )
    qtbot.addWidget(dialog)

    assert dialog.hotkey_table.rowCount() == 3
    assert [
        dialog.hotkey_table.item(row, 0).text()
        for row in range(dialog.hotkey_table.rowCount())
    ] == ["One", "Three", "Two"]
    two = dialog.hotkey_editors["two"]
    two.setFocus()
    qtbot.keyClick(
        two,
        Qt.Key.Key_1,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier,
    )
    assert "Clashes with One" in dialog.hotkey_status_labels["two"].text()
    assert "Clashes with Two" in dialog.hotkey_status_labels["one"].text()

    qtbot.keyClick(
        two,
        Qt.Key.Key_9,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier,
    )
    assert (
        dialog.hotkey_status_labels["two"].text()
        == "Already used by Windows or another app"
    )
    two.clear_hotkey()
    assert dialog.hotkey_status_labels["two"].text() == "Not assigned"
    assert (
        next(action for action in dialog.actions if action.id == "two").hotkey
        is None
    )


def test_hotkeys_tab_saves_a_recorded_launcher_shortcut(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text("{}", encoding="utf-8")
    settings = load_settings(paths.settings_file)
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        settings.popup_hotkey,
        settings,
        hotkey_availability=lambda hotkey: True,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tabs.setCurrentIndex(2)

    launcher = dialog.hotkey_editors["__popup__"]
    assert dialog.launcher_hotkey_editor is launcher
    assert dialog.change_launcher_hotkey_button.text() == "Change"
    qtbot.mouseClick(
        dialog.change_launcher_hotkey_button,
        Qt.MouseButton.LeftButton,
    )
    qtbot.wait(1)
    assert launcher.hasFocus()
    assert (
        dialog.hotkey_status_labels["__popup__"].text()
        == "Press the new shortcut now"
    )
    qtbot.keyClick(
        launcher,
        Qt.Key.Key_F8,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier,
    )
    dialog._save()

    assert load_settings(paths.settings_file).popup_hotkey == "Ctrl+Shift+F8"


def test_action_settings_can_load_shipped_starter_set(
    qtbot,
    tmp_path,
    monkeypatch,
):
    paths = AppPaths.discover(tmp_path)
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog._load_starter_set()

    assert len(dialog.actions) == 26
    assert dialog.actions[0].id == "edit-improve"
