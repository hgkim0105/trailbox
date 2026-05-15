"""Record global keyboard + mouse events with video-synchronized timestamps.

Same output shape as the log collector: ``inputs.jsonl`` (ECS-style, one event
per line) and ``inputs.vtt`` (WebVTT subtitles for overlaying on the video).

Mouse motion is downsampled to ~10 Hz (one event per ``_MOVE_INTERVAL_S``) to
keep the file size manageable; clicks, scrolls, and key events are recorded
in full. Releases are written to JSONL but omitted from VTT to reduce clutter.

If a ``window_hwnd`` is supplied (i.e. WGC window-capture mode), each event
also carries ``window_x``/``window_y`` relative to that window's top-left at
the moment of the event — handy when correlating to a window-only mp4 whose
origin isn't the screen origin.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import win32gui
from pynput import keyboard, mouse


_MOVE_INTERVAL_S = 0.1
_VTT_CUE_DURATION_S = 1.0
_ECS_VERSION = "8.11"


def _format_vtt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _key_name(key) -> str:
    """Best-effort printable name for a pynput key."""
    try:
        ch = getattr(key, "char", None)
        if ch:
            return ch
    except Exception:  # noqa: BLE001 - some bindings throw on .char access
        pass
    name = getattr(key, "name", None)
    return name if name else str(key)


class InputRecorder:
    def __init__(
        self,
        output_dir: Path,
        t0_perf: float,
        window_hwnd: int | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.t0_perf = float(t0_perf)
        self.window_hwnd = int(window_hwnd) if window_hwnd else None

        self._stop = threading.Event()
        self._key_listener: keyboard.Listener | None = None
        self._mouse_listener: mouse.Listener | None = None
        self._jsonl_fh = None
        self._vtt_fh = None
        self._lock = threading.Lock()
        self._events_written = 0
        self._last_move_perf = 0.0
        self._error: BaseException | None = None

    # ---- Public API -------------------------------------------------------

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_fh = open(
            self.output_dir / "inputs.jsonl", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh = open(
            self.output_dir / "inputs.vtt", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh.write("WEBVTT\n\n")

        self._key_listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._key_listener.start()
        self._mouse_listener.start()

    def stop(self) -> None:
        self._stop.set()
        for listener in (self._key_listener, self._mouse_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:  # noqa: BLE001
                    pass
        self._key_listener = None
        self._mouse_listener = None
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

    # ---- Helpers ----------------------------------------------------------

    def _window_origin(self) -> tuple[int, int] | None:
        if self.window_hwnd is None:
            return None
        try:
            left, top, _, _ = win32gui.GetWindowRect(self.window_hwnd)
            return (left, top)
        except Exception:  # noqa: BLE001 - window may have closed
            return None

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
            if self._jsonl_fh is not None:
                try:
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

    def _attach_window_coords(self, payload: dict[str, Any], x: int, y: int) -> None:
        origin = self._window_origin()
        if origin is not None:
            payload["window_x"] = x - origin[0]
            payload["window_y"] = y - origin[1]

    # ---- pynput callbacks (run on listener threads) -----------------------

    def _on_press(self, key) -> bool | None:
        if self._stop.is_set():
            return False
        name = _key_name(key)
        self._emit(
            {"type": "key", "action": "press", "key": name},
            f"⌨ {name}",
        )
        return None

    def _on_release(self, key) -> bool | None:
        if self._stop.is_set():
            return False
        name = _key_name(key)
        # JSONL only; releases would just double the VTT clutter.
        self._emit({"type": "key", "action": "release", "key": name}, None)
        return None

    def _on_click(self, x: int, y: int, button, pressed: bool) -> bool | None:
        if self._stop.is_set():
            return False
        btn_name = getattr(button, "name", None) or str(button)
        payload: dict[str, Any] = {
            "type": "mouse",
            "action": "click",
            "button": btn_name,
            "pressed": bool(pressed),
            "x": int(x),
            "y": int(y),
        }
        self._attach_window_coords(payload, int(x), int(y))
        vtt = f"🖱 {btn_name} press @ ({int(x)},{int(y)})" if pressed else None
        self._emit(payload, vtt)
        return None

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> bool | None:
        if self._stop.is_set():
            return False
        payload: dict[str, Any] = {
            "type": "mouse",
            "action": "scroll",
            "dx": int(dx),
            "dy": int(dy),
            "x": int(x),
            "y": int(y),
        }
        self._attach_window_coords(payload, int(x), int(y))
        self._emit(payload, f"🖱 scroll ({int(dx)},{int(dy)})")
        return None

    def _on_move(self, x: int, y: int) -> bool | None:
        if self._stop.is_set():
            return False
        now = time.perf_counter()
        if now - self._last_move_perf < _MOVE_INTERVAL_S:
            return None
        self._last_move_perf = now
        payload: dict[str, Any] = {
            "type": "mouse",
            "action": "move",
            "x": int(x),
            "y": int(y),
        }
        self._attach_window_coords(payload, int(x), int(y))
        # Moves are noisy in VTT; jsonl only.
        self._emit(payload, None)
        return None
