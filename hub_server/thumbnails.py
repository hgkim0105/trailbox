"""Session thumbnail generation.

Pulls a single jpeg frame out of ``screen.mp4`` using the ffmpeg binary
bundled by ``imageio-ffmpeg`` and caches it as ``thumb.jpg`` next to the
video. Calls are idempotent — if the file already exists we treat it as
cached and serve it as-is.

Why ffmpeg-via-subprocess instead of imageio's reader API:
- Single seek + single frame extract is what ffmpeg is best at; no need
  to spin up a Python-side decoder.
- Constraining to a CLI invocation means the same code works against
  whatever the host's bundled ffmpeg supports (h264 / hevc / etc).

Thumbnails are intentionally small (480px wide, jpeg q=4 fast preset) —
they're rendered in 280–320px CSS containers, so going larger just wastes
bandwidth.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("trailbox.hub.thumbnails")

# Cached ffmpeg path lookup; imageio_ffmpeg.get_ffmpeg_exe() does a disk
# probe on every call so we memoize.
_FFMPEG: Optional[str] = None


def _ffmpeg_path() -> Optional[str]:
    global _FFMPEG
    if _FFMPEG is not None:
        return _FFMPEG or None
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        _FFMPEG = get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        log.exception("thumbnails: imageio_ffmpeg unavailable")
        _FFMPEG = ""
    return _FFMPEG or None


def thumbnail_path(session_dir: Path) -> Path:
    return session_dir / "thumb.jpg"


def ensure_thumbnail(session_dir: Path, *, at_seconds: float = 5.0, width: int = 480) -> Optional[Path]:
    """Return path to ``thumb.jpg``, creating it from ``screen.mp4`` if absent.

    Returns ``None`` when no thumbnail can be produced (no screen.mp4, no
    ffmpeg, decoder failure). Callers should treat ``None`` as "fall back
    to the gradient+icon placeholder".

    Successful generations are cached on disk; subsequent calls short-circuit.
    """
    if not session_dir.is_dir():
        return None
    dest = thumbnail_path(session_dir)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    video = session_dir / "screen.mp4"
    if not video.is_file():
        return None

    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return None

    # Try `at_seconds` first; if the video is shorter, retry at 0.
    for seek in (max(0.0, at_seconds), 0.0):
        try:
            # Fast seek (-ss before -i) for thumbnail speed; accuracy doesn't
            # matter when we just want a representative frame.
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-ss", f"{seek:.2f}",
                    "-i", str(video),
                    "-vframes", "1",
                    "-vf", f"scale={width}:-2",
                    "-q:v", "4",
                    str(dest),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=20,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            # Clean up any partial file before retrying
            try:
                if dest.exists():
                    dest.unlink()
            except OSError:
                pass
            if seek == 0.0:
                log.warning("thumbnails: failed to extract frame for %s: %s", session_dir.name, e)
                return None
            # else: fall through and retry at 0.0
            continue
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
    return None
