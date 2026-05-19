"""Sample Android process telemetry 1 Hz and write to ``process.jsonl``.

Sister to ``core/metrics_recorder.py``. Same wire format on disk so the
viewer's CPU/RAM/jank gauges work without branching on capture source.

Per tick we shell out three times in series:

  - ``pidof <package>`` — re-resolved each tick because Android can restart
    the process (a respawn changes the PID and ``top -p <old>`` would just
    return nothing forever).
  - ``top -p <pid> -n 1 -b`` — one-shot top in batch mode. We parse %CPU
    and RES (RSS) out of the row matching ``pid``.
  - ``dumpsys gfxinfo <package>`` — for jank count + 95/99th frame-time
    percentiles. These are uniquely valuable on Android (no equivalent in
    psutil) so we surface them under ``process.android.*``.

CPU% normalization mirrors the Windows recorder: ``cpu_pct`` is divided by
the device's logical CPU count so 100% means "the whole device", while
``cpu_pct_per_core`` keeps the raw multi-core value. GPU% is left as
``None`` — Android doesn't expose a uniform GPU utilization counter; jank
metrics are the better proxy for graphics health.

Every adb call has an explicit timeout; a hung device drops one sample but
the next tick proceeds normally. Failures are silently skipped so the
session keeps going.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import adb


_ECS_VERSION = "8.11"
_ADB_TIMEOUT_S = 4.0

_CREATIONFLAGS = (
    subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
)


def _adb_shell(serial: str, command: str, timeout: float = _ADB_TIMEOUT_S) -> str | None:
    """One-shot adb shell call. Returns stdout or ``None`` on any failure."""
    try:
        result = subprocess.run(
            [str(adb.get_adb_path()), "-s", serial, "shell", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_CREATIONFLAGS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_pidof(out: str) -> int | None:
    tokens = (out or "").strip().split()
    if not tokens:
        return None
    try:
        return int(tokens[0])
    except ValueError:
        return None


# Memory-shaped token: digits (+ optional decimal) + optional K/M/G suffix.
_MEM_RE = re.compile(r"^(\d+(?:\.\d+)?)([KMG])?$", re.IGNORECASE)
# Process status from `top` is always a single capital letter from this set.
_STATUS_TOKENS = frozenset({"S", "R", "D", "T", "Z", "I"})


def _mem_to_mb(token: str) -> float | None:
    """Parse a `top`-style memory token (e.g. ``26G``, ``482M``, ``1024`` -> KB)
    into megabytes. Returns None if the token isn't memory-shaped."""
    m = _MEM_RE.match(token)
    if not m:
        return None
    val = float(m.group(1))
    suffix = (m.group(2) or "K").upper()
    if suffix == "K":
        return val / 1024.0
    if suffix == "M":
        return val
    return val * 1024.0  # G


def _parse_top_row(out: str, pid: int) -> tuple[float, float] | None:
    """Return ``(cpu_pct_per_core, rss_mb)`` for ``pid`` in toybox-top output.

    Layout we expect (toybox / busybox, with or without the ``-q`` header
    suppression flag):

        PID USER PR NI VIRT RES SHR  S  %CPU %MEM   TIME+  ARGS
        22932 u0_a254 0 -20 26G 482M 271M S  0.0   6.2   0:52.52  com...

    Picking the right RES is the tricky part — the row also has VIRT and
    SHR that match the same memory regex. We anchor on the **status
    column** (single letter S/R/D/T/Z/I): RES is the LAST memory token
    BEFORE status, %CPU is the FIRST float AFTER status. That ordering
    constraint is stable across the OEM variants we've seen.

    No header lookup — works equally with ``top -b -q`` (data-only) and
    plain ``top -b`` (header + data).
    """
    if not out:
        return None
    for ln in out.splitlines():
        parts = ln.split()
        if not parts:
            continue
        try:
            if int(parts[0]) != pid:
                continue
        except ValueError:
            continue

        # Anchor on the STATUS column (single letter). In toybox top the
        # surrounding columns are fixed: ... VIRT RES SHR <S> %CPU %MEM ...
        # so RES = parts[status_idx-2] and %CPU = parts[status_idx+1]. We
        # don't trust an absolute index because PR/NI are sometimes elided.
        status_idx: int | None = None
        for i, tok in enumerate(parts):
            if tok in _STATUS_TOKENS and i >= 3:
                status_idx = i
                break
        if status_idx is None or status_idx + 1 >= len(parts):
            continue

        rss_mb = _mem_to_mb(parts[status_idx - 2]) if status_idx >= 2 else None
        try:
            cpu_pct = float(parts[status_idx + 1])
        except ValueError:
            cpu_pct = None

        if rss_mb is None or cpu_pct is None:
            return None
        return cpu_pct, rss_mb
    return None


_JANK_RE = re.compile(r"Janky frames:\s+(\d+)\s+\(([\d.]+)%\)")
_PERCENTILE_RE = re.compile(r"(\d+)th percentile:\s+(\d+)\s*ms")
_TOTAL_FRAMES_RE = re.compile(r"Total frames rendered:\s+(\d+)")


def _parse_gfxinfo(out: str) -> dict[str, Any]:
    """Extract jank + frame-time percentiles from ``dumpsys gfxinfo``."""
    info: dict[str, Any] = {}
    if not out:
        return info
    m = _TOTAL_FRAMES_RE.search(out)
    if m:
        info["frames_rendered"] = int(m.group(1))
    m = _JANK_RE.search(out)
    if m:
        info["jank_count"] = int(m.group(1))
        info["jank_pct"] = float(m.group(2))
    for m in _PERCENTILE_RE.finditer(out):
        pct = int(m.group(1))
        ms = int(m.group(2))
        info[f"frame_time_p{pct}_ms"] = ms
    return info


class AndroidMetricsRecorder:
    def __init__(
        self,
        serial: str,
        package: str,
        output_path: Path,
        t0_perf: float,
        interval_s: float = 1.0,
    ) -> None:
        self.serial = str(serial)
        self.package = str(package)
        self.output_path = Path(output_path)
        self.t0_perf = float(t0_perf)
        self.interval_s = float(interval_s)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fh = None
        self._samples_written = 0
        self._error: BaseException | None = None
        self._cpu_count: int | None = None

    def start(self) -> None:
        # Probe CPU count once for cpu_pct normalization. If it fails we just
        # don't divide — `cpu_pct_per_core` is still useful by itself.
        try:
            self._cpu_count = adb.get_cpu_count(self.serial)
        except Exception:  # noqa: BLE001
            self._cpu_count = None

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.output_path, "w", encoding="utf-8", newline="\n")

        self._thread = threading.Thread(
            target=self._run, name="AndroidMetrics", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        if self._error is not None:
            raise self._error

    def samples_written(self) -> int:
        return self._samples_written

    # ---- Loop -------------------------------------------------------------

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                start = time.perf_counter()
                self._sample_once()
                elapsed = time.perf_counter() - start
                if self._stop.wait(timeout=max(0.0, self.interval_s - elapsed)):
                    break
        except BaseException as e:  # noqa: BLE001
            self._error = e

    def _sample_once(self) -> None:
        pid_out = _adb_shell(self.serial, f"pidof {self.package}")
        pid = _parse_pidof(pid_out) if pid_out is not None else None

        payload: dict[str, Any] = {}
        android_extras: dict[str, Any] = {}

        if pid is not None:
            top_out = _adb_shell(self.serial, f"top -p {pid} -n 1 -b -q") or _adb_shell(
                self.serial, f"top -p {pid} -n 1 -b"
            )
            parsed = _parse_top_row(top_out, pid) if top_out else None
            if parsed is not None:
                cpu_per_core, rss_mb = parsed
                payload["cpu_pct_per_core"] = round(cpu_per_core, 2)
                if self._cpu_count and self._cpu_count > 0:
                    payload["cpu_pct"] = round(cpu_per_core / self._cpu_count, 2)
                payload["rss_mb"] = round(rss_mb, 1)
            payload["pid"] = pid
        else:
            # App not currently running. Still write a sample so the timeline
            # shows the gap clearly rather than going silent.
            payload["pid"] = None

        gfx_out = _adb_shell(self.serial, f"dumpsys gfxinfo {self.package}")
        if gfx_out:
            android_extras.update(_parse_gfxinfo(gfx_out))

        if android_extras:
            payload["android"] = android_extras

        # gpu_pct stays None on Android - jank metrics carry the equivalent
        # signal and the viewer is already nullable-safe here.
        payload.setdefault("gpu_pct", None)

        t_video = max(0.0, time.perf_counter() - self.t0_perf)
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        sample = {
            "@timestamp": ts_utc,
            "t_video_s": round(t_video, 3),
            "process": payload,
            "ecs": {"version": _ECS_VERSION},
        }
        if self._fh is not None:
            try:
                self._fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
                self._fh.flush()
                self._samples_written += 1
            except OSError:
                pass
