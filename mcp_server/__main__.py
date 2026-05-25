"""MCP server entrypoint. Run as ``python -m mcp_server`` (stdio transport).

Backend selection:
  - ``TRAILBOX_HUB_URL`` set + local output dir exists → HybridBackend
    (local-first, Hub fallback for sessions not found locally).
  - ``TRAILBOX_HUB_URL`` set, no local output → HubBackend (HTTP-only).
  - otherwise → LocalBackend (reads ``$TRAILBOX_OUTPUT/{session_id}/``).
"""
from __future__ import annotations

import functools
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

from .backends.local import LocalBackend
from .backends.hub import HubBackend
from .backends.hybrid import HybridBackend
from .errors import ToolError


def _pick_backend():
    hub_url = os.environ.get("TRAILBOX_HUB_URL", "").strip()
    hub_token = os.environ.get("TRAILBOX_HUB_TOKEN", "").strip()

    local = LocalBackend()

    if hub_url:
        hub = HubBackend(base_url=hub_url, token=hub_token)
        if local.root.is_dir():
            return HybridBackend(local=local, hub=hub)
        return hub

    return local


backend = _pick_backend()

_instructions = (
    "Read-only analysis of Trailbox QA session recordings.\n\n"
    "Each session contains:\n"
    "  - screen.mp4 (video + audio)\n"
    "  - logs/logs.jsonl (game/app logs, ECS-style)\n"
    "  - inputs/inputs.jsonl (keyboard/mouse events)\n"
    "  - metrics/process.jsonl (1Hz CPU/RSS/GPU/threads samples)\n"
    "  - metrics/frames.jsonl (per-frame timing for FPS/jitter analysis)\n"
    "  - session_meta.json, viewer.html\n\n"
    "All events share a 't_video_s' field (seconds from video start) so "
    "logs/inputs/metrics can be correlated across sources at a given moment.\n"
)
if isinstance(backend, HybridBackend):
    _instructions += (
        f"\nBackend: hybrid (local filesystem + Hub at {backend.hub.base_url})\n"
        "Local sessions are preferred; Hub is queried for sessions not found locally.\n"
    )
elif isinstance(backend, HubBackend):
    _instructions += f"\nBackend: Trailbox Hub at {backend.base_url}\n"
else:
    _instructions += "\nBackend: local filesystem\n"


mcp = FastMCP("trailbox", instructions=_instructions)


# ---- Error handling decorator ---------------------------------------------

def _safe_tool(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError as e:
            return e.to_dict()
        except Exception as e:
            return {"error": str(e), "code": "INTERNAL_ERROR"}
    return wrapper


# ---- Tools ----------------------------------------------------------------


@mcp.tool()
@_safe_tool
def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """List the most-recent Trailbox sessions (newest first).

    Each entry has: session_id, started_at, duration_seconds, exe_path,
    log_lines, input_events, metric_samples, screen_frames, effective_fps,
    platform, device_kind, target_name, system_summary, source.
    """
    return backend.list_sessions(limit)


@mcp.tool()
@_safe_tool
def get_session(session_id: str) -> dict[str, Any]:
    """Full session metadata + paths/URLs for the session's artifacts.

    Returns the complete system snapshot (CPU, GPU, RAM, displays),
    pre-computed frame_stats, capture target info, and file paths/URLs.
    """
    return backend.get_session(session_id)


@mcp.tool()
@_safe_tool
def query_events(
    session_id: str,
    t_start: float | None = None,
    t_end: float | None = None,
    kinds: list[str] | None = None,
    text: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Query log + input events in a time window, filtered by kind and/or text.

    Args:
        session_id: target session.
        t_start: lower bound (seconds from video start, inclusive). None = no lower bound.
        t_end:   upper bound (seconds from video start, inclusive). None = no upper bound.
        kinds:   subset of ["log", "input", "mouse", "key"]. None / empty = all.
        text:    case-insensitive substring filter against message / event payload.
        limit:   max events to return; the response carries ``count`` and
                 ``truncated`` so callers know if they hit the cap.

    Events are returned sorted by ``t_video_s`` ascending.
    """
    return backend.query_events(session_id, t_start, t_end, kinds, text, limit)


@mcp.tool()
@_safe_tool
def get_metrics(
    session_id: str,
    t_start: float | None = None,
    t_end: float | None = None,
) -> dict[str, Any]:
    """Process telemetry samples (CPU%, RSS, GPU%, VRAM, threads, handles) in a time window.

    Response includes a ``summary`` block with cpu_max/avg, rss_min/max_mb,
    gpu_max/avg, vram_max_mb, threads_max, handles_max, plus the raw
    ``samples`` array. ``cpu_pct`` is normalized to total system capacity
    (0-100); ``cpu_pct_per_core`` is the raw per-core value.
    """
    return backend.get_metrics(session_id, t_start, t_end)


@mcp.tool()
@_safe_tool
def search_logs(
    session_id: str,
    query: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Free-text search over a session's log messages (case-insensitive)."""
    return backend.search_logs(session_id, query, limit)


@mcp.tool()
@_safe_tool
def get_frame_at(session_id: str, t_video_s: float) -> Image:
    """Extract a single frame from the session's ``screen.mp4`` at ``t_video_s``.

    Returns a JPEG (not PNG — 4K screenshots compress much better as JPEG and
    must fit under Claude's ~1 MB image input limit). Auto-tunes resolution
    and quality to stay under that cap.

    Useful for correlating with logs / input / metrics — e.g. "what was on
    screen when this error logged?" or "what's the UI state at the CPU spike?".
    """
    jpeg = backend.get_frame_jpeg(session_id, t_video_s)
    return Image(data=jpeg, format="jpeg")


@mcp.tool()
@_safe_tool
def get_viewer_path(session_id: str) -> str:
    """Path (local backend) or URL (Hub backend) to the session's viewer.html.

    Local mode: absolute filesystem path the user can open via file://.
    Hub mode: the auth-protected URL to viewer.html on the Hub.
    """
    return backend.get_viewer_path(session_id)


@mcp.tool()
@_safe_tool
def get_frame_stats(
    session_id: str,
    t_start: float | None = None,
    t_end: float | None = None,
) -> dict[str, Any]:
    """Frame timing analysis from the session's screen recording.

    Reads ``metrics/frames.jsonl`` and returns FPS statistics, frame delta
    percentiles (p95/p99), jitter (stddev of deltas), and stutter detection
    (frames exceeding 2x the average delta).

    Response includes a ``stats`` block with: total_frames, duration_s,
    avg_fps, min_delta_ms, max_delta_ms, avg_delta_ms, p95_delta_ms,
    p99_delta_ms, jitter_ms, stutter_count, stutter_pct.
    """
    return backend.get_frame_stats(session_id, t_start, t_end)


if __name__ == "__main__":
    mcp.run()


__all__ = ["mcp", "backend"]
