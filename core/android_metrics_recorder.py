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


_TOP_HEADER_RE = re.compile(r"^\s*PID\s+", re.IGNORECASE)


def _parse_top_row(out: str, pid: int) -> tuple[float, float] | None:
    """Return (cpu_pct_per_core, rss_mb) for ``pid`` in toybox-top output.

    Android's toybox ``top -p <pid> -n 1 -b`` prints a header line, then
    one row per process. Columns vary slightly between OEMs but the layout
    matches busybox/toybox conventions: PID USER PR NI VIRT RES SHR S %CPU
    %MEM TIME+ ARGS. Some builds elide PR/NI; we anchor on the PID column
    and pick %CPU as "the first percent-shaped number" and RES as the
    SI-suffixed memory column right before it.
    """
    lines = out.splitlines() if out else []
    header_idx: int | None = None
    for i, ln in enumerate(lines):
        if _TOP_HEADER_RE.match(ln):
            header_idx = i
            break
    if header_idx is None:
        return None

    for ln in lines[header_idx + 1:]:
        parts = ln.split()
        if not parts:
            continue
        try:
            row_pid = int(parts[0])
        except ValueError:
            continue
        if row_pid != pid:
            continue
        # Walk the row to pick out RES (with k/m/g suffix) + %CPU.
        rss_mb: float | None = None
        cpu_pct: float | None = None
        for tok in parts[1:]:
            if rss_mb is None:
                m = re.match(r"^(\d+(?:\.\d+)?)([KMG])?$", tok, re.IGNORECASE)
                if m:
                    val = float(m.group(1))
                    suffix = (m.group(2) or "K").upper()
                    if suffix == "K":
                        candidate = val / 1024.0
                    elif suffix == "M":
                        candidate = val
                    else:
                        candidate = val * 1024.0
                    # Heuristic: ignore tiny ints that are PR/NI/SHR (< ~32 K).
                    # Real RES is usually ≥ a few MB for Android apps.
                    if candidate >= 0.5:
                        rss_mb = candidate
                    continue
            if cpu_pct is None:
                try:
                    f = float(tok)
                except ValueError:
                    continue
                # %CPU usually shows up as a float column right after the
                # status char. Bound-check so we don't grab %MEM by accident.
                if 0.0 <= f <= 4000.0:
                    cpu_pct = f
        if cpu_pct is None or rss_mb is None:
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
