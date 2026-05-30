"""Sample iOS process telemetry ~1 Hz and write to ``process.jsonl``.

Sister to ``core/metrics_recorder.py`` / ``core/android_metrics_recorder.py``.
Same wire format on disk so the viewer's CPU/RAM/GPU gauges work without
branching on capture source.

Source is the same DVT (DeveloperTools) instruments channel Xcode's
Instruments uses, reached via pymobiledevice3:

  - ``Sysmontap`` — per-process CPU% + resident memory, streamed ~1 Hz. We use
    it as the sample clock.
  - ``Graphics`` (CoreAnimation) — device FPS + GPU utilization, streamed on a
    side task; the latest value is stamped onto each sysmontap sample.

CPU% normalization mirrors the other recorders: ``cpu_pct`` is divided by the
device core count (100% == whole device), ``cpu_pct_per_core`` keeps the raw
value. Unlike Android, iOS *does* surface a device GPU utilization (via the
Graphics service) so ``gpu_pct`` is populated rather than left None.

**Requires ``sudo pymobiledevice3 remote tunneld`` running on the host** for
iOS 17+ (which includes our supported floor of iOS 26). DVT moved to
RemoteXPC/RSD on iOS 17 and only the tunneld daemon (with TUN privileges) can
open that path. If tunneld isn't running, this recorder writes an ``_error``
and the session proceeds with the other signals (best-effort).

NOTE: the Sysmontap / Graphics row shapes shift across pymobiledevice3 and iOS
versions; field extraction is defensive and requires on-device validation.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ECS_VERSION = "8.11"

# Sysmontap rows we'll match against. Empirically these are the keys v9 sysmon
# returns when ``process_attributes`` is the device-default set; fields are
# best-effort and we degrade silently when a key is missing.
_PROC_NAME_KEYS = ("name", "bundleIdentifier", "execName")
_PROC_RSS_KEYS = ("physFootprint", "memResidentSize", "residentSize")
_PROC_CPU_KEYS = ("cpuUsage", "cpu")


async def _device_core_count_async(udid: str) -> int | None:
    """Logical CPU count for cpu_pct normalization, or None on failure."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
    except Exception:  # noqa: BLE001
        return None
    ld = None
    try:
        ld = await (create_using_usbmux(serial=udid) if udid else create_using_usbmux())
        for key in ("NumberOfCores", "ProcessorCount"):
            val = await ld.get_value(key=key)
            if val:
                return int(val)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if ld is not None:
            try:
                await ld.close()
            except Exception:  # noqa: BLE001
                pass
    return None


def _device_core_count(udid: str) -> int | None:
    try:
        return asyncio.run(_device_core_count_async(udid))
    except Exception:  # noqa: BLE001
        return None


async def _open_dvt_service_provider(udid: str):
    """Return an RSD (tunneld) service provider matching ``udid``.

    iOS 17+ DVT is only reachable through RemoteXPC, which requires a
    tunneld daemon running with root (``sudo pymobiledevice3 remote tunneld``)
    to manage the TUN device. We connect to the tunneld API at the default
    loopback port and pick the matching device.

    Raises a RuntimeError with a user-actionable message if tunneld isn't
    running — the caller logs it into ``_error`` so the GUI can surface
    "tunneld not running" instead of a cryptic stacktrace.
    """
    from pymobiledevice3.tunneld.api import TUNNELD_DEFAULT_ADDRESS, get_tunneld_devices

    try:
        rsds = await get_tunneld_devices(TUNNELD_DEFAULT_ADDRESS)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "tunneld not reachable — run `sudo pymobiledevice3 remote tunneld` "
            "in a separate terminal before recording iOS metrics. "
            f"(underlying: {e!s})"
        ) from e

    if not rsds:
        raise RuntimeError(
            "tunneld is running but reports no devices. Reconnect the iPhone, "
            "tap 'Trust', and verify Developer Mode is on."
        )

    picked = None
    if udid:
        picked = next((r for r in rsds if getattr(r, "udid", None) == udid), None)
        if picked is None:
            for r in rsds:
                try:
                    await r.close()
                except Exception:  # noqa: BLE001
                    pass
            raise RuntimeError(f"tunneld has no device matching udid {udid!r}")
    else:
        picked = rsds[0]

    # Close every RSD we didn't pick — they each hold an open socket.
    for r in rsds:
        if r is picked:
            continue
        try:
            await r.close()
        except Exception:  # noqa: BLE001
            pass
    return picked


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
        self._fh = None
        self._samples_written = 0
        self._error: BaseException | None = None
        self._cpu_count: int | None = None

        # Latest GPU/FPS reading from the Graphics async task.
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

    def current_package(self) -> str:
        return self.bundle_id

    # ---- DVT plumbing -----------------------------------------------------

    def _run(self) -> None:
        """Thread entry — drive the async DVT pipeline to completion."""
        try:
            asyncio.run(self._run_async())
        except BaseException as e:  # noqa: BLE001
            self._error = e

    async def _run_async(self) -> None:
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap
        from pymobiledevice3.services.dvt.instruments.graphics import Graphics

        sp = await _open_dvt_service_provider(self.udid)
        try:
            async with DvtProvider(sp) as dvt:
                # Sysmontap drives the sample clock; Graphics fills GPU/FPS on
                # the side. Both share the DVT proxy (DTX multiplexes channels).
                # asyncio.wait + FIRST_COMPLETED lets either task ending (or
                # _stop firing) tear the whole thing down cleanly.
                stop_watch = asyncio.create_task(
                    self._await_stop(), name="ios-metrics-stop"
                )
                sysmon_task = asyncio.create_task(
                    self._sysmon_loop(dvt, Sysmontap), name="ios-metrics-sysmon"
                )
                gfx_task = asyncio.create_task(
                    self._graphics_loop(dvt, Graphics), name="ios-metrics-gfx"
                )

                done, pending = await asyncio.wait(
                    [stop_watch, sysmon_task, gfx_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                # Surface the first non-cancellation error from a primary task.
                for t in done:
                    if t is stop_watch:
                        continue
                    exc = t.exception()
                    if exc is not None and not isinstance(exc, asyncio.CancelledError):
                        raise exc
        finally:
            try:
                await sp.close()
            except Exception:  # noqa: BLE001
                pass

    async def _await_stop(self) -> None:
        """Watcher coroutine that returns when stop() is called from the GUI."""
        while not self._stop.is_set():
            await asyncio.sleep(0.2)

    async def _sysmon_loop(self, dvt, Sysmontap) -> None:
        async with await Sysmontap.create(dvt) as sysmon:
            async for entries in sysmon.iter_processes():
                if self._stop.is_set():
                    return
                self._emit(self._extract_proc(entries))

    async def _graphics_loop(self, dvt, Graphics) -> None:
        # Graphics is optional — losing it shouldn't kill the metrics session.
        try:
            async with Graphics(dvt) as graphics:
                async for sample in graphics:
                    if self._stop.is_set():
                        return
                    gfx = self._extract_gfx(sample)
                    if gfx:
                        with self._gfx_lock:
                            self._latest_gfx = gfx
        except Exception:  # noqa: BLE001 - CPU/mem keep flowing without GPU
            pass

    # ---- Defensive field extraction (version-dependent shapes) ------------

    def _extract_proc(self, entries: list[dict] | Any) -> dict[str, Any]:
        """Pull (cpu_pct_per_core, rss_mb, pid) for our process from a snapshot.

        ``Sysmontap.iter_processes`` yields ``list[dict]`` where each dict is
        one process — keys come from the device's process_attributes set
        (typically includes ``name``, ``pid``, ``cpuUsage``, ``physFootprint``).
        We match on bundle_id substring against name fields and read CPU + RSS
        defensively.
        """
        out: dict[str, Any] = {}
        rows: list[dict] = []
        if isinstance(entries, list):
            rows = [r for r in entries if isinstance(r, dict)]

        for row in rows:
            name = ""
            for key in _PROC_NAME_KEYS:
                v = row.get(key)
                if v:
                    name = str(v)
                    break
            if self.bundle_id and self.bundle_id not in name:
                continue

            cpu = next((row.get(k) for k in _PROC_CPU_KEYS if row.get(k) is not None), None)
            if cpu is not None:
                try:
                    cpu_per_core = float(cpu)
                    # Sysmontap reports CPU as 0-100 (per device) or a 0-1
                    # fraction depending on version / attribute set; normalize.
                    if cpu_per_core <= 1.0:
                        cpu_per_core *= 100.0
                    out["cpu_pct_per_core"] = round(cpu_per_core, 2)
                    if self._cpu_count and self._cpu_count > 0:
                        out["cpu_pct"] = round(cpu_per_core / self._cpu_count, 2)
                except (TypeError, ValueError):
                    pass

            mem = next((row.get(k) for k in _PROC_RSS_KEYS if row.get(k) is not None), None)
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
    def _extract_gfx(sample: Any) -> dict[str, Any]:
        """Pull (fps, gpu_util) from a Graphics event payload.

        Graphics events are queued from both on_dispatch (selector + args
        tuple) and on_notification (raw payload). The sample data we care
        about lives in dict-shaped notifications; tuples skip silently.
        """
        out: dict[str, Any] = {}
        # on_dispatch shape: (selector, [args...]) — args[0] is often the dict
        if isinstance(sample, tuple) and len(sample) >= 2 and isinstance(sample[1], list):
            for a in sample[1]:
                if isinstance(a, dict):
                    sample = a
                    break
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
