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


def cmd_list_ios_devices() -> list[dict]:
    from core.ios_device import list_devices
    return [
        {
            "udid": d.udid,
            "name": d.name,
            "ios_version": d.ios_version,
            "capturable": d.capturable,
            "label": d.label,
        }
        for d in list_devices()
    ]


def cmd_system_info() -> dict:
    from core.system_info import gather
    return gather()


def cmd_pick_window_click() -> dict:
    import time
    import win32api
    import win32con
    import win32gui
    time.sleep(0.3)
    # Wait for a left-click
    while True:
        if win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000:
            break
        time.sleep(0.02)
    pt = win32api.GetCursorPos()
    hwnd = win32gui.WindowFromPoint(pt)
    # Walk up to the top-level window
    while True:
        parent = win32gui.GetParent(hwnd)
        if parent == 0:
            break
        hwnd = parent
    title = win32gui.GetWindowText(hwnd)
    import psutil
    import win32process
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    exe_path = ""
    process_name = ""
    try:
        p = psutil.Process(pid)
        process_name = p.name()
        exe_path = p.exe() or ""
    except Exception:
        pass
    return {"hwnd": hwnd, "title": title, "pid": pid, "process_name": process_name, "exe_path": exe_path, "label": f"{title}  —  {process_name}  [hwnd 0x{hwnd:X}]"}


def cmd_find_window_for_log() -> dict | None:
    log_dir = sys.argv[2] if len(sys.argv) > 2 else ""
    if not log_dir:
        return {"error": "log_dir required"}
    from pathlib import Path as _P
    from core.process_detector import find_pids_for_log_dir
    from core.window_picker import enumerate_windows
    pids = find_pids_for_log_dir(_P(log_dir))
    if not pids:
        return None
    windows = enumerate_windows()
    for w in windows:
        if w.pid in pids:
            return {"hwnd": w.hwnd, "title": w.title, "pid": w.pid, "process_name": w.process_name, "exe_path": w.exe_path, "label": w.label}
    return None


def cmd_launch_exe() -> dict:
    exe_path = sys.argv[2] if len(sys.argv) > 2 else ""
    if not exe_path:
        return {"error": "exe_path required"}
    import subprocess
    try:
        proc = subprocess.Popen([exe_path], creationflags=0x00000008)  # DETACHED_PROCESS
        return {"pid": proc.pid, "exe_path": exe_path}
    except Exception as e:
        return {"error": str(e)}


def cmd_hub_healthz() -> dict:
    url, token = _hub_args()
    from core.hub_client import HubClient
    return HubClient(base_url=url, token=token).healthz()


def cmd_hub_login() -> dict:
    url = sys.argv[2] if len(sys.argv) > 2 else ""
    user = sys.argv[3] if len(sys.argv) > 3 else ""
    pw = sys.argv[4] if len(sys.argv) > 4 else ""
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
    session_id = sys.argv[4] if len(sys.argv) > 4 else ""
    session_dir_arg = sys.argv[5] if len(sys.argv) > 5 else ""
    from pathlib import Path as _P
    session_dir = _P(session_dir_arg) if session_dir_arg else _P(_REPO_ROOT / "output" / session_id)
    if not session_dir.is_dir():
        return {"error": f"session dir not found: {session_dir}"}
    from core.hub_client import HubClient
    return HubClient(base_url=url, token=token).upload_session(session_id, session_dir)


def cmd_hub_share() -> dict:
    url, token = _hub_args()
    session_id = sys.argv[4] if len(sys.argv) > 4 else ""
    from core.hub_client import HubClient
    return HubClient(base_url=url, token=token).create_share(session_id)


def cmd_hub_download() -> dict:
    url, token = _hub_args()
    session_id = sys.argv[4] if len(sys.argv) > 4 else ""
    out_root_arg = sys.argv[5] if len(sys.argv) > 5 else ""
    if not session_id:
        return {"error": "session_id required"}
    from core.hub_client import HubClient
    out_dir = Path(out_root_arg) if out_root_arg else _REPO_ROOT / "output"
    target = HubClient(base_url=url, token=token).download_session(session_id, out_dir)
    return {"session_id": session_id, "path": str(target)}


def cmd_hub_sync_queue() -> dict:
    """Find unuploaded local sessions and upload them all. Returns summary."""
    url, token = _hub_args()
    out_root_arg = sys.argv[4] if len(sys.argv) > 4 else ""
    if not url or not token:
        return {"error": "hub URL and token required", "uploaded": 0, "failed": 0}
    from pathlib import Path as _P
    from core.hub_client import HubClient
    output_root = Path(out_root_arg) if out_root_arg else _REPO_ROOT / "output"
    if not output_root.is_dir():
        return {"uploaded": 0, "failed": 0, "ids": []}
    client = HubClient(base_url=url, token=token)
    uploaded = []
    failed = []
    for d in sorted(output_root.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if name.startswith("_") or name.startswith("."):
            continue
        if not (d / "session_meta.json").is_file():
            continue
        if (d / ".uploaded").is_file():
            continue
        try:
            client.upload_session(name, d)
            (d / ".uploaded").write_text("")
            uploaded.append(name)
        except Exception as e:
            failed.append({"session_id": name, "error": str(e)})
    return {"uploaded": len(uploaded), "failed": len(failed), "ids": uploaded, "errors": failed}


def _hub_args() -> tuple[str, str]:
    url = sys.argv[2] if len(sys.argv) > 2 else ""
    token = sys.argv[3] if len(sys.argv) > 3 else ""
    return url, token


def _hostname() -> str:
    import socket
    return socket.gethostname()


COMMANDS = {
    "enumerate-windows": cmd_enumerate_windows,
    "list-devices": cmd_list_devices,
    "list-ios-devices": cmd_list_ios_devices,
    "system-info": cmd_system_info,
    "pick-window-click": cmd_pick_window_click,
    "find-window-for-log": cmd_find_window_for_log,
    "launch-exe": cmd_launch_exe,
    "hub-healthz": cmd_hub_healthz,
    "hub-login": cmd_hub_login,
    "hub-list-sessions": cmd_hub_list_sessions,
    "hub-upload": cmd_hub_upload,
    "hub-share": cmd_hub_share,
    "hub-download": cmd_hub_download,
    "hub-sync-queue": cmd_hub_sync_queue,
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
