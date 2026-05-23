"""Tauri ↔ Python IPC bridge.

Lightweight CLI that wraps existing Trailbox core modules for the
desktop-tauri frontend.  Tauri's Rust commands spawn this as a
one-shot subprocess and capture the JSON stdout.

Usage:
    python bridge.py enumerate-windows
    python bridge.py list-devices
    python bridge.py system-info
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def cmd_enumerate_windows() -> list[dict]:
    from core.window_picker import enumerate_windows
    return [
        {
            "hwnd": w.hwnd,
            "title": w.title,
            "pid": w.pid,
            "process_name": w.process_name,
            "exe_path": w.exe_path,
            "label": w.label,
        }
        for w in enumerate_windows()
    ]


def cmd_list_devices() -> list[dict]:
    from core.adb import list_devices
    return [
        {
            "serial": d.serial,
            "state": d.state,
            "model": d.model,
            "online": d.online,
            "label": d.label,
        }
        for d in list_devices()
    ]


def cmd_system_info() -> dict:
    from core.system_info import gather
    return gather()


def cmd_hub_healthz() -> dict:
    url, token = _hub_args()
    from core.hub_client import HubClient
    return HubClient(base_url=url, token=token).healthz()


def cmd_hub_login() -> dict:
    url = sys.argv[3] if len(sys.argv) > 3 else ""
    user = sys.argv[4] if len(sys.argv) > 4 else ""
    pw = sys.argv[5] if len(sys.argv) > 5 else ""
    from core.hub_client import HubClient
    client = HubClient(base_url=url)
    user_info, cookies = client.login(user, pw)
    token_info = client.issue_token(label=f"trailbox-{_hostname()}", cookies=cookies)
    return {"user": user_info, "token": token_info}


def cmd_hub_list_sessions() -> list[dict]:
    url, token = _hub_args()
    from core.hub_client import HubClient
    return HubClient(base_url=url, token=token).list_sessions()


def cmd_hub_upload() -> dict:
    url, token = _hub_args()
    session_id = sys.argv[5] if len(sys.argv) > 5 else ""
    from pathlib import Path as _P
    session_dir = _P(_REPO_ROOT / "output" / session_id)
    if not session_dir.is_dir():
        return {"error": f"session dir not found: {session_dir}"}
    from core.hub_client import HubClient
    return HubClient(base_url=url, token=token).upload_session(session_id, session_dir)


def cmd_hub_share() -> dict:
    url, token = _hub_args()
    session_id = sys.argv[5] if len(sys.argv) > 5 else ""
    from core.hub_client import HubClient
    return HubClient(base_url=url, token=token).create_share(session_id)


def _hub_args() -> tuple[str, str]:
    url = sys.argv[3] if len(sys.argv) > 3 else ""
    token = sys.argv[4] if len(sys.argv) > 4 else ""
    return url, token


def _hostname() -> str:
    import socket
    return socket.gethostname()


COMMANDS = {
    "enumerate-windows": cmd_enumerate_windows,
    "list-devices": cmd_list_devices,
    "system-info": cmd_system_info,
    "hub-healthz": cmd_hub_healthz,
    "hub-login": cmd_hub_login,
    "hub-list-sessions": cmd_hub_list_sessions,
    "hub-upload": cmd_hub_upload,
    "hub-share": cmd_hub_share,
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({"error": f"usage: bridge.py <{'|'.join(COMMANDS)}>"}))
        return 1
    try:
        result = COMMANDS[sys.argv[1]]()
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
