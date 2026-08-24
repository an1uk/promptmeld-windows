from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QPlainTextEdit

from promptmeld import app as app_module
from promptmeld import windows as windows_module
from promptmeld.app import PromptMeld
from promptmeld.automation_protocol import (
    ApplyVerification,
    AutomationCheckpoint,
    RecoveryAction,
    SubmissionDisposition,
)
from promptmeld.automation_recovery import PendingAutomationRecord
from promptmeld.models import (
    ApplyReceipt,
    AppSettings,
    ApplicationProfile,
    CapturedSelection,
    SourceFingerprint,
    SubmissionResult,
    WritingAction,
)
from promptmeld.paths import AppPaths
from promptmeld.privacy import RedactionResult
from promptmeld.returning import ReturnDecision
from promptmeld.windows import SourceRecoveryError


def verified_selection(
    text: str = "Original text",
    *,
    source_app: str = "winword.exe",
) -> CapturedSelection:
    return CapturedSelection(
        text,
        123,
        "Private title",
        True,
        source_app,
        SourceFingerprint(
            process_id=456,
            process_started=789,
            top_level_hwnd=123,
            top_level_class="SourceWindow",
            focused_hwnd=124,
            focused_class="RichEditD2DPT",
            adapter_id="win32-edit-v1",
            selection_start=0,
            selection_end=len(text),
        ),
    )


def apply_receipt(
    selection: CapturedSelection,
    generated_text: str,
) -> ApplyReceipt:
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    return ApplyReceipt(
        adapter_id="win32-edit-v1",
        source_fingerprint=fingerprint,
        original_text=selection.text,
        generated_text=generated_text,
        replacement_start=0,
        replacement_end=len(generated_text),
    )


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
    app.pending_result_can_apply = False
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
    selection = verified_selection()
    app = completion_app()
    clipboard = []
    replacements = []
    monkeypatch.setattr(app_module, "write_clipboard_text", clipboard.append)
    monkeypatch.setattr(
        app_module,
        "apply_verified_source_selection",
        lambda captured, generated: replacements.append((captured, generated))
        or apply_receipt(captured, generated),
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
        (selection, "Generated answer")
    ]
    assert app.pending_result_applied is True
    assert app.apply_result_action.enabled is False
    assert app.undo_replacement_action.enabled is True
    assert app.automation_progress.applied is True


def test_apply_now_falls_back_to_copy_when_selection_is_not_safe(monkeypatch):
    selection = verified_selection()
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
        "apply_verified_source_selection",
        lambda *args: (_ for _ in ()).throw(
            SourceRecoveryError("The original selection changed.")
        ),
    )
    monkeypatch.setattr(app_module, "write_clipboard_text", clipboard.append)

    app.apply_latest_result()

    assert clipboard == ["Generated answer"]
    assert app.pending_result_applied is False
    assert app.notifications[-1][0] == "Result could not be applied safely"


def test_automatic_apply_occurs_only_in_main_process_after_readback(
    monkeypatch,
):
    selection = verified_selection()
    app = completion_app()
    calls = []
    receipt = apply_receipt(selection, "Generated answer")
    monkeypatch.setattr(
        app_module,
        "automatic_source_return_is_allowed",
        lambda captured, chatgpt_hwnd: True,
    )
    monkeypatch.setattr(
        app_module,
        "apply_verified_source_selection",
        lambda captured, generated: calls.append((captured, generated)) or receipt,
    )

    result = app._apply_automatic_result_if_safe(
        SubmissionResult(
            submitted=True,
            generated_text="Generated answer",
            chatgpt_hwnd=500,
        ),
        selection,
        ReturnDecision(replace_selection=True),
        1,
    )

    assert calls == [(selection, "Generated answer")]
    assert result.selection_replaced is True
    assert result.apply_verification == ApplyVerification.VERIFIED
    assert app.last_replacement == receipt


def test_unsupported_source_retains_result_without_claiming_apply(monkeypatch):
    selection = CapturedSelection(
        "Original text",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app = completion_app()
    monkeypatch.setattr(
        app_module,
        "apply_verified_source_selection",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("unsupported adapter must not be dispatched")
        ),
    )

    result = app._apply_automatic_result_if_safe(
        SubmissionResult(submitted=True, generated_text="Generated answer"),
        selection,
        ReturnDecision(replace_selection=True),
        1,
    )

    assert result.selection_replaced is False
    assert result.apply_verification == ApplyVerification.UNSUPPORTED
    assert RecoveryAction.COPY_RESULT in result.recovery_actions
    assert result.generated_text == "Generated answer"


def test_automatic_apply_failure_retains_response_for_copy(monkeypatch):
    selection = verified_selection()
    app = completion_app()
    monkeypatch.setattr(
        app_module,
        "automatic_source_return_is_allowed",
        lambda captured, chatgpt_hwnd: True,
    )
    monkeypatch.setattr(
        app_module,
        "apply_verified_source_selection",
        lambda *args: (_ for _ in ()).throw(
            SourceRecoveryError("post-paste readback mismatch")
        ),
    )

    result = app._apply_automatic_result_if_safe(
        SubmissionResult(submitted=True, generated_text="Generated answer"),
        selection,
        ReturnDecision(replace_selection=True),
        1,
    )

    assert result.selection_replaced is False
    assert result.output_failed is True
    assert result.apply_verification == ApplyVerification.FAILED
    assert result.generated_text == "Generated answer"
    assert result.recovery_actions == (
        RecoveryAction.COPY_RESULT,
        RecoveryAction.COPY_ORIGINAL,
    )
    assert app.preserved_original == selection


def test_multiple_alternatives_open_the_review_with_the_first_selected():
    selection = verified_selection()
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
            {
                "requested_count": 2,
                "can_apply": True,
                    "action_purpose": "",
                    "safe_review": False,
                    "source_text": "Original text",
            },
        )
    ]
    assert app.pending_result_text == "First version."
    assert app.copy_result_action.enabled is True
    assert app.apply_result_action.enabled is True
    assert app.notifications[-1][0] == "Alternatives ready"


def test_review_completion_notifies_with_copy_and_apply_actions():
    app = completion_app()
    reviews = []
    app._show_result_review = lambda results, **options: reviews.append(
        (results, options)
    )
    selection = verified_selection(source_app="chrome.exe")

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
    assert reviews[0][0] == ["Generated answer"]


def test_safe_analysis_completion_cannot_apply_over_original_selection():
    app = completion_app()
    reviews = []
    app._show_result_review = lambda results, **options: reviews.append(
        (results, options)
    )
    selection = CapturedSelection(
        "Original text",
        123,
        "Private title",
        True,
        "winword.exe",
    )

    app._submission_finished(
        SubmissionResult(
            submitted=True,
            generated_text="The argument needs stronger evidence.",
        ),
        selection=selection,
        return_decision=ReturnDecision(
            review_result=True,
            action_purpose="analyse",
            purpose_safe_review=True,
            action_policy_locked=True,
        ),
    )

    assert app.copy_result_action.enabled is True
    assert app.apply_result_action.enabled is False
    assert app.pending_result_can_apply is False
    assert reviews == [
        (
            ["The argument needs stronger evidence."],
            {
                "requested_count": 1,
                "can_apply": False,
                    "action_purpose": "analyse",
                    "safe_review": True,
                    "source_text": "Original text",
            },
        )
    ]
    assert "without changing" in app.notifications[-1][1]


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


def test_apply_uses_only_the_changes_selected_in_review(monkeypatch):
    app = completion_app()
    selection = verified_selection("Original sentence.")
    app._remember_completed_result(
        SubmissionResult(
            submitted=True,
            generated_text="Completely revised sentence.",
        ),
        selection,
    )

    class FakeSelectiveReview:
        def is_selective_review(self):
            return True

        def has_selected_changes(self):
            return True

        def isVisible(self):
            return False

    app.result_review = FakeSelectiveReview()
    app._select_completed_result("Partly revised sentence.")
    replacements = []
    monkeypatch.setattr(
        app_module,
        "apply_verified_source_selection",
        lambda captured, generated: replacements.append((captured, generated))
        or apply_receipt(captured, generated),
    )

    app.apply_latest_result()

    assert replacements == [
        (selection, "Partly revised sentence.")
    ]


def recovery_app(selection: CapturedSelection) -> PromptMeld:
    app = object.__new__(PromptMeld)
    app.last_replacement = apply_receipt(selection, "Generated text")
    app.preserved_original = selection
    app.undo_replacement_action = FakeAction()
    app.copy_original_action = FakeAction()
    app.notify = lambda *args: None
    return app


def test_successful_replacement_enables_native_undo(monkeypatch):
    selection = verified_selection()
    app = recovery_app(selection)
    calls = []
    monkeypatch.setattr(
        app_module,
        "reverse_verified_source_replacement",
        lambda receipt: calls.append(receipt),
    )

    app.undo_last_replacement()

    assert calls == [apply_receipt(selection, "Generated text")]
    assert app.last_replacement is None
    assert app.undo_replacement_action.enabled is False
    assert app.copy_original_action.enabled is True


def test_failed_verified_reversal_leaves_clipboard_unchanged(monkeypatch):
    selection = verified_selection("Private original")
    app = recovery_app(selection)
    clipboard = []
    monkeypatch.setattr(
        app_module,
        "reverse_verified_source_replacement",
        lambda receipt: (_ for _ in ()).throw(
            SourceRecoveryError("window closed")
        ),
    )
    monkeypatch.setattr(app_module, "write_clipboard_text", clipboard.append)

    app.undo_last_replacement()

    assert clipboard == []


def test_failed_verified_reversal_keeps_copy_original_action(monkeypatch):
    selection = verified_selection("Private original")
    app = recovery_app(selection)
    notifications = []
    app.notify = lambda *args: notifications.append(args)
    monkeypatch.setattr(
        app_module,
        "reverse_verified_source_replacement",
        lambda receipt: (_ for _ in ()).throw(
            SourceRecoveryError("window closed")
        ),
    )
    monkeypatch.setattr(
        app_module,
        "write_clipboard_text",
        lambda text: (_ for _ in ()).throw(RuntimeError("clipboard busy")),
    )

    app.undo_last_replacement()

    assert notifications[0][0] == "Undo was unavailable"
    assert app.copy_original_action.enabled is True
    assert app.undo_replacement_action.enabled is False
    assert app.last_replacement is None


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


def test_review_submission_requests_structured_rewrite_and_feedback(
    monkeypatch,
):
    app = object.__new__(PromptMeld)
    app.automation_worker = None
    app.settings = AppSettings(
        auto_submit_enabled=True,
        privacy_preview_enabled=False,
        application_profiles={
            "winword.exe": ApplicationProfile(return_mode="review")
        },
    )
    app.current_selection = CapturedSelection(
        "Original text",
        123,
        "Private title",
        True,
        "winword.exe",
    )
    app.popup = None
    app.cancel_automation_action = FakeAction()
    app.notify = lambda *args: None
    app._show_automation_progress = lambda *args, **kwargs: FakeProgress()

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
        lambda prompt, project, settings, **options: calls.append(prompt)
        or SubmissionResult(submitted=True),
    )
    prompt = (
        "Writing task:\nRewrite this.\n\n"
        "Source text begins below:\n<<<SOURCE>>>\nOriginal text\n"
        "<<<END SOURCE>>>"
    )

    app._submit_prompt(
        prompt,
        action=WritingAction(
            "rewrite",
            "Rewrite",
            (),
            "Rewrite this.",
            purpose="transform",
        ),
    )
    app.thread_pool.worker.function(lambda *args: None)

    submitted_prompt = calls[0]
    assert "<<<PROMPTMELD_REWRITE>>>" in submitted_prompt
    assert "<<<PROMPTMELD_FEEDBACK>>>" in submitted_prompt
    assert submitted_prompt.index("Selective review output:") < (
        submitted_prompt.index("Source text begins below:")
    )


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


def test_interrupted_run_message_distinguishes_submission_ownership():
    before_send = PendingAutomationRecord.create("run-before")
    maybe = PendingAutomationRecord.create("run-maybe").advanced(
        AutomationCheckpoint.SEND_STARTED,
        SubmissionDisposition.MAYBE_SUBMITTED,
    )
    confirmed = PendingAutomationRecord.create("run-confirmed").advanced(
        AutomationCheckpoint.SUBMISSION_CONFIRMED,
        SubmissionDisposition.CONFIRMED,
    )

    assert "stopped before Send" in PromptMeld._interrupted_automation_message(
        before_send
    )
    assert "submission was not confirmed" in (
        PromptMeld._interrupted_automation_message(maybe)
    )
    assert "definitely submitted" in PromptMeld._interrupted_automation_message(
        confirmed
    )


def test_ambiguous_send_cannot_reenter_delivery_even_via_stale_ui_signal():
    app = object.__new__(PromptMeld)
    original_run_id = "ambiguous-run"
    app.automation_run_context = SimpleNamespace(run_id=original_run_id)
    app.automation_worker = None
    app.last_automation_result = SubmissionResult(
        submitted=False,
        checkpoint=AutomationCheckpoint.SEND_STARTED,
        submission_disposition=SubmissionDisposition.MAYBE_SUBMITTED,
        retry_mode="inspect",
        recoverable=True,
    )
    starts = []
    app._start_automation_context = lambda *args, **kwargs: starts.append(
        (args, kwargs)
    )

    app.retry_automation("delivery")

    assert starts == []
    assert app.automation_run_context.run_id == original_run_id


@pytest.mark.parametrize("markdown_escaped", [False, True])
def test_full_canary_verifies_promptmeld_owned_scratch_application(
    monkeypatch,
    qtbot,
    markdown_escaped,
):
    app = completion_app()
    app.cancel_automation_action = FakeAction()
    app.automation_run_context = object()
    app.automation_state = "waiting"
    app.pending_automation_path = None
    app.pending_automation_record = None
    app.interrupted_automation = None
    expected = "PROMPTMELD_CANARY_123"
    captured_response = (
        expected.replace("_", "\\_") if markdown_escaped else expected
    )
    copied_text = []
    monkeypatch.setattr(app_module, "write_clipboard_text", copied_text.append)
    scratch = QPlainTextEdit()
    qtbot.addWidget(scratch)
    scratch.setPlainText("PromptMeld canary source")
    scratch.selectAll()
    monkeypatch.setattr(
        windows_module.SelectionCapture,
        "_source_process_identity",
        staticmethod(lambda hwnd: (123, 456)),
    )
    monkeypatch.setattr(
        windows_module.SelectionCapture,
        "_current_process_identity",
        staticmethod(lambda: (123, 456)),
    )
    monkeypatch.setattr(
        windows_module.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (1, 123),
    )
    monkeypatch.setattr(
        windows_module.win32gui,
        "IsWindow",
        lambda hwnd: True,
    )
    monkeypatch.setattr(
        windows_module.SelectionCapture,
        "_window_class",
        staticmethod(lambda hwnd: "PromptMeldScratch"),
    )
    monkeypatch.setattr(
        windows_module,
        "_validate_source_fingerprint",
        lambda *args: None,
    )
    scratch_selection = app_module.capture_promptmeld_scratch_selection(scratch)

    class ClipboardProbe:
        def finish(self):
            return True

    class CanaryProgress:
        def __init__(self):
            self.finished = None

        def finish(self, result, can_apply=False):
            self.finished = (result, can_apply)

    progress = CanaryProgress()
    app._full_canary_finished(
        SubmissionResult(
            submitted=True,
            generated_text=captured_response,
            submission_confirmed=True,
            checkpoint=AutomationCheckpoint.RESPONSE_CAPTURED,
            submission_disposition=SubmissionDisposition.CONFIRMED,
        ),
        progress,
        expected,
        scratch,
        scratch_selection,
        ClipboardProbe(),
    )

    assert app.last_automation_result.apply_verification == (
        ApplyVerification.VERIFIED
    )
    assert app.last_automation_result.checkpoint == AutomationCheckpoint.COMPLETE
    assert app.last_automation_result.recoverable is False
    assert scratch.toPlainText() == "PromptMeld canary source"
    assert progress.finished[1] is False
    assert app.notifications[-1][0] == "Full automation test passed"
    app.copy_latest_result()
    assert copied_text == [captured_response]
    assert app.automation_progress.copied is True


def test_full_canary_is_opt_in_temporary_chat_with_no_source_payload(
    monkeypatch,
    qtbot,
):
    app = object.__new__(PromptMeld)
    app.popup = None
    app.settings = AppSettings()
    app.cancel_automation_action = FakeAction()
    app.automation_worker = None
    app._automation_is_active = lambda: False
    app._begin_pending_automation = lambda context: None
    app._show_automation_progress = lambda *args, **kwargs: FakeProgress()
    app.notify = lambda *args: None

    class ThreadPool:
        def __init__(self):
            self.worker = None

        def start(self, worker):
            self.worker = worker

    app.thread_pool = ThreadPool()
    calls = []
    questions = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: questions.append((args, kwargs))
        or QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        app_module,
        "submit_via_worker",
        lambda prompt, project, settings, **options: calls.append(
            (prompt, project, settings, options)
        )
        or SubmissionResult(submitted=True, generated_text="mismatch"),
    )
    monkeypatch.setattr(
        app_module,
        "capture_promptmeld_scratch_selection",
        lambda scratch: SimpleNamespace(text="PromptMeld canary source"),
    )

    class ClipboardProbe:
        @classmethod
        def begin(cls, token):
            return cls()

        def finish(self):
            return True

    monkeypatch.setattr(app_module, "ClipboardCanaryProbe", ClipboardProbe)

    app.run_full_automation_canary()
    app.thread_pool.worker.function(lambda *args: None)

    prompt, project, settings, options = calls[0]
    assert prompt.startswith("Reply with exactly this phrase")
    assert project == ""
    assert settings.temporary_chat_enabled is True
    assert settings.auto_submit_enabled is True
    assert settings.replace_selected_text_enabled is False
    assert options["capture_generated_text"] is True
    assert "source_text" not in options
    assert "source_hwnd" not in options
    assert "full-format restoration" in questions[0][0][2]
    assert "unique test phrase" in questions[0][0][2]
    assert "nonce" not in questions[0][0][2].casefold()


def test_full_canary_markdown_normalisation_remains_exact():
    expected = "PROMPTMELD_CANARY_123"

    assert app_module._canonical_canary_response(
        "PROMPTMELD\\_CANARY\\_123",
        expected,
    ) == expected
    assert app_module._canonical_canary_response(
        "PROMPTMELD\\_CANARY\\_123 extra",
        expected,
    ) is None


def test_full_canary_rejects_missing_clipboard_round_trip(
    monkeypatch,
    qtbot,
):
    app = completion_app()
    app.cancel_automation_action = FakeAction()
    app.automation_run_context = object()
    app.automation_state = "waiting"
    app.pending_automation_path = None
    app.pending_automation_record = None
    app.interrupted_automation = None
    expected = "PROMPTMELD_CANARY_123"
    original = "PromptMeld canary source"
    scratch = QPlainTextEdit()
    qtbot.addWidget(scratch)
    scratch.setPlainText(original)
    scratch_selection = SimpleNamespace(text=original)

    def apply_scratch(selection, generated):
        scratch.setPlainText(generated)
        return object()

    def reverse_scratch(receipt):
        scratch.setPlainText(original)

    monkeypatch.setattr(
        app_module,
        "apply_verified_source_selection",
        apply_scratch,
    )
    monkeypatch.setattr(
        app_module,
        "reverse_verified_source_replacement",
        reverse_scratch,
    )
    monkeypatch.setattr(
        app_module,
        "release_promptmeld_scratch_selection",
        lambda selection: None,
    )

    class ClipboardProbe:
        def finish(self):
            return False

    class CanaryProgress:
        def finish(self, result, can_apply=False):
            self.result = result

    progress = CanaryProgress()
    app._full_canary_finished(
        SubmissionResult(
            submitted=True,
            generated_text=expected,
            submission_confirmed=True,
            checkpoint=AutomationCheckpoint.RESPONSE_CAPTURED,
            submission_disposition=SubmissionDisposition.CONFIRMED,
        ),
        progress,
        expected,
        scratch,
        scratch_selection,
        ClipboardProbe(),
    )

    assert app.last_automation_result.failure_code == (
        "canary_clipboard_verification_failed"
    )
    assert app.last_automation_result.apply_verification == (
        ApplyVerification.FAILED
    )
    assert scratch.toPlainText() == original
