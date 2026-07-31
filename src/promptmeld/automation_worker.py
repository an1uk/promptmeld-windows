from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import asdict

from .chatgpt import ChatGPTDesktop

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
) -> dict[str, object]:
    adapter = ChatGPTDesktop(
        timeout_seconds=float(payload.get("timeout_seconds", 8.0)),
        chatgpt_uri=str(payload.get("chatgpt_uri", "chatgpt:")),
        project_uri=str(payload.get("project_uri", "")),
        progress_callback=progress_callback,
    )
    result = adapter.submit(
        str(payload["prompt"]),
        str(payload["project_name"]),
        auto_submit=bool(payload.get("auto_submit", False)),
        temporary_chat=bool(payload.get("temporary_chat", False)),
    )
    response = asdict(result)
    response["_timings"] = adapter.timings
    return response


def _run_server() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if payload.get("_command") == "shutdown":
                return 0

            def report_progress(stage: str, message: str) -> None:
                sys.stdout.write(
                    json.dumps(
                        {
                            "_event": "progress",
                            "stage": stage,
                            "message": message,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                sys.stdout.flush()

            response = _process_payload(
                payload,
                progress_callback=report_progress,
            )
        except Exception as exc:
            response = {
                "error": (
                    "Automation worker failed: "
                    f"{type(exc).__name__}"
                )
            }
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


def main() -> int:
    _enable_per_monitor_dpi_awareness()
    try:
        if "--self-test" in sys.argv[1:]:
            return _run_self_test()
        if "--server" in sys.argv[1:]:
            return _run_server()
        payload = json.load(sys.stdin)
        response = _process_payload(payload)
        sys.stdout.write(json.dumps(response, ensure_ascii=False))
        sys.stdout.flush()
        return 0
    except Exception as exc:
        sys.stderr.write(f"Automation worker failed: {type(exc).__name__}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
