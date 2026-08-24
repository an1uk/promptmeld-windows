from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from .automation_protocol import (
    AUTOMATION_PROTOCOL_VERSION,
    CANCELLATION_GRACE_SECONDS,
    ApplyVerification,
    AutomationCheckpoint,
    RecoveryAction,
    SubmissionDisposition,
    checkpoint_is_at_least,
    coerce_checkpoint,
    coerce_submission_disposition,
    disposition_for_checkpoint,
    recovery_actions_for,
    submission_disposition_is_at_least,
)
from .branding import AUTOMATION_EXECUTABLE_NAME
from .chatgpt import DEFAULT_RESPONSE_TIMEOUT_SECONDS
from .models import AppSettings, ResponseAnchor, SubmissionResult

LOGGER = logging.getLogger(__name__)
HELPER_IDLE_SECONDS = 45.0


class AutomationTransportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        checkpoint: AutomationCheckpoint = AutomationCheckpoint.PREPARING,
        submission_disposition: SubmissionDisposition | None = None,
        captured_result: str = "",
        response_anchor: ResponseAnchor | None = None,
        failure_code: str = "helper_failed",
    ):
        super().__init__(message)
        self.checkpoint = checkpoint
        self.submission_disposition = (
            submission_disposition or disposition_for_checkpoint(checkpoint)
        )
        self.captured_result = captured_result
        self.response_anchor = response_anchor
        self.failure_code = failure_code


class AutomationCancelled(AutomationTransportError):
    pass


class AutomationProtocolError(AutomationTransportError):
    pass


def _helper_command() -> list[str]:
    return (
        [
            str(
                Path(sys.executable).parent
                / "_internal"
                / AUTOMATION_EXECUTABLE_NAME
            )
        ]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "promptmeld.automation_worker"]
    )


def _response_anchor_from_raw(value: object) -> ResponseAnchor | None:
    if not isinstance(value, dict):
        return None
    raw_baseline = value.get("baseline_tokens", ())
    baseline = raw_baseline if isinstance(raw_baseline, (list, tuple)) else ()
    return ResponseAnchor(
        destination_token=str(value.get("destination_token", "")),
        destination_kind=str(value.get("destination_kind", "")),
        destination_name=str(value.get("destination_name", "")),
        destination_hwnd=_int_from_raw(value.get("destination_hwnd", 0)),
        baseline_tokens=tuple(str(token) for token in baseline),
        user_message_baseline_tokens=tuple(
            str(token)
            for token in value.get("user_message_baseline_tokens", ())
        ),
        prompt_digest=str(value.get("prompt_digest", "")),
        submitted_message_token=str(value.get("submitted_message_token", "")),
        conversation_container_token=str(
            value.get("conversation_container_token", "")
        ),
        response_control_token=str(value.get("response_control_token", "")),
    )


def _recovery_actions_from_raw(
    value: object,
    disposition: SubmissionDisposition,
    *,
    has_result: bool,
) -> tuple[RecoveryAction, ...]:
    if isinstance(value, (list, tuple)):
        parsed: list[RecoveryAction] = []
        for item in value:
            try:
                parsed.append(RecoveryAction(str(item)))
            except ValueError:
                continue
        if parsed:
            return tuple(parsed)
    return recovery_actions_for(disposition, has_result=has_result)


def _strings_from_raw(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)


def _timings_from_raw(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    timings: list[tuple[str, float]] = []
    for timing in value:
        if not isinstance(timing, dict):
            continue
        try:
            milliseconds = float(timing.get("milliseconds", 0.0))
        except (TypeError, ValueError):
            continue
        timings.append((str(timing.get("stage", "unknown")), milliseconds))
    return tuple(timings)


def _int_from_raw(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class _AutomationHelperSession:
    def __init__(self, command: list[str]):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [*command, "--server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creation_flags,
        )
        self.responses: queue.Queue[str | None] = queue.Queue()
        self.reader = threading.Thread(
            target=self._read_responses,
            name="PromptMeldAutomationReader",
            daemon=True,
        )
        self.reader.start()
        try:
            self.protocol_version = self._await_handshake()
            self.require_envelopes = True
        except Exception:
            self.close()
            raise

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def _read_responses(self) -> None:
        stdout = self.process.stdout
        if stdout is None:
            self.responses.put(None)
            return
        try:
            for line in stdout:
                self.responses.put(line)
        finally:
            self.responses.put(None)

    def _await_handshake(self) -> int:
        try:
            raw = self.responses.get(timeout=5.0)
        except queue.Empty as exc:
            raise AutomationProtocolError(
                "Automation helper did not provide a protocol handshake.",
                failure_code="protocol_handshake_timeout",
            ) from exc
        if raw is None:
            raise AutomationProtocolError(
                "Automation helper stopped before its protocol handshake.",
                failure_code="protocol_handshake_failed",
            )
        try:
            decoded = json.loads(raw)
            version = int(decoded.get("protocol_version", 0))
            attempt = int(decoded.get("attempt", -1))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AutomationProtocolError(
                "Automation helper returned an invalid protocol handshake.",
                failure_code="protocol_handshake_invalid",
            ) from exc
        if (
            decoded.get("_event") != "hello"
            or version != AUTOMATION_PROTOCOL_VERSION
            or str(decoded.get("request_id", ""))
            or str(decoded.get("run_id", ""))
            or str(decoded.get("checkpoint", ""))
            != AutomationCheckpoint.PREPARING.value
            or str(decoded.get("submission_disposition", ""))
            != SubmissionDisposition.NOT_ATTEMPTED.value
            or attempt != 0
        ):
            raise AutomationProtocolError(
                "Automation helper protocol is incompatible with this PromptMeld build.",
                failure_code="protocol_mismatch",
            )
        return version

    def _send(self, payload: dict[str, object]) -> None:
        if not self.alive or self.process.stdin is None:
            raise RuntimeError("Automation helper is not running.")
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def request(
        self,
        payload: dict[str, object],
        timeout_seconds: float | None,
        progress_callback: Callable[[str, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        request_id = str(payload.get("request_id", "") or uuid.uuid4())
        run_id = str(payload.get("run_id", ""))
        payload["request_id"] = request_id
        payload["_protocol_version"] = AUTOMATION_PROTOCOL_VERSION
        payload.setdefault("checkpoint", AutomationCheckpoint.PREPARING.value)
        payload.setdefault("attempt", 1)
        self._send(payload)
        stall_timeout = max(1.0, float(timeout_seconds or 15.0))
        last_activity = time.monotonic()
        cancellation_sent = False
        cancellation_deadline: float | None = None
        checkpoint = AutomationCheckpoint.PREPARING
        disposition = SubmissionDisposition.NOT_ATTEMPTED
        captured_result = ""
        response_anchor: ResponseAnchor | None = None
        current_attempt = 1
        require_envelopes = bool(getattr(self, "require_envelopes", False))
        while True:
            now = time.monotonic()
            if (
                is_cancelled is not None
                and is_cancelled()
                and not cancellation_sent
            ):
                try:
                    self._send(
                        {
                            "_command": "cancel",
                            "_protocol_version": AUTOMATION_PROTOCOL_VERSION,
                            "request_id": request_id,
                            "run_id": run_id,
                            "checkpoint": checkpoint.value,
                            "attempt": current_attempt,
                        }
                    )
                except (BrokenPipeError, OSError, RuntimeError) as exc:
                    raise AutomationTransportError(
                        "Automation helper stopped while cancellation was requested.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="helper_cancel_transport_failed",
                    ) from exc
                cancellation_sent = True
                cancellation_deadline = now + CANCELLATION_GRACE_SECONDS
            if cancellation_deadline is not None and now >= cancellation_deadline:
                raise AutomationCancelled(
                    "Automation helper did not acknowledge cancellation safely.",
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                    failure_code="cancellation_timeout",
                )
            if now - last_activity >= stall_timeout:
                raise AutomationTransportError(
                    "Automation helper stopped making progress.",
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                    failure_code="helper_stalled",
                )
            try:
                response = self.responses.get(timeout=0.1)
            except queue.Empty:
                continue
            if response is None:
                raise AutomationTransportError(
                    "Automation helper stopped unexpectedly.",
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                )
            try:
                decoded = json.loads(response)
            except json.JSONDecodeError as exc:
                raise AutomationProtocolError(
                    "Automation helper returned malformed JSON.",
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                    failure_code="protocol_malformed",
                ) from exc
            if not isinstance(decoded, dict):
                raise AutomationProtocolError(
                    "Automation helper returned an invalid response envelope.",
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                    failure_code="protocol_invalid",
                )
            event = str(decoded.get("_event", ""))
            if require_envelopes and event != "hello":
                if event not in {
                    "heartbeat",
                    "cancel_ack",
                    "response_captured",
                    "progress",
                    "result",
                }:
                    raise AutomationProtocolError(
                        "Automation helper returned an unknown event type.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_event_invalid",
                    )
                try:
                    event_version = int(decoded.get("protocol_version", 0))
                except (TypeError, ValueError) as exc:
                    raise AutomationProtocolError(
                        "Automation helper response omitted its protocol version.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_mismatch",
                    ) from exc
                if event_version != AUTOMATION_PROTOCOL_VERSION:
                    raise AutomationProtocolError(
                        "Automation helper response used an incompatible protocol.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_mismatch",
                    )
                if str(decoded.get("request_id", "")) != request_id:
                    raise AutomationProtocolError(
                        "Automation helper response belonged to another request.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_request_mismatch",
                    )
                if str(decoded.get("run_id", "")) != run_id:
                    raise AutomationProtocolError(
                        "Automation helper response belonged to another run.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_run_mismatch",
                    )
                try:
                    current_attempt = int(decoded["attempt"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise AutomationProtocolError(
                        "Automation helper response omitted its attempt number.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_attempt_invalid",
                    ) from exc
                if current_attempt < 1:
                    raise AutomationProtocolError(
                        "Automation helper response used an invalid attempt number.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_attempt_invalid",
                    )
            last_activity = time.monotonic()
            raw_checkpoint = decoded.get("checkpoint", checkpoint.value)
            if require_envelopes:
                try:
                    event_checkpoint = AutomationCheckpoint(str(raw_checkpoint))
                except ValueError as exc:
                    raise AutomationProtocolError(
                        "Automation helper response used an unknown checkpoint.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_checkpoint_invalid",
                    ) from exc
            else:
                event_checkpoint = coerce_checkpoint(raw_checkpoint)
            if (
                require_envelopes
                and event_checkpoint == AutomationCheckpoint.PREPARING
                and checkpoint != AutomationCheckpoint.PREPARING
            ):
                raise AutomationProtocolError(
                    "Automation helper reported an out-of-order checkpoint.",
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                    failure_code="protocol_checkpoint_order",
                )
            if event_checkpoint == AutomationCheckpoint.PREPARING:
                raw_disposition = decoded.get(
                    "submission_disposition",
                    SubmissionDisposition.NOT_ATTEMPTED.value,
                )
                try:
                    preparing_disposition = SubmissionDisposition(
                        str(raw_disposition)
                    )
                except ValueError as exc:
                    raise AutomationProtocolError(
                        "Automation helper response used an unknown submission disposition.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_disposition_invalid",
                    ) from exc
                if preparing_disposition != SubmissionDisposition.NOT_ATTEMPTED:
                    raise AutomationProtocolError(
                        "Automation helper reported submission without a matching checkpoint.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_disposition_order",
                    )
            if event_checkpoint != AutomationCheckpoint.PREPARING:
                if not checkpoint_is_at_least(event_checkpoint, checkpoint):
                    raise AutomationProtocolError(
                        "Automation helper reported an out-of-order checkpoint.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_checkpoint_order",
                    )
                checkpoint = event_checkpoint
                raw_disposition = decoded.get(
                    "submission_disposition",
                    disposition_for_checkpoint(checkpoint).value,
                )
                if require_envelopes:
                    try:
                        event_disposition = SubmissionDisposition(
                            str(raw_disposition)
                        )
                    except ValueError as exc:
                        raise AutomationProtocolError(
                            "Automation helper response used an unknown submission disposition.",
                            checkpoint=checkpoint,
                            submission_disposition=disposition,
                            captured_result=captured_result,
                            response_anchor=response_anchor,
                            failure_code="protocol_disposition_invalid",
                        ) from exc
                else:
                    event_disposition = coerce_submission_disposition(
                        raw_disposition
                    )
                expected_disposition = (
                    disposition
                    if checkpoint
                    in {
                        AutomationCheckpoint.COMPLETE,
                        AutomationCheckpoint.CANCELLED,
                    }
                    else disposition_for_checkpoint(checkpoint)
                )
                if not submission_disposition_is_at_least(
                    event_disposition,
                    expected_disposition,
                ) or not submission_disposition_is_at_least(
                    event_disposition,
                    disposition,
                ):
                    raise AutomationProtocolError(
                        "Automation helper response regressed submission ownership.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_disposition_order",
                    )
                disposition = event_disposition
            if event == "heartbeat" or event == "cancel_ack":
                continue
            if event == "response_captured":
                value = decoded.get("generated_text", "")
                if not isinstance(value, str) or not value.strip():
                    raise AutomationProtocolError(
                        "Automation helper acknowledged an empty captured response.",
                        checkpoint=checkpoint,
                        submission_disposition=disposition,
                        captured_result=captured_result,
                        response_anchor=response_anchor,
                        failure_code="protocol_response_invalid",
                    )
                captured_result = value
                response_anchor = _response_anchor_from_raw(
                    decoded.get("response_anchor")
                )
                checkpoint = AutomationCheckpoint.RESPONSE_CAPTURED
                disposition = SubmissionDisposition.CONFIRMED
                continue
            if event == "progress":
                if progress_callback is not None:
                    try:
                        progress_callback(
                            str(decoded.get("stage", "")),
                            str(decoded.get("message", "")),
                        )
                    except Exception:
                        LOGGER.debug(
                            "Automation progress callback failed",
                            exc_info=True,
                        )
                continue
            final = decoded.get("payload") if event == "result" else decoded
            if not isinstance(final, dict):
                raise AutomationProtocolError(
                    "Automation helper returned an invalid result payload.",
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                    failure_code="protocol_result_invalid",
                )
            if error := final.get("error"):
                raise AutomationTransportError(
                    str(error),
                    checkpoint=checkpoint,
                    submission_disposition=disposition,
                    captured_result=captured_result,
                    response_anchor=response_anchor,
                    failure_code=str(final.get("failure_code", "helper_failed")),
                )
            if captured_result and not final.get("generated_text"):
                final["generated_text"] = captured_result
            if response_anchor is not None and not final.get("response_anchor"):
                final["response_anchor"] = {
                    "destination_token": response_anchor.destination_token,
                    "destination_kind": response_anchor.destination_kind,
                    "destination_name": response_anchor.destination_name,
                    "destination_hwnd": response_anchor.destination_hwnd,
                    "baseline_tokens": list(response_anchor.baseline_tokens),
                    "user_message_baseline_tokens": list(
                        response_anchor.user_message_baseline_tokens
                    ),
                    "prompt_digest": response_anchor.prompt_digest,
                    "submitted_message_token": response_anchor.submitted_message_token,
                    "conversation_container_token": (
                        response_anchor.conversation_container_token
                    ),
                    "response_control_token": (
                        response_anchor.response_control_token
                    ),
                }
            if require_envelopes:
                final["checkpoint"] = checkpoint.value
                final["submission_disposition"] = disposition.value
            else:
                final.setdefault("checkpoint", checkpoint.value)
                final.setdefault("submission_disposition", disposition.value)
            return final

    def close(self) -> None:
        if self.alive and self.process.stdin is not None:
            try:
                self._send(
                    {
                        "_command": "shutdown",
                        "_protocol_version": AUTOMATION_PROTOCOL_VERSION,
                        "request_id": "",
                        "run_id": "",
                        "checkpoint": AutomationCheckpoint.PREPARING.value,
                        "attempt": 1,
                    }
                )
            except (BrokenPipeError, OSError):
                pass
        try:
            self.process.wait(timeout=CANCELLATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.process.kill()


_helper_lock = threading.Lock()
_helper_session: _AutomationHelperSession | None = None
_helper_idle_timer: threading.Timer | None = None


def _stop_helper_if_current(session: _AutomationHelperSession) -> None:
    global _helper_session, _helper_idle_timer
    with _helper_lock:
        if _helper_session is not session:
            return
        _helper_session = None
        _helper_idle_timer = None
        session.close()
        LOGGER.info("Stopped idle ChatGPT automation helper")


def _schedule_helper_shutdown(session: _AutomationHelperSession) -> None:
    global _helper_idle_timer
    if _helper_idle_timer is not None:
        _helper_idle_timer.cancel()
    _helper_idle_timer = threading.Timer(
        HELPER_IDLE_SECONDS,
        _stop_helper_if_current,
        args=(session,),
    )
    _helper_idle_timer.daemon = True
    _helper_idle_timer.start()


def shutdown_automation_helper() -> None:
    global _helper_session, _helper_idle_timer
    if not _helper_lock.acquire(timeout=0.1):
        LOGGER.info(
            "Automation helper is busy; it will close when the app exits"
        )
        return
    try:
        if _helper_idle_timer is not None:
            _helper_idle_timer.cancel()
            _helper_idle_timer = None
        session = _helper_session
        _helper_session = None
        if session is not None:
            session.close()
    finally:
        _helper_lock.release()


def _request_from_helper(
    payload: dict[str, object],
    timeout_seconds: float | None,
    progress_callback: Callable[[str, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    global _helper_session
    with _helper_lock:
        for request_attempt in range(2):
            if _helper_session is None or not _helper_session.alive:
                if _helper_session is not None:
                    _helper_session.close()
                last_protocol_error: AutomationProtocolError | None = None
                for handshake_attempt in range(2):
                    try:
                        _helper_session = _AutomationHelperSession(
                            _helper_command()
                        )
                        break
                    except AutomationProtocolError as exc:
                        last_protocol_error = exc
                        LOGGER.warning(
                            "Automation helper handshake failed on attempt %s: %s",
                            handshake_attempt + 1,
                            exc.failure_code,
                        )
                else:
                    assert last_protocol_error is not None
                    raise last_protocol_error
                LOGGER.info("Started warm ChatGPT automation helper")
            session = _helper_session
            try:
                if is_cancelled is None:
                    response = session.request(
                        payload,
                        timeout_seconds,
                        progress_callback,
                    )
                else:
                    response = session.request(
                        payload,
                        timeout_seconds,
                        progress_callback,
                        is_cancelled,
                    )
            except AutomationProtocolError as exc:
                session.close()
                _helper_session = None
                if (
                    request_attempt == 0
                    and exc.failure_code == "protocol_mismatch"
                    and exc.submission_disposition
                    == SubmissionDisposition.NOT_ATTEMPTED
                    and not checkpoint_is_at_least(
                        exc.checkpoint,
                        AutomationCheckpoint.SEND_STARTED,
                    )
                    and not exc.captured_result
                ):
                    LOGGER.warning(
                        "Restarting incompatible warm automation helper once"
                    )
                    continue
                raise
            except Exception:
                session.close()
                _helper_session = None
                raise
            _schedule_helper_shutdown(session)
            return response
        raise AutomationProtocolError(
            "Automation helper remained incompatible after one restart.",
            failure_code="protocol_mismatch",
        )


def submit_via_worker(
    prompt: str,
    project_name: str,
    settings: AppSettings,
    *,
    source_hwnd: int | None = None,
    source_is_editable: bool = False,
    source_text: str = "",
    source_app: str = "",
    replace_selected_text: bool | None = None,
    copy_generated_text: bool | None = None,
    capture_generated_text: bool = False,
    response_timeout_seconds: float | None = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    redaction_replacements: dict[str, str] | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    run_id: str = "",
    operation: str = "deliver",
    response_baseline: tuple[str, ...] = (),
    response_anchor: ResponseAnchor | None = None,
) -> SubmissionResult:
    effective_replace = (
        settings.replace_selected_text_enabled
        if replace_selected_text is None
        else replace_selected_text
    )
    effective_copy = (
        settings.copy_generated_text_enabled
        if copy_generated_text is None
        else copy_generated_text
    )
    request_id = str(uuid.uuid4())
    payload = {
        "_protocol_version": AUTOMATION_PROTOCOL_VERSION,
        "request_id": request_id,
        "run_id": run_id or str(uuid.uuid4()),
        "checkpoint": AutomationCheckpoint.PREPARING.value,
        "attempt": 1,
        "operation": operation,
        "prompt": prompt,
        "project_name": project_name,
        "timeout_seconds": settings.automation_timeout_seconds,
        "response_timeout_seconds": response_timeout_seconds,
        "chatgpt_uri": settings.chatgpt_uri,
        "project_uri": settings.project_uri,
        "auto_submit": settings.auto_submit_enabled,
        "temporary_chat": settings.temporary_chat_enabled,
        # Source content and handles deliberately remain in the main process.
        # A requested replacement makes response capture mandatory; the main
        # process applies it only through a verified source adapter.
        "replace_selected_text": False,
        "copy_generated_text": effective_copy,
        "capture_generated_text": bool(capture_generated_text or effective_replace),
        "redaction_replacements": dict(redaction_replacements or {}),
        "response_baseline": list(response_baseline),
        "response_anchor": (
            {
                "destination_token": response_anchor.destination_token,
                "destination_kind": response_anchor.destination_kind,
                "destination_name": response_anchor.destination_name,
                "destination_hwnd": response_anchor.destination_hwnd,
                "baseline_tokens": list(response_anchor.baseline_tokens),
                "user_message_baseline_tokens": list(
                    response_anchor.user_message_baseline_tokens
                ),
                "prompt_digest": response_anchor.prompt_digest,
                "submitted_message_token": response_anchor.submitted_message_token,
                "conversation_container_token": (
                    response_anchor.conversation_container_token
                ),
                "response_control_token": response_anchor.response_control_token,
            }
            if response_anchor is not None
            else None
        ),
    }
    try:
        # This is a no-activity watchdog, not a total run deadline. The worker
        # pulses during navigation and long response waits, so a healthy
        # indefinite response wait remains possible while a stuck UIA call is
        # still bounded.
        helper_timeout = max(
            15.0,
            settings.automation_timeout_seconds + 5.0,
        )
        request_args = (
            payload,
            helper_timeout,
            progress_callback,
        )
        raw = (
            _request_from_helper(*request_args)
            if is_cancelled is None
            else _request_from_helper(
                *request_args,
                is_cancelled=is_cancelled,
            )
        )
        raw_timings = raw.get("_timings", ())
        for stage, milliseconds in _timings_from_raw(raw_timings):
            LOGGER.info(
                "ChatGPT automation timing - %s: %s ms",
                stage,
                milliseconds,
            )
        checkpoint = coerce_checkpoint(raw.get("checkpoint", "preparing"))
        disposition = coerce_submission_disposition(
            raw.get(
                "submission_disposition",
                disposition_for_checkpoint(checkpoint).value,
            )
        )
        generated_text = (
            str(raw.get("generated_text", ""))
            if isinstance(raw.get("generated_text", ""), str)
            else ""
        )
        LOGGER.info(
            "ChatGPT automation result checkpoint=%s disposition=%s "
            "submitted=%s has_response=%s failure_code=%s selectors=%s",
            checkpoint.value,
            disposition.value,
            bool(raw.get("submitted", False)),
            bool(generated_text),
            str(raw.get("failure_code", "") or "none"),
            ",".join(_strings_from_raw(raw.get("selector_ids", ())))
            or "none",
        )
        try:
            apply_verification = ApplyVerification(
                str(raw.get("apply_verification", "not_requested"))
            )
        except ValueError:
            apply_verification = ApplyVerification.NOT_REQUESTED
        return SubmissionResult(
            submitted=bool(raw.get("submitted", False)),
            prepared=bool(raw.get("prepared", False)),
            fallback_copied=bool(raw.get("fallback_copied", False)),
            generated_text_copied=bool(
                raw.get("generated_text_copied", False)
            ),
            selection_replaced=bool(raw.get("selection_replaced", False)),
            output_failed=bool(raw.get("output_failed", False)),
            cancelled=bool(raw.get("cancelled", False)),
            message=str(raw.get("message", "")),
            generated_text=generated_text,
            run_id=str(raw.get("run_id", payload["run_id"])),
            failed_stage=str(raw.get("failed_stage", "")),
            failure_code=str(raw.get("failure_code", "")),
            submission_confirmed=bool(raw.get("submission_confirmed", False)),
            retry_mode=str(raw.get("retry_mode", "")),
            recoverable=bool(raw.get("recoverable", False)),
            response_baseline=_strings_from_raw(
                raw.get("response_baseline", ())
            ),
            timings=_timings_from_raw(raw_timings),
            checkpoint=checkpoint,
            submission_disposition=disposition,
            recovery_actions=_recovery_actions_from_raw(
                raw.get("recovery_actions"),
                disposition,
                has_result=bool(generated_text),
            ),
            response_anchor=_response_anchor_from_raw(raw.get("response_anchor")),
            apply_verification=apply_verification,
            selector_ids=_strings_from_raw(raw.get("selector_ids", ())),
            chatgpt_hwnd=_int_from_raw(raw.get("chatgpt_hwnd", 0)),
        )
    except AutomationCancelled as exc:
        LOGGER.info("ChatGPT automation was cancelled")
        submitted = exc.submission_disposition == SubmissionDisposition.CONFIRMED
        return SubmissionResult(
            submitted=submitted,
            cancelled=True,
            message=(
                "Automation stopped after ChatGPT accepted the prompt; ChatGPT "
                "may continue generating the response."
                if submitted
                else (
                    "Automation stopped after Send was activated. Inspect ChatGPT "
                    "before trying again to avoid a duplicate request."
                    if exc.submission_disposition
                    == SubmissionDisposition.MAYBE_SUBMITTED
                    else "Automation stopped before a ChatGPT submission was confirmed."
                )
            ),
            generated_text=exc.captured_result,
            run_id=str(payload["run_id"]),
            failed_stage="cancelling",
            failure_code=exc.failure_code,
            submission_confirmed=submitted,
            retry_mode=("response" if submitted else ""),
            recoverable=exc.submission_disposition != SubmissionDisposition.NOT_ATTEMPTED,
            response_baseline=response_baseline,
            checkpoint=exc.checkpoint,
            submission_disposition=exc.submission_disposition,
            recovery_actions=recovery_actions_for(
                exc.submission_disposition,
                has_result=bool(exc.captured_result),
            ),
            response_anchor=exc.response_anchor,
        )
    except AutomationTransportError as exc:
        LOGGER.exception("ChatGPT automation helper failed")
        disposition = exc.submission_disposition
        submitted = disposition == SubmissionDisposition.CONFIRMED
        has_result = bool(exc.captured_result)
        retry_mode = (
            ""
            if has_result
            else (
                "response"
                if submitted
                else (
                    "inspect"
                    if disposition == SubmissionDisposition.MAYBE_SUBMITTED
                    else "delivery"
                )
            )
        )
        return SubmissionResult(
            submitted=submitted,
            prepared=False,
            fallback_copied=False,
            output_failed=submitted and not has_result,
            generated_text=exc.captured_result,
            message=(
                "The generated result was recovered before the automation helper "
                "stopped. Review or copy it from PromptMeld."
                if has_result
                else (
                    "The automation helper stopped after ChatGPT accepted the "
                    "request. Retry response retrieval; the prompt will not be sent again."
                    if submitted
                    else (
                        "The automation helper stopped after Send was activated. "
                        "Inspect ChatGPT before retrying to avoid a duplicate request."
                        if disposition == SubmissionDisposition.MAYBE_SUBMITTED
                        else (
                            "The automation helper stopped before Send was activated. "
                            "Retry delivery or copy the prepared prompt explicitly."
                        )
                    )
                )
            ),
            run_id=str(payload["run_id"]),
            failed_stage="helper",
            failure_code=exc.failure_code,
            retry_mode=retry_mode,
            recoverable=True,
            submission_confirmed=submitted,
            response_baseline=response_baseline,
            checkpoint=exc.checkpoint,
            submission_disposition=disposition,
            recovery_actions=recovery_actions_for(
                disposition,
                has_result=has_result,
            ),
            response_anchor=exc.response_anchor,
        )
    except Exception as exc:
        LOGGER.exception("Unexpected ChatGPT automation client failure")
        transport = AutomationTransportError(str(exc))
        return SubmissionResult(
            submitted=False,
            message=(
                "PromptMeld could not start its automation companion. The clipboard "
                "was left unchanged; retry or copy the prompt explicitly."
            ),
            run_id=str(payload["run_id"]),
            failed_stage="helper",
            failure_code=transport.failure_code,
            retry_mode="delivery",
            recoverable=True,
            checkpoint=transport.checkpoint,
            submission_disposition=transport.submission_disposition,
            recovery_actions=recovery_actions_for(
                transport.submission_disposition
            ),
        )
