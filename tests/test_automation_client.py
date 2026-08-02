from __future__ import annotations

import io
import json
import queue
import sys

import pytest

from promptmeld import automation_client
from promptmeld.models import AppSettings


@pytest.fixture(autouse=True)
def reset_helper_session():
    automation_client.shutdown_automation_helper()
    yield
    automation_client.shutdown_automation_helper()


def test_automation_client_sends_prompt_to_helper(monkeypatch):
    calls = []

    def fake_request(
        payload,
        timeout_seconds,
        progress_callback=None,
    ):
        calls.append((payload, timeout_seconds))
        return {
            "submitted": True,
            "fallback_copied": False,
            "message": "Submitted.",
            "_timings": [
                {"stage": "total submission", "milliseconds": 125.4}
            ],
        }

    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        fake_request,
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(),
    )

    assert result.submitted is True
    assert calls[0][0]["prompt"] == "private prompt"
    assert calls[0][0]["auto_submit"] is False
    assert calls[0][0]["temporary_chat"] is False
    assert calls[0][0]["replace_selected_text"] is False
    assert calls[0][0]["copy_generated_text"] is False
    assert calls[0][1] == 75.0


def test_temporary_chat_allows_time_for_user_confirmation(monkeypatch):
    calls = []

    def fake_request(payload, timeout_seconds, progress_callback=None):
        calls.append((payload, timeout_seconds))
        return {
            "submitted": False,
            "prepared": True,
            "fallback_copied": False,
            "message": "Prompt ready.",
        }

    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        fake_request,
    )

    automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(temporary_chat_enabled=True),
    )

    assert calls[0][0]["temporary_chat"] is True
    assert calls[0][1] >= 75.0


def test_automation_client_preserves_prepared_result(monkeypatch):
    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        lambda *args, **kwargs: {
            "submitted": False,
            "prepared": True,
            "fallback_copied": False,
            "message": "Prompt ready.",
        },
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(),
    )

    assert result.submitted is False
    assert result.prepared is True
    assert result.fallback_copied is False


def test_automation_client_copies_fallback_if_helper_fails(monkeypatch):
    clipboard = []
    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("failed")),
    )
    monkeypatch.setattr(
        automation_client,
        "write_clipboard_text",
        clipboard.append,
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(),
    )

    assert result.submitted is False
    assert result.fallback_copied is True
    assert clipboard == ["private prompt"]


def test_frozen_client_uses_internal_helper(monkeypatch, tmp_path):
    executable = tmp_path / "PromptMeld.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert automation_client._helper_command() == [
        str(
            tmp_path
            / "_internal"
            / "PromptMeldAutomation.exe"
        )
    ]


def test_helper_session_is_reused_until_idle(monkeypatch):
    created = []

    class FakeSession:
        def __init__(self, command):
            self.command = command
            self.alive = True
            self.requests = []
            created.append(self)

        def request(
            self,
            payload,
            timeout_seconds,
            progress_callback=None,
        ):
            self.requests.append((payload, timeout_seconds))
            return {"submitted": True}

        def close(self):
            self.alive = False

    monkeypatch.setattr(
        automation_client,
        "_AutomationHelperSession",
        FakeSession,
    )
    monkeypatch.setattr(
        automation_client,
        "_schedule_helper_shutdown",
        lambda session: None,
    )

    first = automation_client._request_from_helper({"prompt": "one"}, 20.0)
    second = automation_client._request_from_helper({"prompt": "two"}, 20.0)

    assert first["submitted"] is True
    assert second["submitted"] is True
    assert len(created) == 1
    assert [request[0]["prompt"] for request in created[0].requests] == [
        "one",
        "two",
    ]


def test_helper_session_streams_progress_before_final_response():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put(
        json.dumps(
            {
                "_event": "progress",
                "stage": "opening-project",
                "message": "Opening the project",
            }
        )
    )
    session.responses.put(
        json.dumps(
            {
                "submitted": True,
                "message": "Submitted.",
            }
        )
    )
    progress = []

    response = session.request(
        {"prompt": "private prompt"},
        1.0,
        lambda stage, message: progress.append((stage, message)),
    )

    assert progress == [("opening-project", "Opening the project")]
    assert response["submitted"] is True
