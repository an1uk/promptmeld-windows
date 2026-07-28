from __future__ import annotations

from writing_launcher.actions import ActionRegistry
from writing_launcher.app import make_tray_icon
from writing_launcher.config import load_actions, load_settings
from writing_launcher.icons import ActionIconProvider
from writing_launcher.models import (
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    WritingAction,
)
from writing_launcher.paths import AppPaths
from writing_launcher.settings_ui import (
    ActionSettingsDialog,
    NoWheelComboBox,
)
from writing_launcher.ui import LauncherPopup
from writing_launcher.usage import UsageTracker
from PySide6.QtWidgets import QLabel, QMessageBox


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
    )
    qtbot.addWidget(dialog)

    assert dialog.instruction.objectName() == "actionInstruction"
    assert "QPlainTextEdit#actionInstruction" in dialog.styleSheet()
    assert "color: #ffffff" in dialog.styleSheet()


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
