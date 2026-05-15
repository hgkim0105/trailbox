"""Sample target process telemetry once per second and write to JSONL.

Each line is one sample (CPU%, RSS, threads, handles) with the same
``t_video_s`` offset used elsewhere — so metrics overlay cleanly on the
video timeline in the viewer.

Notes:
- ``psutil.Process.cpu_percent(interval=None)`` is a NON-blocking call but
  the FIRST invocation always returns 0.0 (psutil needs two samples). We
  prime it once at start, then loop.
- ``num_handles()`` is Windows-only; on other OSes the field is omitted.
- Sampling does NOT require admin and survives anti-cheat: psutil reads
  perf counters via undocumented but stable Win32 APIs that aren't gated.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


_ECS_VERSION = "8.11"
# psutil.Process.cpu_percent() returns *per-logical-core* percent (a 16-core box
# running 11.4 cores busy reports 1140%). For QA we normalize to 0–100% of
# total system capacity. Raw per-core value is kept under ``cpu_pct_per_core``
# for callers that want to see threading behavior explicitly.
_CPU_CORES = psutil.cpu_count(logical=True) or 1


class MetricsRecorder:
    def __init__(
        self,
        pid: int,
        output_path: Path,
        t0_perf: float,
        interval_s: float = 1.0,
    ) -> None:
        self.pid = int(pid)
        self.output_path = Path(output_path)
        self.t0_perf = float(t0_perf)
        self.interval_s = float(interval_s)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fh = None
        self._samples_written = 0
        self._error: BaseException | None = None

    # ---- Public API -------------------------------------------------------

    def start(self) -> None:
        # Validate the process up-front so the caller gets immediate feedback.
        try:
            proc = psutil.Process(self.pid)
            proc.cpu_percent(interval=None)  # prime
        except psutil.NoSuchProcess as e:
            raise RuntimeError(f"target PID {self.pid} not running") from e
        except psutil.AccessDenied as e:
            raise RuntimeError(
                f"access denied reading PID {self.pid} (anti-cheat or elevated process)"
            ) from e

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.output_path, "w", encoding="utf-8", newline="\n")
        self._thread = threading.Thread(
            target=self._run, name="MetricsRecorder", daemon=True
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
            proc = psutil.Process(self.pid)
            while not self._stop.is_set():
                start = time.perf_counter()
                if not self._sample_once(proc):
                    # Process is gone; stop cleanly.
                    break
                elapsed = time.perf_counter() - start
                if self._stop.wait(timeout=max(0.0, self.interval_s - elapsed)):
                    break
        except BaseException as e:  # noqa: BLE001
            self._error = e

    def _sample_once(self, proc: psutil.Process) -> bool:
        t_video = max(0.0, time.perf_counter() - self.t0_perf)
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload: dict = {}
        try:
            raw_cpu = proc.cpu_percent(interval=None)
            payload["cpu_pct"] = round(raw_cpu / _CPU_CORES, 2)
            payload["cpu_pct_per_core"] = round(raw_cpu, 2)
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            pass

        try:
            mem = proc.memory_info()
            payload["rss_mb"] = round(mem.rss / 1024 / 1024, 1)
            payload["vms_mb"] = round(mem.vms / 1024 / 1024, 1)
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            pass

        try:
            payload["threads"] = proc.num_threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        try:
            payload["handles"] = proc.num_handles()
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass

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
                return False
        return True
