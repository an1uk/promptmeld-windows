from __future__ import annotations

import threading

from promptmeld import app as app_module
from promptmeld.app import PromptMeld
from promptmeld.models import (
    AppSettings,
    ApplicationProfile,
    CapturedSelection,
    SubmissionResult,
)
from promptmeld.paths import AppPaths
from promptmeld.privacy import RedactionResult
from promptmeld.returning import ReturnDecision
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


class FakeProgress:
    def __init__(self):
        self.copied = False
        self.applied = False

    def mark_result_copied(self):
        self.copied = True

    def mark_result_applied(self):
        self.applied = True

    def update_stage(self, stage, message):
        pass


def completion_app() -> PromptMeld:
    app = object.__new__(PromptMeld)
    app.pending_result_text = ""
    app.pending_result_selection = None
    app.pending_result_applied = False
    app.preserved_original = None
    app.last_replacement = None
    app.copy_result_action = FakeAction()
    app.apply_result_action = FakeAction()
    app.undo_replacement_action = FakeAction()
    app.copy_original_action = FakeAction()
    app.automation_progress = FakeProgress()
    app.notifications = []
    app.notify = lambda *args: app.notifications.append(args)
    return app


def test_completed_result_enables_direct_copy_and_apply(monkeypatch):
    selection = CapturedSelection(
        "Original text",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app = completion_app()
    clipboard = []
    replacements = []
    monkeypatch.setattr(app_module, "write_clipboard_text", clipboard.append)
    monkeypatch.setattr(
        app_module,
        "replace_source_selection",
        lambda *args: replacements.append(args),
    )

    can_apply = app._remember_completed_result(
        SubmissionResult(
            submitted=True,
            generated_text="Generated answer",
        ),
        selection,
    )

    assert can_apply is True
    assert app.copy_result_action.enabled is True
    assert app.apply_result_action.enabled is True
    app.copy_latest_result()
    assert clipboard == ["Generated answer"]
    assert app.automation_progress.copied is True

    app.apply_latest_result()
    assert replacements == [
        (123, "Original text", "Generated answer", "winword.exe")
    ]
    assert app.pending_result_applied is True
    assert app.apply_result_action.enabled is False
    assert app.undo_replacement_action.enabled is True
    assert app.automation_progress.applied is True


def test_apply_now_falls_back_to_copy_when_selection_is_not_safe(monkeypatch):
    selection = CapturedSelection(
        "Original text",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app = completion_app()
    app._remember_completed_result(
        SubmissionResult(
            submitted=True,
            generated_text="Generated answer",
        ),
        selection,
    )
    clipboard = []
    monkeypatch.setattr(
        app_module,
        "replace_source_selection",
        lambda *args: (_ for _ in ()).throw(
            SourceRecoveryError("The original selection changed.")
        ),
    )
    monkeypatch.setattr(app_module, "write_clipboard_text", clipboard.append)

    app.apply_latest_result()

    assert clipboard == ["Generated answer"]
    assert app.pending_result_applied is False
    assert app.notifications[-1][0] == "Result could not be applied safely"


def test_multiple_alternatives_open_the_review_with_the_first_selected():
    selection = CapturedSelection(
        "Original text",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app = completion_app()
    app.result_review = None
    reviews = []
    app._show_result_review = lambda alternatives, **options: reviews.append(
        (alternatives, options)
    )
    response = """
<<<PROMPTMELD_ALTERNATIVE_1>>>
First version.
<<<END_PROMPTMELD_ALTERNATIVE_1>>>
<<<PROMPTMELD_ALTERNATIVE_2>>>
Second version.
<<<END_PROMPTMELD_ALTERNATIVE_2>>>
"""

    app._submission_finished(
        SubmissionResult(submitted=True, generated_text=response),
        selection=selection,
        alternative_count=2,
    )

    assert reviews == [
        (
            ["First version.", "Second version."],
            {"requested_count": 2, "can_apply": True},
        )
    ]
    assert app.pending_result_text == "First version."
    assert app.copy_result_action.enabled is True
    assert app.apply_result_action.enabled is True
    assert app.notifications[-1][0] == "Alternatives ready"


def test_review_completion_notifies_with_copy_and_apply_actions():
    app = completion_app()
    selection = CapturedSelection(
        "Original text",
        123,
        "Private title",
        True,
        "chrome.exe",
    )

    app._submission_finished(
        SubmissionResult(
            submitted=True,
            generated_text="Generated answer",
        ),
        selection=selection,
        return_decision=ReturnDecision(review_result=True),
    )

    assert app.notifications[-1][0] == "Response ready"
    assert app.copy_result_action.enabled is True
    assert app.apply_result_action.enabled is True


def test_review_choice_becomes_the_result_used_by_tray_actions(monkeypatch):
    app = completion_app()
    clipboard = []
    app._remember_completed_result(
        SubmissionResult(submitted=True, generated_text="First version"),
        None,
    )
    monkeypatch.setattr(app_module, "write_clipboard_text", clipboard.append)

    app._select_completed_result("Second version")
    app.copy_latest_result()

    assert clipboard == ["Second version"]


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


def test_submission_uses_explicitly_approved_redacted_prompt(
    monkeypatch,
):
    app = object.__new__(PromptMeld)
    app.automation_worker = None
    app.settings = AppSettings(
        auto_submit_enabled=True,
        copy_generated_text_enabled=True,
    )
    app.current_selection = CapturedSelection(
        "Email jane@example.com",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app.popup = None
    app.cancel_automation_action = FakeAction()
    app.notify = lambda *args: None
    app._show_automation_progress = lambda *args, **kwargs: FakeProgress()
    app._review_prompt_privacy = lambda prompt: RedactionResult(
        "Email [EMAIL_1]",
        {"[EMAIL_1]": "jane@example.com"},
    )

    class ThreadPool:
        def __init__(self):
            self.worker = None

        def start(self, worker):
            self.worker = worker

    app.thread_pool = ThreadPool()
    calls = []
    monkeypatch.setattr(
        app_module,
        "submit_via_worker",
        lambda prompt, project, settings, **options: calls.append(
            (prompt, options)
        )
        or SubmissionResult(submitted=True),
    )

    app._submit_prompt("Email jane@example.com")
    app.thread_pool.worker.function(lambda *args: None)

    prompt, options = calls[0]
    assert prompt.startswith("Email [EMAIL_1]")
    assert "Preserve every placeholder exactly" in prompt
    assert options["redaction_replacements"] == {
        "[EMAIL_1]": "jane@example.com"
    }


def test_submission_skips_privacy_preview_when_disabled_for_application(
    monkeypatch,
):
    app = object.__new__(PromptMeld)
    app.automation_worker = None
    app.settings = AppSettings(
        auto_submit_enabled=True,
        application_profiles={
            "winword.exe": ApplicationProfile(privacy_preview="off")
        },
    )
    app.current_selection = CapturedSelection(
        "Email jane@example.com",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app.popup = None
    app.cancel_automation_action = FakeAction()
    app.notify = lambda *args: None
    app._show_automation_progress = lambda *args, **kwargs: FakeProgress()
    app._review_prompt_privacy = lambda _prompt: (_ for _ in ()).throw(
        AssertionError("privacy preview should be skipped")
    )

    class ThreadPool:
        def __init__(self):
            self.worker = None

        def start(self, worker):
            self.worker = worker

    app.thread_pool = ThreadPool()
    calls = []
    monkeypatch.setattr(
        app_module,
        "submit_via_worker",
        lambda prompt, project, settings, **options: calls.append(
            (prompt, options)
        )
        or SubmissionResult(submitted=True),
    )

    app._submit_prompt("Email jane@example.com")
    app.thread_pool.worker.function(lambda *args: None)

    prompt, options = calls[0]
    assert prompt == "Email jane@example.com"
    assert options["redaction_replacements"] == {}


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
