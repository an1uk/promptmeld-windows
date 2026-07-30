from __future__ import annotations

import io
import json

from promptmeld import automation_worker


def test_worker_requests_per_monitor_v2_dpi_awareness(monkeypatch):
    requested = []
    monkeypatch.setattr(automation_worker.sys, "platform", "win32")

    enabled = automation_worker._enable_per_monitor_dpi_awareness(
        lambda value: requested.append(value) or True
    )

    assert enabled is True
    assert requested == [automation_worker.PER_MONITOR_AWARE_V2]


def test_server_processes_multiple_requests_before_shutdown(monkeypatch):
    stdin = io.StringIO(
        '{"prompt":"one"}\n'
        '{"prompt":"two"}\n'
        '{"_command":"shutdown"}\n'
    )
    stdout = io.StringIO()
    monkeypatch.setattr(automation_worker.sys, "stdin", stdin)
    monkeypatch.setattr(automation_worker.sys, "stdout", stdout)
    monkeypatch.setattr(
        automation_worker,
        "_process_payload",
        lambda payload: {
            "submitted": True,
            "message": payload["prompt"],
        },
    )

    assert automation_worker._run_server() == 0

    responses = [
        json.loads(line)
        for line in stdout.getvalue().splitlines()
    ]
    assert [response["message"] for response in responses] == [
        "one",
        "two",
    ]
