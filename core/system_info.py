"""Snapshot the host PC's hardware/software profile for a session.

Captured once at session start and embedded in ``session_meta.json`` under the
``system`` key, so a recording is interpretable in isolation later
("this Netflix-was-smooth comparison was on a 5800X3D + RTX 4080" etc.).

Everything is best-effort — any single probe failing returns an empty/None
field rather than aborting collection.
"""
from __future__ import annotations

import platform
import subprocess
from typing import Any

import psutil


def _windows_release() -> dict[str, Any]:
    """Friendlier Windows version string than ``platform.platform()``."""
    info: dict[str, Any] = {"platform": platform.platform()}
    try:
        release, version, csd, ptype = platform.win32_ver()
        info["release"] = release
        info["build"] = version
    except Exception:  # noqa: BLE001
        pass
    return info


def _cpu_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": platform.processor() or "",
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
    }
    try:
        freq = psutil.cpu_freq()
        if freq is not None:
            info["max_mhz"] = round(freq.max) if freq.max else None
    except Exception:  # noqa: BLE001
        pass
    return info


def _ram_info() -> dict[str, Any]:
    try:
        vm = psutil.virtual_memory()
        return {
            "total_mb": round(vm.total / 1024 / 1024),
            "available_mb_at_start": round(vm.available / 1024 / 1024),
        }
    except Exception:  # noqa: BLE001
        return {}


def _gpu_names() -> list[str]:
    """Query Win32_VideoController via wmic. Returns empty list on any failure.

    wmic is being deprecated by Microsoft but still ships on Windows 10/11.
    If absent we fall back silently — GPU info is nice-to-have.
    """
    try:
        result = subprocess.run(
            [
                "wmic",
                "path",
                "win32_videocontroller",
                "get",
                "name",
                "/format:list",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    names: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Name="):
            name = line[len("Name=") :].strip()
            if name and name not in names:
                names.append(name)
    return names


def _display_info() -> list[dict[str, Any]]:
    """Per-screen geometry + refresh rate via Qt. Requires QGuiApplication."""
    try:
        from PyQt6.QtGui import QGuiApplication
    except Exception:  # noqa: BLE001
        return []
    app = QGuiApplication.instance()
    if app is None:
        return []
    screens: list[dict[str, Any]] = []
    for s in QGuiApplication.screens():
        geom = s.geometry()
        ratio = s.devicePixelRatio()
        screens.append(
            {
                "name": s.name(),
                # Qt geometry is device-independent (DIP) — multiply by
                # device_pixel_ratio for native pixels (which the screen
                # recorder and pynput coordinates use).
                "width": geom.width(),
                "height": geom.height(),
                "device_pixel_ratio": round(ratio, 3),
                "native_width": int(geom.width() * ratio),
                "native_height": int(geom.height() * ratio),
                "refresh_hz": round(s.refreshRate(), 2),
                "primary": s is QGuiApplication.primaryScreen(),
            }
        )
    return screens


def gather() -> dict[str, Any]:
    """One-shot snapshot. Call from main.py at session start."""
    info: dict[str, Any] = {
        "os": _windows_release(),
        "cpu": _cpu_info(),
        "ram": _ram_info(),
        "gpus": _gpu_names(),
        "displays": _display_info(),
        "python": platform.python_version(),
    }
    try:
        from main import __version__ as trailbox_version
        info["trailbox_version"] = trailbox_version
    except Exception:  # noqa: BLE001
        pass
    return info
