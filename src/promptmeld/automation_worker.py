from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict

from . import display_version
from .automation_protocol import (
    AUTOMATION_PROTOCOL_VERSION,
    CANCELLATION_GRACE_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    AutomationCheckpoint,
    SubmissionDisposition,
    checkpoint_for_stage,
    coerce_checkpoint,
    coerce_submission_disposition,
    disposition_for_checkpoint,
    submission_disposition_is_at_least,
)
from .chatgpt import ChatGPTDesktop, DEFAULT_RESPONSE_TIMEOUT_SECONDS
from .models import DEFAULT_CHATGPT_URI, ResponseAnchor

PER_MONITOR_AWARE_V2 = -4


def _enable_per_monitor_dpi_awareness(
    set_awareness: Callable[[int], bool] | None = None,
) -> bool:
    """Use physical screen coordinates across differently scaled monitors."""

    if sys.platform != "win32":
        return False
    try:
        if set_awareness is None:
            import ctypes
            from ctypes import wintypes

            native_set_awareness = ctypes.WinDLL(
                "user32",
                use_last_error=True,
            ).SetProcessDpiAwarenessContext
            native_set_awareness.argtypes = [ctypes.c_void_p]
            native_set_awareness.restype = wintypes.BOOL
            set_awareness = lambda value: bool(
                native_set_awareness(ctypes.c_void_p(value))
            )
        return bool(set_awareness(PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError):
        # A packaged build declares this in its manifest. This fallback is for
        # source runs and must not prevent the guarded clipboard fallback if
        # Windows has already fixed the process awareness context.
        return False


def _run_self_test() -> int:
    import pythoncom
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys

    pythoncom.CoInitialize()
    try:
        if not callable(Desktop) or not callable(send_keys):
            raise RuntimeError("Automation dependencies are unavailable.")
    finally:
        pythoncom.CoUninitialize()
    sys.stdout.write(json.dumps({"ok": True}))
    sys.stdout.flush()
    return 0


def _process_payload(
    payload: dict[str, object],
    progress_callback: Callable[[str, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    activity_callback: Callable[[], None] | None = None,
    response_captured_callback: (
        Callable[[str, ResponseAnchor | None], None] | None
    ) = None,
) -> dict[str, object]:
    raw_response_timeout = payload.get(
        "response_timeout_seconds",
        DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    )
    adapter = ChatGPTDesktop(
        timeout_seconds=float(payload.get("timeout_seconds", 8.0)),
        response_timeout_seconds=(
            None
            if raw_response_timeout is None
            else float(raw_response_timeout)
        ),
        chatgpt_uri=str(payload.get("chatgpt_uri", DEFAULT_CHATGPT_URI)),
        project_uri=str(payload.get("project_uri", "")),
        progress_callback=progress_callback,
        is_cancelled=is_cancelled,
        activity_callback=activity_callback,
        response_callback=response_captured_callback,
        run_id=str(payload.get("run_id", "")),
    )
    if str(payload.get("operation", "deliver")) == "retrieve_response":
        result = adapter.retrieve_response(
            str(payload.get("prompt", "")),
            response_baseline=tuple(payload.get("response_baseline", ())),
            response_anchor=_response_anchor_from_payload(
                payload.get("response_anchor")
            ),
            redaction_replacements=dict(
                payload.get("redaction_replacements", {})
            ),
        )
        return _serialise_result(adapter, result)
    if str(payload.get("operation", "deliver")) == "check_connection":
        result = adapter.check_connection()
        return _serialise_result(adapter, result)
    submit_kwargs: dict[str, object] = {
        "auto_submit": bool(payload.get("auto_submit", False)),
        "temporary_chat": bool(payload.get("temporary_chat", False)),
    }
    if any(
        key in payload
        for key in (
            "copy_generated_text",
            "capture_generated_text",
            "redaction_replacements",
        )
    ):
        submit_kwargs.update(
            copy_generated_text=bool(payload.get("copy_generated_text", False)),
            capture_generated_text=bool(
                payload.get("capture_generated_text", False)
            ),
            redaction_replacements={
                str(placeholder): str(original)
                for placeholder, original in dict(
                    payload.get("redaction_replacements", {})
                ).items()
            },
        )
    result = adapter.submit(
        str(payload["prompt"]),
        str(payload["project_name"]),
        **submit_kwargs,
    )
    return _serialise_result(adapter, result)


def _serialise_result(adapter: ChatGPTDesktop, result) -> dict[str, object]:
    response = asdict(result)
    response["_timings"] = getattr(adapter, "timings", [])
    checkpoint = getattr(
        adapter,
        "checkpoint",
        getattr(result, "checkpoint", AutomationCheckpoint.PREPARING),
    )
    disposition = getattr(
        adapter,
        "submission_disposition",
        getattr(
            result,
            "submission_disposition",
            disposition_for_checkpoint(checkpoint),
        ),
    )
    response["checkpoint"] = checkpoint.value
    response["submission_disposition"] = disposition.value
    response["selector_ids"] = sorted(getattr(adapter, "selector_ids", ()))
    response["chatgpt_hwnd"] = int(getattr(adapter, "chatgpt_hwnd", 0) or 0)
    response_anchor = getattr(adapter, "response_anchor", None)
    if response_anchor is not None:
        response["response_anchor"] = asdict(response_anchor)
    return response


def _response_anchor_from_payload(value: object) -> ResponseAnchor | None:
    if not isinstance(value, dict):
        return None
    return ResponseAnchor(
        destination_token=str(value.get("destination_token", "")),
        destination_kind=str(value.get("destination_kind", "")),
        destination_name=str(value.get("destination_name", "")),
        destination_hwnd=int(value.get("destination_hwnd", 0) or 0),
        baseline_tokens=tuple(
            str(token) for token in value.get("baseline_tokens", ())
        ),
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


def _run_server() -> int:
    output_lock = threading.Lock()
    active_lock = threading.Lock()
    active: dict[str, object] = {}

    def write_message(message: dict[str, object]) -> None:
        with output_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def envelope(
        event: str,
        request_id: str,
        run_id: str,
        checkpoint: AutomationCheckpoint,
        disposition: SubmissionDisposition,
        attempt: int,
        **values: object,
    ) -> dict[str, object]:
        return {
            "_event": event,
            "protocol_version": AUTOMATION_PROTOCOL_VERSION,
            "request_id": request_id,
            "run_id": run_id,
            "checkpoint": checkpoint.value,
            "submission_disposition": disposition.value,
            "attempt": max(1, int(attempt)),
            **values,
        }

    write_message(
        {
            "_event": "hello",
            "protocol_version": AUTOMATION_PROTOCOL_VERSION,
            "request_id": "",
            "run_id": "",
            "checkpoint": AutomationCheckpoint.PREPARING.value,
            "submission_disposition": SubmissionDisposition.NOT_ATTEMPTED.value,
            "attempt": 0,
            "worker_version": display_version(),
        }
    )

    def process_request(payload: dict[str, object], cancel_event: threading.Event) -> None:
        request_id = str(payload.get("request_id", ""))
        run_id = str(payload.get("run_id", ""))
        state = {
            "checkpoint": AutomationCheckpoint.PREPARING,
            "disposition": SubmissionDisposition.NOT_ATTEMPTED,
            "last_heartbeat": 0.0,
            "attempt": 1,
        }
        attempts: dict[str, int] = {}

        def report_progress(stage: str, message: str) -> None:
            attempt = attempts.get(stage, 0) + 1
            attempts[stage] = attempt
            state["attempt"] = attempt
            next_checkpoint = checkpoint_for_stage(stage)
            if next_checkpoint != AutomationCheckpoint.PREPARING:
                state["checkpoint"] = next_checkpoint
                if next_checkpoint not in {
                    AutomationCheckpoint.COMPLETE,
                    AutomationCheckpoint.CANCELLED,
                }:
                    state["disposition"] = disposition_for_checkpoint(next_checkpoint)
                with active_lock:
                    if str(active.get("request_id", "")) == request_id:
                        active["checkpoint"] = next_checkpoint
                        active["attempt"] = attempt
            write_message(
                envelope(
                    "progress",
                    request_id,
                    run_id,
                    state["checkpoint"],
                    state["disposition"],
                    attempt,
                    stage=stage,
                    message=message,
                )
            )
            state["last_heartbeat"] = time.monotonic()

        def report_activity() -> None:
            now = time.monotonic()
            if now - float(state["last_heartbeat"]) < HEARTBEAT_INTERVAL_SECONDS:
                return
            state["last_heartbeat"] = now
            write_message(
                envelope(
                    "heartbeat",
                    request_id,
                    run_id,
                    state["checkpoint"],
                    state["disposition"],
                    int(state["attempt"]),
                )
            )

        def report_response_captured(
            generated_text: str,
            response_anchor: ResponseAnchor | None,
        ) -> None:
            if not generated_text:
                return
            state["checkpoint"] = AutomationCheckpoint.RESPONSE_CAPTURED
            state["disposition"] = SubmissionDisposition.CONFIRMED
            state["captured_result"] = generated_text
            state["response_anchor"] = response_anchor
            state["last_heartbeat"] = time.monotonic()
            with active_lock:
                if str(active.get("request_id", "")) == request_id:
                    active["checkpoint"] = AutomationCheckpoint.RESPONSE_CAPTURED
                    active["attempt"] = int(state["attempt"])
            write_message(
                envelope(
                    "response_captured",
                    request_id,
                    run_id,
                    AutomationCheckpoint.RESPONSE_CAPTURED,
                    SubmissionDisposition.CONFIRMED,
                    int(state["attempt"]),
                    generated_text=generated_text,
                    response_anchor=(
                        asdict(response_anchor)
                        if response_anchor is not None
                        else None
                    ),
                )
            )

        report_activity()
        try:
            response = _process_payload(
                payload,
                progress_callback=report_progress,
                is_cancelled=cancel_event.is_set,
                activity_callback=report_activity,
                response_captured_callback=report_response_captured,
            )
        except Exception as exc:
            response = {
                "error": f"Automation worker failed: {type(exc).__name__}",
                "failure_code": "worker_exception",
            }
        captured_result = state.get("captured_result", "")
        if isinstance(captured_result, str) and captured_result:
            response.setdefault("generated_text", captured_result)
            captured_anchor = state.get("response_anchor")
            if captured_anchor is not None:
                response.setdefault("response_anchor", asdict(captured_anchor))
            checkpoint = AutomationCheckpoint.RESPONSE_CAPTURED
        else:
            checkpoint = coerce_checkpoint(
                response.get("checkpoint", state["checkpoint"])
            )
        expected_disposition = (
            state["disposition"]
            if checkpoint
            in {
                AutomationCheckpoint.COMPLETE,
                AutomationCheckpoint.CANCELLED,
            }
            else disposition_for_checkpoint(checkpoint)
        )
        disposition = coerce_submission_disposition(
            response.get(
                "submission_disposition",
                expected_disposition.value,
            )
        )
        if not submission_disposition_is_at_least(
            disposition,
            expected_disposition,
        ):
            disposition = expected_disposition
        generated_text = response.get("generated_text", "")
        if (
            isinstance(generated_text, str)
            and generated_text
            and not captured_result
        ):
            checkpoint = AutomationCheckpoint.RESPONSE_CAPTURED
            disposition = SubmissionDisposition.CONFIRMED
            write_message(
                envelope(
                    "response_captured",
                    request_id,
                    run_id,
                    checkpoint,
                    disposition,
                    int(state["attempt"]),
                    generated_text=generated_text,
                    response_anchor=response.get("response_anchor"),
                )
            )
        response["checkpoint"] = checkpoint.value
        response["submission_disposition"] = disposition.value
        write_message(
            envelope(
                "result",
                request_id,
                run_id,
                checkpoint,
                disposition,
                int(state["attempt"]),
                payload=response,
            )
        )
        with active_lock:
            active.clear()

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            if payload.get("_command") == "shutdown":
                with active_lock:
                    cancel = active.get("cancel")
                    thread = active.get("thread")
                    if isinstance(cancel, threading.Event):
                        cancel.set()
                if isinstance(thread, threading.Thread):
                    thread.join(timeout=CANCELLATION_GRACE_SECONDS)
                return 0
            if payload.get("_command") == "cancel":
                request_id = str(payload.get("request_id", ""))
                run_id = str(payload.get("run_id", ""))
                with active_lock:
                    cancel = active.get("cancel")
                    matches = (
                        int(payload.get("_protocol_version", 0))
                        == AUTOMATION_PROTOCOL_VERSION
                        and request_id == str(active.get("request_id", ""))
                        and run_id == str(active.get("run_id", ""))
                    )
                    checkpoint = active.get(
                        "checkpoint", AutomationCheckpoint.PREPARING
                    )
                    attempt = int(active.get("attempt", 1) or 1)
                    if isinstance(cancel, threading.Event) and matches:
                        cancel.set()
                if not isinstance(checkpoint, AutomationCheckpoint):
                    checkpoint = AutomationCheckpoint.PREPARING
                write_message(
                    envelope(
                        "cancel_ack",
                        request_id,
                        run_id,
                        checkpoint,
                        disposition_for_checkpoint(checkpoint),
                        attempt,
                    )
                )
                continue
            request_id = str(payload.get("request_id", ""))
            run_id = str(payload.get("run_id", ""))
            if int(payload.get("_protocol_version", 0)) != AUTOMATION_PROTOCOL_VERSION:
                write_message(
                    envelope(
                        "result",
                        request_id,
                        run_id,
                        AutomationCheckpoint.PREPARING,
                        SubmissionDisposition.NOT_ATTEMPTED,
                        1,
                        payload={
                            "error": "Automation protocol mismatch.",
                            "failure_code": "protocol_mismatch",
                        },
                    )
                )
                continue
            try:
                incoming_checkpoint = AutomationCheckpoint(
                    str(payload["checkpoint"])
                )
                incoming_attempt = int(payload["attempt"])
            except (KeyError, TypeError, ValueError):
                incoming_checkpoint = AutomationCheckpoint.CANCELLED
                incoming_attempt = 0
            if (
                not request_id
                or not run_id
                or incoming_checkpoint != AutomationCheckpoint.PREPARING
                or incoming_attempt < 1
            ):
                write_message(
                    envelope(
                        "result",
                        request_id,
                        run_id,
                        AutomationCheckpoint.PREPARING,
                        SubmissionDisposition.NOT_ATTEMPTED,
                        1,
                        payload={
                            "error": "Automation request envelope is invalid.",
                            "failure_code": "protocol_request_invalid",
                        },
                    )
                )
                continue
            with active_lock:
                existing = active.get("thread")
                if isinstance(existing, threading.Thread) and existing.is_alive():
                    write_message(
                        envelope(
                            "result",
                            request_id,
                            run_id,
                            AutomationCheckpoint.PREPARING,
                            SubmissionDisposition.NOT_ATTEMPTED,
                            1,
                            payload={
                                "error": "Automation helper is already processing a request.",
                                "failure_code": "helper_busy",
                            },
                        )
                    )
                    continue
                cancel_event = threading.Event()
                thread = threading.Thread(
                    target=process_request,
                    args=(payload, cancel_event),
                    name="PromptMeldAutomationRequest",
                    daemon=True,
                )
                active.update(
                    thread=thread,
                    cancel=cancel_event,
                    request_id=request_id,
                    run_id=run_id,
                    checkpoint=AutomationCheckpoint.PREPARING,
                    attempt=1,
                )
                thread.start()
        except Exception:
            # A malformed command cannot be associated safely with a run. Keep
            # the server alive so the client watchdog can replace it cleanly.
            continue
    with active_lock:
        cancel = active.get("cancel")
        thread = active.get("thread")
        if isinstance(cancel, threading.Event):
            cancel.set()
    if isinstance(thread, threading.Thread):
        thread.join(timeout=CANCELLATION_GRACE_SECONDS)
    return 0


def main() -> int:
    _enable_per_monitor_dpi_awareness()
    try:
        if "--self-test" in sys.argv[1:]:
            return _run_self_test()
        if "--server" in sys.argv[1:]:
            return _run_server()
        sys.stderr.write(
            "Automation worker requires the versioned --server protocol.\n"
        )
        return 2
    except Exception as exc:
        sys.stderr.write(f"Automation worker failed: {type(exc).__name__}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
