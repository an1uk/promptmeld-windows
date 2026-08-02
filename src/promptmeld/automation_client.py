from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .branding import AUTOMATION_EXECUTABLE_NAME
from .clipboard import write_clipboard_text
from .models import AppSettings, SubmissionResult

LOGGER = logging.getLogger(__name__)
HELPER_IDLE_SECONDS = 45.0


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
        timeout_seconds: float,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> dict[str, object]:
        if not self.alive or self.process.stdin is None:
            raise RuntimeError("Automation helper is not running.")
        self.process.stdin.write(
            json.dumps(payload, ensure_ascii=False) + "\n"
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Automation helper did not respond before the timeout."
                )
            try:
                response = self.responses.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(
                    "Automation helper did not respond before the timeout."
                ) from exc
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
    timeout_seconds: float,
    progress_callback: Callable[[str, str], None] | None = None,
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
            response = session.request(
                payload,
                timeout_seconds,
                progress_callback,
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
    progress_callback: Callable[[str, str], None] | None = None,
) -> SubmissionResult:
    payload = {
        "prompt": prompt,
        "project_name": project_name,
        "timeout_seconds": settings.automation_timeout_seconds,
        "chatgpt_uri": settings.chatgpt_uri,
        "project_uri": settings.project_uri,
        "auto_submit": settings.auto_submit_enabled,
        "temporary_chat": settings.temporary_chat_enabled,
        "source_hwnd": source_hwnd,
        "source_is_editable": source_is_editable,
        "replace_selected_text": settings.replace_selected_text_enabled,
        "copy_generated_text": settings.copy_generated_text_enabled,
    }
    try:
        raw = _request_from_helper(
            payload,
            max(
                75.0,
                settings.automation_timeout_seconds + 12.0,
            ),
            progress_callback,
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
            message=str(raw.get("message", "")),
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
        )
