"""MCP server entrypoint. Run as ``python -m mcp_server`` (stdio transport).

Backend selection:
  - ``TRAILBOX_HUB_URL`` set → HubBackend (HTTP-driven; reads from a remote
    Trailbox Hub. Optional ``TRAILBOX_HUB_TOKEN`` for the API token).
  - otherwise → LocalBackend (reads ``$TRAILBOX_OUTPUT/{session_id}/`` from
    the local filesystem). Default ``TRAILBOX_OUTPUT`` is ``../output``
    relative to this module (source layout) or ``<exe_dir>/output`` when
    frozen.
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

from .backends.local import LocalBackend
from .backends.hub import HubBackend


def _pick_backend():
    hub_url = os.environ.get("TRAILBOX_HUB_URL", "").strip()
    if hub_url:
        return HubBackend(
            base_url=hub_url,
            token=os.environ.get("TRAILBOX_HUB_TOKEN", "").strip(),
        )
    return LocalBackend()


backend = _pick_backend()
_is_hub = isinstance(backend, HubBackend)

_instructions = (
    "Read-only analysis of Trailbox QA session recordings.\n\n"
    "Each session contains:\n"
    "  - screen.mp4 (video + audio)\n"
    "  - logs/logs.jsonl (game/app logs, ECS-style)\n"
    "  - inputs/inputs.jsonl (keyboard/mouse events)\n"
    "  - metrics/process.jsonl (1Hz CPU/RSS/threads samples)\n"
    "  - session_meta.json, viewer.html\n\n"
    "All events share a 't_video_s' field (seconds from video start) so "
    "logs/inputs/metrics can be correlated across sources at a given moment.\n"
)
if _is_hub:
    _instructions += f"\nBackend: Trailbox Hub at {backend.base_url}\n"
else:
    _instructions += "\nBackend: local filesystem\n"


mcp = FastMCP("trailbox", instructions=_instructions)


# ---- Tools — thin shells around the backend -------------------------------


@mcp.tool()
def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """List the most-recent Trailbox sessions (newest first).

    Each entry has: session_id, started_at, duration_seconds, exe_path,
    log_lines, input_events, metric_samples, screen_frames, effective_fps.
    """
    return backend.list_sessions(limit)


@mcp.tool()
def get_session(session_id: str) -> dict[str, Any]:
    """Full session metadata + paths/URLs for the session's artifacts."""
    return backend.get_session(session_id)


@mcp.tool()
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
def get_metrics(
    session_id: str,
    t_start: float | None = None,
    t_end: float | None = None,
) -> dict[str, Any]:
    """Process telemetry samples (CPU%, RSS, threads, handles) in a time window.

    Response includes a ``summary`` block with cpu_max/avg and rss_min/max,
    plus the raw ``samples`` array. ``cpu_pct`` is normalized to total system
    capacity (0-100); ``cpu_pct_per_core`` is the raw per-core value.
    """
    return backend.get_metrics(session_id, t_start, t_end)


@mcp.tool()
def search_logs(
    session_id: str,
    query: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Free-text search over a session's log messages (case-insensitive)."""
    return backend.search_logs(session_id, query, limit)


@mcp.tool()
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
def get_viewer_path(session_id: str) -> str:
    """Path (local backend) or URL (Hub backend) to the session's viewer.html.

    Local mode: absolute filesystem path the user can open via file://.
    Hub mode: the auth-protected URL to viewer.html on the Hub.
    """
    return backend.get_viewer_path(session_id)


if __name__ == "__main__":
    mcp.run()


__all__ = ["mcp", "backend"]
