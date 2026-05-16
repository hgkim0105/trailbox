"""MCP server entrypoint. Run as ``python -m mcp_server`` (stdio transport).

Configure the output directory via the ``TRAILBOX_OUTPUT`` env var; otherwise
the server looks at ``../output`` relative to this file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image


def _output_root() -> Path:
    """Resolve where to read sessions from.

    Priority:
      1. ``$TRAILBOX_OUTPUT`` (explicit override — always wins)
      2. When frozen by PyInstaller: ``<exe_dir>/output`` so users can drop
         Trailbox-mcp.exe next to the GUI's output folder and Just Work
      3. Otherwise: ``../output`` relative to this module (source layout)
    """
    env = os.environ.get("TRAILBOX_OUTPUT")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "output"
    return Path(__file__).resolve().parent.parent / "output"


mcp = FastMCP(
    "trailbox",
    instructions=(
        "Read-only analysis of Trailbox QA session recordings.\n\n"
        "Each session lives at <output>/{session_id}/ and contains:\n"
        "  - screen.mp4 (video + audio)\n"
        "  - logs/logs.jsonl (game/app logs, ECS-style)\n"
        "  - inputs/inputs.jsonl (keyboard/mouse events)\n"
        "  - metrics/process.jsonl (1Hz CPU/RSS/threads samples)\n"
        "  - session_meta.json, viewer.html\n\n"
        "All events share a 't_video_s' field (seconds from video start) so "
        "logs/inputs/metrics can be correlated across sources at a given moment."
    ),
)


# ---- Helpers ---------------------------------------------------------------


def _resolve_session(session_id: str) -> Path:
    root = _output_root()
    session_dir = root / session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"session not found: {session_id}")
    return session_dir


def _load_meta(session_dir: Path) -> dict[str, Any]:
    meta_path = session_dir / "session_meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue


def _matches_kind(event: dict, kind_set: set[str]) -> bool:
    """Match against {'log','input','mouse','key'}; empty set = match all."""
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


# ---- Tools -----------------------------------------------------------------


@mcp.tool()
def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """List the most-recent Trailbox sessions (newest first).

    Each entry has: session_id, started_at, duration_seconds, exe_path,
    log_lines, input_events, metric_samples, screen_frames, effective_fps.
    """
    root = _output_root()
    if not root.is_dir():
        return []
    sessions = [p for p in root.iterdir() if p.is_dir()]
    sessions.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for s in sessions[: max(1, int(limit))]:
        meta = _load_meta(s)
        out.append(
            {
                "session_id": meta.get("session_id", s.name),
                "started_at": meta.get("started_at"),
                "duration_seconds": meta.get("duration_seconds"),
                "exe_path": meta.get("exe_path"),
                "log_lines": meta.get("log_lines", 0),
                "input_events": meta.get("input_events", 0),
                "metric_samples": meta.get("metric_samples", 0),
                "screen_frames": meta.get("screen_frames", 0),
                "effective_fps": meta.get("effective_fps"),
            }
        )
    return out


@mcp.tool()
def get_session(session_id: str) -> dict[str, Any]:
    """Full session metadata + filesystem paths for the session's artifacts."""
    session_dir = _resolve_session(session_id)
    meta = _load_meta(session_dir)
    files = {
        "screen_mp4": str((session_dir / "screen.mp4").resolve()),
        "logs_jsonl": str((session_dir / "logs" / "logs.jsonl").resolve()),
        "logs_vtt": str((session_dir / "logs" / "logs.vtt").resolve()),
        "inputs_jsonl": str((session_dir / "inputs" / "inputs.jsonl").resolve()),
        "inputs_vtt": str((session_dir / "inputs" / "inputs.vtt").resolve()),
        "metrics_jsonl": str((session_dir / "metrics" / "process.jsonl").resolve()),
        "viewer_html": str((session_dir / "viewer.html").resolve()),
        "session_meta": str((session_dir / "session_meta.json").resolve()),
    }
    return {
        "session_id": session_id,
        "session_dir": str(session_dir.resolve()),
        "meta": meta,
        "files": files,
    }


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
    session_dir = _resolve_session(session_id)
    kind_set = {k.lower() for k in (kinds or [])}
    text_lo = text.lower() if text else None

    matched: list[dict[str, Any]] = []

    for rec in _iter_jsonl(session_dir / "logs" / "logs.jsonl"):
        t = float(rec.get("t_video_s", 0.0))
        if t_start is not None and t < t_start:
            continue
        if t_end is not None and t > t_end:
            continue
        if not _matches_kind(rec, kind_set):
            continue
        if text_lo:
            blob = (
                rec.get("message", "")
                + " "
                + json.dumps(rec.get("log", {}), ensure_ascii=False)
            ).lower()
            if text_lo not in blob:
                continue
        matched.append({"kind": "log", **rec})

    for rec in _iter_jsonl(session_dir / "inputs" / "inputs.jsonl"):
        t = float(rec.get("t_video_s", 0.0))
        if t_start is not None and t < t_start:
            continue
        if t_end is not None and t > t_end:
            continue
        if not _matches_kind(rec, kind_set):
            continue
        if text_lo:
            blob = json.dumps(rec.get("input", {}), ensure_ascii=False).lower()
            if text_lo not in blob:
                continue
        matched.append({"kind": "input", **rec})

    matched.sort(key=lambda e: float(e.get("t_video_s", 0.0)))
    truncated = len(matched) > limit
    return {
        "count": len(matched),
        "truncated": truncated,
        "events": matched[: max(0, int(limit))],
    }


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
    session_dir = _resolve_session(session_id)
    samples: list[dict[str, Any]] = []
    for rec in _iter_jsonl(session_dir / "metrics" / "process.jsonl"):
        t = float(rec.get("t_video_s", 0.0))
        if t_start is not None and t < t_start:
            continue
        if t_end is not None and t > t_end:
            continue
        samples.append(rec)

    if not samples:
        return {"count": 0, "samples": []}

    cpus = [s.get("process", {}).get("cpu_pct") for s in samples]
    cpus = [c for c in cpus if isinstance(c, (int, float))]
    rss = [s.get("process", {}).get("rss_mb") for s in samples]
    rss = [r for r in rss if isinstance(r, (int, float))]

    summary: dict[str, Any] = {}
    if cpus:
        summary["cpu_max"] = max(cpus)
        summary["cpu_avg"] = round(sum(cpus) / len(cpus), 2)
    if rss:
        summary["rss_max_mb"] = max(rss)
        summary["rss_min_mb"] = min(rss)

    return {
        "count": len(samples),
        "summary": summary,
        "samples": samples,
    }


_FRAME_MAX_BYTES = 950_000   # Stay safely under Claude's 1 MB image input cap.
_FRAME_DEFAULT_WIDTH = 1280  # Initial downscale target; auto-tunes down if needed.
_FRAME_MIN_WIDTH = 480       # Don't degrade below this even chasing the byte cap.


def _extract_frame(video: Path, t: float, max_width: int, q: int) -> bytes:
    """One ffmpeg call: seek, decode 1 frame, downscale, JPEG-encode to stdout."""
    from imageio_ffmpeg import get_ffmpeg_exe

    cmd = [
        get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel", "error",
        # -ss BEFORE -i = fast keyframe seek; accurate enough for QA review.
        "-ss", f"{t:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        # Clamp width to max_width while preserving aspect; -2 keeps height even.
        "-vf", f"scale='min({max_width},iw)':-2",
        "-q:v", str(q),  # JPEG quality: 2 (best) … 31 (worst). 4–7 is sweet spot.
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        check=False,
        creationflags=(
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        ),
    )
    if result.returncode != 0 or not result.stdout:
        stderr_tail = (result.stderr or b"").decode("utf-8", errors="replace")[-200:]
        raise RuntimeError(
            f"ffmpeg failed to extract frame at t={t:.3f}s: {stderr_tail}"
        )
    return result.stdout


@mcp.tool()
def get_frame_at(session_id: str, t_video_s: float) -> Image:
    """Extract a single frame from the session's ``screen.mp4`` at ``t_video_s``.

    Returns a JPEG (not PNG — 4K screenshots compress much better as JPEG and
    must fit under Claude's ~1 MB image input limit). Auto-tunes resolution
    and quality to stay under that cap: starts at 1280px wide, q=5; if still
    too large (very busy frame), drops to 960px then 720px.

    Useful for correlating with logs / input / metrics — e.g. "what was on
    screen when this error logged?" or "what's the UI state at the CPU spike?".
    """
    session_dir = _resolve_session(session_id)
    video = session_dir / "screen.mp4"
    if not video.exists():
        raise FileNotFoundError(f"screen.mp4 not in {session_dir}")

    t = max(0.0, float(t_video_s))

    # Try progressively cheaper outputs until we fit under the byte cap.
    attempts = [
        (_FRAME_DEFAULT_WIDTH, 5),
        (960, 6),
        (720, 7),
        (_FRAME_MIN_WIDTH, 9),
    ]
    last: bytes = b""
    for width, q in attempts:
        last = _extract_frame(video, t, width, q)
        if len(last) <= _FRAME_MAX_BYTES:
            return Image(data=last, format="jpeg")
    # All attempts > cap; return the smallest anyway so the caller can decide.
    return Image(data=last, format="jpeg")


@mcp.tool()
def get_viewer_path(session_id: str) -> str:
    """Absolute filesystem path to the session's viewer.html.

    Useful for the client to open the integrated viewer in a browser (file://).
    """
    session_dir = _resolve_session(session_id)
    viewer = session_dir / "viewer.html"
    if not viewer.exists():
        raise FileNotFoundError(f"viewer.html not in {session_dir}")
    return str(viewer.resolve())


@mcp.tool()
def search_logs(
    session_id: str,
    query: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Free-text search over a session's log messages (case-insensitive)."""
    session_dir = _resolve_session(session_id)
    q_lo = query.lower()
    hits: list[dict[str, Any]] = []
    for rec in _iter_jsonl(session_dir / "logs" / "logs.jsonl"):
        msg = rec.get("message", "")
        if q_lo in msg.lower():
            hits.append(rec)
    truncated = len(hits) > limit
    return {
        "count": len(hits),
        "truncated": truncated,
        "matches": hits[: max(0, int(limit))],
    }


if __name__ == "__main__":
    mcp.run()
