"""Shared filtering, aggregation, and summary helpers for MCP backends.

Both LocalBackend and HubBackend delegate their data-processing logic here
so the filtering/summarisation code exists in exactly one place.
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------

def matches_kind(event: dict[str, Any], kind_set: set[str]) -> bool:
    if not kind_set:
        return True
    if "log" in event:
        return "log" in kind_set
    if "input" in event:
        if "input" in kind_set:
            return True
        t = event.get("input", {}).get("type")
        if t == "mouse" and "mouse" in kind_set:
            return True
        if t == "key" and ("key" in kind_set or "keyboard" in kind_set):
            return True
        return False
    return False


def _matches_text(event: dict[str, Any], text_lower: str | None) -> bool:
    if not text_lower:
        return True
    if "log" in event:
        blob = (
            event.get("message", "")
            + " "
            + json.dumps(event.get("log", {}), ensure_ascii=False)
        ).lower()
        return text_lower in blob
    if "input" in event:
        blob = json.dumps(event.get("input", {}), ensure_ascii=False).lower()
        return text_lower in blob
    return False


def _classify_event(rec: dict[str, Any]) -> dict[str, Any]:
    if "log" in rec:
        return {"kind": "log", **rec}
    if "input" in rec:
        return {"kind": "input", **rec}
    return rec


def filter_events(
    log_records: Iterable[dict[str, Any]],
    input_records: Iterable[dict[str, Any]],
    t_start: float | None,
    t_end: float | None,
    kind_set: set[str],
    text: str | None,
    limit: int,
) -> dict[str, Any]:
    text_lower = text.lower() if text else None
    matched: list[dict[str, Any]] = []

    for rec in log_records:
        t = float(rec.get("t_video_s", 0.0))
        if t_start is not None and t < t_start:
            continue
        if t_end is not None and t > t_end:
            continue
        if not matches_kind(rec, kind_set):
            continue
        if not _matches_text(rec, text_lower):
            continue
        matched.append(_classify_event(rec))

    for rec in input_records:
        t = float(rec.get("t_video_s", 0.0))
        if t_start is not None and t < t_start:
            continue
        if t_end is not None and t > t_end:
            continue
        if not matches_kind(rec, kind_set):
            continue
        if not _matches_text(rec, text_lower):
            continue
        matched.append(_classify_event(rec))

    matched.sort(key=lambda e: float(e.get("t_video_s", 0.0)))
    truncated = len(matched) > limit
    return {
        "count": len(matched),
        "truncated": truncated,
        "events": matched[: max(0, int(limit))],
    }


# ---------------------------------------------------------------------------
# Time-range filter (for metrics / frames)
# ---------------------------------------------------------------------------

def filter_time_range(
    records: Iterable[dict[str, Any]],
    t_start: float | None,
    t_end: float | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        t = float(rec.get("t_video_s", 0.0))
        if t_start is not None and t < t_start:
            continue
        if t_end is not None and t > t_end:
            continue
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------

def summarize_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {}

    def _extract(field: str) -> list[float]:
        vals = [s.get("process", {}).get(field) for s in samples]
        return [v for v in vals if isinstance(v, (int, float))]

    summary: dict[str, Any] = {}

    cpus = _extract("cpu_pct")
    if cpus:
        summary["cpu_max"] = max(cpus)
        summary["cpu_avg"] = round(sum(cpus) / len(cpus), 2)

    rss = _extract("rss_mb")
    if rss:
        summary["rss_max_mb"] = max(rss)
        summary["rss_min_mb"] = min(rss)

    gpus = _extract("gpu_pct")
    if gpus:
        summary["gpu_max"] = max(gpus)
        summary["gpu_avg"] = round(sum(gpus) / len(gpus), 2)

    vram = _extract("gpu_vram_mb")
    if vram:
        summary["vram_max_mb"] = max(vram)

    threads = _extract("threads")
    if threads:
        summary["threads_max"] = int(max(threads))

    handles = _extract("handles")
    if handles:
        summary["handles_max"] = int(max(handles))

    return summary


# ---------------------------------------------------------------------------
# Frame-timing statistics
# ---------------------------------------------------------------------------

def summarize_frame_stats(frames: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [
        f.get("frame", {}).get("delta_ms")
        for f in frames
        if f.get("frame", {}).get("delta_ms") is not None
    ]
    deltas = [d for d in deltas if isinstance(d, (int, float))]

    total_frames = len(frames)
    if not deltas:
        return {"total_frames": total_frames}

    sorted_d = sorted(deltas)
    n = len(sorted_d)
    avg_delta = sum(sorted_d) / n
    duration_s = sum(sorted_d) / 1000.0

    variance = sum((d - avg_delta) ** 2 for d in sorted_d) / n
    jitter_ms = round(math.sqrt(variance), 3)

    stutter_threshold = avg_delta * 2
    stutter_count = sum(1 for d in sorted_d if d > stutter_threshold)

    return {
        "total_frames": total_frames,
        "duration_s": round(duration_s, 3),
        "avg_fps": round(1000.0 / avg_delta, 2) if avg_delta > 0 else 0,
        "min_delta_ms": round(sorted_d[0], 3),
        "max_delta_ms": round(sorted_d[-1], 3),
        "avg_delta_ms": round(avg_delta, 3),
        "p95_delta_ms": round(sorted_d[min(n - 1, int(n * 0.95))], 3),
        "p99_delta_ms": round(sorted_d[min(n - 1, int(n * 0.99))], 3),
        "jitter_ms": jitter_ms,
        "stutter_count": stutter_count,
        "stutter_pct": round(stutter_count / n * 100, 2) if n else 0,
    }


# ---------------------------------------------------------------------------
# Log search
# ---------------------------------------------------------------------------

def search_log_records(
    records: Iterable[dict[str, Any]],
    query: str,
    limit: int,
) -> dict[str, Any]:
    q_lower = query.lower()
    hits: list[dict[str, Any]] = []
    for rec in records:
        msg = rec.get("message", "")
        if q_lower in msg.lower():
            hits.append(rec)
    truncated = len(hits) > limit
    return {
        "count": len(hits),
        "truncated": truncated,
        "matches": hits[: max(0, int(limit))],
    }


# ---------------------------------------------------------------------------
# Session summary builder
# ---------------------------------------------------------------------------

def build_session_summary(
    meta: dict[str, Any],
    session_id_fallback: str = "",
    source: str = "local",
) -> dict[str, Any]:
    system = meta.get("system") or {}
    cpu = system.get("cpu") or {}
    gpus = system.get("gpus") or []
    ram = system.get("ram") or {}
    os_info = system.get("os") or {}

    capture = meta.get("capture") if isinstance(meta.get("capture"), dict) else {}
    target = capture.get("target") if isinstance(capture.get("target"), dict) else {}

    return {
        "session_id": meta.get("session_id") or session_id_fallback,
        "started_at": meta.get("started_at"),
        "duration_seconds": meta.get("duration_seconds"),
        "exe_path": meta.get("exe_path"),
        "log_lines": meta.get("log_lines", 0),
        "input_events": meta.get("input_events", 0),
        "metric_samples": meta.get("metric_samples", 0),
        "screen_frames": meta.get("screen_frames", 0),
        "effective_fps": meta.get("effective_fps"),
        "platform": os_info.get("platform"),
        "device_kind": target.get("kind"),
        "target_name": meta.get("metrics_target_name"),
        "owner": meta.get("owner", ""),
        "description": meta.get("description", ""),
        "system_summary": {
            "cpu": cpu.get("name"),
            "gpu": gpus[0] if gpus else None,
            "ram_mb": ram.get("total_mb"),
        },
        "source": source,
    }
