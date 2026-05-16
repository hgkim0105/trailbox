"""Local filesystem backend — reads ``$TRAILBOX_OUTPUT/{session_id}/`` directly."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

from core.frame_extractor import extract_frame_jpeg


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


def _matches_kind(event: dict, kind_set: set[str]) -> bool:
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


class LocalBackend:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _output_root()

    # ---- Helpers ----------------------------------------------------------

    def _resolve(self, session_id: str) -> Path:
        d = self.root / session_id
        if not d.is_dir():
            raise FileNotFoundError(f"session not found: {session_id}")
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
            out.append({
                "session_id": meta.get("session_id", s.name),
                "started_at": meta.get("started_at"),
                "duration_seconds": meta.get("duration_seconds"),
                "exe_path": meta.get("exe_path"),
                "log_lines": meta.get("log_lines", 0),
                "input_events": meta.get("input_events", 0),
                "metric_samples": meta.get("metric_samples", 0),
                "screen_frames": meta.get("screen_frames", 0),
                "effective_fps": meta.get("effective_fps"),
            })
        return out

    def get_session(self, session_id: str) -> dict[str, Any]:
        d = self._resolve(session_id)
        meta = _load_meta(d)
        files = {
            "screen_mp4": str((d / "screen.mp4").resolve()),
            "logs_jsonl": str((d / "logs" / "logs.jsonl").resolve()),
            "logs_vtt": str((d / "logs" / "logs.vtt").resolve()),
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
        text_lo = text.lower() if text else None
        matched: list[dict[str, Any]] = []

        for rec in _iter_jsonl(d / "logs" / "logs.jsonl"):
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

        for rec in _iter_jsonl(d / "inputs" / "inputs.jsonl"):
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

    def get_metrics(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]:
        d = self._resolve(session_id)
        samples: list[dict[str, Any]] = []
        for rec in _iter_jsonl(d / "metrics" / "process.jsonl"):
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

        return {"count": len(samples), "summary": summary, "samples": samples}

    def search_logs(
        self,
        session_id: str,
        query: str,
        limit: int,
    ) -> dict[str, Any]:
        d = self._resolve(session_id)
        q_lo = query.lower()
        hits: list[dict[str, Any]] = []
        for rec in _iter_jsonl(d / "logs" / "logs.jsonl"):
            msg = rec.get("message", "")
            if q_lo in msg.lower():
                hits.append(rec)
        truncated = len(hits) > limit
        return {
            "count": len(hits),
            "truncated": truncated,
            "matches": hits[: max(0, int(limit))],
        }

    def get_frame_jpeg(self, session_id: str, t_video_s: float) -> bytes:
        d = self._resolve(session_id)
        video = d / "screen.mp4"
        if not video.exists():
            raise FileNotFoundError(f"screen.mp4 not in {d}")
        return extract_frame_jpeg(video, t_video_s)

    def get_viewer_path(self, session_id: str) -> str:
        d = self._resolve(session_id)
        viewer = d / "viewer.html"
        if not viewer.exists():
            raise FileNotFoundError(f"viewer.html not in {d}")
        return str(viewer.resolve())
