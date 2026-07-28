from __future__ import annotations

import io
import json

from writing_launcher import automation_worker


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
