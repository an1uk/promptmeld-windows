from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from promptmeld import settings_ui as settings_ui_module
from promptmeld.actions import ActionRegistry
from promptmeld.app import PromptMeld, make_tray_icon
from promptmeld.automation_progress import AutomationProgressWindow
from promptmeld.config import load_actions, load_settings
from promptmeld.icons import ActionIconProvider
from promptmeld.models import (
    AppSettings,
    ApplicationProfile,
    CapturedSelection,
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    SubmissionResult,
    WritingAction,
)
from promptmeld.paths import AppPaths
from promptmeld.returning import (
    ReturnDecision,
    resolve_application_profile,
)
from promptmeld.settings_ui import (
    ActionSettingsDialog,
    ApplicationProfileDialog,
    BranchArrowStyle,
    HotkeyCaptureEdit,
    NoWheelComboBox,
)
from promptmeld.ui import LauncherPopup
from promptmeld.usage import UsageTracker
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSystemTrayIcon,
)


def test_promptmeld_application_icon_is_available(qtbot):
    assert not make_tray_icon().isNull()


def test_automation_progress_appends_and_centres_operations(qtbot):
    window = AutomationProgressWindow("light")
    qtbot.addWidget(window)

    window.begin("PromptMeld - Editing")
    operations = [
        ("locating-chatgpt", "Opening or focusing ChatGPT"),
        ("selecting-mode", "Switching to ChatGPT"),
        ("opening-project", "Opening the Editing project"),
        ("finding-composer", "Finding the message box"),
        ("inserting-prompt", "Inserting the generated prompt"),
        ("finishing", "Leaving the prompt ready for review"),
    ]
    for stage, message in operations:
        window.update_stage(stage, message)
    window.update_stage(*operations[-1])
    qtbot.wait(350)

    assert len(window.operation_labels) == len(operations) + 1
    assert all(
        label.property("state") == "complete"
        for label in window.operation_labels[:-1]
    )
    assert window.operation_labels[-1].property("state") == "current"
    assert window.scroll_animation is not None
    assert window.scroll_animation.duration() == 280
    current_centre = window.current_operation.mapTo(
        window.history.viewport(),
        window.current_operation.rect().center(),
    ).y()
    viewport_centre = window.history.viewport().height() // 2
    assert abs(current_centre - viewport_centre) <= 20


def test_automation_progress_keeps_final_result_in_history(qtbot):
    window = AutomationProgressWindow("dark")
    qtbot.addWidget(window)
    window.begin("PromptMeld")
    window.update_stage("finding-composer", "Finding the message box")

    window.finish(
        SubmissionResult(
            submitted=False,
            prepared=True,
            message="Prompt ready.",
        )
    )

    assert window.title.text() == "Ready in ChatGPT"
    assert window.operation_labels[-1].property("state") == "success"
    assert "ready for your review" in window.operation_labels[-1].text()
    assert window.close_button.isVisible()


def test_automation_progress_identifies_temporary_chat(qtbot):
    window = AutomationProgressWindow("light")
    qtbot.addWidget(window)

    window.begin("PromptMeld", temporary_chat=True)

    assert window.project.text() == "Temporary Chat (outside Projects)"


def test_automation_progress_is_keyboard_accessible_and_cancellable(qtbot):
    window = AutomationProgressWindow("light")
    qtbot.addWidget(window)
    cancelled = QSignalSpy(window.cancel_requested)

    window.begin("PromptMeld")
    qtbot.keyClick(window, Qt.Key.Key_Escape)

    assert cancelled.count() == 1
    assert window.title.text() == "Cancelling"
    assert window.cancel_button.isEnabled() is False
    assert window.accessibleName() == "PromptMeld automation progress"


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
    popup.show()
    qtbot.wait(0)
    popup.layout().activate()
    dialog.layout().activate()
    assert popup.tagline.geometry().top() == popup.title.geometry().top()
    assert (
        abs(
            popup.tagline.mapTo(popup, popup.tagline.rect().center()).x()
            - popup.rect().center().x()
        )
        <= 2
    )
    heading = dialog.findChild(QLabel, "settingsTitle")
    assert heading is not None
    assert dialog.tagline.geometry().top() == heading.geometry().top()


def test_launcher_header_can_drag_the_window(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    popup.move(120, 100)
    popup.show()
    qtbot.wait(0)
    start = popup.title.mapToGlobal(QPoint(4, 4))

    pressed = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(4, 4),
        QPointF(start),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    moved = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(44, 29),
        QPointF(start + QPoint(40, 25)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    released = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(44, 29),
        QPointF(start + QPoint(40, 25)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    assert popup.eventFilter(popup.title, pressed) is True
    assert popup.eventFilter(popup.title, moved) is True
    assert popup.pos() == QPoint(160, 125)
    assert popup.eventFilter(popup.title, released) is True
    assert popup._dragging is False


def test_launcher_has_top_right_close_button(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    popup.show()

    assert popup.close_button.text() == "×"
    assert popup.close_button.accessibleName() == "Close launcher"
    assert popup.close_button.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert popup.close_button.geometry().center().x() > popup.width() // 2

    qtbot.mouseClick(popup.close_button, Qt.MouseButton.LeftButton)

    assert popup.isVisible() is False


def test_launcher_exposes_keyboard_search_and_accessible_action_list(
    qtbot,
    tmp_path,
):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    popup.show()
    popup.list.setFocus()
    popup.search.setText("edit")

    popup.focus_search_shortcut.activated.emit()

    assert popup.search.selectedText() == "edit"
    assert popup.search.accessibleName() == "Search writing actions"
    assert popup.list.accessibleName() == "Writing actions"


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


def test_popup_exposes_paste_result_back_for_editable_sources(
    qtbot,
    tmp_path,
):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        auto_submit_enabled=True,
        replace_selected_text_enabled=False,
    )
    qtbot.addWidget(popup)

    assert popup.replace_selected_text.text() == "Paste result back"
    assert popup.replace_selected_text.isEnabled() is True
    with qtbot.waitSignal(
        popup.replace_selected_text_changed
    ) as signal:
        popup.replace_selected_text.setChecked(True)

    assert signal.args == [True]
    assert popup.replace_selected_text_enabled is True

    popup.set_source_is_editable(False)
    assert popup.replace_selected_text.isEnabled() is False


def test_launcher_shows_application_result_policy(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        auto_submit_enabled=True,
    )
    qtbot.addWidget(popup)

    popup.set_source_context(
        "chrome.exe",
        ReturnDecision(
            copy_result=True,
            requested_mode="copy",
            application="chrome.exe",
            overridden=True,
        ),
    )

    assert "Copy the result for Google Chrome" in popup.source_context.text()
    assert popup.replace_selected_text.isEnabled() is False
    assert "application policy" in popup.replace_selected_text.text()
    popup.set_source_is_editable(True)
    popup.set_auto_submit_enabled(False)
    assert popup.replace_selected_text.isEnabled() is False


def test_launcher_applies_application_guidance_defaults(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
    )
    qtbot.addWidget(popup)
    settings = AppSettings(
        application_profiles={
            "outlook.exe": ApplicationProfile(
                recipient_audience="customer_client",
                editing_strength="improve",
                preserve_facts="off",
                natural_voice="on",
                auto_submit="on",
                resulting_text_length="short",
            )
        }
    )
    selection = CapturedSelection(
        "Text",
        123,
        "Message",
        True,
        "outlook.exe",
    )
    effective = resolve_application_profile(settings, selection)

    popup.set_source_context(
        "outlook.exe",
        ReturnDecision(application="outlook.exe"),
        effective,
    )
    popup.show_at_cursor()

    assert popup.recipient_audience_value == "customer_client"
    assert popup.editing_strength_value == "improve"
    assert popup.preserve_facts_enabled is False
    assert popup.natural_voice.isChecked() is True
    assert popup.natural_voice.isEnabled() is False
    assert popup.auto_submit.isChecked() is True
    assert popup.output_button.isEnabled() is False


def test_launcher_paste_result_back_toggle_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(replace_selected_text_enabled=False)
    app.paths = paths
    app.popup = None
    app.notify = lambda *args: None

    app.set_replace_selected_text_enabled(True)

    assert load_settings(paths.settings_file).replace_selected_text_enabled is True


def test_open_configuration_hides_tool_windows_and_reuses_dialog(qtbot):
    events: list[str] = []

    class ToolWindow:
        def hide(self):
            events.append("hide-tool")

    class SettingsDialog(QDialog):
        def showNormal(self):
            events.append("show-normal")
            super().showNormal()

        def raise_(self):
            events.append("raise")
            super().raise_()

        def activateWindow(self):
            events.append("activate")
            super().activateWindow()

    app = object.__new__(PromptMeld)
    app.popup = ToolWindow()
    app.automation_progress = ToolWindow()
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    app.settings_dialog = dialog

    app.open_action_settings()

    assert events == [
        "hide-tool",
        "hide-tool",
        "show-normal",
        "raise",
        "activate",
    ]
    app.settings_dialog = None
    dialog.close()


def test_open_configuration_recreates_an_unusable_dialog(qtbot):
    events: list[str] = []

    class StaleSettingsDialog:
        def windowState(self):
            raise RuntimeError("Internal C++ object already deleted")

        def hide(self):
            events.append("discard-stale")

        def close(self):
            events.append("close-stale")

    class FreshSettingsDialog(QDialog):
        def showNormal(self):
            events.append("show-fresh")
            super().showNormal()

    class SignalStub:
        def connect(self, callback):
            self.callback = callback

    class Hotkeys:
        def unregister_all(self):
            events.append("unregister-hotkeys")

    app = object.__new__(PromptMeld)
    app.popup = None
    app.automation_progress = None
    app.settings_dialog = StaleSettingsDialog()
    app.hotkeys = Hotkeys()
    app.icons = None
    app.register_hotkeys = lambda: events.append("register-hotkeys")
    app.reload_configuration_after_save = lambda: None
    app.notify = lambda *args: events.append("notify")

    fresh = FreshSettingsDialog()
    fresh.actions_saved = SignalStub()
    qtbot.addWidget(fresh)
    app._create_settings_dialog = lambda: fresh

    app.open_action_settings()

    assert app.settings_dialog is fresh
    assert events == [
        "discard-stale",
        "close-stale",
        "unregister-hotkeys",
        "show-fresh",
    ]
    app.settings_dialog = None
    fresh.close()


def test_tray_double_click_opens_configuration_not_launcher(qtbot):
    events: list[str] = []
    app = object.__new__(PromptMeld)
    app.open_action_settings = lambda: events.append("configuration")
    app.capture_and_show = lambda: events.append("launcher")

    app._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    qtbot.wait(1)

    assert events == ["configuration"]


def test_tray_launcher_entry_is_a_current_hotkey_reminder():
    class Action:
        text = ""

        def setText(self, text: str):
            self.text = text

    notifications: list[tuple] = []
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(popup_hotkey="Ctrl+Shift+F8")
    app.open_launcher_action = Action()
    app.notify = lambda *args: notifications.append(args)

    app._update_tray_shortcut_action()
    app.show_launcher_shortcut_help()

    assert app.open_launcher_action.text == "Launcher hotkey: Ctrl+Shift+F8"
    assert "Select text" in notifications[0][1]
    assert "Ctrl+Shift+F8" in notifications[0][1]
    assert "Double-click" in notifications[0][1]


def test_popup_exposes_remembered_temporary_chat_toggle(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        temporary_chat_enabled=True,
    )
    qtbot.addWidget(popup)

    assert popup.temporary_chat.isChecked() is True
    with qtbot.waitSignal(popup.temporary_chat_changed) as signal:
        popup.temporary_chat.setChecked(False)

    assert signal.args == [False]
    assert popup.temporary_chat_enabled is False


def test_popup_exposes_remembered_guided_questions_toggle(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("reply", "Reply", (), "Write a reply.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        guided_drafting_enabled=True,
    )
    qtbot.addWidget(popup)

    assert popup.guided_drafting.isChecked() is True
    with qtbot.waitSignal(popup.guided_drafting_changed) as signal:
        popup.guided_drafting.setChecked(False)

    assert signal.args == [False]
    assert popup.guided_drafting_enabled is False


def test_launcher_guided_questions_toggle_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    settings = AppSettings(guided_drafting_enabled=False)
    app = object.__new__(PromptMeld)
    app.settings = settings
    app.paths = paths
    app.popup = None
    app.notify = lambda *args: None

    app.set_guided_drafting_enabled(True)

    assert load_settings(paths.settings_file).guided_drafting_enabled is True


def test_launcher_temporary_chat_toggle_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(temporary_chat_enabled=False)
    app.paths = paths
    app.popup = None
    app.notify = lambda *args: None

    app.set_temporary_chat_enabled(True)

    assert load_settings(paths.settings_file).temporary_chat_enabled is True


def test_popup_exposes_remembered_resulting_text_length(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        resulting_text_length="long",
    )
    qtbot.addWidget(popup)

    assert list(popup.length_actions) == [
        "default",
        "extra_short",
        "short",
        "medium",
        "long",
        "extra_long",
    ]
    assert popup.length_actions["long"].isCheckable() is False
    assert popup.length_actions["long"].text() == "Long  (selected)"
    assert popup.length_actions["long"].font().bold() is True
    assert popup.length_menu_action.text() == "Resulting text length: Long"
    with qtbot.waitSignal(popup.resulting_text_length_changed) as signal:
        popup.length_actions["extra_short"].trigger()

    assert signal.args == ["extra_short"]
    assert popup.resulting_text_length_value == "extra_short"
    assert (
        popup.length_actions["extra_short"].text()
        == "Extra short  (selected)"
    )
    assert popup.length_actions["long"].text() == "Long"


def test_launcher_resulting_text_length_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(resulting_text_length="default")
    app.paths = paths
    app.popup = None
    app.notify = lambda *args: None

    app.set_resulting_text_length("extra_long")

    assert load_settings(paths.settings_file).resulting_text_length == "extra_long"


def test_popup_exposes_remembered_writing_block_toggle(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        writing_block_enabled=True,
    )
    qtbot.addWidget(popup)

    assert popup.writing_block_actions[True].isCheckable() is False
    assert popup.writing_block_actions[True].text() == "On  (selected)"
    assert (
        popup.writing_block_menu_action.text()
        == "Copyable writing block: On"
    )
    with qtbot.waitSignal(popup.writing_block_changed) as signal:
        popup.writing_block_actions[False].trigger()

    assert signal.args == [False]
    assert popup.writing_block_enabled is False
    assert popup.writing_block_actions[False].text() == "Off  (selected)"


def test_launcher_writing_block_toggle_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(writing_block_enabled=False)
    app.paths = paths
    app.popup = None
    app.notify = lambda *args: None

    app.set_writing_block_enabled(True)

    assert load_settings(paths.settings_file).writing_block_enabled is True


def test_popup_exposes_resulting_text_formatting_in_output_menu(
    qtbot,
    tmp_path,
):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        resulting_text_formatting="plain",
    )
    qtbot.addWidget(popup)

    assert popup.formatting_actions["plain"].isCheckable() is False
    assert (
        popup.formatting_actions["plain"].text()
        == "Do not add formatting  (selected)"
    )
    assert (
        popup.formatting_menu_action.text()
        == "Formatting: Do not add formatting"
    )
    assert "No added formatting" in popup.output_summary.text()
    with qtbot.waitSignal(
        popup.resulting_text_formatting_changed
    ) as signal:
        popup.formatting_actions["formatted"].trigger()

    assert signal.args == ["formatted"]
    assert popup.resulting_text_formatting_value == "formatted"
    assert "Helpful formatting" in popup.output_summary.text()


def test_launcher_resulting_text_formatting_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(resulting_text_formatting="default")
    app.paths = paths
    app.popup = None
    app.notify = lambda *args: None

    app.set_resulting_text_formatting("formatted")

    assert (
        load_settings(paths.settings_file).resulting_text_formatting
        == "formatted"
    )


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


def test_popup_single_clicks_folders_but_not_actions(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [
                WritingAction(
                    "edit",
                    "Edit",
                    (),
                    "Edit it.",
                    folder="Editing",
                )
            ],
            UsageTracker(tmp_path / "usage.json"),
        ),
        ActionIconProvider(tmp_path),
    )
    qtbot.addWidget(popup)
    requested = QSignalSpy(popup.action_requested)

    popup.list.itemClicked.emit(popup.list.item(1))

    assert popup.current_folder == "Editing"
    assert requested.count() == 0
    action_item = popup.list.item(1)
    popup.list.itemClicked.emit(action_item)
    assert requested.count() == 0
    popup.additional_information.setPlainText(
        "Mention that Tuesday afternoon works."
    )
    popup.set_editing_strength("proofread")
    popup.set_preserve_facts_enabled(False)
    popup.set_recipient_audience("company_support")

    popup.list.itemDoubleClicked.emit(action_item)

    assert requested.count() == 1
    assert requested.at(0) == [
        "edit",
        "Mention that Tuesday afternoon works.",
        "proofread",
        False,
        "company_support",
    ]


def test_popup_adds_information_to_a_one_off_instruction(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    requested = QSignalSpy(popup.custom_requested)
    popup.custom.setText("Draft a reply")
    popup.additional_information.setPlainText(
        "Make clear that I cannot agree to the fee."
    )
    popup.set_editing_strength("rewrite")
    popup.set_recipient_audience("customer_client")

    popup.custom_send.click()

    assert requested.count() == 1
    assert requested.at(0) == [
        "Draft a reply",
        "Make clear that I cannot agree to the fee.",
        "rewrite",
        True,
        "customer_client",
    ]


def test_popup_writing_guidance_menu_shows_current_choices(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)

    assert popup.editing_actions["default"].isCheckable() is False
    assert popup.editing_actions["default"].text() == "Default  (selected)"
    assert popup.preserve_actions[True].text() == "On  (selected)"
    assert (
        popup.audience_actions["unspecified"].text()
        == "Not specified  (selected)"
    )

    popup.editing_actions["improve"].trigger()
    popup.preserve_actions[False].trigger()
    popup.audience_actions["manager_senior"].trigger()

    assert popup.editing_menu_action.text() == "Editing strength: Improve"
    assert (
        popup.preserve_menu_action.text()
        == "Preserve facts and specifics: Off"
    )
    assert (
        popup.audience_menu_action.text()
        == "Recipient or audience: Manager or senior colleague"
    )
    assert "Improve" in popup.guidance_summary.text()
    assert "Specifics unprotected" in popup.guidance_summary.text()
    assert "Manager or senior colleague" in popup.guidance_summary.text()


def test_popup_clears_additional_information_for_a_new_capture(
    qtbot,
    tmp_path,
):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    popup.additional_information.setPlainText("Context from an old request")
    popup.set_editing_strength("rewrite")
    popup.set_preserve_facts_enabled(False)
    popup.set_recipient_audience("public_online")

    popup.show_at_cursor()

    assert popup.additional_information.toPlainText() == ""
    assert popup.editing_strength_value == "default"
    assert popup.preserve_facts_enabled is True
    assert popup.recipient_audience_value == "unspecified"


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
    assert dialog.close_button.text() == "Discard changes and close"
    dialog._save()

    saved = paths.actions_file.read_text(encoding="utf-8")
    assert '"name": "Make concise"' in saved
    assert '"icon": "lucide:shrink"' in saved
    assert '"folder": "Editing/Quick actions"' in saved
    assert '"show_on_home": true' in saved
    assert dialog.save_status.text() == "Changes saved"
    assert dialog.close_button.text() == "Close"


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
    assert "QCheckBox::indicator:checked" in dark_popup.styleSheet()
    assert "check-white.svg" in dark_popup.styleSheet()
    assert "border: 2px solid #ffffff" in dark_popup.styleSheet()
    assert "background: #4f7cff" in dark_popup.styleSheet()
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
    assert "QTableWidget#hotkeyTable::item" in light_dialog.styleSheet()
    assert "color: #000000" in light_dialog.styleSheet()
    assert "QCheckBox::indicator:checked" in dark_dialog.styleSheet()
    assert "check-white.svg" in dark_dialog.styleSheet()
    assert "border: 2px solid #ffffff" in dark_dialog.styleSheet()
    assert "background: #4f7cff" in dark_dialog.styleSheet()
    assert "show-decoration-selected: 0" in dark_dialog.styleSheet()
    assert isinstance(dark_dialog.branch_arrow_style, BranchArrowStyle)
    assert "QTreeWidget::branch" not in dark_dialog.styleSheet()
    assert "QTableWidget::item" in dark_dialog.styleSheet()
    assert "color: #f6f7fa" in dark_dialog.styleSheet()
    assert "color: #000000" not in dark_dialog.styleSheet()
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
    ] == [
        "General",
        "Applications",
        "Writing actions",
        "Hotkeys",
        "Defaults & style",
        "Backup && recovery",
    ]
    general_page = dialog.tabs.widget(0)
    defaults_page = dialog.tabs.widget(3)
    for control in (
        dialog.theme,
        dialog.most_used_count,
        dialog.primary_language,
        dialog.start_with_windows,
        dialog.check_for_updates,
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
    assert dialog.check_for_updates.isChecked() is True
    assert dialog.check_updates_button.text() == "Check now"
    assert "github.com/an1uk/promptmeld-windows" in dialog.github_link.text()
    assert dialog.github_link.openExternalLinks()
    assert (
        dialog.buttons.button(QDialogButtonBox.StandardButton.Close).text()
        == "Close"
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
    assert dialog.close_button.text() == "Discard changes and close"
    dialog.start_with_windows.setChecked(False)
    assert dialog.save_status.text() == ""
    assert dialog.close_button.text() == "Close"

    dialog.name.setText("Changed")
    assert dialog.save_status.text() == "Unsaved changes"
    assert dialog.close_button.text() == "Discard changes and close"
    dialog.name.setText("Edit")
    assert dialog.save_status.text() == ""
    assert dialog.close_button.text() == "Close"

    long_index = dialog.resulting_text_length.findData("long")
    default_index = dialog.resulting_text_length.findData("default")
    dialog.resulting_text_length.setCurrentIndex(long_index)
    assert dialog.save_status.text() == "Unsaved changes"
    dialog.resulting_text_length.setCurrentIndex(default_index)
    assert dialog.save_status.text() == ""

    dialog.writing_block_default.setChecked(True)
    assert dialog.save_status.text() == "Unsaved changes"
    dialog.writing_block_default.setChecked(False)
    assert dialog.save_status.text() == ""

    formatted_index = dialog.resulting_text_formatting.findData("formatted")
    default_formatting = dialog.resulting_text_formatting.findData("default")
    dialog.resulting_text_formatting.setCurrentIndex(formatted_index)
    assert dialog.save_status.text() == "Unsaved changes"
    dialog.resulting_text_formatting.setCurrentIndex(default_formatting)
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


def test_automatic_update_check_option_is_saved(qtbot, tmp_path):
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

    dialog.check_for_updates.setChecked(False)
    assert dialog.has_unsaved_changes() is True
    assert dialog.save_changes() is True

    assert load_settings(paths.settings_file).check_for_updates_enabled is False


def test_configuration_update_status_controls_available_actions(qtbot, tmp_path):
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    dialog.set_update_status(
        "PromptMeld 0.1.1 is available.",
        release_available=True,
        install_available=True,
        version="0.1.1",
    )

    assert dialog.view_update_release_button.isEnabled() is True
    assert dialog.install_update_button.isEnabled() is True
    assert "0.1.1" in dialog.install_update_button.text()


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
    dialog.temporary_chat_default.setChecked(True)
    dialog.natural_voice_instruction.setPlainText("Keep my own vocabulary.")
    dialog.primary_language.setCurrentText("English (US)")
    dialog.natural_voice_mode.setCurrentIndex(
        dialog.natural_voice_mode.findData("never")
    )
    dialog.guided_drafting_default.setChecked(True)
    dialog.guided_drafting.setChecked(True)
    dialog.resulting_text_length.setCurrentIndex(
        dialog.resulting_text_length.findData("extra_long")
    )
    dialog.writing_block_default.setChecked(True)
    dialog.resulting_text_formatting.setCurrentIndex(
        dialog.resulting_text_formatting.findData("formatted")
    )
    dialog._save()

    saved_settings = load_settings(paths.settings_file)
    assert saved_settings.natural_voice_enabled is True
    assert saved_settings.auto_submit_enabled is True
    assert saved_settings.temporary_chat_enabled is True
    assert (
        saved_settings.natural_voice_instruction
        == "Keep my own vocabulary."
    )
    assert saved_settings.primary_language == "English (US)"
    assert saved_settings.guided_drafting_enabled is True
    assert saved_settings.resulting_text_length == "extra_long"
    assert saved_settings.writing_block_enabled is True
    assert saved_settings.resulting_text_formatting == "formatted"
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

    help_text = dialog.natural_voice_help.accessibleDescription()
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
    assert dialog.temporary_chat_default.isChecked() is False
    assert "width='340'" in dialog.auto_submit_help.toolTip()
    assert "model or reasoning level" in dialog.auto_submit_help.toolTip()
    assert "must review and confirm yourself" in (
        dialog.temporary_chat_help.toolTip()
    )


def test_copy_generated_text_tooltip_has_readable_theme_contrast(
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

    dialog.theme.setCurrentIndex(dialog.theme.findData("light"))
    dialog._apply_style()
    light_style = dialog.styleSheet()
    assert "QToolTip" in light_style
    assert "color: #202631" in light_style
    assert "background-color: #ffffff" in light_style
    assert "Copy the generated result to the clipboard" in (
        dialog.copy_generated_text_default.text()
    )
    assert dialog.copy_generated_text_help.text() == "?"
    assert dialog.copy_generated_text_help.toolTip()

    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog._apply_style()
    dark_style = dialog.styleSheet()
    assert "color: #f4f5f7" in dark_style
    assert "background-color: #22252c" in dark_style


def test_automatic_replacement_warning_is_attached_to_its_help_icon(
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

    assert dialog.replace_selected_text_default.text() == (
        "Replace the original selection with the generated result"
    )
    replacement_help = dialog.replace_selected_text_help.toolTip()
    assert "Clipboard History" in replacement_help
    assert "Warning:" not in dialog.copy_generated_text_help.toolTip()
    assert dialog.replace_selected_text_warning.text().startswith(
        "Warning:"
    )
    assert dialog.replace_selected_text_warning.objectName() == "warning"

    dialog.theme.setCurrentIndex(dialog.theme.findData("light"))
    dialog._apply_style()
    light_style = dialog.styleSheet()
    assert "QToolButton#helpIcon" in light_style
    assert "color: #244fae" in light_style
    assert "background-color: #eef3ff" in light_style

    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog._apply_style()
    dark_style = dialog.styleSheet()
    assert "color: #d9e2ff" in dark_style
    assert "background-color: #2b3347" in dark_style


def test_defaults_style_uses_compact_help_icons_for_explanations(
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

    for help_button in (
        dialog.resulting_text_length_help,
        dialog.resulting_text_formatting_help,
        dialog.writing_block_help,
        dialog.natural_voice_help,
        dialog.guided_drafting_help,
    ):
        assert help_button.text() == "?"
        assert "width='340'" in help_button.toolTip()
        assert help_button.accessibleDescription()


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
    hotkey_header = dialog.hotkey_table.horizontalHeader()
    assert (
        hotkey_header.sectionResizeMode(0)
        == QHeaderView.ResizeMode.Stretch
    )
    assert (
        hotkey_header.sectionResizeMode(2)
        == QHeaderView.ResizeMode.Fixed
    )
    assert hotkey_header.sectionSize(2) == 150
    assert (
        dialog.hotkey_table.horizontalHeaderItem(2).textAlignment()
        & Qt.AlignmentFlag.AlignHCenter
    )
    assert (
        dialog.hotkey_status_labels["one"].alignment()
        & Qt.AlignmentFlag.AlignHCenter
    )
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


def test_hotkeys_sort_unavailable_first_then_by_shortcut_and_empty_last(
    qtbot,
    tmp_path,
):
    actions = [
        WritingAction("later", "Later", (), "Later.", "Ctrl+Alt+F10"),
        WritingAction("empty", "Empty", (), "Empty."),
        WritingAction("unavailable", "Unavailable", (), "No.", "Ctrl+Alt+F9"),
        WritingAction("first", "First", (), "First.", "Ctrl+Alt+F2"),
    ]
    dialog = ActionSettingsDialog(
        actions,
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        hotkey_availability=lambda hotkey: hotkey != "Ctrl+Alt+F9",
    )
    qtbot.addWidget(dialog)

    assert [
        dialog.hotkey_table.item(row, 0).text()
        for row in range(dialog.hotkey_table.rowCount())
    ] == ["Unavailable", "First", "Later", "Empty"]
    assert dialog.hotkey_status_labels["unavailable"].text() == (
        "Already used by Windows or another app"
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
    dialog.tabs.setCurrentIndex(
        next(
            index
            for index in range(dialog.tabs.count())
            if dialog.tabs.tabText(index) == "Hotkeys"
        )
    )

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


def test_application_result_policy_is_accessible_and_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    settings = AppSettings(auto_submit_enabled=True)
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        settings.popup_hotkey,
        settings,
    )
    qtbot.addWidget(dialog)
    chrome_index = dialog.application_picker.findData("chrome.exe")
    dialog.application_picker.setCurrentIndex(chrome_index)

    qtbot.mouseClick(
        dialog.add_application_policy_button,
        Qt.MouseButton.LeftButton,
    )

    assert dialog.application_policy_table.rowCount() == 1
    assert dialog.application_policy_table.accessibleName() == (
        "Application profiles"
    )
    profile = dialog._application_profiles()["chrome.exe"]
    assert profile.return_mode == "copy"
    dialog._application_profile_values["chrome.exe"] = replace(
        profile,
        return_mode="replace",
        recipient_audience="public_online",
    )
    assert dialog._save() is True
    saved = load_settings(paths.settings_file)
    assert saved.application_return_policies == {
        "chrome.exe": "replace"
    }
    assert saved.application_profiles[
        "chrome.exe"
    ].recipient_audience == "public_online"


def test_application_profile_dialog_edits_useful_writing_defaults(
    qtbot,
):
    editor = ApplicationProfileDialog(
        "outlook.exe",
        ApplicationProfile(return_mode="copy"),
        AppSettings(primary_language="English (UK)"),
    )
    qtbot.addWidget(editor)
    editor.audience.setCurrentIndex(
        editor.audience.findData("customer_client")
    )
    editor.length.setCurrentIndex(editor.length.findData("short"))
    editor.auto_submit.setCurrentIndex(editor.auto_submit.findData("on"))
    editor.project_name.setText("Email writing")

    profile = editor.profile()

    assert profile.recipient_audience == "customer_client"
    assert profile.resulting_text_length == "short"
    assert profile.auto_submit == "on"
    assert profile.project_name == "Email writing"


def test_double_clicking_application_opens_its_profile_editor(
    qtbot,
    tmp_path,
    monkeypatch,
):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(
            application_profiles={
                "outlook.exe": ApplicationProfile(return_mode="copy")
            }
        ),
    )
    qtbot.addWidget(dialog)

    class FakeProfileDialog:
        def __init__(self, application, profile, overall, parent):
            assert application == "outlook.exe"
            self._profile = replace(
                profile,
                recipient_audience="colleague_peer",
            )

        def exec(self):
            return QDialog.DialogCode.Accepted

        def profile(self):
            return self._profile

    monkeypatch.setattr(
        settings_ui_module,
        "ApplicationProfileDialog",
        FakeProfileDialog,
    )

    dialog.application_policy_table.cellDoubleClicked.emit(0, 0)

    assert dialog._application_profiles()[
        "outlook.exe"
    ].recipient_audience == "colleague_peer"


def test_configuration_exposes_privacy_filtered_diagnostics_actions(
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
    recovery_index = next(
        index
        for index in range(dialog.tabs.count())
        if dialog.tabs.tabText(index) == "Backup && recovery"
    )
    recovery_page = dialog.tabs.widget(recovery_index)
    assert recovery_page.isAncestorOf(dialog.copy_diagnostics_button)
    copy_requested = QSignalSpy(dialog.diagnostics_copy_requested)
    open_requested = QSignalSpy(dialog.diagnostics_open_requested)

    qtbot.mouseClick(
        dialog.copy_diagnostics_button,
        Qt.MouseButton.LeftButton,
    )
    qtbot.mouseClick(
        dialog.open_log_folder_button,
        Qt.MouseButton.LeftButton,
    )

    assert copy_requested.count() == 1
    assert open_requested.count() == 1


def test_configuration_creates_one_backup_file(qtbot, tmp_path, monkeypatch):
    paths = AppPaths.discover(tmp_path)
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    destination = tmp_path / "portable-backup"
    created = []
    monkeypatch.setattr(
        settings_ui_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )
    monkeypatch.setattr(
        settings_ui_module,
        "create_configuration_backup",
        lambda supplied_paths, supplied_destination: (
            created.append((supplied_paths, supplied_destination))
            or SimpleNamespace(action_count=3, icon_count=2)
        ),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    qtbot.mouseClick(
        dialog.create_backup_button,
        Qt.MouseButton.LeftButton,
    )

    assert created == [(paths, tmp_path / "portable-backup.zip")]


def test_configuration_restore_confirms_reloads_and_closes(
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
    archive = tmp_path / "portable-backup.zip"
    safety = tmp_path / "PromptMeld-pre-restore.zip"
    restored = []
    monkeypatch.setattr(
        settings_ui_module.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(archive), ""),
    )
    monkeypatch.setattr(
        settings_ui_module,
        "inspect_configuration_backup",
        lambda supplied: SimpleNamespace(
            created_at="2026-08-05T12:00:00+00:00",
            app_version="0.1.5",
            action_count=26,
            icon_count=2,
        ),
    )
    monkeypatch.setattr(
        settings_ui_module,
        "restore_configuration_backup",
        lambda supplied_paths, supplied_archive: (
            restored.append((supplied_paths, supplied_archive))
            or SimpleNamespace(safety_backup=safety)
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    restore_signal = QSignalSpy(dialog.configuration_restored)

    qtbot.mouseClick(
        dialog.restore_backup_button,
        Qt.MouseButton.LeftButton,
    )

    assert restored == [(paths, archive)]
    assert restore_signal.count() == 1
    assert dialog.result() == QDialog.DialogCode.Accepted
