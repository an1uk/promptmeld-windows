from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from promptmeld import automation_progress as automation_progress_module
from promptmeld import result_review as result_review_module
from promptmeld import settings_ui as settings_ui_module
from promptmeld import ui as ui_module
from promptmeld.action_packs import (
    ActionPack,
    load_action_pack,
    load_builtin_action_packs,
    save_action_pack,
)
from promptmeld.actions import ActionRegistry
from promptmeld.app import PromptMeld, make_tray_icon
from promptmeld.automation_progress import AutomationProgressWindow
from promptmeld.chatgpt_install import CHATGPT_DOWNLOAD_URL
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
from promptmeld.result_review import ResultReviewDialog
from promptmeld.settings_ui import (
    ActionCreationWizard,
    ActionSettingsDialog,
    ApplicationProfileDialog,
    BranchArrowStyle,
    FirstRunSetupWizard,
    HotkeyCaptureEdit,
    NestedFolderDialog,
    NoWheelComboBox,
    StarterPackCatalogueDialog,
)
from promptmeld.ui import LauncherPopup
from promptmeld.usage import UsageTracker
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPalette
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSystemTrayIcon,
    QWizard,
)


def test_promptmeld_application_icon_is_available(qtbot):
    assert not make_tray_icon().isNull()


def test_automation_progress_appends_and_centres_operations(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr(
        automation_progress_module,
        "system_reduced_motion_enabled",
        lambda: False,
    )
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


def test_automation_stages_emit_screen_reader_announcements(qtbot):
    window = AutomationProgressWindow("light")
    qtbot.addWidget(window)
    announcements = QSignalSpy(window.stage_announced)

    window.begin("PromptMeld")
    qtbot.wait(1)
    window.update_stage("opening-project", "Opening the Editing project")
    qtbot.wait(1)

    assert [
        announcements.at(index)[0]
        for index in range(announcements.count())
    ] == [
        "Automation status: Preparing the writing request",
        "Automation status: Opening the Editing project",
    ]
    assert window.current_operation.accessibleName() == (
        "Current automation stage: Opening the Editing project"
    )
    assert window.accessibleDescription() == (
        "Automation status: Opening the Editing project"
    )


def test_recoverable_delivery_exposes_guided_actions(qtbot):
    window = AutomationProgressWindow("light")
    qtbot.addWidget(window)
    retries = QSignalSpy(window.retry_requested)
    window.begin("PromptMeld")

    window.finish(
        SubmissionResult(
            submitted=False,
            recoverable=True,
            retry_mode="delivery",
            failure_code="chatgpt_not_ready",
        )
    )

    assert window.retry_button.isHidden() is False
    assert window.open_chatgpt_button.isHidden() is False
    assert window.copy_prompt_button.isHidden() is False
    window.retry_button.click()
    assert retries.at(0) == ["delivery"]


def test_ambiguous_submission_never_offers_automatic_retry(qtbot):
    window = AutomationProgressWindow("dark")
    qtbot.addWidget(window)
    window.begin("PromptMeld")

    window.finish(
        SubmissionResult(
            submitted=False,
            recoverable=True,
            retry_mode="inspect",
            failure_code="submission_unconfirmed",
        )
    )

    assert window.retry_button.isHidden() is True
    assert window.open_chatgpt_button.isHidden() is False
    assert window.copy_prompt_button.isHidden() is False


def test_automation_stage_announcements_do_not_use_audible_alerts(
    qtbot,
    monkeypatch,
):
    accessibility_events: list[str] = []

    class QuietAccessible:
        class Event:
            NameChanged = "name-changed"

        @staticmethod
        def updateAccessibility(event):
            accessibility_events.append(event)

    monkeypatch.setattr(
        automation_progress_module,
        "QAccessible",
        QuietAccessible,
    )
    monkeypatch.setattr(
        automation_progress_module,
        "QAccessibleEvent",
        lambda _label, event: event,
    )
    window = AutomationProgressWindow("light")
    qtbot.addWidget(window)

    window.begin("PromptMeld")
    window.update_stage("opening-project", "Opening the Editing project")
    qtbot.wait(1)

    assert accessibility_events == ["name-changed", "name-changed"]


def test_automation_progress_skips_scroll_animation_for_reduced_motion(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr(
        automation_progress_module,
        "system_reduced_motion_enabled",
        lambda: True,
    )
    window = AutomationProgressWindow("dark")
    qtbot.addWidget(window)

    window.begin("PromptMeld")
    for index in range(8):
        window.update_stage(f"stage-{index}", f"Operation {index}")
    qtbot.wait(1)

    assert window.reduced_motion is True
    assert window.scroll_animation is None


def test_windows_high_contrast_uses_system_palette_across_main_windows(
    qtbot,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        automation_progress_module,
        "system_high_contrast_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        result_review_module,
        "system_high_contrast_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        settings_ui_module,
        "system_high_contrast_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        ui_module,
        "system_high_contrast_enabled",
        lambda: True,
    )
    registry = ActionRegistry(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        UsageTracker(tmp_path / "usage.json"),
    )
    windows = [
        AutomationProgressWindow("dark"),
        ResultReviewDialog("dark"),
        LauncherPopup(registry, theme="dark"),
        FirstRunSetupWizard(
            "Ctrl+Alt+Space",
            lambda _hotkey: True,
            theme="dark",
        ),
        ApplicationProfileDialog(
            "winword.exe",
            ApplicationProfile(),
            AppSettings(theme="dark"),
        ),
        ActionSettingsDialog(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            AppPaths.discover(tmp_path),
            ActionIconProvider(tmp_path),
            "Ctrl+Alt+Space",
            AppSettings(theme="dark"),
        ),
    ]
    for window in windows:
        qtbot.addWidget(window)

    assert all(
        "palette(window-text)" in window.styleSheet()
        for window in windows
    )
    assert windows[2].testAttribute(
        Qt.WidgetAttribute.WA_TranslucentBackground
    ) is False


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


def test_completion_notification_offers_copy_and_apply_actions(qtbot):
    window = AutomationProgressWindow("dark")
    qtbot.addWidget(window)
    copied = QSignalSpy(window.copy_result_requested)
    applied = QSignalSpy(window.apply_result_requested)
    window.begin("PromptMeld")

    window.finish(
        SubmissionResult(
            submitted=True,
            generated_text="Generated answer",
        ),
        can_apply=True,
    )

    assert window.title.text() == "Response ready"
    assert window.copy_result_button.isVisible()
    assert window.apply_result_button.isVisible()
    assert window.close_button.isVisible()
    assert window.hide_timer.isActive() is False
    qtbot.mouseClick(window.copy_result_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.apply_result_button, Qt.MouseButton.LeftButton)
    assert copied.count() == 1
    assert applied.count() == 1


def test_completion_notification_hides_apply_after_automatic_replacement(qtbot):
    window = AutomationProgressWindow("light")
    qtbot.addWidget(window)
    window.begin("PromptMeld")

    window.finish(
        SubmissionResult(
            submitted=True,
            selection_replaced=True,
            generated_text="Generated answer",
        )
    )

    assert window.copy_result_button.isVisible()
    assert not window.apply_result_button.isVisible()


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


def test_launcher_starter_pack_link_requests_separate_catalogue(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    requested = QSignalSpy(popup.starter_packs_requested)

    assert popup.starter_pack_link.text() == "Add a starter pack…"
    assert "separate window" in popup.starter_pack_link.accessibleName()
    popup.starter_pack_link.click()

    assert requested.count() == 1


def test_hotkey_during_active_run_restores_progress_without_capture():
    events: list[str] = []
    progress = SimpleNamespace(
        showNormal=lambda: events.append("show"),
        raise_=lambda: events.append("raise"),
    )
    app = PromptMeld.__new__(PromptMeld)
    app.automation_worker = object()
    app.automation_state = "waiting"
    app.automation_progress = progress
    app.capture = SimpleNamespace(
        capture=lambda: (_ for _ in ()).throw(
            AssertionError("selection capture must not run")
        )
    )
    app.notify = lambda *args, **kwargs: events.append("notify")

    app.handle_hotkey("__popup__")

    assert events == ["show", "raise", "notify"]


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


def test_launcher_prioritises_action_space_until_options_are_requested(
    qtbot,
    tmp_path,
):
    popup = LauncherPopup(
        ActionRegistry(
            [
                WritingAction(
                    f"action-{index}",
                    f"Action {index}",
                    (),
                    f"Instruction {index}.",
                )
                for index in range(8)
            ],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    popup.show()
    qtbot.wait(1)
    collapsed_height = popup.list.height()

    assert popup.options_panel.isHidden()
    assert popup.options_panel.isAncestorOf(popup.additional_information)
    assert popup.options_toggle.accessibleName().startswith("Show")

    popup.options_toggle.setChecked(True)
    qtbot.wait(1)
    expanded_height = popup.list.height()

    assert popup.options_panel.isVisible()
    assert popup.options_toggle.text() == "Hide request options"
    assert popup.options_toggle.accessibleName().startswith("Hide")
    assert collapsed_height > expanded_height


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


def test_launcher_applies_action_audience_until_user_overrides_it(
    qtbot,
    tmp_path,
):
    actions = [
        WritingAction(
            "public-reply",
            "Public reply",
            (),
            "Draft a public reply.",
            show_on_home=True,
            recipient_audience="public_online",
        ),
        WritingAction(
            "general-edit",
            "General edit",
            (),
            "Edit this.",
            show_on_home=True,
        ),
    ]
    popup = LauncherPopup(
        ActionRegistry(actions, UsageTracker(tmp_path / "usage.json"))
    )
    qtbot.addWidget(popup)
    popup.application_audience_default = "customer_client"
    popup.audience_explicitly_selected = False
    popup.refresh()

    def action_item(action_id):
        return next(
            popup.list.item(row)
            for row in range(popup.list.count())
            if popup.list.item(row).data(Qt.ItemDataRole.UserRole)
            == action_id
        )

    popup.list.setCurrentItem(action_item("public-reply"))
    assert popup.recipient_audience_value == "public_online"

    popup.list.setCurrentItem(action_item("general-edit"))
    assert popup.recipient_audience_value == "customer_client"

    popup._recipient_audience_selected("friend_family")
    popup.list.setCurrentItem(action_item("public-reply"))
    assert popup.recipient_audience_value == "friend_family"


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


def test_configuration_reset_applies_startup_default_and_quits(tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    settings_ui_module.save_settings(
        paths.settings_file,
        AppSettings(
            startup_enabled=False,
            first_run_setup_completed=False,
        ),
    )
    events: list[object] = []
    app = object.__new__(PromptMeld)
    app.paths = paths
    app.startup = SimpleNamespace(
        set_enabled=lambda enabled: events.append(("startup", enabled))
    )
    app.quit = lambda: events.append("quit")

    app._close_after_configuration_reset()

    assert events == [("startup", False), "quit"]


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


def test_launcher_title_or_subject_option_is_remembered(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        ),
        title_subject="automatic",
    )
    qtbot.addWidget(popup)

    assert "Automatic title/subject" in popup.output_summary.text()
    with qtbot.waitSignal(popup.title_subject_changed) as signal:
        popup.title_subject_actions["title"].trigger()

    assert signal.args == ["title"]
    assert popup.title_subject_value == "title"
    assert "Include title" in popup.output_summary.text()


def test_launcher_title_or_subject_setting_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(title_subject="none")
    app.paths = paths
    app.popup = None
    app.notify = lambda *args: None

    app.set_title_subject("subject")

    assert load_settings(paths.settings_file).title_subject == "subject"


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
        1,
    ]


def test_popup_selected_action_has_an_explicit_send_button(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    requested = QSignalSpy(popup.action_requested)

    assert popup.list.currentItem().data(
        popup.ITEM_KIND_ROLE
    ) == "action"
    assert popup.send_selected_action.isEnabled() is True
    assert popup.send_selected_action.text() == "Send selected action"

    qtbot.mouseClick(
        popup.send_selected_action,
        Qt.MouseButton.LeftButton,
    )

    assert requested.count() == 1
    assert requested.at(0)[0] == "edit"


def test_popup_adds_information_to_a_one_off_instruction(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    requested = QSignalSpy(popup.custom_requested)
    assert popup.custom_send.text() == "Use instruction"
    assert popup.custom_send.isEnabled() is False
    popup.custom.setText("Draft a reply")
    assert popup.custom_send.isEnabled() is True
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
        1,
    ]


def test_popup_requests_three_alternatives_for_this_request(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [WritingAction("edit", "Edit", (), "Improve this.")],
            UsageTracker(tmp_path / "usage.json"),
        )
    )
    qtbot.addWidget(popup)
    requested = QSignalSpy(popup.action_requested)

    popup.alternative_actions[3].trigger()
    popup.send_selected_action.click()

    assert popup.alternative_count_value == 3
    assert "Three alternatives" in popup.guidance_summary.text()
    assert requested.at(0)[-1] == 3


def test_alternative_review_switches_copy_and_apply_choice(qtbot):
    dialog = ResultReviewDialog("dark")
    qtbot.addWidget(dialog)
    selected = QSignalSpy(dialog.selected_result_changed)
    copied = QSignalSpy(dialog.copy_result_requested)
    applied = QSignalSpy(dialog.apply_result_requested)

    dialog.set_results(
        ["First version", "Second version", "Third version"],
        requested_count=3,
        can_apply=True,
    )
    dialog.show()
    dialog.options.setCurrentRow(1)

    assert dialog.preview.toPlainText() == "Second version"
    assert selected.at(selected.count() - 1)[0] == "Second version"
    assert not dialog.parse_note.isVisible()
    qtbot.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert copied.count() == 1
    assert applied.count() == 1


def test_alternative_review_explains_an_unseparated_response(qtbot):
    dialog = ResultReviewDialog("light")
    qtbot.addWidget(dialog)

    dialog.set_results(
        ["Combined response"],
        requested_count=3,
        can_apply=False,
    )
    dialog.show()

    assert dialog.parse_note.isVisible()
    assert "could not separate" in dialog.parse_note.text()
    assert not dialog.apply_button.isVisible()


def test_safe_single_result_review_preserves_original_and_withholds_apply(qtbot):
    dialog = ResultReviewDialog("light")
    qtbot.addWidget(dialog)

    dialog.set_results(
        ["The passage is strongest when the conflict becomes specific."],
        requested_count=1,
        can_apply=False,
        action_purpose="analyse",
        safe_review=True,
    )
    dialog.show()

    assert dialog.title.text() == "Review the analysis result"
    assert "preserved the original" in dialog.explanation.text()
    assert dialog.preview.toPlainText().startswith("The passage")
    assert not dialog.options.isVisible()
    assert not dialog.apply_button.isVisible()


def test_selective_review_accepts_changes_and_links_editorial_comments(qtbot):
    dialog = ResultReviewDialog("light")
    qtbot.addWidget(dialog)
    selected = QSignalSpy(dialog.selected_result_changed)
    source = "The draft is very unclear. Keep this sentence."
    response = """
<<<PROMPTMELD_REWRITE>>>
The draft is clear and direct. Keep this sentence.
<<<END_PROMPTMELD_REWRITE>>>
<<<PROMPTMELD_FEEDBACK>>>
The revision removes vague intensification.
<<<END_PROMPTMELD_FEEDBACK>>>
<<<PROMPTMELD_COMMENT>>>
<<<PROMPTMELD_SOURCE_PASSAGE>>>
very unclear
<<<END_PROMPTMELD_SOURCE_PASSAGE>>>
<<<PROMPTMELD_COMMENT_TEXT>>>
This describes the problem without showing it.
<<<END_PROMPTMELD_COMMENT_TEXT>>>
<<<END_PROMPTMELD_COMMENT>>>
"""

    dialog.set_results(
        [response],
        requested_count=1,
        can_apply=True,
        action_purpose="transform",
        source_text=source,
    )
    dialog.show()

    assert dialog.is_selective_review() is True
    assert dialog.changes.topLevelItemCount() >= 1
    assert dialog.selected_result() == (
        "The draft is clear and direct. Keep this sentence."
    )
    assert dialog.apply_button.text() == "Apply selected changes"
    assert dialog.feedback_overview.toPlainText().startswith("The revision")
    assert dialog.comments.topLevelItemCount() == 1

    dialog.reject_all_button.click()
    assert dialog.selected_result() == source
    assert dialog.has_selected_changes() is False
    assert dialog.apply_button.isEnabled() is False
    assert selected.at(selected.count() - 1)[0] == source

    dialog.accept_all_button.click()
    assert dialog.has_selected_changes() is True
    assert dialog.apply_button.isEnabled() is True

    comment = dialog.comments.topLevelItem(0)
    dialog.comments.setCurrentItem(comment)
    assert dialog.before_preview.textCursor().selectedText() == "very unclear"


def test_popup_disables_paste_back_for_safe_action_purpose(qtbot, tmp_path):
    popup = LauncherPopup(
        ActionRegistry(
            [
                WritingAction(
                    "review",
                    "Review",
                    (),
                    "Analyse this.",
                    purpose="analyse",
                )
            ],
            UsageTracker(tmp_path / "usage.json"),
        ),
        auto_submit_enabled=True,
        replace_selected_text_enabled=True,
    )
    qtbot.addWidget(popup)

    popup.set_action_context(
        ReturnDecision(
            review_result=True,
            action_purpose="analyse",
            purpose_safe_review=True,
            action_policy_locked=True,
        )
    )

    assert popup.replace_selected_text.isChecked() is False
    assert popup.replace_selected_text.isEnabled() is False
    assert "disabled for this action" in popup.replace_selected_text.text()
    assert "without replacing" in popup.source_context.text()


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


def test_popup_shows_local_contextual_action_suggestions(qtbot, tmp_path):
    actions = [
        WritingAction(
            "technical",
            "Explain technical issue",
            (),
            "Explain the technical issue.",
        ),
        WritingAction(
            "email",
            "Reply to email",
            ("email", "reply"),
            "Write a useful email reply.",
        ),
    ]
    popup = LauncherPopup(
        ActionRegistry(actions, UsageTracker(tmp_path / "usage.json")),
        ActionIconProvider(tmp_path),
    )
    qtbot.addWidget(popup)

    selected_text = (
        "From: Pat\nSubject: Delivery\nCan you confirm the delivery date?"
    )
    popup.set_source_context(
        "outlook.exe",
        ReturnDecision(copy_result=True),
        selected_text=selected_text,
    )
    popup.refresh()

    assert [popup.list.item(row).text() for row in range(2)] == [
        "SUGGESTED",
        "Reply to email",
    ]
    assert popup.list.currentRow() == 1
    assert "Microsoft Outlook" in popup.suggestion_context_label.text()
    assert "looks like email" in popup.list.item(1).toolTip()
    assert selected_text not in repr(popup.suggestion_context)
    assert not hasattr(popup.suggestion_context, "text")


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


def test_nested_folder_dialog_builds_a_child_path(qtbot):
    dialog = NestedFolderDialog(
        ("Reply", "Reply/Customer"),
        "Reply",
        moving_action=True,
    )
    qtbot.addWidget(dialog)
    dialog.folder_name.setText("Firm replies")

    assert dialog.create_button.isEnabled() is True
    assert dialog.folder_path() == "Reply/Firm replies"


def test_action_settings_guides_moving_an_action_to_a_new_subfolder(
    qtbot,
    tmp_path,
    monkeypatch,
):
    action = WritingAction(
        "reply",
        "Reply",
        (),
        "Write a reply.",
        folder="Reply",
    )
    dialog = ActionSettingsDialog(
        [action],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    dialog._refresh_list(0)

    class AcceptedFolderDialog:
        def __init__(
            self,
            folders,
            selected_parent,
            *,
            moving_action,
            parent,
        ):
            assert "Reply" in folders
            assert selected_parent == "Reply"
            assert moving_action is True
            assert parent is dialog

        def exec(self):
            return QDialog.DialogCode.Accepted

        def folder_path(self):
            return "Reply/Customer"

    monkeypatch.setattr(
        settings_ui_module,
        "NestedFolderDialog",
        AcceptedFolderDialog,
    )

    dialog._new_subfolder()

    assert dialog.actions[0].folder == "Reply/Customer"
    assert dialog.folder_help.isHidden() is False
    assert dialog.has_unsaved_changes() is True


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
        "Overall defaults",
        "Backup && recovery",
    ]
    general_page = dialog.tabs.widget(0)
    defaults_page = dialog.tabs.widget(4)
    assert not isinstance(general_page, QScrollArea)
    for control in (
        dialog.theme,
        dialog.most_used_count,
        dialog.project_name,
        dialog.project_naming_mode,
        dialog.primary_language,
        dialog.start_with_windows,
        dialog.check_for_updates,
    ):
        assert general_page.isAncestorOf(control)
        assert not defaults_page.isAncestorOf(control)


def test_project_naming_strategy_shows_examples_and_is_saved(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    settings_ui_module.save_settings(paths.settings_file, AppSettings())
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        paths,
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(),
    )
    qtbot.addWidget(dialog)

    assert "PromptMeld - Editing" in dialog.project_naming_example.text()

    dialog.project_naming_mode.setCurrentIndex(
        dialog.project_naming_mode.findData("single")
    )
    assert "Example: PromptMeld." in dialog.project_naming_example.text()

    dialog.project_name.setText("My writing")
    dialog.project_naming_mode.setCurrentIndex(
        dialog.project_naming_mode.findData("application")
    )
    assert (
        "My writing - Microsoft Outlook"
        in dialog.project_naming_example.text()
    )

    assert dialog._save() is True
    saved = load_settings(paths.settings_file)
    assert saved.project_name == "My writing"
    assert saved.project_naming_mode == "application"


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
    dialog.action_recipient_audience.setCurrentIndex(
        dialog.action_recipient_audience.findData("customer_client")
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
    dialog.title_subject.setCurrentIndex(
        dialog.title_subject.findData("automatic")
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
    assert saved_settings.title_subject == "automatic"
    assert load_actions(paths.actions_file)[0].natural_voice == "never"
    assert load_actions(paths.actions_file)[0].guided_drafting is True
    assert (
        load_actions(paths.actions_file)[0].recipient_audience
        == "customer_client"
    )


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
        dialog.title_subject_help,
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


def test_first_run_setup_tests_launcher_shortcut_and_explains_scope(qtbot):
    checked: list[str] = []
    download_urls: list[str] = []
    wizard = FirstRunSetupWizard(
        "Ctrl+Alt+Space",
        lambda hotkey: checked.append(hotkey) or True,
        {"Ctrl+Alt+7": "Summarise"},
        startup_enabled=True,
        chatgpt_app_available=lambda: True,
        open_chatgpt_download=lambda url: download_urls.append(url) or True,
    )
    qtbot.addWidget(wizard)

    assert wizard.hotkey_is_available is True
    assert wizard.selected_hotkey() == "Ctrl+Alt+Space"
    assert checked == ["Ctrl+Alt+Space"]
    assert wizard.start_with_windows.isChecked() is True
    assert wizard.chatgpt_app_is_available is True
    assert "desktop app was detected" in wizard.chatgpt_status.text()
    assert "tested and available" in wizard.summary_label.text()

    wizard._open_chatgpt_download()

    assert download_urls == [CHATGPT_DOWNLOAD_URL]

    wizard.hotkey_editor.set_hotkey("Alt+Ctrl+7")
    wizard._test_hotkey()

    assert wizard.hotkey_is_available is False
    assert "Summarise" in wizard.hotkey_status.text()


def test_first_run_setup_offers_a_small_deliberate_starter_pack_choice(qtbot):
    wizard = FirstRunSetupWizard(
        "Ctrl+Alt+Space",
        lambda _hotkey: True,
        chatgpt_app_available=lambda: True,
    )
    qtbot.addWidget(wizard)

    assert tuple(wizard.starter_pack_checkboxes) == (
        "editing",
        "email",
        "reports",
        "social-replies",
        "authors-fiction",
        "authors-nonfiction",
    )
    assert wizard.selected_starter_pack_ids() == ()
    descriptions = wizard.findChildren(QLabel, "setupStarterPackDescription")
    assert len(descriptions) == 6
    assert all(description.wordWrap() for description in descriptions)
    assert wizard.starter_pack_stack.count() == 6
    assert wizard.starter_pack_stack.currentIndex() == 0
    assert wizard.starter_pack_position.text() == "Starter pack 1 of 6"
    assert wizard.previous_starter_pack_button.isEnabled() is False
    assert any(
        "Configuration > Writing actions > Browse starter packs" in label.text()
        for label in wizard.findChildren(QLabel)
    )

    for pack_id in ("editing", "email", "reports"):
        wizard.starter_pack_checkboxes[pack_id].setChecked(True)

    assert wizard.selected_starter_pack_ids() == (
        "editing",
        "email",
        "reports",
    )
    assert wizard.starter_pack_checkboxes["authors-fiction"].isEnabled() is False
    assert "Three starter packs selected" in wizard.starter_pack_limit_label.text()

    wizard.starter_pack_checkboxes["reports"].setChecked(False)

    assert wizard.starter_pack_checkboxes["authors-fiction"].isEnabled() is True
    wizard.next_starter_pack_button.click()
    assert wizard.starter_pack_stack.currentIndex() == 1
    assert wizard.previous_starter_pack_button.isEnabled() is True


def test_first_run_starter_pack_carousel_keeps_navigation_below_card_and_animates(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr(
        settings_ui_module,
        "system_reduced_motion_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        settings_ui_module,
        "system_high_contrast_enabled",
        lambda: False,
    )
    wizard = FirstRunSetupWizard(
        "Ctrl+Alt+Space",
        lambda _hotkey: True,
        chatgpt_app_available=lambda: True,
    )
    qtbot.addWidget(wizard)
    wizard.show()
    qtbot.wait(1)
    for _ in range(3):
        wizard.button(QWizard.WizardButton.NextButton).click()
        qtbot.wait(1)

    card = wizard.starter_pack_stack.currentWidget()
    assert card is not None
    card_bottom = card.mapTo(
        wizard,
        card.rect().bottomLeft(),
    ).y()
    navigation_top = wizard.previous_starter_pack_button.mapTo(
        wizard,
        wizard.previous_starter_pack_button.rect().topLeft(),
    ).y()
    assert navigation_top > card_bottom

    wizard.next_starter_pack_button.click()

    assert wizard.starter_pack_animation is not None
    assert wizard.starter_pack_animation.animationAt(0).duration() == 180
    qtbot.wait(220)
    assert wizard.starter_pack_animation is None


def test_first_run_starter_pack_carousel_skips_animation_for_reduced_motion(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr(
        settings_ui_module,
        "system_reduced_motion_enabled",
        lambda: True,
    )
    wizard = FirstRunSetupWizard(
        "Ctrl+Alt+Space",
        lambda _hotkey: True,
        chatgpt_app_available=lambda: True,
    )
    qtbot.addWidget(wizard)

    wizard.next_starter_pack_button.click()

    assert wizard.starter_pack_stack.currentIndex() == 1
    assert wizard.starter_pack_animation is None


def test_first_run_setup_rechecks_missing_chatgpt_app(qtbot):
    checks = iter((False, True))
    wizard = FirstRunSetupWizard(
        "Ctrl+Alt+Space",
        lambda _hotkey: True,
        chatgpt_app_available=lambda: next(checks),
    )
    qtbot.addWidget(wizard)

    assert wizard.chatgpt_app_is_available is False
    assert "Not detected" in wizard.chatgpt_status.text()
    assert "not detected" in wizard.summary_label.text()

    wizard._check_chatgpt_app()

    assert wizard.chatgpt_app_is_available is True
    assert "Ready" in wizard.chatgpt_status.text()


def test_first_run_setup_warns_before_finishing_without_chatgpt(
    qtbot,
    monkeypatch,
):
    wizard = FirstRunSetupWizard(
        "Ctrl+Alt+Space",
        lambda _hotkey: True,
        chatgpt_app_available=lambda: False,
    )
    qtbot.addWidget(wizard)
    choices = iter(
        (
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: next(choices),
    )

    wizard.accept()

    assert wizard.result() == QDialog.DialogCode.Rejected

    wizard.accept()

    assert wizard.result() == QDialog.DialogCode.Accepted


def test_first_run_setup_has_explicit_readable_dark_appearance(qtbot):
    wizard = FirstRunSetupWizard(
        "Ctrl+Alt+Space",
        lambda _hotkey: True,
        theme="dark",
    )
    qtbot.addWidget(wizard)
    wizard.show()
    qtbot.wait(1)

    style = wizard.styleSheet()
    assert wizard.resolved_theme == "dark"
    assert "QWizard, QWizardPage" in style
    assert "background: #17191e" in style
    assert "QWizard QLabel { color: #f4f5f7; }" in style
    assert "QLabel#setupSteps" in style
    assert "color: #d9e2ff" in style
    assert "QFrame#setupStarterPackCard" in style
    assert "QLabel#setupStarterPackDescription" in style
    assert "color: #d3dbea" in style
    assert "QPushButton:default" in style
    assert "background-color: #17191e" in wizard.native_header_style


def test_first_run_setup_is_saved_and_reloads_hotkeys(tmp_path, monkeypatch):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    original = AppSettings(first_run_setup_completed=False)
    settings_ui_module.save_settings(paths.settings_file, original)
    events: list[str] = []

    class FakeWizard:
        def __init__(self, *args, **kwargs):
            self.start_with_windows = SimpleNamespace(
                isChecked=lambda: True
            )

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_hotkey(self):
            return "Ctrl+Shift+F8"

        def selected_starter_pack_ids(self):
            return ("email", "reports")

        def deleteLater(self):
            events.append("deleted")

    class Hotkeys:
        is_available = staticmethod(lambda _hotkey: True)

        def unregister_all(self):
            events.append("unregistered")

    monkeypatch.setattr(
        settings_ui_module,
        "FirstRunSetupWizard",
        FakeWizard,
    )
    app = object.__new__(PromptMeld)
    app.first_run_wizard = None
    app.settings = original
    app.paths = paths
    app.registry = SimpleNamespace(
        all=lambda: [WritingAction("edit", "Edit", (), "Edit.")]
    )
    app.hotkeys = Hotkeys()
    app.startup = SimpleNamespace(is_enabled=lambda: False)
    app._reload_configuration = lambda register_hotkeys: (
        setattr(app, "settings", load_settings(paths.settings_file)),
        events.append(f"reloaded:{register_hotkeys}"),
    )
    app._apply_startup_preference = lambda: events.append("startup")
    app._refresh_update_surfaces = lambda: events.append("updates")
    app.notify = lambda *args: events.append("notified")

    app.open_first_run_setup()

    saved = load_settings(paths.settings_file)
    assert saved.first_run_setup_completed is True
    assert saved.popup_hotkey == "Ctrl+Shift+F8"
    assert saved.startup_enabled is True
    assert {action.id for action in load_actions(paths.actions_file)} >= {
        "edit",
        "email-draft",
        "report-from-notes",
    }
    assert events == [
        "unregistered",
        "reloaded:True",
        "startup",
        "updates",
        "notified",
        "deleted",
    ]


def test_configuration_can_reopen_the_first_use_setup_guide(
    qtbot,
    tmp_path,
    monkeypatch,
):
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        hotkey_availability=lambda _hotkey: True,
    )
    qtbot.addWidget(dialog)

    class FakeWizard:
        def __init__(self, *args, **kwargs):
            self.start_with_windows = SimpleNamespace(
                isChecked=lambda: True
            )

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_hotkey(self):
            return "Ctrl+Shift+F8"

    monkeypatch.setattr(
        settings_ui_module,
        "FirstRunSetupWizard",
        FakeWizard,
    )

    dialog._open_setup_guide()

    assert dialog.popup_hotkey == "Ctrl+Shift+F8"
    assert dialog.launcher_hotkey_editor.text() == "Ctrl+Shift+F8"
    assert dialog.start_with_windows.isChecked() is True
    assert dialog.has_unsaved_changes() is True


def test_action_creation_wizard_builds_and_validates_an_action(qtbot, tmp_path):
    source = WritingAction(
        "new-action",
        "",
        (),
        "",
        icon="lucide:wand-sparkles",
        folder="Replies",
    )
    wizard = ActionCreationWizard(
        source,
        ActionIconProvider(tmp_path),
        folders=("Replies", "Editing"),
        used_hotkeys={"Ctrl+Alt+Space": "Open launcher"},
        hotkey_availability=lambda hotkey: hotkey != "Ctrl+Alt+9",
    )
    qtbot.addWidget(wizard)
    wizard.name.setText("Make diplomatic")
    wizard.instruction.setPlainText("Rewrite this with a tactful tone.")
    wizard.keywords.setText("polite, tactful")
    wizard.show_on_home.setChecked(True)
    wizard.guided_drafting.setChecked(True)
    wizard.natural_voice.setCurrentIndex(
        wizard.natural_voice.findData("always")
    )
    wizard.recipient_audience.setCurrentIndex(
        wizard.recipient_audience.findData("public_online")
    )
    wizard.purpose.setCurrentIndex(wizard.purpose.findData("analyse"))
    wizard.result_handling.setCurrentIndex(
        wizard.result_handling.findData("copy")
    )

    action = wizard.action("make-diplomatic")

    assert action.name == "Make diplomatic"
    assert action.instruction == "Rewrite this with a tactful tone."
    assert action.keywords == ("polite", "tactful")
    assert action.folder == "Replies"
    assert action.show_on_home is True
    assert action.guided_drafting is True
    assert action.natural_voice == "always"
    assert action.recipient_audience == "public_online"
    assert action.purpose == "analyse"
    assert action.result_handling == "copy"
    assert "explicitly overrides" in wizard.result_handling_help.text()

    wizard.sample_text.setPlainText("This example is difficult to read.")
    wizard._preview_action()
    preview = wizard.prompt_preview.toPlainText()
    assert "Rewrite this with a tactful tone." in preview
    assert "This example is difficult to read." in preview
    assert "<<<SOURCE>>>" in preview

    wizard.hotkey.set_hotkey("Alt+Ctrl+Space")
    wizard._test_hotkey()
    assert wizard.hotkey_is_available is False
    assert "Open launcher" in wizard.hotkey_status.text()

    wizard.hotkey.set_hotkey("Ctrl+Alt+9")
    wizard._test_hotkey()
    assert wizard.hotkey_is_available is False
    assert "Unavailable" in wizard.hotkey_status.text()

    wizard.hotkey.clear_hotkey()
    assert wizard.hotkey_is_available is True
    assert "No shortcut assigned" in wizard.hotkey_status.text()


def test_action_creation_wizard_is_readable_and_accessible_in_both_themes(
    qtbot,
    tmp_path,
):
    source = WritingAction(
        "reply",
        "Draft reply",
        ("reply",),
        "Write a useful reply to the selected text.",
    )

    for theme, background, foreground, field_background, subtitle in (
        ("light", "#f5f7fa", "#202631", "#ffffff", "#4b5563"),
        ("dark", "#17191e", "#f4f5f7", "#22252c", "#d2d7e0"),
    ):
        wizard = ActionCreationWizard(
            source,
            ActionIconProvider(tmp_path),
            mode="duplicate",
            theme=theme,
        )
        qtbot.addWidget(wizard)
        wizard.show()
        qtbot.wait(1)

        style = wizard.styleSheet()
        assert wizard.resolved_theme == theme
        assert "QWizard, QWizardPage" in style
        assert f"background: {background}" in style
        assert f"QWizard QLabel {{ color: {foreground}; }}" in style
        assert f"background: {field_background}" in style
        assert f"QLabel#qt_wizard_subtitle {{ color: {subtitle}; }}" in style
        assert wizard.palette().color(
            QPalette.ColorRole.WindowText
        ).name() == foreground
        assert wizard.accessibleName() == "Duplicate writing action"
        assert "Current step: Name the copy" in wizard.accessibleDescription()
        assert wizard.currentPage().accessibleName() == "Name the copy"
        assert wizard.folder.accessibleName() == "Writing action folder"
        assert wizard.instruction.accessibleName() == (
            "Writing action instruction"
        )
        assert f"background-color: {background}" in (
            wizard.native_header_style
        )
        wizard.close()


def test_action_creation_wizard_uses_windows_palette_in_high_contrast(
    qtbot,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        settings_ui_module,
        "system_high_contrast_enabled",
        lambda: True,
    )
    wizard = ActionCreationWizard(
        WritingAction("edit", "Edit", (), "Improve the selected text."),
        ActionIconProvider(tmp_path),
        theme="dark",
    )
    qtbot.addWidget(wizard)

    assert "color: palette(window-text)" in wizard.styleSheet()
    assert "background-color: palette(window)" in wizard.styleSheet()


def test_action_settings_add_and_duplicate_use_the_guided_wizard(
    qtbot,
    tmp_path,
    monkeypatch,
):
    original = WritingAction("edit", "Edit", (), "Improve this.")
    dialog = ActionSettingsDialog(
        [original],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    calls: list[tuple[str, str]] = []

    class AcceptedWizard:
        def __init__(self, source, mode):
            self.source = source
            self.mode = mode

        def exec(self):
            return QDialog.DialogCode.Accepted

        def action(self, action_id):
            calls.append((self.mode, action_id))
            return replace(
                self.source,
                id=action_id,
                name=(
                    "Created with wizard"
                    if self.mode == "create"
                    else self.source.name
                ),
                instruction="Wizard instruction.",
            )

    monkeypatch.setattr(
        dialog,
        "_action_wizard",
        lambda source, mode: AcceptedWizard(source, mode),
    )

    dialog._add_action()
    assert dialog.actions[-1].name == "Created with wizard"
    assert calls[0] == ("create", "new-action")

    dialog._refresh_list(0)
    dialog._duplicate_action()
    assert dialog.actions[1].name == "Edit copy"
    assert dialog.actions[1].hotkey is None
    assert calls[1] == ("duplicate", "edit-copy")


def test_action_settings_passes_selected_theme_to_action_wizard(
    qtbot,
    tmp_path,
):
    dialog = ActionSettingsDialog(
        [WritingAction("edit", "Edit", (), "Improve this.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(theme="dark"),
    )
    qtbot.addWidget(dialog)

    wizard = dialog._action_wizard(dialog.actions[0], "duplicate")
    qtbot.addWidget(wizard)

    assert wizard.theme == "dark"
    assert wizard.resolved_theme == "dark"


def test_action_settings_folder_delete_requires_confirmation_and_is_recursive(
    qtbot,
    tmp_path,
    monkeypatch,
):
    actions = [
        WritingAction(
            "reply",
            "Reply",
            (),
            "Write a reply.",
            folder="Replies",
        ),
        WritingAction(
            "customer-reply",
            "Customer reply",
            (),
            "Reply to the customer.",
            folder="Replies/Customer",
        ),
        WritingAction(
            "vip-reply",
            "VIP reply",
            (),
            "Reply to the VIP customer.",
            folder="Replies/Customer/VIP",
        ),
        WritingAction(
            "report",
            "Report",
            (),
            "Write a report.",
            folder="Reports",
        ),
    ]
    settings = AppSettings(
        folder_icons={
            "Replies": "lucide:messages-square",
            "Replies/Customer": "lucide:message-circle-reply",
            "Replies/Customer/VIP": "lucide:star",
            "Reports": "lucide:file-pen-line",
        }
    )
    dialog = ActionSettingsDialog(
        actions,
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        settings,
    )
    qtbot.addWidget(dialog)
    replies_folder = dialog.action_list.topLevelItem(0)
    assert replies_folder.data(0, dialog.ITEM_KIND_ROLE) == "folder"
    assert replies_folder.data(0, Qt.ItemDataRole.UserRole) == "Replies"
    dialog.action_list.setCurrentItem(replies_folder)

    assert dialog.delete_button.isEnabled() is True
    assert dialog.delete_button.text() == "Delete folder"
    assert "its writing actions" in dialog.delete_button.accessibleName()
    confirmations: list[tuple[str, int, int]] = []
    monkeypatch.setattr(
        dialog,
        "_confirm_delete_folder",
        lambda folder, action_count, nested_count: (
            confirmations.append((folder, action_count, nested_count))
            or False
        ),
    )

    dialog._delete_action()

    assert confirmations == [("Replies", 3, 2)]
    assert dialog.actions == actions
    assert dialog.folder_icons == settings.folder_icons
    assert dialog.has_unsaved_changes() is False

    monkeypatch.setattr(
        dialog,
        "_confirm_delete_folder",
        lambda *_args: True,
    )
    dialog._delete_action()

    assert [action.id for action in dialog.actions] == ["report"]
    assert dialog.folder_icons == {
        "Reports": "lucide:file-pen-line",
    }
    assert dialog.selected_folder == "Reports"
    assert dialog.has_unsaved_changes() is True
    assert [
        dialog.folder_combo.itemText(index)
        for index in range(dialog.folder_combo.count())
    ] == ["", "Reports"]


def test_folder_delete_confirmation_reports_counts_and_is_accessible(
    qtbot,
    tmp_path,
):
    dialog = ActionSettingsDialog(
        [
            WritingAction(
                "reply",
                "Reply",
                (),
                "Write a reply.",
                folder="Replies",
            )
        ],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(theme="light"),
    )
    qtbot.addWidget(dialog)

    message = dialog._folder_delete_confirmation_message(
        "Replies",
        3,
        2,
    )
    qtbot.addWidget(message)

    assert message.windowTitle() == "Delete writing action folder?"
    assert '"Replies"' in message.text()
    assert "3 writing actions" in message.informativeText()
    assert "2 nested folders" in message.informativeText()
    assert message.accessibleName() == (
        "Confirm writing action folder deletion"
    )
    assert message.delete_folder_button.text() == (
        "Delete folder and actions"
    )
    assert message.defaultButton().text() == "Cancel"
    assert "#ffffff" in message.styleSheet()


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

    assert [action.id for action in dialog.actions] == [
        "edit-improve",
        "proofread",
        "shorten",
        "draft-reply",
    ]
    assert all(action.folder == "Essentials" for action in dialog.actions)
    assert dialog.actions[-1].guided_drafting is True


def test_action_settings_opens_catalogue_and_adds_builtin_pack_once(
    qtbot,
    tmp_path,
    monkeypatch,
):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

    assert [pack.pack_id for pack in dialog.builtin_action_packs] == [
        "editing",
        "customer-relations",
        "email",
        "tone-voice",
        "complaints",
        "reports",
        "social-posts",
        "social-replies",
        "social-editing",
        "reviews-feedback",
        "meetings",
        "technical-communication",
        "learning",
        "career-writing",
        "replies-arguments",
        "argument-editing",
        "summaries-extraction",
        "draft-from-selection",
        "decisions-planning",
        "authors-fiction",
        "authors-nonfiction",
    ]
    assert dialog.starter_pack_button.text() == "Browse starter packs…"
    assert dialog.starter_pack_button.menu() is None
    reports = next(
        pack for pack in dialog.builtin_action_packs if pack.pack_id == "reports"
    )

    catalogue = StarterPackCatalogueDialog(
        dialog.builtin_action_packs,
        dialog.actions,
        dialog.icon_provider,
        theme="light",
    )
    qtbot.addWidget(catalogue)
    catalogue.search.setText("Reports and updates")
    assert catalogue.pack_list.count() == 1
    assert catalogue.selected_pack_id() == "reports"
    assert len(catalogue.action_rows) == 4
    assert catalogue.action_rows[0].instruction_label.text() == (
        reports.actions[0].instruction
    )
    requested = QSignalSpy(catalogue.operation_requested)
    catalogue.primary_button.click()
    assert requested.at(0) == ["reports", "add"]

    dialog._add_builtin_action_pack(reports)

    assert len(dialog.actions) == 5
    assert dialog.actions[1].id == "report-from-notes"
    assert dialog.actions[1].folder == "Draft & create/Reports"
    assert dialog.folder_icons["Draft & create"] == "lucide:file-pen-line"
    assert dialog.folder_icons["Draft & create/Reports"] == (
        "lucide:list-checks"
    )
    assert dialog.has_unsaved_changes() is True
    catalogue.set_actions(dialog.actions)
    assert "Installed" in catalogue.pack_status.text()
    assert catalogue.primary_button.isHidden() is True
    assert [
        action.text()
        for action in catalogue.more_menu.actions()
        if not action.isSeparator()
    ] == ["Remove pack"]

    dialog._add_builtin_action_pack(reports)

    assert len(dialog.actions) == 5


def test_launcher_catalogue_is_add_only_and_non_modal(qtbot, tmp_path):
    packs = load_builtin_action_packs()
    installed = list(packs[0].actions)
    dialog = StarterPackCatalogueDialog(
        packs,
        installed,
        ActionIconProvider(tmp_path),
        add_only=True,
    )
    qtbot.addWidget(dialog)
    dialog.setModal(False)
    dialog.refresh(packs[0].pack_id)

    assert dialog.isModal() is False
    assert dialog.primary_button.isHidden() is True
    assert dialog.more_button.isHidden() is True

    dialog.refresh(packs[1].pack_id)

    assert dialog.primary_button.text() == "Add pack"
    assert dialog.primary_button.isHidden() is False
    assert dialog.more_button.isHidden() is True


def test_launcher_catalogue_adds_pack_immediately(qtbot, tmp_path, monkeypatch):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    original = [WritingAction("one", "One", (), "First.")]
    settings_ui_module.save_actions(paths.actions_file, original)
    settings_ui_module.save_settings(paths.settings_file, AppSettings())
    app = PromptMeld.__new__(PromptMeld)
    app.paths = paths
    app.actions = original
    app.settings = AppSettings()
    refreshed: list[bool] = []

    def reload_configuration():
        app.actions = load_actions(paths.actions_file)
        app.settings = load_settings(paths.settings_file)
        refreshed.append(True)

    app.reload_configuration_after_save = reload_configuration
    catalogue_actions: list[list[WritingAction]] = []
    catalogue = SimpleNamespace(
        set_actions=lambda actions: catalogue_actions.append(list(actions))
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

    app._starter_pack_operation(catalogue, "reports", "add")

    assert refreshed == [True]
    assert len(app.actions) == 5
    assert app.actions[1].id == "report-from-notes"
    assert catalogue_actions[-1] == app.actions
    assert app.settings.folder_icons["Draft & create/Reports"] == (
        "lucide:list-checks"
    )


def test_starter_pack_catalogue_filters_and_reports_status(
    qtbot,
    tmp_path,
):
    packs = load_builtin_action_packs()
    dialog = StarterPackCatalogueDialog(
        packs,
        [],
        ActionIconProvider(tmp_path),
        theme="dark",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.pack_list.minimumWidth() == 190
    assert dialog.pack_list.maximumWidth() == 250
    assert 190 <= dialog.splitter.sizes()[0] <= 250
    assert dialog.action_scroll.horizontalScrollBar().maximum() == 0
    dialog.category.setCurrentText("Review or develop")
    assert dialog.pack_list.count() == 2
    assert {
        dialog.pack_list.item(row).data(dialog.PACK_ID_ROLE)
        for row in range(dialog.pack_list.count())
    } == {"authors-fiction", "authors-nonfiction"}

    dialog.category.setCurrentIndex(0)
    dialog.search.setText("beta reader")
    assert dialog.pack_list.count() == 1
    assert dialog.selected_pack_id() == "authors-fiction"
    assert dialog.pack_status.text().endswith("Not installed")
    assert dialog.primary_button.text() == "Add pack"
    assert dialog.primary_button.isHidden() is False
    assert dialog.more_button.isHidden() is True
    assert len(dialog.action_rows) == 4
    fiction = dialog.selected_pack()
    assert fiction is not None
    assert dialog.action_rows[0].name_label.text() == fiction.actions[0].name
    assert dialog.action_rows[0].instruction_label.text() == (
        fiction.actions[0].instruction
    )
    assert dialog.action_rows[0].instruction_label.wordWrap() is True
    assert dialog.action_rows[0].status_label == "Not in your library"
    assert dialog.action_rows[0].status_icon.accessibleName() == (
        "Library status: Not in your library"
    )
    assert dialog.pack_list_rows["authors-fiction"].name_label.wordWrap() is True
    assert "<br>" in dialog.pack_list.currentItem().toolTip()
    wrapped = settings_ui_module._wrapped_catalogue_tooltip(
        "This intentionally long tooltip demonstrates that catalogue help "
        "is split into readable lines instead of becoming one long strip."
    )
    assert all(len(line) <= 55 for line in wrapped[4:-5].split("<br>"))

    dialog.set_actions([fiction.actions[0]])
    assert "Partially installed" in dialog.pack_status.text()
    assert dialog.primary_button.text() == "Add missing actions"
    assert [
        action.text()
        for action in dialog.more_menu.actions()
        if not action.isSeparator()
    ] == [
        "Update from catalogue",
        "Restore shipped version",
        "Remove pack",
    ]
    requested = QSignalSpy(dialog.operation_requested)
    update_action = next(
        action
        for action in dialog.more_menu.actions()
        if action.data() == "update"
    )
    update_action.trigger()
    assert requested.at(0) == ["authors-fiction", "update"]

    dialog.set_actions(list(fiction.actions))
    assert dialog.pack_status.text().endswith("Installed")
    assert dialog.primary_button.isHidden() is True
    assert dialog.more_button.isHidden() is False


def test_starter_pack_catalogue_update_restore_and_remove_lifecycle(
    qtbot,
    tmp_path,
    monkeypatch,
):
    dialog = ActionSettingsDialog(
        [WritingAction("mine", "Mine", (), "Keep me.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    catalogue = StarterPackCatalogueDialog(
        dialog.builtin_action_packs,
        dialog.actions,
        dialog.icon_provider,
        theme="light",
    )
    qtbot.addWidget(catalogue)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    pack = next(
        item for item in dialog.builtin_action_packs if item.pack_id == "reports"
    )
    catalogue.refresh(pack.pack_id)

    dialog._catalogue_pack_operation(catalogue, pack.pack_id, "add")
    installed = next(
        action for action in dialog.actions if action.id == pack.actions[0].id
    )
    index = dialog.actions.index(installed)
    dialog.actions[index] = replace(
        installed,
        instruction="A locally changed instruction.",
        folder="My reports",
        hotkey="Ctrl+Alt+8",
    )
    dialog._refresh_list(index)
    catalogue.set_actions(dialog.actions)
    assert "Content differs from catalogue" in catalogue.pack_status.text()
    assert catalogue.primary_button.text() == "Update from catalogue"

    dialog._catalogue_pack_operation(catalogue, pack.pack_id, "update")
    updated = next(
        action for action in dialog.actions if action.id == pack.actions[0].id
    )
    assert updated.instruction == pack.actions[0].instruction
    assert updated.folder == "My reports"
    assert updated.hotkey == "Ctrl+Alt+8"

    dialog._catalogue_pack_operation(catalogue, pack.pack_id, "restore")
    restored = next(
        action for action in dialog.actions if action.id == pack.actions[0].id
    )
    assert restored == pack.actions[0]

    dialog._catalogue_pack_operation(catalogue, pack.pack_id, "remove")
    assert [action.id for action in dialog.actions] == ["mine"]
    assert "Not installed" in catalogue.pack_status.text()


def test_action_settings_imports_and_exports_readable_action_packs(
    qtbot,
    tmp_path,
    monkeypatch,
):
    imported_path = tmp_path / "import.json"
    exported_path = tmp_path / "export.json"
    save_action_pack(
        imported_path,
        ActionPack(
            "Imported tools",
            "A test pack.",
            (WritingAction("imported", "Imported", (), "Transform this."),),
        ),
    )
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(imported_path), ""),
    )

    dialog._import_action_pack()

    assert [action.id for action in dialog.actions] == ["one", "imported"]

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(exported_path), ""),
    )
    dialog._export_action_pack(selected_only=False)

    exported = load_action_pack(exported_path)
    assert [action.id for action in exported.actions] == ["one", "imported"]


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
    editor.title_subject.setCurrentIndex(
        editor.title_subject.findData("subject")
    )
    editor.auto_submit.setCurrentIndex(editor.auto_submit.findData("on"))
    editor.privacy_preview.setCurrentIndex(
        editor.privacy_preview.findData("off")
    )
    editor.return_mode.setCurrentIndex(
        editor.return_mode.findData("review")
    )
    editor.response_wait.setCurrentIndex(
        editor.response_wait.findData("indefinite")
    )
    editor.project_name.setText("Email writing")

    profile = editor.profile()

    assert profile.recipient_audience == "customer_client"
    assert profile.resulting_text_length == "short"
    assert profile.title_subject == "subject"
    assert profile.auto_submit == "on"
    assert profile.privacy_preview == "off"
    assert profile.return_mode == "review"
    assert profile.response_wait == "indefinite"
    assert profile.project_name == "Email writing"
    assert "ChatGPT may take seconds or several minutes" in (
        editor.response_wait_help.accessibleDescription()
    )
    assert "width='340'" in editor.response_wait_help.toolTip()


def test_configuration_saves_privacy_preview_default(qtbot, tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(privacy_preview_enabled=True),
    )
    qtbot.addWidget(dialog)

    dialog.privacy_preview_default.setChecked(False)

    assert dialog._save() is True
    assert load_settings(paths.settings_file).privacy_preview_enabled is False


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


def test_backup_and_restore_buttons_are_together(qtbot, tmp_path):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
    )
    qtbot.addWidget(dialog)

    assert dialog.create_backup_button.parent() is (
        dialog.restore_backup_button.parent()
    )
    assert dialog.backup_actions_layout.indexOf(
        dialog.create_backup_button
    ) == 0
    assert dialog.backup_actions_layout.indexOf(
        dialog.restore_backup_button
    ) == 1


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
            format_version=1,
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


def test_configuration_reset_confirms_resets_and_closes(
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
    safety = tmp_path / "PromptMeld-pre-reset.zip"
    resets = []
    monkeypatch.setattr(
        dialog,
        "_confirm_configuration_reset",
        lambda: True,
    )
    monkeypatch.setattr(
        settings_ui_module,
        "reset_configuration_to_defaults",
        lambda supplied_paths: (
            resets.append(supplied_paths)
            or SimpleNamespace(safety_backup=safety)
        ),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    reset_signal = QSignalSpy(dialog.configuration_reset)

    qtbot.mouseClick(
        dialog.reset_configuration_button,
        Qt.MouseButton.LeftButton,
    )

    assert resets == [paths]
    assert reset_signal.count() == 1
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_configuration_reset_confirmation_is_readable_in_both_themes(
    qtbot,
    tmp_path,
):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text("{}", encoding="utf-8")
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        paths,
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(theme="light"),
    )
    qtbot.addWidget(dialog)

    for theme, expected_body, expected_reset in (
        ("light", "#344052", "#a32626"),
        ("dark", "#e1e5ee", "#a32626"),
    ):
        dialog.theme.setCurrentIndex(dialog.theme.findData(theme))
        message = dialog._configuration_reset_message()
        qtbot.addWidget(message)
        stylesheet = message.styleSheet()
        assert expected_body in stylesheet
        assert expected_reset in stylesheet
        assert message.minimumWidth() >= 560
        assert message.reset_button.objectName() == "resetConfigurationButton"
        message.close()


def test_all_message_box_types_are_readable_in_both_themes(
    qtbot,
    tmp_path,
):
    dialog = ActionSettingsDialog(
        [WritingAction("one", "One", (), "First.")],
        AppPaths.discover(tmp_path),
        ActionIconProvider(tmp_path),
        "Ctrl+Alt+Space",
        AppSettings(theme="light"),
    )
    qtbot.addWidget(dialog)
    app = QApplication.instance()
    original_stylesheet = app.styleSheet()
    try:
        for theme, expected_background, expected_text, expected_detail in (
            ("light", "#ffffff", "#111827", "#344052"),
            ("dark", "#17191e", "#ffffff", "#e1e5ee"),
        ):
            dialog.theme.setCurrentIndex(dialog.theme.findData(theme))
            for icon in (
                QMessageBox.Icon.Information,
                QMessageBox.Icon.Warning,
                QMessageBox.Icon.Critical,
                QMessageBox.Icon.Question,
            ):
                message = QMessageBox(dialog)
                qtbot.addWidget(message)
                message.setIcon(icon)
                message.setText("Add the Reports starter pack?")
                message.setInformativeText(
                    "The pack description and confirmation must remain readable."
                )
                message.setStandardButtons(
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                )
                message.show()
                qtbot.wait(1)

                body = message.findChild(QLabel, "qt_msgbox_label")
                detail = message.findChild(
                    QLabel,
                    "qt_msgbox_informativelabel",
                )
                assert message.palette().color(
                    message.backgroundRole()
                ).name() == expected_background
                assert body.palette().color(
                    body.foregroundRole()
                ).name() == expected_text
                assert detail.palette().color(
                    detail.foregroundRole()
                ).name() == expected_detail
                assert all(
                    button.palette().color(button.foregroundRole()).name()
                    == "#ffffff"
                    for button in message.buttons()
                )
                message.close()
    finally:
        app.setStyleSheet(original_stylesheet)


def test_launcher_owned_confirmations_keep_readable_dialog_colours(
    qtbot,
    tmp_path,
):
    registry = ActionRegistry(
        [WritingAction("one", "One", (), "First.")],
        UsageTracker(tmp_path / "usage.json"),
    )
    for theme, background, foreground in (
        ("light", "#ffffff", "#111827"),
        ("dark", "#17191e", "#ffffff"),
    ):
        popup = LauncherPopup(registry, theme=theme)
        qtbot.addWidget(popup)
        message = QMessageBox(popup)
        qtbot.addWidget(message)
        message.setIcon(QMessageBox.Icon.Question)
        message.setText("Submit this request?")
        message.setStandardButtons(
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel
        )
        message.show()
        qtbot.wait(1)

        body = message.findChild(QLabel, "qt_msgbox_label")
        assert message.palette().color(
            message.backgroundRole()
        ).name() == background
        assert body.palette().color(body.foregroundRole()).name() == foreground
        message.close()
