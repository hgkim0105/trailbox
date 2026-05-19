"""Capture Android touch + key events via ``adb shell getevent -lt``.

Sister to ``core/input_recorder.py``. Same output shape (``inputs.jsonl`` +
``inputs.vtt``) so the viewer doesn't branch.

What we parse, from the labelled long-timestamp stream
(``getevent -lt`` example):

    [   12345.678901] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID   00000005
    [   12345.678901] /dev/input/event2: EV_ABS       ABS_MT_POSITION_X    000004b0
    [   12345.678901] /dev/input/event2: EV_ABS       ABS_MT_POSITION_Y    0000086c
    [   12345.678902] /dev/input/event2: EV_SYN       SYN_REPORT           00000000
    [   12345.700101] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID   ffffffff   ← release
    [   12345.700101] /dev/input/event2: EV_SYN       SYN_REPORT           00000000
    [   12345.812000] /dev/input/event0: EV_KEY       KEY_VOLUMEUP         DOWN

Multitouch protocol B: a tracking id of ``ffffffff`` (=-1) on a slot ends
the touch. We only emit on ``SYN_REPORT`` (the OS-imposed event boundary)
so we get whole-gesture frames instead of one record per axis update.

Coordinates come straight from the device input axis. We probe ``getevent
-p`` once at start to learn each touch device's X/Y max, then normalize raw
event values to ``screen_size`` pixels so the data lines up with the
recorded video. If probing fails we fall back to writing raw values
(``coord_space="raw"``) — never block the session.

Known limitations: a few vendor builds (Samsung Knox, some MIUI variants)
deny non-root ``getevent``. Failure is caught and stashed in ``_error`` so
``finalize`` can write it into the meta. Other recorders proceed.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import adb


_ECS_VERSION = "8.11"
_VTT_CUE_DURATION_S = 1.0

_CREATIONFLAGS = (
    subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
)

# Event line: "[   12345.678] /dev/input/eventN: EV_X CODE VALUE"
_EVENT_RE = re.compile(
    r"^\[\s*(?P<ts>[\d.]+)\]\s+(?P<dev>/dev/input/event\d+):\s+"
    r"(?P<type>EV_\w+)\s+(?P<code>\S+)\s+(?P<value>\S+)$"
)

# `getevent -p` block per device:
#   add device 1: /dev/input/event2
#     ...
#     events:
#       ABS (0003): ... ABS_MT_POSITION_X : value 0, min 0, max 1080, fuzz 0, flat 0, resolution 0
_PROBE_DEVICE_RE = re.compile(r"add device \d+:\s+(/dev/input/event\d+)")
_PROBE_ABS_RE = re.compile(
    r"(ABS_MT_POSITION_[XY])\s*:\s*value\s+\d+\s*,\s*min\s+(\d+)\s*,\s*max\s+(\d+)"
)


@dataclass
class _DeviceAxes:
    """Per-device ABS range for X/Y, used to normalize raw event values."""
    x_max: int = 0
    y_max: int = 0


@dataclass
class _TouchState:
    """Latest in-flight values per input device (one entry per /dev/input/eventN)."""
    x: int | None = None
    y: int | None = None
    pressed: bool = False
    tracking_id: int | None = None
    dirty: bool = False


def _format_vtt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_hex_value(token: str) -> int:
    """Hex value as ``int`` — getevent prints ``00000123`` or ``ffffffff``."""
    try:
        v = int(token, 16)
    except ValueError:
        return 0
    # Treat as signed 32-bit so ``ffffffff`` becomes -1 (tracking-id release).
    if v >= 0x80000000:
        v -= 0x100000000
    return v


def _probe_device_axes(serial: str) -> dict[str, _DeviceAxes]:
    """Run ``getevent -p`` once to learn ABS_MT axis ranges per device.

    Failure is non-fatal: we return an empty dict and the recorder falls back
    to emitting raw coordinates with ``coord_space="raw"``.
    """
    try:
        result = subprocess.run(
            [str(adb.get_adb_path()), "-s", serial, "shell", "getevent", "-p"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6.0,
            creationflags=_CREATIONFLAGS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {}
    if result.returncode != 0:
        return {}

    axes: dict[str, _DeviceAxes] = {}
    current: str | None = None
    for line in result.stdout.splitlines():
        m_dev = _PROBE_DEVICE_RE.search(line)
        if m_dev:
            current = m_dev.group(1)
            continue
        if current is None:
            continue
        m_abs = _PROBE_ABS_RE.search(line)
        if m_abs:
            entry = axes.setdefault(current, _DeviceAxes())
            if "_X" in m_abs.group(1):
                entry.x_max = int(m_abs.group(3))
            else:
                entry.y_max = int(m_abs.group(3))
    return axes


class AndroidInputRecorder:
    def __init__(
        self,
        serial: str,
        output_dir: Path,
        t0_perf: float,
        screen_size: tuple[int, int] | None = None,
    ) -> None:
        self.serial = str(serial)
        self.output_dir = Path(output_dir)
        self.t0_perf = float(t0_perf)
        self.screen_size = screen_size  # (w, h) for normalizing to pixels

        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._jsonl_fh = None
        self._vtt_fh = None
        self._lock = threading.Lock()
        self._events_written = 0
        self._error: BaseException | None = None

        self._axes: dict[str, _DeviceAxes] = {}
        self._touches: dict[str, _TouchState] = {}

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_fh = open(
            self.output_dir / "inputs.jsonl", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh = open(
            self.output_dir / "inputs.vtt", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh.write("WEBVTT\n\n")

        # Best-effort axis probe before we open the streaming process.
        self._axes = _probe_device_axes(self.serial)

        args = [str(adb.get_adb_path()), "-s", self.serial, "shell", "getevent", "-lt"]
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
            creationflags=_CREATIONFLAGS,
        )

        self._thread = threading.Thread(
            target=self._reader_loop, name="AndroidGetevent", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        self._proc = None

        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

        with self._lock:
            for fh in (self._jsonl_fh, self._vtt_fh):
                if fh is not None:
                    try:
                        fh.close()
                    except OSError:
                        pass
            self._jsonl_fh = None
            self._vtt_fh = None

        if self._error is not None:
            raise self._error

    def events_written(self) -> int:
        return self._events_written

    # ---- Reader loop ------------------------------------------------------

    def _reader_loop(self) -> None:
        try:
            assert self._proc is not None and self._proc.stdout is not None
            for raw in self._proc.stdout:
                if self._stop.is_set():
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                self._handle_line(line)
        except BaseException as e:  # noqa: BLE001
            self._error = e

    def _handle_line(self, line: str) -> None:
        m = _EVENT_RE.match(line)
        if not m:
            return

        ev_type = m.group("type")
        code = m.group("code")
        value_raw = m.group("value")
        device = m.group("dev")

        state = self._touches.setdefault(device, _TouchState())

        if ev_type == "EV_ABS":
            if code == "ABS_MT_POSITION_X":
                state.x = _parse_hex_value(value_raw)
                state.dirty = True
            elif code == "ABS_MT_POSITION_Y":
                state.y = _parse_hex_value(value_raw)
                state.dirty = True
            elif code == "ABS_MT_TRACKING_ID":
                tid = _parse_hex_value(value_raw)
                if tid == -1:
                    state.pressed = False
                    state.dirty = True
                else:
                    state.tracking_id = tid
                    state.pressed = True
                    state.dirty = True

        elif ev_type == "EV_KEY":
            # Vol/Power/etc. press-release. ``value_raw`` is ``DOWN``/``UP``/
            # ``REPEAT`` in -l mode; track only DOWN/UP and emit immediately
            # (no need to wait for SYN_REPORT — these are atomic).
            if value_raw in ("DOWN", "UP"):
                if code in ("BTN_TOUCH",):
                    state.pressed = (value_raw == "DOWN")
                    state.dirty = True
                else:
                    self._emit_key(code, value_raw == "DOWN")

        elif ev_type == "EV_SYN" and code == "SYN_REPORT":
            if state.dirty and state.x is not None and state.y is not None:
                self._emit_touch(device, state)
                state.dirty = False

    # ---- Emit -------------------------------------------------------------

    def _normalize(self, device: str, x: int, y: int) -> tuple[int, int, str]:
        """Map raw input-device coordinates to screen pixels, or pass through."""
        axes = self._axes.get(device)
        if (
            axes is not None
            and axes.x_max > 0
            and axes.y_max > 0
            and self.screen_size is not None
        ):
            sw, sh = self.screen_size
            nx = int(round(x / axes.x_max * sw))
            ny = int(round(y / axes.y_max * sh))
            return nx, ny, "screen"
        return x, y, "raw"

    def _emit(self, payload: dict[str, Any], vtt_text: str | None) -> None:
        if self._stop.is_set():
            return
        t_video = max(0.0, time.perf_counter() - self.t0_perf)
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "@timestamp": ts_utc,
            "t_video_s": round(t_video, 3),
            "input": payload,
            "ecs": {"version": _ECS_VERSION},
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                if self._jsonl_fh is not None:
                    self._jsonl_fh.write(line)
            except OSError:
                return
            if vtt_text and self._vtt_fh is not None:
                try:
                    start = _format_vtt_time(t_video)
                    end = _format_vtt_time(t_video + _VTT_CUE_DURATION_S)
                    self._vtt_fh.write(
                        f"{start} --> {end}\n{_vtt_escape(vtt_text)}\n\n"
                    )
                except OSError:
                    pass
            self._events_written += 1

    def _emit_touch(self, device: str, state: _TouchState) -> None:
        x, y, space = self._normalize(device, int(state.x or 0), int(state.y or 0))
        action = "press" if state.pressed else "release"
        payload: dict[str, Any] = {
            "type": "touch",
            "action": action,
            "x": x,
            "y": y,
            "coord_space": space,
            "device": device,
        }
        if state.tracking_id is not None and state.pressed:
            payload["tracking_id"] = int(state.tracking_id)
        icon = "👆" if state.pressed else "✋"
        vtt = f"{icon} touch {action} @ ({x},{y})" if state.pressed else None
        self._emit(payload, vtt)

    def _emit_key(self, code: str, pressed: bool) -> None:
        payload: dict[str, Any] = {
            "type": "key",
            "action": "press" if pressed else "release",
            "key": code,
        }
        vtt = f"⌨ {code}" if pressed else None
        self._emit(payload, vtt)
