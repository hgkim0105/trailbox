"""Hub HTTP backend — drives the same tools against a remote Trailbox Hub.

Reads jsonl files via ``GET /api/sessions/{id}/files/{path}`` and offloads
frame extraction to ``GET /api/sessions/{id}/frame?t=...``. All filtering and
aggregation is delegated to ``mcp_server.filters`` so the logic stays in one
place.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import httpx

from .. import filters
from ..errors import SessionNotFound, FileNotAvailable, HubUnavailable

log = logging.getLogger(__name__)


class HubBackend:
    def __init__(self, base_url: str, token: str = "", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ---- HTTP plumbing ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"X-Trailbox-Token": self.token} if self.token else {}

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=httpx.Timeout(self.timeout, read=self.timeout * 2),
        )

    def _get_json(self, path: str) -> Any:
        try:
            with self._client() as c:
                r = c.get(path)
                if r.status_code == 404:
                    raise SessionNotFound(path)
                r.raise_for_status()
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HubUnavailable(str(e)) from e

    def _get_bytes(self, path: str, params: dict | None = None) -> bytes:
        try:
            with self._client() as c:
                r = c.get(path, params=params)
                if r.status_code == 404:
                    raise FileNotAvailable(path)
                r.raise_for_status()
                return r.content
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HubUnavailable(str(e)) from e

    def _iter_jsonl(self, session_id: str, rel: str) -> Iterator[dict[str, Any]]:
        try:
            with self._client() as c:
                with c.stream("GET", f"/api/sessions/{session_id}/files/{rel}") as r:
                    if r.status_code == 404:
                        return
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HubUnavailable(str(e)) from e

    def _log_jsonl_paths(self, session_id: str) -> list[str]:
        try:
            meta = self._get_json(
                f"/api/sessions/{session_id}/files/session_meta.json"
            )
        except (httpx.HTTPError, SessionNotFound):
            return ["logs/logs.jsonl"]
        files = meta.get("files") or []
        rels = [
            f for f in files
            if isinstance(f, str) and f.startswith("logs/") and f.endswith(".jsonl")
        ]
        return sorted(rels) or ["logs/logs.jsonl"]

    def _iter_log_records(self, session_id: str) -> Iterator[dict[str, Any]]:
        for rel in self._log_jsonl_paths(session_id):
            yield from self._iter_jsonl(session_id, rel)

    # ---- Tools ------------------------------------------------------------

    def list_sessions(self, limit: int) -> list[dict[str, Any]]:
        data = self._get_json("/api/sessions")
        items = data.get("sessions", [])
        out: list[dict[str, Any]] = []
        for s in items[: max(1, int(limit))]:
            out.append(filters.build_session_summary(s, source="hub"))
        return out

    def get_session(self, session_id: str) -> dict[str, Any]:
        self._get_json(f"/api/sessions/{session_id}")
        meta = self._get_json(f"/api/sessions/{session_id}/files/session_meta.json")
        base = f"{self.base_url}/api/sessions/{session_id}/files"
        meta_files = meta.get("files") or []
        log_files = [
            f"{base}/{f}" for f in meta_files
            if isinstance(f, str) and f.startswith("logs/") and f.endswith(".jsonl")
        ]
        files = {
            "screen_mp4": f"{base}/screen.mp4",
            "logs_jsonl": f"{base}/logs/logs.jsonl",
            "logs_vtt": f"{base}/logs/logs.vtt",
            "log_files": log_files,
            "inputs_jsonl": f"{base}/inputs/inputs.jsonl",
            "inputs_vtt": f"{base}/inputs/inputs.vtt",
            "metrics_jsonl": f"{base}/metrics/process.jsonl",
            "viewer_html": f"{base}/viewer.html",
            "session_meta": f"{base}/session_meta.json",
        }
        return {
            "session_id": session_id,
            "session_dir": None,
            "session_url": f"{self.base_url}/api/sessions/{session_id}",
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
        kind_set = {k.lower() for k in (kinds or [])}
        return filters.filter_events(
            self._iter_log_records(session_id),
            self._iter_jsonl(session_id, "inputs/inputs.jsonl"),
            t_start, t_end, kind_set, text, limit,
        )

    def get_metrics(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]:
        samples = filters.filter_time_range(
            self._iter_jsonl(session_id, "metrics/process.jsonl"), t_start, t_end,
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
        return filters.search_log_records(
            self._iter_log_records(session_id), query, limit,
        )

    def get_frame_jpeg(self, session_id: str, t_video_s: float) -> bytes:
        return self._get_bytes(
            f"/api/sessions/{session_id}/frame",
            params={"t": max(0.0, float(t_video_s))},
        )

    def get_viewer_path(self, session_id: str) -> str:
        return f"{self.base_url}/api/sessions/{session_id}/files/viewer.html"

    def get_frame_stats(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]:
        frames = filters.filter_time_range(
            self._iter_jsonl(session_id, "metrics/frames.jsonl"), t_start, t_end,
        )
        if not frames:
            return {"count": 0, "stats": {}, "frames": []}
        stats = filters.summarize_frame_stats(frames)
        return {"count": len(frames), "stats": stats, "frames": frames}
