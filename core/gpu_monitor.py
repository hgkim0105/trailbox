r"""Per-process GPU utilization + VRAM via Windows Performance Counters (PDH).

Vendor-agnostic — works on NVIDIA / AMD / Intel uniformly because Windows
exposes ``\GPU Engine(*)\Utilization Percentage`` for any WDDM driver.

For a target PID we add one PDH counter per ``(luid, phys, engine_type)``
instance and sample them together. ``gpu_pct`` is the **maximum** engine
utilization (matches Task Manager's "GPU" column convention — different
engines run in parallel on different parts of the GPU, so the busiest engine
is the bottleneck for the process). ``gpu_engines`` carries the per-engine
breakdown so callers can distinguish render-bound (3D high) from playback
(VideoDecode high) etc.

Note: PDH utilization counters are *delta*-based — the first sample after
``AddCounter`` always returns 0. We prime once at start and skip that read.
"""
from __future__ import annotations

import re
from typing import Any

import win32pdh


_ENG_PATH = r"\GPU Engine(*)\Utilization Percentage"
_MEM_PATH = r"\GPU Process Memory(*)\Dedicated Usage"

# Instance name format observed on Windows 10/11:
#   pid_1234_luid_0x00000000_0x00012345_phys_0_eng_0_engtype_3D
_ENG_RE = re.compile(r"pid_(\d+).*?engtype_([A-Za-z0-9]+)")
_MEM_RE = re.compile(r"pid_(\d+)")


class GPUMonitor:
    def __init__(self, target_pid: int) -> None:
        self.target_pid = int(target_pid)
        self._query = None
        self._engine_counters: dict[Any, str] = {}  # handle -> engine type
        self._memory_counters: list[Any] = []

    def start(self) -> None:
        """Open the PDH query and attach counters for ``target_pid``.

        Safe to call even if no GPU counters exist for the target — in that
        case ``sample()`` will just return zeros.
        """
        self._query = win32pdh.OpenQuery()
        try:
            self._attach_engine_counters()
            self._attach_memory_counters()
            # Prime delta counters (first read is always 0).
            try:
                win32pdh.CollectQueryData(self._query)
            except Exception:  # noqa: BLE001 - empty query case
                pass
        except Exception:  # noqa: BLE001
            self.stop()
            raise

    def stop(self) -> None:
        if self._query is not None:
            try:
                win32pdh.CloseQuery(self._query)
            except Exception:  # noqa: BLE001
                pass
            self._query = None
        self._engine_counters.clear()
        self._memory_counters.clear()

    def sample(self) -> dict[str, Any]:
        """Read all attached counters once. Returns zeros on any failure path."""
        if self._query is None:
            return {"gpu_pct": 0.0, "gpu_vram_mb": 0.0, "gpu_engines": {}}
        try:
            win32pdh.CollectQueryData(self._query)
        except Exception:  # noqa: BLE001
            return {"gpu_pct": 0.0, "gpu_vram_mb": 0.0, "gpu_engines": {}}

        engines: dict[str, float] = {}
        for handle, eng in self._engine_counters.items():
            try:
                _, val = win32pdh.GetFormattedCounterValue(
                    handle, win32pdh.PDH_FMT_DOUBLE
                )
            except Exception:  # noqa: BLE001 - instance may have disappeared
                continue
            engines[eng] = engines.get(eng, 0.0) + float(val)

        # Task-Manager-style headline number: the busiest engine.
        gpu_pct = max(engines.values()) if engines else 0.0

        mem_bytes = 0
        for handle in self._memory_counters:
            try:
                _, val = win32pdh.GetFormattedCounterValue(
                    handle, win32pdh.PDH_FMT_LARGE
                )
            except Exception:  # noqa: BLE001
                continue
            mem_bytes += int(val)

        return {
            "gpu_pct": round(gpu_pct, 2),
            "gpu_vram_mb": round(mem_bytes / 1024 / 1024, 1),
            "gpu_engines": {k: round(v, 2) for k, v in engines.items() if v > 0.01},
        }

    # ---- Internals --------------------------------------------------------

    def _attach_engine_counters(self) -> None:
        try:
            paths = win32pdh.ExpandCounterPath(_ENG_PATH)
        except Exception:  # noqa: BLE001 - GPU counters not available
            return
        for path in paths:
            m = _ENG_RE.search(path)
            if not m:
                continue
            if int(m.group(1)) != self.target_pid:
                continue
            try:
                handle = win32pdh.AddCounter(self._query, path)
            except Exception:  # noqa: BLE001
                continue
            self._engine_counters[handle] = m.group(2)

    def _attach_memory_counters(self) -> None:
        try:
            paths = win32pdh.ExpandCounterPath(_MEM_PATH)
        except Exception:  # noqa: BLE001
            return
        for path in paths:
            m = _MEM_RE.search(path)
            if not m:
                continue
            if int(m.group(1)) != self.target_pid:
                continue
            try:
                handle = win32pdh.AddCounter(self._query, path)
            except Exception:  # noqa: BLE001
                continue
            self._memory_counters.append(handle)
