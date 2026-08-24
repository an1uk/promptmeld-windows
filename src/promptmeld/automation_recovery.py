from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .automation_protocol import (
    AutomationCheckpoint,
    SubmissionDisposition,
    coerce_checkpoint,
    coerce_submission_disposition,
    checkpoint_is_at_least,
    submission_disposition_is_at_least,
)


PENDING_RUN_SCHEMA_VERSION = 1
PENDING_RUN_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class PendingAutomationRecord:
    """Content-free recovery state safe to retain across app restarts."""

    schema_version: int
    run_id: str
    started_at: str
    updated_at: str
    checkpoint: AutomationCheckpoint
    submission_disposition: SubmissionDisposition
    response_captured: bool = False
    source_apply_started: bool = False

    @classmethod
    def create(cls, run_id: str) -> "PendingAutomationRecord":
        now = datetime.now(UTC).isoformat()
        return cls(
            schema_version=PENDING_RUN_SCHEMA_VERSION,
            run_id=run_id,
            started_at=now,
            updated_at=now,
            checkpoint=AutomationCheckpoint.PREPARING,
            submission_disposition=SubmissionDisposition.NOT_ATTEMPTED,
        )

    def advanced(
        self,
        checkpoint: AutomationCheckpoint,
        disposition: SubmissionDisposition,
    ) -> "PendingAutomationRecord":
        if (
            checkpoint
            not in {
                AutomationCheckpoint.COMPLETE,
                AutomationCheckpoint.CANCELLED,
            }
            and not checkpoint_is_at_least(checkpoint, self.checkpoint)
        ):
            checkpoint = self.checkpoint
        if not submission_disposition_is_at_least(
            disposition,
            self.submission_disposition,
        ):
            disposition = self.submission_disposition
        return PendingAutomationRecord(
            schema_version=self.schema_version,
            run_id=self.run_id,
            started_at=self.started_at,
            updated_at=datetime.now(UTC).isoformat(),
            checkpoint=checkpoint,
            submission_disposition=disposition,
            response_captured=(
                self.response_captured
                or checkpoint
                in {
                    AutomationCheckpoint.RESPONSE_CAPTURED,
                    AutomationCheckpoint.SOURCE_APPLY_STARTED,
                    AutomationCheckpoint.SOURCE_APPLY_VERIFIED,
                    AutomationCheckpoint.COMPLETE,
                }
            ),
            source_apply_started=(
                self.source_apply_started
                or checkpoint
                in {
                    AutomationCheckpoint.SOURCE_APPLY_STARTED,
                    AutomationCheckpoint.SOURCE_APPLY_VERIFIED,
                }
            ),
        )


def save_pending_automation(
    path: Path,
    record: PendingAutomationRecord,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = asdict(record)
    payload["checkpoint"] = record.checkpoint.value
    payload["submission_disposition"] = record.submission_disposition.value
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def clear_pending_automation(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def load_pending_automation(path: Path) -> PendingAutomationRecord | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("pending automation record must be an object")
        record = PendingAutomationRecord(
            schema_version=int(raw.get("schema_version", 0)),
            run_id=str(raw.get("run_id", "")),
            started_at=str(raw.get("started_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            checkpoint=coerce_checkpoint(raw.get("checkpoint", "")),
            submission_disposition=coerce_submission_disposition(
                raw.get("submission_disposition", "")
            ),
            response_captured=bool(raw.get("response_captured", False)),
            source_apply_started=bool(raw.get("source_apply_started", False)),
        )
        if (
            record.schema_version != PENDING_RUN_SCHEMA_VERSION
            or not record.run_id
        ):
            raise ValueError("unsupported pending automation record")
        updated = datetime.fromisoformat(record.updated_at)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        if datetime.now(UTC) - updated > PENDING_RUN_MAX_AGE:
            clear_pending_automation(path)
            return None
        return record
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        clear_pending_automation(path)
        return None
