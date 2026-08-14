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

from .branding import AUTOMATION_EXECUTABLE_NAME
from .chatgpt import DEFAULT_RESPONSE_TIMEOUT_SECONDS
from .clipboard import write_clipboard_text
from .models import AppSettings, SubmissionResult

LOGGER = logging.getLogger(__name__)
HELPER_IDLE_SECONDS = 45.0


class AutomationCancelled(RuntimeError):
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

    def request(
        self,
        payload: dict[str, object],
        timeout_seconds: float | None,
        progress_callback: Callable[[str, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        if not self.alive or self.process.stdin is None:
            raise RuntimeError("Automation helper is not running.")
        self.process.stdin.write(
            json.dumps(payload, ensure_ascii=False) + "\n"
        )
        self.process.stdin.flush()
        deadline = (
            None
            if timeout_seconds is None
            else time.monotonic() + timeout_seconds
        )
        while True:
            if is_cancelled is not None and is_cancelled():
                raise AutomationCancelled("Automation cancelled by the user.")
            remaining = (
                None if deadline is None else deadline - time.monotonic()
            )
            if remaining is not None and remaining <= 0:
                raise TimeoutError(
                    "Automation helper did not respond before the timeout."
                )
            try:
                response = self.responses.get(
                    timeout=(
                        0.1 if remaining is None else min(0.1, remaining)
                    )
                )
            except queue.Empty:
                continue
            if response is None:
                raise RuntimeError("Automation helper stopped unexpectedly.")
            decoded = json.loads(response)
            if not isinstance(decoded, dict):
                raise RuntimeError(
                    "Automation helper returned an invalid response."
                )
            if decoded.get("_event") == "progress":
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
            if error := decoded.get("error"):
                raise RuntimeError(str(error))
            return decoded

    def close(self) -> None:
        if self.alive and self.process.stdin is not None:
            try:
                self.process.stdin.write('{"_command":"shutdown"}\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        try:
            self.process.wait(timeout=0.75)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=0.5)
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
        if _helper_session is None or not _helper_session.alive:
            if _helper_session is not None:
                _helper_session.close()
            _helper_session = _AutomationHelperSession(_helper_command())
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
        except Exception:
            session.close()
            _helper_session = None
            raise
        _schedule_helper_shutdown(session)
        return response


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
    payload = {
        "run_id": run_id or str(uuid.uuid4()),
        "operation": operation,
        "prompt": prompt,
        "project_name": project_name,
        "timeout_seconds": settings.automation_timeout_seconds,
        "response_timeout_seconds": response_timeout_seconds,
        "chatgpt_uri": settings.chatgpt_uri,
        "project_uri": settings.project_uri,
        "auto_submit": settings.auto_submit_enabled,
        "temporary_chat": settings.temporary_chat_enabled,
        "source_hwnd": source_hwnd,
        "source_is_editable": source_is_editable,
        "source_text": source_text,
        "source_app": source_app,
        "replace_selected_text": effective_replace,
        "copy_generated_text": effective_copy,
        "capture_generated_text": capture_generated_text,
        "redaction_replacements": dict(redaction_replacements or {}),
        "response_baseline": list(response_baseline),
    }
    try:
        waits_for_generated_text = bool(
            settings.auto_submit_enabled
            and (effective_replace or effective_copy or capture_generated_text)
        )
        helper_timeout = max(
            75.0,
            settings.automation_timeout_seconds + 12.0,
        )
        if waits_for_generated_text:
            helper_timeout = (
                None
                if response_timeout_seconds is None
                else max(helper_timeout, response_timeout_seconds + 60.0)
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
        for timing in raw.get("_timings", []):
            if not isinstance(timing, dict):
                continue
            LOGGER.info(
                "ChatGPT automation timing - %s: %s ms",
                timing.get("stage", "unknown"),
                timing.get("milliseconds", "?"),
            )
        return SubmissionResult(
            submitted=bool(raw["submitted"]),
            prepared=bool(raw.get("prepared", False)),
            fallback_copied=bool(raw.get("fallback_copied", False)),
            generated_text_copied=bool(
                raw.get("generated_text_copied", False)
            ),
            selection_replaced=bool(raw.get("selection_replaced", False)),
            output_failed=bool(raw.get("output_failed", False)),
            cancelled=bool(raw.get("cancelled", False)),
            message=str(raw.get("message", "")),
            generated_text=(
                str(raw.get("generated_text", ""))
                if isinstance(raw.get("generated_text", ""), str)
                else ""
            ),
            run_id=str(raw.get("run_id", payload["run_id"])),
            failed_stage=str(raw.get("failed_stage", "")),
            failure_code=str(raw.get("failure_code", "")),
            submission_confirmed=bool(raw.get("submission_confirmed", False)),
            retry_mode=str(raw.get("retry_mode", "")),
            recoverable=bool(raw.get("recoverable", False)),
            response_baseline=tuple(raw.get("response_baseline", ())),
            timings=tuple(
                (
                    str(timing.get("stage", "unknown")),
                    float(timing.get("milliseconds", 0.0)),
                )
                for timing in raw.get("_timings", ())
                if isinstance(timing, dict)
            ),
        )
    except AutomationCancelled:
        LOGGER.info("ChatGPT automation was cancelled")
        return SubmissionResult(
            submitted=False,
            cancelled=True,
            message=(
                "Automation stopped. ChatGPT may continue if the prompt was "
                "already submitted. Check the original application before "
                "trying again."
            ),
            run_id=str(payload["run_id"]),
            failed_stage="cancelling",
        )
    except Exception:
        LOGGER.exception("ChatGPT automation helper failed")
        write_clipboard_text(prompt)
        return SubmissionResult(
            submitted=False,
            prepared=False,
            fallback_copied=True,
            message=(
                "The ChatGPT automation helper failed. The complete prompt has "
                "been copied to the clipboard."
            ),
            run_id=str(payload["run_id"]),
            failed_stage="helper",
            failure_code="helper_failed",
            retry_mode="delivery" if operation == "deliver" else "response",
            recoverable=True,
            submission_confirmed=(operation == "retrieve_response"),
            response_baseline=response_baseline,
        )
