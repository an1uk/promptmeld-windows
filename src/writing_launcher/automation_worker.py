from __future__ import annotations

import json
import sys
from dataclasses import asdict

from .chatgpt import ChatGPTDesktop


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


def _process_payload(payload: dict[str, object]) -> dict[str, object]:
    adapter = ChatGPTDesktop(
        timeout_seconds=float(payload.get("timeout_seconds", 8.0)),
        chatgpt_uri=str(payload.get("chatgpt_uri", "chatgpt:")),
        project_uri=str(payload.get("project_uri", "")),
    )
    result = adapter.submit(
        str(payload["prompt"]),
        str(payload["project_name"]),
        auto_submit=bool(payload.get("auto_submit", False)),
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
            response = _process_payload(payload)
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
