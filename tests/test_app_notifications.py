from __future__ import annotations

from promptmeld.app import PromptMeld
from promptmeld.models import SubmissionResult


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

    assert notifications[0][0] == "Generated text could not be returned"
    assert notifications[0][1] == result.message
