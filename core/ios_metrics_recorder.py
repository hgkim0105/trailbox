"""Sample iOS process telemetry ~1 Hz and write to ``process.jsonl``.

Sister to ``core/metrics_recorder.py`` / ``core/android_metrics_recorder.py``.
Same wire format on disk so the viewer's CPU/RAM/GPU gauges work without
branching on capture source.

Source is the same DVT (DeveloperTools) instruments channel Xcode's
Instruments uses, reached via pymobiledevice3:

  - ``Sysmontap`` — per-process CPU% + resident memory, streamed ~1 Hz. We use
    it as the sample clock.
  - ``Graphics`` (CoreAnimation) — device FPS + GPU utilization, streamed on a
    side thread; the latest value is stamped onto each sysmontap sample.

CPU% normalization mirrors the other recorders: ``cpu_pct`` is divided by the
device core count (100% == whole device), ``cpu_pct_per_core`` keeps the raw
value. Unlike Android, iOS *does* surface a device GPU utilization (via the
Graphics service) so ``gpu_pct`` is populated rather than left None.

Requires Developer Mode + a mounted Developer Disk Image on iOS 16+ (tunneld /
RemoteXPC on 17+). pymobiledevice3 handles the plumbing, but if DVT can't be
reached the recorder records ``_error`` and the session proceeds with the other
signals (best-effort).

NOTE: the Sysmontap / Graphics row shapes shift across pymobiledevice3 and iOS
versions; field extraction is defensive and requires on-device validation.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ECS_VERSION = "8.11"


def _device_core_count(udid: str) -> int | None:
    """Logical CPU count for cpu_pct normalization, or None on failure."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux

        ld = create_using_usbmux(serial=udid) if udid else create_using_usbmux()
        # HardwarePlatform doesn't give core count directly; some lockdown
        # builds expose it via a domain query. Best-effort, None is fine.
        for key in ("NumberOfCores", "ProcessorCount"):
            val = ld.get_value(key=key)
            if val:
                return int(val)
    except Exception:  # noqa: BLE001
        pass
    return None


class IOSMetricsRecorder:
    def __init__(
        self,
        udid: str,
        bundle_id: str,
        output_path: Path,
        t0_perf: float,
        interval_s: float = 1.0,
    ) -> None:
        self.udid = str(udid)
        self.bundle_id = str(bundle_id or "")
        self.output_path = Path(output_path)
        self.t0_perf = float(t0_perf)
        self.interval_s = float(interval_s)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._gfx_thread: threading.Thread | None = None
        self._fh = None
        self._samples_written = 0
        self._error: BaseException | None = None
        self._cpu_count: int | None = None

        # Latest GPU/FPS reading from the Graphics side thread.
        self._gfx_lock = threading.Lock()
        self._latest_gfx: dict[str, Any] = {}

    def start(self) -> None:
        self._cpu_count = _device_core_count(self.udid)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.output_path, "w", encoding="utf-8", newline="\n")
        self._thread = threading.Thread(target=self._run, name="IOSMetrics", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for th in (self._thread, self._gfx_thread):
            if th is not None:
                th.join(timeout=timeout)
        self._thread = None
        self._gfx_thread = None
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

    def current_package(self) -> str:
        return self.bundle_id

    # ---- DVT plumbing -----------------------------------------------------

    def _run(self) -> None:
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import (
                DvtSecureSocketProxyService,
            )
            from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap

            ld = create_using_usbmux(serial=self.udid) if self.udid else create_using_usbmux()
            with DvtSecureSocketProxyService(ld) as dvt:
                # Graphics (GPU/FPS) on a side thread sharing the DVT proxy;
                # DVT multiplexes channels so both services run concurrently.
                self._gfx_thread = threading.Thread(
                    target=self._graphics_loop, args=(dvt,), name="IOSGraphics",
                    daemon=True,
                )
                self._gfx_thread.start()

                with Sysmontap(dvt) as sysmon:
                    for snapshot in sysmon:
                        if self._stop.is_set():
                            break
                        self._emit(self._extract_proc(snapshot))
        except BaseException as e:  # noqa: BLE001
            self._error = e

    def _graphics_loop(self, dvt) -> None:
        try:
            from pymobiledevice3.services.dvt.instruments.graphics import Graphics

            with Graphics(dvt) as graphics:
                for sample in graphics:
                    if self._stop.is_set():
                        break
                    gfx = self._extract_gfx(sample)
                    if gfx:
                        with self._gfx_lock:
                            self._latest_gfx = gfx
        except Exception:  # noqa: BLE001 - graphics is optional; CPU/mem still flow
            pass

    # ---- Defensive field extraction (version-dependent shapes) ------------

    def _extract_proc(self, snapshot: Any) -> dict[str, Any]:
        """Pull (cpu_pct_per_core, rss_mb, pid) for our process from sysmontap.

        Sysmontap yields a structure carrying a per-process table. The exact
        keys vary; we search for the row whose bundle/name matches our target
        and read CPU + memory defensively.
        """
        out: dict[str, Any] = {}
        rows = self._iter_proc_rows(snapshot)
        for row in rows:
            name = str(row.get("name") or row.get("bundleIdentifier") or "")
            if self.bundle_id and self.bundle_id not in name:
                continue
            cpu = row.get("cpuUsage")
            if cpu is None:
                cpu = row.get("cpu")
            mem = row.get("physFootprint")
            if mem is None:
                mem = row.get("memResidentSize") or row.get("residentSize")
            if cpu is not None:
                try:
                    cpu_per_core = float(cpu)
                    # Sysmontap reports CPU as a 0-100 (per device) or 0-1
                    # fraction depending on version; normalize the fraction case.
                    if cpu_per_core <= 1.0:
                        cpu_per_core *= 100.0
                    out["cpu_pct_per_core"] = round(cpu_per_core, 2)
                    if self._cpu_count and self._cpu_count > 0:
                        out["cpu_pct"] = round(cpu_per_core / self._cpu_count, 2)
                except (TypeError, ValueError):
                    pass
            if mem is not None:
                try:
                    out["rss_mb"] = round(float(mem) / 1024 / 1024, 1)
                except (TypeError, ValueError):
                    pass
            pid = row.get("pid")
            try:
                out["pid"] = int(pid) if pid is not None else None
            except (TypeError, ValueError):
                out["pid"] = None
            break
        return out

    @staticmethod
    def _iter_proc_rows(snapshot: Any):
        """Yield per-process dicts from a sysmontap snapshot, shape-tolerant."""
        if isinstance(snapshot, dict):
            procs = snapshot.get("Processes") or snapshot.get("processes")
            if isinstance(procs, dict):
                for pid, val in procs.items():
                    if isinstance(val, dict):
                        val.setdefault("pid", pid)
                        yield val
                    elif isinstance(val, (list, tuple)):
                        yield {"pid": pid, "_raw": list(val)}
                return
            if isinstance(procs, list):
                yield from (p for p in procs if isinstance(p, dict))
                return
        if isinstance(snapshot, (list, tuple)):
            for item in snapshot:
                if isinstance(item, dict):
                    yield from IOSMetricsRecorder._iter_proc_rows(item)

    @staticmethod
    def _extract_gfx(sample: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if not isinstance(sample, dict):
            return out
        fps = sample.get("CoreAnimationFramesPerSecond") or sample.get("fps")
        gpu = sample.get("Device Utilization %") or sample.get("gpu_utilization")
        if fps is not None:
            try:
                out["fps"] = round(float(fps), 1)
            except (TypeError, ValueError):
                pass
        if gpu is not None:
            try:
                out["gpu_util"] = round(float(gpu), 2)
            except (TypeError, ValueError):
                pass
        return out

    # ---- Emit -------------------------------------------------------------

    def _emit(self, payload: dict[str, Any]) -> None:
        with self._gfx_lock:
            gfx = dict(self._latest_gfx)

        payload.setdefault("pid", None)
        payload["bundle_id"] = self.bundle_id

        ios_extras: dict[str, Any] = {}
        if "fps" in gfx:
            ios_extras["fps"] = gfx["fps"]
        if "gpu_util" in gfx:
            ios_extras["gpu_util"] = gfx["gpu_util"]
        if ios_extras:
            payload["ios"] = ios_extras

        # iOS exposes device GPU utilization (Android can't) — surface it as the
        # standard gpu_pct so the viewer's GPU gauge lights up without a branch.
        payload["gpu_pct"] = gfx.get("gpu_util")

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
