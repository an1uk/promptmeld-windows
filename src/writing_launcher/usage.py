from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import UsageRecord


class UsageTracker:
    def __init__(self, path: Path):
        self.path = path
        self._records: dict[str, UsageRecord] = {}
        self.load()

    def load(self) -> None:
        self._records = {}
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            for action_id, item in raw.items():
                if not isinstance(item, dict):
                    continue
                count = max(0, int(item.get("count", 0)))
                last_used_raw = item.get("last_used")
                last_used = (
                    datetime.fromisoformat(last_used_raw)
                    if isinstance(last_used_raw, str) and last_used_raw
                    else None
                )
                self._records[str(action_id)] = UsageRecord(count, last_used)
        except (OSError, ValueError, TypeError):
            self._records = {}

    def get(self, action_id: str) -> UsageRecord:
        return self._records.get(action_id, UsageRecord())

    def record(self, action_id: str, now: datetime | None = None) -> None:
        current = self.get(action_id)
        timestamp = now or datetime.now(UTC)
        self._records[action_id] = UsageRecord(
            count=current.count + 1,
            last_used=timestamp,
        )
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            action_id: {
                "count": record.count,
                "last_used": (
                    record.last_used.isoformat() if record.last_used else None
                ),
            }
            for action_id, record in self._records.items()
        }
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
