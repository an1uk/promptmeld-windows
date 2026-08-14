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
    adapter_options = []

    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            adapter_options.append(kwargs)

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
    assert adapter_options[0]["response_timeout_seconds"] == 300.0


def test_worker_forwards_configured_response_timeout(monkeypatch):
    adapter_options = []

    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            adapter_options.append(kwargs)

        def submit(self, prompt, project_name, **kwargs):
            return SubmissionResult(submitted=True, message="Submitted.")

    monkeypatch.setattr(automation_worker, "ChatGPTDesktop", FakeAdapter)

    automation_worker._process_payload(
        {
            "prompt": "complete prompt",
            "project_name": "PromptMeld",
            "response_timeout_seconds": 240.0,
        }
    )

    assert adapter_options[0]["response_timeout_seconds"] == 240.0


def test_worker_forwards_indefinite_response_wait(monkeypatch):
    adapter_options = []

    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            adapter_options.append(kwargs)

        def submit(self, prompt, project_name, **kwargs):
            return SubmissionResult(submitted=True, message="Submitted.")

    monkeypatch.setattr(automation_worker, "ChatGPTDesktop", FakeAdapter)

    automation_worker._process_payload(
        {
            "prompt": "complete prompt",
            "project_name": "PromptMeld",
            "response_timeout_seconds": None,
        }
    )

    assert adapter_options[0]["response_timeout_seconds"] is None


def test_worker_returns_generated_text_to_the_main_process(monkeypatch):
    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            pass

        def submit(self, prompt, project_name, **kwargs):
            return SubmissionResult(
                submitted=True,
                generated_text="Generated answer",
            )

    monkeypatch.setattr(automation_worker, "ChatGPTDesktop", FakeAdapter)

    response = automation_worker._process_payload(
        {"prompt": "complete prompt", "project_name": "PromptMeld"}
    )

    assert response["generated_text"] == "Generated answer"


def test_worker_forwards_capture_without_clipboard_output(monkeypatch):
    calls = []

    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            pass

        def submit(self, prompt, project_name, **kwargs):
            calls.append(kwargs)
            return SubmissionResult(
                submitted=True,
                generated_text="Alternatives",
            )

    monkeypatch.setattr(automation_worker, "ChatGPTDesktop", FakeAdapter)

    automation_worker._process_payload(
        {
            "prompt": "complete prompt",
            "project_name": "PromptMeld",
            "capture_generated_text": True,
        }
    )

    assert calls[0]["capture_generated_text"] is True
    assert calls[0]["copy_generated_text"] is False
    assert calls[0]["replace_selected_text"] is False


def test_worker_forwards_redaction_key_for_local_result_restoration(
    monkeypatch,
):
    calls = []

    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            pass

        def submit(self, prompt, project_name, **kwargs):
            calls.append(kwargs)
            return SubmissionResult(submitted=True)

    monkeypatch.setattr(automation_worker, "ChatGPTDesktop", FakeAdapter)

    automation_worker._process_payload(
        {
            "prompt": "Email [EMAIL_1]",
            "project_name": "PromptMeld",
            "redaction_replacements": {
                "[EMAIL_1]": "jane@example.com"
            },
        }
    )

    assert calls[0]["redaction_replacements"] == {
        "[EMAIL_1]": "jane@example.com"
    }


def test_response_retry_never_calls_submit(monkeypatch):
    calls = []

    class FakeAdapter:
        timings = []

        def __init__(self, **kwargs):
            pass

        def submit(self, *args, **kwargs):
            raise AssertionError("response retry must not submit")

        def retrieve_response(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return SubmissionResult(
                submitted=True,
                generated_text="Existing response",
                submission_confirmed=True,
            )

    monkeypatch.setattr(automation_worker, "ChatGPTDesktop", FakeAdapter)

    response = automation_worker._process_payload(
        {
            "operation": "retrieve_response",
            "prompt": "original prompt",
            "response_baseline": ["0:old"],
        }
    )

    assert response["generated_text"] == "Existing response"
    assert calls[0][1]["response_baseline"] == ("0:old",)


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
