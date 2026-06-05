"""Tiny helpers shared by anything that reads / writes the t_video_s timeline.

Lives separate from `core/lookback.py` because trimming (`core/trim.py`) reuses
the same VTT formatting and the lookback module is heavy (imports every
recorder). Keep this file dependency-free.
"""
from __future__ import annotations


def format_vtt_time(seconds: float) -> str:
    """WebVTT cue timestamp: HH:MM:SS.mmm."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    return f"{h:02d}:{m:02d}:{s:06.3f}"
