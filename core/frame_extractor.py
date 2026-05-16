"""Extract a single JPEG frame from an mp4 via ffmpeg, sized to fit a byte cap.

Used by both the local MCP server and the Hub server, since both need to
return frames that fit under Claude's ~1 MB image input limit.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

FRAME_MAX_BYTES = 950_000   # Safely under Claude's 1 MB image input cap.
FRAME_DEFAULT_WIDTH = 1280  # Initial downscale target.
FRAME_MIN_WIDTH = 480       # Don't degrade below this chasing the byte cap.


def _extract_once(video: Path, t: float, max_width: int, q: int) -> bytes:
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


def extract_frame_jpeg(video: Path, t_video_s: float) -> bytes:
    """Extract a JPEG frame at ``t_video_s``, auto-tuning size to fit the cap."""
    t = max(0.0, float(t_video_s))
    attempts = [
        (FRAME_DEFAULT_WIDTH, 5),
        (960, 6),
        (720, 7),
        (FRAME_MIN_WIDTH, 9),
    ]
    last: bytes = b""
    for width, q in attempts:
        last = _extract_once(video, t, width, q)
        if len(last) <= FRAME_MAX_BYTES:
            return last
    return last  # > cap; let caller decide what to do.
