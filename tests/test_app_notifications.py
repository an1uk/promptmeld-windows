from __future__ import annotations

import threading

from promptmeld import app as app_module
from promptmeld.app import PromptMeld
from promptmeld.models import (
    AppSettings,
    CapturedSelection,
    SubmissionResult,
)
from promptmeld.paths import AppPaths
from promptmeld.windows import SourceRecoveryError


def _notifications_for(result: SubmissionResult) -> list[tuple[object, ...]]:
    app = object.__new__(PromptMeld)
    notifications: list[tuple[object, ...]] = []
    app.notify = lambda *args: notifications.append(args)
    app._submission_finished(result)
    return notifications


def test_successful_automatic_submission_is_silent():
    assert _notifications_for(SubmissionResult(submitted=True)) == []


def test_unsent_prompt_notifies_user_to_complete_submission():
    result = SubmissionResult(
        submitted=False,
        prepared=True,
        message="Choose a model or reasoning level, then press Enter.",
    )

    notifications = _notifications_for(result)

    assert notifications[0][0] == "Prompt ready in ChatGPT"
    assert notifications[0][1] == result.message


def test_failed_submission_notifies_user_to_take_action():
    result = SubmissionResult(
        submitted=False,
        fallback_copied=True,
        message="The complete prompt has been copied to the clipboard.",
    )

    notifications = _notifications_for(result)

    assert notifications[0][0] == "ChatGPT needs attention"
    assert notifications[0][1] == result.message


def test_failed_generated_output_notifies_user_that_text_was_not_replaced():
    result = SubmissionResult(
        submitted=True,
        output_failed=True,
        message="The original text was not replaced.",
    )

    notifications = _notifications_for(result)

    assert notifications[0][0] == "Generated text needs attention"
    assert notifications[0][1] == result.message


class FakeAction:
    def __init__(self):
        self.enabled = False
        self.text = ""

    def setEnabled(self, enabled):
        self.enabled = enabled

    def setText(self, text):
        self.text = text


def recovery_app(selection: CapturedSelection) -> PromptMeld:
    app = object.__new__(PromptMeld)
    app.last_replacement = selection
    app.preserved_original = selection
    app.undo_replacement_action = FakeAction()
    app.copy_original_action = FakeAction()
    app.notify = lambda *args: None
    return app


def test_successful_replacement_enables_native_undo(monkeypatch):
    selection = CapturedSelection(
        "Original text",
        123,
        "Private document title",
        True,
        "winword.exe",
    )
    app = recovery_app(selection)
    calls = []
    monkeypatch.setattr(
        app_module,
        "undo_source_replacement",
        lambda hwnd: calls.append(hwnd),
    )

    app.undo_last_replacement()

    assert calls == [123]
    assert app.last_replacement is None
    assert app.undo_replacement_action.enabled is False
    assert app.copy_original_action.enabled is True


def test_failed_native_undo_copies_preserved_original(monkeypatch):
    selection = CapturedSelection(
        "Private original",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app = recovery_app(selection)
    clipboard = []
    monkeypatch.setattr(
        app_module,
        "undo_source_replacement",
        lambda hwnd: (_ for _ in ()).throw(
            SourceRecoveryError("window closed")
        ),
    )
    monkeypatch.setattr(app_module, "write_clipboard_text", clipboard.append)

    app.undo_last_replacement()

    assert clipboard == ["Private original"]


def test_failed_native_undo_handles_clipboard_recovery_failure(monkeypatch):
    selection = CapturedSelection(
        "Private original",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app = recovery_app(selection)
    notifications = []
    app.notify = lambda *args: notifications.append(args)
    monkeypatch.setattr(
        app_module,
        "undo_source_replacement",
        lambda hwnd: (_ for _ in ()).throw(
            SourceRecoveryError("window closed")
        ),
    )
    monkeypatch.setattr(
        app_module,
        "write_clipboard_text",
        lambda text: (_ for _ in ()).throw(RuntimeError("clipboard busy")),
    )

    app.undo_last_replacement()

    assert notifications[0][0] == (
        "Undo and clipboard recovery were unavailable"
    )


def test_cancel_automation_sets_event_and_disables_tray_action():
    app = object.__new__(PromptMeld)
    app.automation_cancel_event = threading.Event()
    app.cancel_automation_action = FakeAction()

    app.cancel_automation()

    assert app.automation_cancel_event.is_set() is True
    assert app.cancel_automation_action.enabled is False
    assert app.cancel_automation_action.text == "Cancelling automation..."


def test_diagnostics_exclude_selected_text_and_window_title(tmp_path):
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(auto_submit_enabled=True)
    app.paths = AppPaths.discover(tmp_path)
    app.current_selection = CapturedSelection(
        "Highly private selected text",
        123,
        "Confidential document title",
        True,
        "winword.exe",
    )
    app.last_automation_result = SubmissionResult(
        submitted=True,
        selection_replaced=True,
    )

    diagnostics = app._diagnostics_text()

    assert "winword.exe" in diagnostics
    assert "Highly private" not in diagnostics
    assert "Confidential document" not in diagnostics
