"""Stream ``adb logcat`` from a connected device into video-synchronized output.

Sister to ``core/log_collector.py`` for the Android branch. Same output shape
(``logs.jsonl`` + ``logs.vtt`` with ECS-style fields + ``t_video_s``) so the
viewer renders Android sessions without any branch in the rendering code.

Differences from the file-tailing LogCollector:

- Source is the device's ring buffer reached via ``adb -s SERIAL logcat
  -v threadtime``, not files on disk. No raw-archive sub-folder.
- We carve ``log.process.{pid,tid}``, ``log.level``, and ``log.tag`` out of
  the threadtime line. These ride alongside the standard ``message`` field.
- ``@timestamp`` is set at host-side line receipt for monotonic ordering with
  the other recorders; the device-local timestamp is preserved verbatim in
  ``log.device_ts`` for cross-reference.

Best-effort throughout — adb dying or returning bad bytes is logged into
``_error`` but never escapes to the GUI thread.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from core import adb


_ECS_VERSION = "8.11"
_VTT_CUE_DURATION_S = 3.0
_READ_TIMEOUT_S = 5.0

# threadtime format example:
#   "02-15 14:23:45.678  1234  5678 I MyTag: Some log message"
# Tag may contain spaces/symbols up to the first ':'; message takes the rest.
_THREADTIME_RE = re.compile(
    r"^(?P<ts>\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+"
    r"(?P<level>[VDIWEF])\s+"
    r"(?P<tag>[^:]+?):\s?(?P<msg>.*)$"
)

_CREATIONFLAGS = (
    subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
)


def _format_vtt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _device_now_for_logcat(serial: str) -> str | None:
    """Format current device-local time as ``adb logcat -T`` expects.

    Without ``-T`` logcat dumps the entire ring buffer first (potentially
    thousands of old lines) which then all collapse onto ``t_video_s=0`` and
    drown the timeline. Querying the device's own clock instead of using the
    host clock avoids timezone skew between host and device.
    """
    try:
        result = subprocess.run(
            [str(adb.get_adb_path()), "-s", serial, "shell", 'date "+%m-%d %H:%M:%S.000"'],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
            creationflags=_CREATIONFLAGS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def _resolve_package_pid(serial: str, package: str) -> int | None:
    """``adb shell pidof <pkg>`` — returns first PID or None."""
    try:
        result = subprocess.run(
            [str(adb.get_adb_path()), "-s", serial, "shell", f"pidof {package}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
            creationflags=_CREATIONFLAGS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    tokens = result.stdout.strip().split()
    if not tokens:
        return None
    try:
        return int(tokens[0])
    except ValueError:
        return None


class AndroidLogCollector:
    """``adb logcat`` → ``logs.jsonl`` + ``logs.vtt``.

    ``package_filter`` is best-effort — if pidof resolves we narrow logcat to
    just that PID, otherwise we capture everything. The dropped-noise vs
    completeness tradeoff is intentionally conservative (capture more rather
    than missing logs from a freshly-respawned PID).
    """

    def __init__(
        self,
        serial: str,
        output_dir: Path,
        t0_perf: float,
        package_filter: str | None = None,
    ) -> None:
        self.serial = str(serial)
        self.output_dir = Path(output_dir)
        self.t0_perf = float(t0_perf)
        self.package_filter = package_filter or None

        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._jsonl_fh = None
        self._vtt_fh = None
        self._lines_written = 0
        self._lock = threading.Lock()
        self._error: BaseException | None = None

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_fh = open(
            self.output_dir / "logs.jsonl", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh = open(
            self.output_dir / "logs.vtt", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh.write("WEBVTT\n\n")

        args = [str(adb.get_adb_path()), "-s", self.serial, "logcat", "-v", "threadtime"]

        since = _device_now_for_logcat(self.serial)
        if since:
            args += ["-T", since]

        if self.package_filter:
            pid = _resolve_package_pid(self.serial, self.package_filter)
            if pid is not None:
                args += [f"--pid={pid}"]

        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # decode manually so a bad byte doesn't kill the reader
            bufsize=0,
            creationflags=_CREATIONFLAGS,
        )

        self._thread = threading.Thread(
            target=self._reader_loop, name="AndroidLogcat", daemon=True
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

    def lines_written(self) -> int:
        return self._lines_written

    # ---- Reader loop ------------------------------------------------------

    def _reader_loop(self) -> None:
        try:
            assert self._proc is not None and self._proc.stdout is not None
            for raw in self._proc.stdout:
                if self._stop.is_set():
                    break
                line = raw.rstrip(b"\r\n")
                if not line:
                    continue
                text = line.decode("utf-8", errors="replace")
                self._emit(text)
        except BaseException as e:  # noqa: BLE001
            self._error = e

    def _emit(self, line: str) -> None:
        t_video = max(0.0, time.perf_counter() - self.t0_perf)
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        m = _THREADTIME_RE.match(line)
        if m:
            payload = {
                "device_ts": m.group("ts"),
                "process": {
                    "pid": int(m.group("pid")),
                    "tid": int(m.group("tid")),
                },
                "level": m.group("level"),
                "tag": m.group("tag").strip(),
            }
            message = m.group("msg").strip()
            vtt_text = f"[{payload['level']}] {payload['tag']}: {message}"
        else:
            # Logcat preamble lines like "--------- beginning of main" land here.
            payload = {}
            message = line
            vtt_text = line

        record = {
            "@timestamp": ts_utc,
            "t_video_s": round(t_video, 3),
            "log": payload,
            "message": message,
            "ecs": {"version": _ECS_VERSION},
        }

        with self._lock:
            try:
                if self._jsonl_fh is not None:
                    self._jsonl_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                return

            try:
                if self._vtt_fh is not None:
                    start = _format_vtt_time(t_video)
                    end = _format_vtt_time(t_video + _VTT_CUE_DURATION_S)
                    self._vtt_fh.write(
                        f"{start} --> {end}\n{_vtt_escape(vtt_text)}\n\n"
                    )
            except OSError:
                pass

            self._lines_written += 1
