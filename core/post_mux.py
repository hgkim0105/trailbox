"""Combine a video file and an audio file into a single mp4."""
from __future__ import annotations

import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe


def mux_av(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    audio_bitrate: str = "192k",
) -> None:
    """Mux video + audio into mp4. Video is copied; audio is re-encoded to AAC.

    Raises subprocess.CalledProcessError if ffmpeg exits non-zero.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = output_path.with_suffix(output_path.suffix + ".mux.log")
    with open(log_path, "wb") as log:
        cmd = [
            get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", audio_bitrate,
            "-shortest",
            str(output_path),
        ]
        subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
