from __future__ import annotations

import io
import json
import queue
import sys

import pytest

from promptmeld import automation_client
from promptmeld.automation_protocol import (
    AUTOMATION_PROTOCOL_VERSION,
    AutomationCheckpoint,
    RecoveryAction,
    SubmissionDisposition,
)
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
    assert "source_text" not in calls[0][0]
    assert "source_app" not in calls[0][0]
    assert "source_hwnd" not in calls[0][0]
    assert calls[0][0]["_protocol_version"] == AUTOMATION_PROTOCOL_VERSION
    assert calls[0][0]["checkpoint"] == "preparing"
    assert calls[0][0]["attempt"] == 1
    assert calls[0][0]["request_id"]
    assert calls[0][0]["run_id"]
    assert calls[0][0]["response_timeout_seconds"] == 300.0
    assert calls[0][0]["redaction_replacements"] == {}
    assert calls[0][1] == 15.0


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


def test_generated_result_uses_no_progress_watchdog_not_total_wait(monkeypatch):
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
    assert calls[0][1] == 15.0
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
    assert calls[0][1] == 15.0
    assert result.generated_text == "Marked alternatives"


@pytest.mark.parametrize(
    "response_timeout",
    [600.0, None],
)
def test_generated_result_wait_does_not_change_activity_watchdog(
    monkeypatch,
    response_timeout,
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
    assert calls[0][1] == 15.0


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
    assert calls[0][1] == 15.0


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


def test_automation_client_leaves_clipboard_unchanged_if_helper_fails(monkeypatch):
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
        raising=False,
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(),
    )

    assert result.submitted is False
    assert result.fallback_copied is False
    assert result.retry_mode == "delivery"
    assert RecoveryAction.RETRY_DELIVERY in result.recovery_actions
    assert clipboard == []


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
        raising=False,
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
    session.require_envelopes = True
    metadata = {
        "protocol_version": AUTOMATION_PROTOCOL_VERSION,
        "request_id": "request-1",
        "run_id": "run-1",
        "checkpoint": "destination_verified",
        "submission_disposition": "not_attempted",
        "attempt": 1,
    }
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": "progress",
                "stage": "opening-project",
                "message": "Opening the project",
            }
        )
    )
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": "result",
                "payload": {
                    "submitted": True,
                    "message": "Submitted.",
                },
            }
        )
    )
    progress = []

    response = session.request(
        {
            "prompt": "private prompt",
            "request_id": "request-1",
            "run_id": "run-1",
        },
        1.0,
        lambda stage, message: progress.append((stage, message)),
    )

    assert progress == [("opening-project", "Opening the project")]
    assert response["submitted"] is True


def test_helper_session_sends_cooperative_cancel_and_accepts_final_result():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.require_envelopes = True
    metadata = {
        "protocol_version": AUTOMATION_PROTOCOL_VERSION,
        "request_id": "request-1",
        "run_id": "run-1",
        "checkpoint": "composer_verified",
        "submission_disposition": "not_attempted",
        "attempt": 1,
    }
    session.responses.put(json.dumps({**metadata, "_event": "cancel_ack"}))
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": "result",
                "payload": {"submitted": False, "cancelled": True},
            }
        )
    )

    result = session.request(
        {
            "prompt": "private prompt",
            "request_id": "request-1",
            "run_id": "run-1",
        },
        None,
        is_cancelled=lambda: True,
    )

    assert result["cancelled"] is True
    commands = [
        json.loads(line)
        for line in session.process.stdin.getvalue().splitlines()
    ]
    assert commands[1]["_command"] == "cancel"
    assert commands[1]["checkpoint"] == "preparing"
    assert commands[1]["attempt"] == 1


@pytest.mark.parametrize(
    (
        "checkpoint",
        "disposition",
        "captured_result",
        "retry_mode",
        "forbidden_action",
    ),
    [
        (
            AutomationCheckpoint.PREPARING,
            SubmissionDisposition.NOT_ATTEMPTED,
            "",
            "delivery",
            RecoveryAction.RETRY_RESPONSE,
        ),
        (
            AutomationCheckpoint.DESTINATION_VERIFIED,
            SubmissionDisposition.NOT_ATTEMPTED,
            "",
            "delivery",
            RecoveryAction.RETRY_RESPONSE,
        ),
        (
            AutomationCheckpoint.COMPOSER_VERIFIED,
            SubmissionDisposition.NOT_ATTEMPTED,
            "",
            "delivery",
            RecoveryAction.RETRY_RESPONSE,
        ),
        (
            AutomationCheckpoint.SEND_STARTED,
            SubmissionDisposition.MAYBE_SUBMITTED,
            "",
            "inspect",
            RecoveryAction.RETRY_DELIVERY,
        ),
        (
            AutomationCheckpoint.SUBMISSION_CONFIRMED,
            SubmissionDisposition.CONFIRMED,
            "",
            "response",
            RecoveryAction.RETRY_DELIVERY,
        ),
        (
            AutomationCheckpoint.RESPONSE_CAPTURED,
            SubmissionDisposition.CONFIRMED,
            "Recovered answer",
            "",
            RecoveryAction.RETRY_DELIVERY,
        ),
        (
            AutomationCheckpoint.SOURCE_APPLY_STARTED,
            SubmissionDisposition.CONFIRMED,
            "Recovered answer",
            "",
            RecoveryAction.RETRY_DELIVERY,
        ),
        (
            AutomationCheckpoint.SOURCE_APPLY_VERIFIED,
            SubmissionDisposition.CONFIRMED,
            "Recovered answer",
            "",
            RecoveryAction.RETRY_DELIVERY,
        ),
    ],
)
def test_transport_failure_recovery_is_checkpoint_aware(
    monkeypatch,
    checkpoint,
    disposition,
    captured_result,
    retry_mode,
    forbidden_action,
):
    clipboard = []
    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            automation_client.AutomationTransportError(
                "failed",
                checkpoint=checkpoint,
                submission_disposition=disposition,
                captured_result=captured_result,
            )
        ),
    )
    monkeypatch.setattr(
        automation_client,
        "write_clipboard_text",
        clipboard.append,
        raising=False,
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(auto_submit_enabled=True),
    )

    assert result.checkpoint == checkpoint
    assert result.submission_disposition == disposition
    assert result.retry_mode == retry_mode
    assert result.generated_text == captured_result
    assert forbidden_action not in result.recovery_actions
    assert result.fallback_copied is False
    assert clipboard == []


@pytest.mark.parametrize(
    ("checkpoint", "disposition", "captured_result"),
    [
        (
            AutomationCheckpoint.SEND_STARTED,
            SubmissionDisposition.MAYBE_SUBMITTED,
            "",
        ),
        (
            AutomationCheckpoint.SUBMISSION_CONFIRMED,
            SubmissionDisposition.CONFIRMED,
            "",
        ),
        (
            AutomationCheckpoint.RESPONSE_CAPTURED,
            SubmissionDisposition.CONFIRMED,
            "Recovered answer",
        ),
    ],
)
def test_protocol_mismatch_after_send_never_reissues_request(
    monkeypatch,
    checkpoint,
    disposition,
    captured_result,
):
    class UnsafeWarmSession:
        alive = True

        def __init__(self):
            self.closed = False
            self.requests = 0

        def request(self, *args, **kwargs):
            self.requests += 1
            raise automation_client.AutomationProtocolError(
                "incompatible event",
                checkpoint=checkpoint,
                submission_disposition=disposition,
                captured_result=captured_result,
                failure_code="protocol_mismatch",
            )

        def close(self):
            self.closed = True
            self.alive = False

    warm = UnsafeWarmSession()
    automation_client._helper_session = warm
    replacements = []
    monkeypatch.setattr(
        automation_client,
        "_AutomationHelperSession",
        lambda command: replacements.append(command),
    )

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        automation_client._request_from_helper(
            {"prompt": "private prompt"},
            1.0,
        )

    assert raised.value.checkpoint == checkpoint
    assert raised.value.captured_result == captured_result
    assert warm.requests == 1
    assert warm.closed is True
    assert replacements == []


def test_response_captured_event_survives_helper_death():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.require_envelopes = True
    metadata = {
        "protocol_version": AUTOMATION_PROTOCOL_VERSION,
        "request_id": "request-1",
        "run_id": "run-1",
        "checkpoint": "response_captured",
        "submission_disposition": "confirmed",
        "attempt": 1,
    }
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": "response_captured",
                "generated_text": "Recovered answer",
            }
        )
    )
    session.responses.put(None)

    with pytest.raises(automation_client.AutomationTransportError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.checkpoint == AutomationCheckpoint.RESPONSE_CAPTURED
    assert raised.value.captured_result == "Recovered answer"


def test_response_captured_event_survives_later_protocol_mismatch():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    metadata = {
        "protocol_version": AUTOMATION_PROTOCOL_VERSION,
        "request_id": "request-1",
        "run_id": "run-1",
        "checkpoint": "response_captured",
        "submission_disposition": "confirmed",
        "attempt": 1,
    }
    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": "response_captured",
                "generated_text": "Recovered answer",
            }
        )
    )
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": "progress",
                "protocol_version": AUTOMATION_PROTOCOL_VERSION + 1,
                "stage": "cleanup",
                "message": "cleanup",
            }
        )
    )
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == "protocol_mismatch"
    assert raised.value.checkpoint == AutomationCheckpoint.RESPONSE_CAPTURED
    assert raised.value.captured_result == "Recovered answer"


@pytest.mark.parametrize(
    ("event_update", "failure_code"),
    [
        ({"checkpoint": "unknown"}, "protocol_checkpoint_invalid"),
        ({"attempt": 0}, "protocol_attempt_invalid"),
        ({"request_id": "other"}, "protocol_request_mismatch"),
        ({"run_id": "other"}, "protocol_run_mismatch"),
        ({"_event": "unexpected"}, "protocol_event_invalid"),
    ],
)
def test_helper_session_rejects_malformed_envelope_metadata(
    event_update,
    failure_code,
):
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    event = {
        "_event": "progress",
        "protocol_version": AUTOMATION_PROTOCOL_VERSION,
        "request_id": "request-1",
        "run_id": "run-1",
        "checkpoint": "destination_verified",
        "submission_disposition": "not_attempted",
        "attempt": 1,
        "stage": "destination-verified",
        "message": "Verified",
        **event_update,
    }
    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put(json.dumps(event))
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == failure_code


def test_helper_session_rejects_out_of_order_checkpoint():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    def event(checkpoint):
        return json.dumps(
            {
                "_event": "progress",
                "protocol_version": AUTOMATION_PROTOCOL_VERSION,
                "request_id": "request-1",
                "run_id": "run-1",
                "checkpoint": checkpoint,
                "submission_disposition": "confirmed",
                "attempt": 1,
                "stage": checkpoint.replace("_", "-"),
                "message": checkpoint,
            }
        )

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put(event("submission_confirmed"))
    session.responses.put(event("composer_verified"))
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == "protocol_checkpoint_order"


def test_helper_session_rejects_preparing_checkpoint_regression():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    def event(checkpoint, disposition):
        return json.dumps(
            {
                "_event": "progress",
                "protocol_version": AUTOMATION_PROTOCOL_VERSION,
                "request_id": "request-1",
                "run_id": "run-1",
                "checkpoint": checkpoint,
                "submission_disposition": disposition,
                "attempt": 1,
                "stage": "test",
                "message": "test",
            }
        )

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put(event("send_started", "maybe_submitted"))
    session.responses.put(event("preparing", "not_attempted"))
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == "protocol_checkpoint_order"


def test_helper_session_rejects_empty_response_capture_event():
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
                "_event": "response_captured",
                "protocol_version": AUTOMATION_PROTOCOL_VERSION,
                "request_id": "request-1",
                "run_id": "run-1",
                "checkpoint": "response_captured",
                "submission_disposition": "confirmed",
                "attempt": 1,
                "generated_text": "",
            }
        )
    )
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == "protocol_response_invalid"


def test_helper_session_rejects_disposition_regression_after_send():
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
                "protocol_version": AUTOMATION_PROTOCOL_VERSION,
                "request_id": "request-1",
                "run_id": "run-1",
                "checkpoint": "send_started",
                "submission_disposition": "not_attempted",
                "attempt": 1,
                "stage": "send-started",
                "message": "Send activated",
            }
        )
    )
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == "protocol_disposition_order"


def test_malformed_optional_result_fields_cannot_lose_confirmed_checkpoint(
    monkeypatch,
):
    monkeypatch.setattr(
        automation_client,
        "_request_from_helper",
        lambda *args, **kwargs: {
            "submitted": True,
            "submission_confirmed": True,
            "checkpoint": "submission_confirmed",
            "submission_disposition": "confirmed",
            "_timings": None,
            "response_baseline": None,
            "selector_ids": None,
            "chatgpt_hwnd": "invalid",
        },
    )

    result = automation_client.submit_via_worker(
        "private prompt",
        "PromptMeld",
        AppSettings(auto_submit_enabled=True),
    )

    assert result.submitted is True
    assert result.checkpoint == AutomationCheckpoint.SUBMISSION_CONFIRMED
    assert result.submission_disposition == SubmissionDisposition.CONFIRMED
    assert result.chatgpt_hwnd == 0


@pytest.mark.parametrize(
    ("checkpoint", "disposition", "event_type", "captured_result"),
    [
        ("preparing", "not_attempted", "progress", ""),
        ("destination_verified", "not_attempted", "progress", ""),
        ("composer_verified", "not_attempted", "progress", ""),
        ("send_started", "maybe_submitted", "progress", ""),
        ("submission_confirmed", "confirmed", "progress", ""),
        ("response_captured", "confirmed", "response_captured", "answer"),
    ],
)
def test_helper_session_no_progress_watchdog_reports_last_checkpoint(
    monkeypatch,
    checkpoint,
    disposition,
    event_type,
    captured_result,
):
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    ticks = iter((0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr(
        automation_client.time,
        "monotonic",
        lambda: next(ticks),
    )
    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put(
        json.dumps(
            {
                "_event": event_type,
                "protocol_version": AUTOMATION_PROTOCOL_VERSION,
                "request_id": "request-1",
                "run_id": "run-1",
                "checkpoint": checkpoint,
                "submission_disposition": disposition,
                "attempt": 1,
                "stage": checkpoint,
                "message": "progress",
                "generated_text": captured_result,
            }
        )
    )
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationTransportError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == "helper_stalled"
    assert raised.value.checkpoint == AutomationCheckpoint(checkpoint)
    assert raised.value.submission_disposition == SubmissionDisposition(
        disposition
    )
    assert raised.value.captured_result == captured_result


@pytest.mark.parametrize(
    ("checkpoint", "disposition", "event_type", "captured_result"),
    [
        ("preparing", "not_attempted", "progress", ""),
        ("destination_verified", "not_attempted", "progress", ""),
        ("composer_verified", "not_attempted", "progress", ""),
        ("send_started", "maybe_submitted", "progress", ""),
        ("submission_confirmed", "confirmed", "progress", ""),
        ("response_captured", "confirmed", "response_captured", "answer"),
    ],
)
def test_cooperative_cancel_carries_each_helper_checkpoint(
    checkpoint,
    disposition,
    event_type,
    captured_result,
):
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    metadata = {
        "protocol_version": AUTOMATION_PROTOCOL_VERSION,
        "request_id": "request-1",
        "run_id": "run-1",
        "checkpoint": checkpoint,
        "submission_disposition": disposition,
        "attempt": 1,
    }
    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": event_type,
                "stage": checkpoint,
                "message": "progress",
                "generated_text": captured_result,
            }
        )
    )
    session.responses.put(json.dumps({**metadata, "_event": "cancel_ack"}))
    session.responses.put(
        json.dumps(
            {
                **metadata,
                "_event": "result",
                "payload": {
                    "submitted": disposition == "confirmed",
                    "cancelled": True,
                },
            }
        )
    )
    session.require_envelopes = True
    cancellation_checks = iter((False, True, True, True))

    result = session.request(
        {
            "prompt": "private prompt",
            "request_id": "request-1",
            "run_id": "run-1",
        },
        1.0,
        is_cancelled=lambda: next(cancellation_checks),
    )

    commands = [
        json.loads(line)
        for line in session.process.stdin.getvalue().splitlines()
    ]
    assert result["cancelled"] is True
    assert result.get("generated_text", "") == captured_result
    assert commands[1]["_command"] == "cancel"
    assert commands[1]["checkpoint"] == checkpoint


def test_helper_close_waits_for_cooperative_grace_before_termination():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.waits = []
            self.terminated = False
            self.killed = False

        def poll(self):
            return 0 if self.terminated or self.killed else None

        def wait(self, timeout):
            self.waits.append(timeout)
            if not self.terminated:
                raise automation_client.subprocess.TimeoutExpired(
                    "helper",
                    timeout,
                )
            return 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()

    session.close()

    command = json.loads(session.process.stdin.getvalue())
    assert command["_command"] == "shutdown"
    assert session.process.waits == [
        automation_client.CANCELLATION_GRACE_SECONDS,
        1.0,
    ]
    assert session.process.terminated is True
    assert session.process.killed is False


def test_helper_session_rejects_malformed_json():
    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    session = object.__new__(automation_client._AutomationHelperSession)
    session.process = FakeProcess()
    session.responses = queue.Queue()
    session.responses.put("not-json")
    session.require_envelopes = True

    with pytest.raises(automation_client.AutomationProtocolError) as raised:
        session.request(
            {
                "prompt": "private prompt",
                "request_id": "request-1",
                "run_id": "run-1",
            },
            1.0,
        )

    assert raised.value.failure_code == "protocol_malformed"


def test_incompatible_warm_helper_is_restarted_once(monkeypatch):
    class IncompatibleWarmSession:
        alive = True

        def __init__(self):
            self.closed = False

        def request(self, *args, **kwargs):
            raise automation_client.AutomationProtocolError(
                "old worker",
                failure_code="protocol_mismatch",
            )

        def close(self):
            self.closed = True
            self.alive = False

    created = []

    class CompatibleSession:
        alive = True

        def __init__(self, command):
            created.append(self)

        def request(self, *args, **kwargs):
            return {"submitted": True}

        def close(self):
            self.alive = False

    warm = IncompatibleWarmSession()
    automation_client._helper_session = warm
    monkeypatch.setattr(
        automation_client,
        "_AutomationHelperSession",
        CompatibleSession,
    )
    monkeypatch.setattr(
        automation_client,
        "_schedule_helper_shutdown",
        lambda session: None,
    )

    response = automation_client._request_from_helper(
        {"prompt": "private prompt"},
        1.0,
    )

    assert response["submitted"] is True
    assert warm.closed is True
    assert len(created) == 1


def test_helper_startup_retries_protocol_handshake_once(monkeypatch):
    attempts = []

    class Session:
        alive = True

        def __init__(self, command):
            attempts.append(command)
            if len(attempts) == 1:
                raise automation_client.AutomationProtocolError(
                    "incompatible",
                    failure_code="protocol_mismatch",
                )

        def request(self, *args, **kwargs):
            return {"submitted": True}

        def close(self):
            self.alive = False

    monkeypatch.setattr(automation_client, "_AutomationHelperSession", Session)
    monkeypatch.setattr(
        automation_client,
        "_schedule_helper_shutdown",
        lambda session: None,
    )

    response = automation_client._request_from_helper(
        {"prompt": "private prompt"},
        1.0,
    )

    assert response["submitted"] is True
    assert len(attempts) == 2
