from __future__ import annotations

import io
import json

from promptmeld import automation_worker
from promptmeld.models import SubmissionResult


def test_worker_requests_per_monitor_v2_dpi_awareness(monkeypatch):
    requested = []
    monkeypatch.setattr(automation_worker.sys, "platform", "win32")

    enabled = automation_worker._enable_per_monitor_dpi_awareness(
        lambda value: requested.append(value) or True
    )

    assert enabled is True
    assert requested == [automation_worker.PER_MONITOR_AWARE_V2]


def test_worker_forwards_temporary_chat_choice(monkeypatch):
    calls = []

    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            pass

        def submit(self, prompt, project_name, **kwargs):
            calls.append((prompt, project_name, kwargs))
            return SubmissionResult(
                submitted=False,
                fallback_copied=False,
                prepared=True,
                message="Prompt ready.",
            )

    monkeypatch.setattr(automation_worker, "ChatGPTDesktop", FakeAdapter)

    response = automation_worker._process_payload(
        {
            "prompt": "complete prompt",
            "project_name": "PromptMeld",
            "temporary_chat": True,
        }
    )

    assert calls == [
        (
            "complete prompt",
            "PromptMeld",
            {"auto_submit": False, "temporary_chat": True},
        )
    ]
    assert response["prepared"] is True


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
        lambda payload, progress_callback=None: {
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


def test_server_emits_progress_before_result(monkeypatch):
    stdin = io.StringIO('{"prompt":"one"}\n{"_command":"shutdown"}\n')
    stdout = io.StringIO()
    monkeypatch.setattr(automation_worker.sys, "stdin", stdin)
    monkeypatch.setattr(automation_worker.sys, "stdout", stdout)

    def process(payload, progress_callback=None):
        progress_callback("finding-composer", "Finding the message box")
        return {"submitted": True, "message": payload["prompt"]}

    monkeypatch.setattr(automation_worker, "_process_payload", process)

    assert automation_worker._run_server() == 0

    responses = [
        json.loads(line)
        for line in stdout.getvalue().splitlines()
    ]
    assert responses[0] == {
        "_event": "progress",
        "stage": "finding-composer",
        "message": "Finding the message box",
    }
    assert responses[1]["submitted"] is True
