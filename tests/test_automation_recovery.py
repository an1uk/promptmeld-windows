from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from promptmeld.automation_protocol import (
    AutomationCheckpoint,
    SubmissionDisposition,
)
from promptmeld.automation_recovery import (
    PENDING_RUN_SCHEMA_VERSION,
    PendingAutomationRecord,
    load_pending_automation,
    save_pending_automation,
)


def test_pending_run_journal_is_atomic_metadata_only(tmp_path):
    path = tmp_path / "pending-automation.json"
    record = PendingAutomationRecord.create("run-123").advanced(
        AutomationCheckpoint.SEND_STARTED,
        SubmissionDisposition.MAYBE_SUBMITTED,
    )

    save_pending_automation(path, record)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "checkpoint",
        "response_captured",
        "run_id",
        "schema_version",
        "source_apply_started",
        "started_at",
        "submission_disposition",
        "updated_at",
    }
    assert payload["schema_version"] == PENDING_RUN_SCHEMA_VERSION
    assert payload["run_id"] == "run-123"
    assert payload["checkpoint"] == "send_started"
    assert payload["submission_disposition"] == "maybe_submitted"
    serialised = path.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "selected_text",
        "source_title",
        "project_name",
        "prompt",
        "generated_text",
        "response_text",
    ):
        assert forbidden not in serialised
    assert not list(tmp_path.glob(".*.tmp"))


def test_pending_run_journal_never_regresses_checkpoint_or_disposition():
    record = PendingAutomationRecord.create("run-123").advanced(
        AutomationCheckpoint.SUBMISSION_CONFIRMED,
        SubmissionDisposition.CONFIRMED,
    )

    regressed = record.advanced(
        AutomationCheckpoint.COMPOSER_VERIFIED,
        SubmissionDisposition.NOT_ATTEMPTED,
    )

    assert regressed.checkpoint == AutomationCheckpoint.SUBMISSION_CONFIRMED
    assert regressed.submission_disposition == SubmissionDisposition.CONFIRMED


def test_pending_run_journal_tracks_response_and_source_apply_flags():
    record = PendingAutomationRecord.create("run-123").advanced(
        AutomationCheckpoint.SOURCE_APPLY_STARTED,
        SubmissionDisposition.CONFIRMED,
    )

    assert record.response_captured is True
    assert record.source_apply_started is True


def test_expired_pending_run_is_removed(tmp_path):
    path = tmp_path / "pending-automation.json"
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    path.write_text(
        json.dumps(
            {
                "schema_version": PENDING_RUN_SCHEMA_VERSION,
                "run_id": "run-123",
                "started_at": old,
                "updated_at": old,
                "checkpoint": "submission_confirmed",
                "submission_disposition": "confirmed",
            }
        ),
        encoding="utf-8",
    )

    assert load_pending_automation(path) is None
    assert path.exists() is False


def test_malformed_pending_run_is_removed(tmp_path):
    path = tmp_path / "pending-automation.json"
    path.write_text("contains private prompt but is not JSON", encoding="utf-8")

    assert load_pending_automation(path) is None
    assert path.exists() is False
