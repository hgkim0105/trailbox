"""Local filesystem backend — reads ``$TRAILBOX_OUTPUT/{session_id}/`` directly."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

from core.frame_extractor import extract_frame_jpeg
from .. import filters
from ..errors import SessionNotFound, FileNotAvailable


def _output_root() -> Path:
    env = os.environ.get("TRAILBOX_OUTPUT")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "output"
    return Path(__file__).resolve().parent.parent.parent / "output"


def _load_meta(session_dir: Path) -> dict[str, Any]:
    p = session_dir / "session_meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue


def _iter_log_records(session_dir: Path) -> Iterator[dict[str, Any]]:
    logs_dir = session_dir / "logs"
    if not logs_dir.is_dir():
        return
    for p in sorted(logs_dir.glob("*.jsonl")):
        yield from _iter_jsonl(p)


class LocalBackend:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _output_root()

    def _resolve(self, session_id: str) -> Path:
        d = self.root / session_id
        if not d.is_dir():
            raise SessionNotFound(session_id)
        return d

    # ---- Tools ------------------------------------------------------------

    def list_sessions(self, limit: int) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        sessions = [p for p in self.root.iterdir() if p.is_dir()]
        sessions.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        out: list[dict[str, Any]] = []
        for s in sessions[: max(1, int(limit))]:
            meta = _load_meta(s)
            out.append(filters.build_session_summary(
                meta, session_id_fallback=s.name, source="local",
            ))
        return out

    def get_session(self, session_id: str) -> dict[str, Any]:
        d = self._resolve(session_id)
        meta = _load_meta(d)
        logs_dir = d / "logs"
        log_files = (
            [str(p.resolve()) for p in sorted(logs_dir.glob("*.jsonl"))]
            if logs_dir.is_dir()
            else []
        )
        files = {
            "screen_mp4": str((d / "screen.mp4").resolve()),
            "logs_jsonl": str((logs_dir / "logs.jsonl").resolve()),
            "logs_vtt": str((logs_dir / "logs.vtt").resolve()),
            "log_files": log_files,
            "inputs_jsonl": str((d / "inputs" / "inputs.jsonl").resolve()),
            "inputs_vtt": str((d / "inputs" / "inputs.vtt").resolve()),
            "metrics_jsonl": str((d / "metrics" / "process.jsonl").resolve()),
            "viewer_html": str((d / "viewer.html").resolve()),
            "session_meta": str((d / "session_meta.json").resolve()),
        }
        return {
            "session_id": session_id,
            "session_dir": str(d.resolve()),
            "meta": meta,
            "files": files,
            "system": meta.get("system"),
            "frame_stats": meta.get("frame_stats"),
            "capture": meta.get("capture") if isinstance(meta.get("capture"), dict) else None,
            "metrics_target_name": meta.get("metrics_target_name"),
        }

    def query_events(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
        kinds: list[str] | None,
        text: str | None,
        limit: int,
    ) -> dict[str, Any]:
        d = self._resolve(session_id)
        kind_set = {k.lower() for k in (kinds or [])}
        return filters.filter_events(
            _iter_log_records(d),
            _iter_jsonl(d / "inputs" / "inputs.jsonl"),
            t_start, t_end, kind_set, text, limit,
        )

    def get_metrics(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]:
        d = self._resolve(session_id)
        samples = filters.filter_time_range(
            _iter_jsonl(d / "metrics" / "process.jsonl"), t_start, t_end,
        )
        if not samples:
            return {"count": 0, "summary": {}, "samples": []}
        summary = filters.summarize_metrics(samples)
        return {"count": len(samples), "summary": summary, "samples": samples}

    def search_logs(
        self,
        session_id: str,
        query: str,
        limit: int,
    ) -> dict[str, Any]:
        d = self._resolve(session_id)
        return filters.search_log_records(_iter_log_records(d), query, limit)

    def get_frame_jpeg(self, session_id: str, t_video_s: float) -> bytes:
        d = self._resolve(session_id)
        video = d / "screen.mp4"
        if not video.exists():
            raise FileNotAvailable(f"screen.mp4 not in {session_id}")
        return extract_frame_jpeg(video, t_video_s)

    def get_viewer_path(self, session_id: str) -> str:
        d = self._resolve(session_id)
        viewer = d / "viewer.html"
        if not viewer.exists():
            raise FileNotAvailable(f"viewer.html not in {session_id}")
        return str(viewer.resolve())

    def get_frame_stats(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]:
        d = self._resolve(session_id)
        frames = filters.filter_time_range(
            _iter_jsonl(d / "metrics" / "frames.jsonl"), t_start, t_end,
        )
        if not frames:
            return {"count": 0, "stats": {}, "frames": []}
        stats = filters.summarize_frame_stats(frames)
        return {"count": len(frames), "stats": stats, "frames": frames}
