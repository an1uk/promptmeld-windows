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
        source_text="private source",
        source_app="winword.exe",
    )

    assert result.submitted is True
    assert calls[0][0]["prompt"] == "private prompt"
    assert calls[0][0]["auto_submit"] is False
    assert calls[0][0]["temporary_chat"] is False
    assert calls[0][0]["replace_selected_text"] is False
    assert calls[0][0]["copy_generated_text"] is False
    assert calls[0][0]["source_text"] == "private source"
    assert calls[0][0]["source_app"] == "winword.exe"
    assert calls[0][0]["response_timeout_seconds"] == 300.0
    assert calls[0][0]["redaction_replacements"] == {}
    assert calls[0][1] == 75.0


def test_automation_client_sends_local_redaction_key_to_helper(monkeypatch):
    calls = []

    def fake_request(payload, timeout_seconds, progress_callback=None):
        calls.append(payload)
        return {"submitted": True, "message": "Submitted."}

    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        fake_request,
    )

    automation_client.submit_via_worker(
        "Email [EMAIL_1]",
        "PromptMeld",
        AppSettings(),
        redaction_replacements={"[EMAIL_1]": "jane@example.com"},
    )

    assert calls[0]["redaction_replacements"] == {
        "[EMAIL_1]": "jane@example.com"
    }


def test_generated_result_wait_gets_a_five_minute_helper_window(monkeypatch):
    calls = []

    def fake_request(payload, timeout_seconds, progress_callback=None):
        calls.append((payload, timeout_seconds))
        return {
            "submitted": True,
            "generated_text_copied": True,
            "generated_text": "Generated answer",
            "message": "Generated text copied.",
        }

    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        fake_request,
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(
            auto_submit_enabled=True,
            copy_generated_text_enabled=True,
        ),
    )

    assert calls[0][0]["response_timeout_seconds"] == 300.0
    assert calls[0][1] == 360.0
    assert result.generated_text == "Generated answer"


def test_alternative_capture_waits_without_copying_or_replacing(monkeypatch):
    calls = []

    def fake_request(payload, timeout_seconds, progress_callback=None):
        calls.append((payload, timeout_seconds))
        return {
            "submitted": True,
            "generated_text": "Marked alternatives",
        }

    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        fake_request,
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(auto_submit_enabled=True),
        replace_selected_text=False,
        copy_generated_text=False,
        capture_generated_text=True,
    )

    assert calls[0][0]["capture_generated_text"] is True
    assert calls[0][0]["copy_generated_text"] is False
    assert calls[0][0]["replace_selected_text"] is False
    assert calls[0][1] == 360.0
    assert result.generated_text == "Marked alternatives"


@pytest.mark.parametrize(
    ("response_timeout", "helper_timeout"),
    [(600.0, 660.0), (None, None)],
)
def test_generated_result_uses_per_application_wait_window(
    monkeypatch,
    response_timeout,
    helper_timeout,
):
    calls = []

    def fake_request(payload, timeout_seconds, progress_callback=None):
        calls.append((payload, timeout_seconds))
        return {"submitted": True, "generated_text": "Generated answer"}

    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        fake_request,
    )

    automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(auto_submit_enabled=True),
        capture_generated_text=True,
        response_timeout_seconds=response_timeout,
    )

    assert calls[0][0]["response_timeout_seconds"] == response_timeout
    assert calls[0][1] == helper_timeout


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


def test_cancelled_automation_does_not_copy_the_private_prompt(monkeypatch):
    clipboard = []
    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            automation_client.AutomationCancelled("cancelled")
        ),
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
        is_cancelled=lambda: True,
    )

    assert result.cancelled is True
    assert result.fallback_copied is False
    assert clipboard == []


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


def test_helper_session_observes_cancellation_while_waiting():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()

    with pytest.raises(automation_client.AutomationCancelled):
        session.request(
            {"prompt": "private prompt"},
            None,
            is_cancelled=lambda: True,
        )
