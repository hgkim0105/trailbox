"""Stream iOS device syslog (os_log) into video-synchronized output.

Sister to ``core/android_log_collector.py`` for the iOS branch. Same output
shape (``logs/*.jsonl`` + ``*.vtt`` with ECS-style fields + ``t_video_s``) so
the viewer renders iOS sessions without any branch in the rendering code.

Source is the device's unified log reached via pymobiledevice3's OsTrace /
syslog service (pure-python libimobiledevice replacement — no native binary to
bundle, unlike Android's adb). Each entry carries pid / process label / level
which we map onto ``log.process`` / ``log.level`` / ``log.tag``.

Best-effort throughout — the lib dying or the device locking is logged into
``_error`` but never escapes to the GUI thread.

NOTE: the pymobiledevice3 syslog API surface shifts across versions; field
access is defensive (getattr + str fallback) and requires on-device validation.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


_ECS_VERSION = "8.11"
_VTT_CUE_DURATION_S = 3.0


def _format_vtt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _iter_syslog(udid: str):
    """Yield syslog entries from pymobiledevice3 (structured if available).

    Tries the structured ``OsTraceService.syslog()`` first (gives pid / label /
    level), falling back to the plain ``SyslogService.watch()`` line stream.
    """
    from pymobiledevice3.lockdown import create_using_usbmux

    ld = create_using_usbmux(serial=udid) if udid else create_using_usbmux()
    try:
        from pymobiledevice3.services.os_trace import OsTraceService

        yield from OsTraceService(ld).syslog()
        return
    except Exception:  # noqa: BLE001 - fall back to the plain line stream
        pass
    from pymobiledevice3.services.syslog import SyslogService

    yield from SyslogService(ld).watch()


class IOSLogCollector:
    """iOS unified log → ``logs/syslog.jsonl`` + ``logs/syslog.vtt``.

    ``bundle_filter`` (a process/label substring) is best-effort noise
    reduction: if set, only entries whose process label contains it are
    written. Unset captures everything.
    """

    def __init__(
        self,
        udid: str,
        output_dir: Path,
        t0_perf: float,
        bundle_filter: str | None = None,
    ) -> None:
        self.udid = str(udid)
        self.output_dir = Path(output_dir)
        self.t0_perf = float(t0_perf)
        self.bundle_filter = bundle_filter or None

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jsonl_fh = None
        self._vtt_fh = None
        self._lines_written = 0
        self._lock = threading.Lock()
        self._error: BaseException | None = None

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Distinct filenames from any PC LogCollector in the same session;
        # viewer_generator and the MCP backends glob logs/*.jsonl so both
        # sources surface together (same convention as Android's logcat.jsonl).
        self._jsonl_fh = open(
            self.output_dir / "syslog.jsonl", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh = open(
            self.output_dir / "syslog.vtt", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh.write("WEBVTT\n\n")

        self._thread = threading.Thread(
            target=self._reader_loop, name="IOSSyslog", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        # The pymobiledevice3 generator blocks on the socket; closing the file
        # handles is what bounds the join. The daemon thread is reclaimed at
        # process exit if the generator never yields again.
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
            for entry in _iter_syslog(self.udid):
                if self._stop.is_set():
                    break
                self._emit(entry)
        except BaseException as e:  # noqa: BLE001
            self._error = e

    @staticmethod
    def _fields(entry) -> tuple[str, str, str, int | None, str]:
        """Extract (message, label, level, pid, device_ts) defensively.

        Structured ``SyslogEntry`` exposes these as attributes; the plain
        watch() stream yields a string — then everything but message is empty.
        """
        if isinstance(entry, str):
            return entry, "", "", None, ""
        msg = str(getattr(entry, "message", "") or getattr(entry, "event_message", ""))
        label = str(getattr(entry, "label", "") or getattr(entry, "process", "") or "")
        level = str(getattr(entry, "level", "") or "")
        pid = getattr(entry, "pid", None)
        try:
            pid = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid = None
        ts = getattr(entry, "timestamp", "")
        return msg, label, level, pid, str(ts) if ts else ""

    def _emit(self, entry) -> None:
        message, label, level, pid, device_ts = self._fields(entry)

        if self.bundle_filter and self.bundle_filter not in label:
            return

        t_video = max(0.0, time.perf_counter() - self.t0_perf)
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        payload: dict = {"source": {"name": "syslog"}}
        if device_ts:
            payload["device_ts"] = device_ts
        if level:
            payload["level"] = level
        if label:
            payload["tag"] = label
        if pid is not None:
            payload["process"] = {"pid": pid, "name": label}

        vtt_text = message
        if level or label:
            prefix = "/".join(p for p in (level, label) if p)
            vtt_text = f"[{prefix}] {message}"

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
                    self._vtt_fh.write(f"{start} --> {end}\n{_vtt_escape(vtt_text)}\n\n")
            except OSError:
                pass
            self._lines_written += 1
