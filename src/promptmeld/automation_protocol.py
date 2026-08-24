from __future__ import annotations

from enum import StrEnum


AUTOMATION_PROTOCOL_VERSION = 5
HEARTBEAT_INTERVAL_SECONDS = 2.0
CANCELLATION_GRACE_SECONDS = 6.0


class AutomationCheckpoint(StrEnum):
    """Privacy-safe milestones acknowledged by the automation companion."""

    PREPARING = "preparing"
    DESTINATION_VERIFIED = "destination_verified"
    COMPOSER_VERIFIED = "composer_verified"
    SEND_STARTED = "send_started"
    SUBMISSION_CONFIRMED = "submission_confirmed"
    RESPONSE_CAPTURED = "response_captured"
    SOURCE_APPLY_STARTED = "source_apply_started"
    SOURCE_APPLY_VERIFIED = "source_apply_verified"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


class SubmissionDisposition(StrEnum):
    """Whether starting another delivery could duplicate a ChatGPT request."""

    NOT_ATTEMPTED = "not_attempted"
    MAYBE_SUBMITTED = "maybe_submitted"
    CONFIRMED = "confirmed"


class RecoveryAction(StrEnum):
    RETRY_DELIVERY = "retry_delivery"
    INSPECT_CHATGPT = "inspect_chatgpt"
    COPY_PROMPT = "copy_prompt"
    RETRY_RESPONSE = "retry_response"
    COPY_RESULT = "copy_result"
    APPLY_RESULT = "apply_result"
    COPY_ORIGINAL = "copy_original"
    REVERSE_APPLY = "reverse_apply"


class ApplyVerification(StrEnum):
    NOT_REQUESTED = "not_requested"
    UNSUPPORTED = "unsupported"
    VERIFIED = "verified"
    FAILED = "failed"


_CHECKPOINT_ORDER = {
    AutomationCheckpoint.PREPARING: 0,
    AutomationCheckpoint.DESTINATION_VERIFIED: 1,
    AutomationCheckpoint.COMPOSER_VERIFIED: 2,
    AutomationCheckpoint.SEND_STARTED: 3,
    AutomationCheckpoint.SUBMISSION_CONFIRMED: 4,
    AutomationCheckpoint.RESPONSE_CAPTURED: 5,
    AutomationCheckpoint.SOURCE_APPLY_STARTED: 6,
    AutomationCheckpoint.SOURCE_APPLY_VERIFIED: 7,
    AutomationCheckpoint.COMPLETE: 8,
    # Cancellation is terminal but can be acknowledged from any checkpoint.
    AutomationCheckpoint.CANCELLED: 9,
}

_DISPOSITION_ORDER = {
    SubmissionDisposition.NOT_ATTEMPTED: 0,
    SubmissionDisposition.MAYBE_SUBMITTED: 1,
    SubmissionDisposition.CONFIRMED: 2,
}


def coerce_checkpoint(value: object) -> AutomationCheckpoint:
    try:
        return AutomationCheckpoint(str(value))
    except ValueError:
        return AutomationCheckpoint.PREPARING


def coerce_submission_disposition(value: object) -> SubmissionDisposition:
    try:
        return SubmissionDisposition(str(value))
    except ValueError:
        return SubmissionDisposition.NOT_ATTEMPTED


def checkpoint_is_at_least(
    checkpoint: AutomationCheckpoint,
    expected: AutomationCheckpoint,
) -> bool:
    return _CHECKPOINT_ORDER[checkpoint] >= _CHECKPOINT_ORDER[expected]


def submission_disposition_is_at_least(
    disposition: SubmissionDisposition,
    expected: SubmissionDisposition,
) -> bool:
    return _DISPOSITION_ORDER[disposition] >= _DISPOSITION_ORDER[expected]


def disposition_for_checkpoint(
    checkpoint: AutomationCheckpoint,
) -> SubmissionDisposition:
    if checkpoint in {
        AutomationCheckpoint.SUBMISSION_CONFIRMED,
        AutomationCheckpoint.RESPONSE_CAPTURED,
        AutomationCheckpoint.SOURCE_APPLY_STARTED,
        AutomationCheckpoint.SOURCE_APPLY_VERIFIED,
    }:
        return SubmissionDisposition.CONFIRMED
    if checkpoint == AutomationCheckpoint.SEND_STARTED:
        return SubmissionDisposition.MAYBE_SUBMITTED
    return SubmissionDisposition.NOT_ATTEMPTED


def checkpoint_for_stage(stage: object) -> AutomationCheckpoint:
    folded = str(stage or "").strip().casefold().replace("-", "_")
    explicit = {
        "destination_verified": AutomationCheckpoint.DESTINATION_VERIFIED,
        "composer_verified": AutomationCheckpoint.COMPOSER_VERIFIED,
        "send_started": AutomationCheckpoint.SEND_STARTED,
        "submitted": AutomationCheckpoint.SUBMISSION_CONFIRMED,
        "submission_confirmed": AutomationCheckpoint.SUBMISSION_CONFIRMED,
        "response_captured": AutomationCheckpoint.RESPONSE_CAPTURED,
        "source_apply_started": AutomationCheckpoint.SOURCE_APPLY_STARTED,
        "source_apply_verified": AutomationCheckpoint.SOURCE_APPLY_VERIFIED,
        "complete": AutomationCheckpoint.COMPLETE,
        "cancelled": AutomationCheckpoint.CANCELLED,
    }
    return explicit.get(folded, AutomationCheckpoint.PREPARING)


def recovery_actions_for(
    disposition: SubmissionDisposition,
    *,
    has_result: bool = False,
) -> tuple[RecoveryAction, ...]:
    if has_result:
        return (
            RecoveryAction.COPY_RESULT,
            RecoveryAction.INSPECT_CHATGPT,
        )
    if disposition == SubmissionDisposition.CONFIRMED:
        return (
            RecoveryAction.RETRY_RESPONSE,
            RecoveryAction.INSPECT_CHATGPT,
        )
    if disposition == SubmissionDisposition.MAYBE_SUBMITTED:
        return (
            RecoveryAction.INSPECT_CHATGPT,
            RecoveryAction.COPY_PROMPT,
        )
    return (
        RecoveryAction.RETRY_DELIVERY,
        RecoveryAction.COPY_PROMPT,
        RecoveryAction.INSPECT_CHATGPT,
    )
