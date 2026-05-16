"""Hub HTTP backend — drives the same 7 tools against a remote Trailbox Hub.

Reads jsonl files via ``GET /api/sessions/{id}/files/{path}`` and offloads
frame extraction to ``GET /api/sessions/{id}/frame?t=...``. All filtering and
aggregation that the local backend does is reproduced client-side so the wire
schema stays identical.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import httpx


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
        with self._client() as c:
            r = c.get(path)
            r.raise_for_status()
            return r.json()

    def _get_bytes(self, path: str, params: dict | None = None) -> bytes:
        with self._client() as c:
            r = c.get(path, params=params)
            r.raise_for_status()
            return r.content

    def _iter_jsonl(self, session_id: str, rel: str) -> Iterator[dict[str, Any]]:
        with self._client() as c:
            # Stream line-by-line so we don't buffer huge files in RAM.
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

    @staticmethod
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

    # ---- Tools ------------------------------------------------------------

    def list_sessions(self, limit: int) -> list[dict[str, Any]]:
        data = self._get_json("/api/sessions")
        items = data.get("sessions", [])
        # Hub summaries already carry the same fields; shape them like the local
        # response and clip to ``limit``.
        out: list[dict[str, Any]] = []
        for s in items[: max(1, int(limit))]:
            out.append({
                "session_id": s.get("session_id"),
                "started_at": s.get("started_at"),
                "duration_seconds": s.get("duration_seconds"),
                "exe_path": s.get("exe_path"),
                "log_lines": s.get("log_lines", 0),
                "input_events": s.get("input_events", 0),
                "metric_samples": s.get("metric_samples", 0),
                "screen_frames": s.get("screen_frames", 0),
                "effective_fps": None,  # not in summary; left None for parity
            })
        return out

    def get_session(self, session_id: str) -> dict[str, Any]:
        summary = self._get_json(f"/api/sessions/{session_id}")
        meta = self._get_json(f"/api/sessions/{session_id}/files/session_meta.json")
        base = f"{self.base_url}/api/sessions/{session_id}/files"
        files = {
            "screen_mp4": f"{base}/screen.mp4",
            "logs_jsonl": f"{base}/logs/logs.jsonl",
            "logs_vtt": f"{base}/logs/logs.vtt",
            "inputs_jsonl": f"{base}/inputs/inputs.jsonl",
            "inputs_vtt": f"{base}/inputs/inputs.vtt",
            "metrics_jsonl": f"{base}/metrics/process.jsonl",
            "viewer_html": f"{base}/viewer.html",
            "session_meta": f"{base}/session_meta.json",
        }
        return {
            "session_id": session_id,
            "session_dir": None,  # remote — no local path
            "session_url": f"{self.base_url}/api/sessions/{session_id}",
            "meta": meta,
            "files": files,
            "summary": summary,
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
        text_lo = text.lower() if text else None
        matched: list[dict[str, Any]] = []

        for rec in self._iter_jsonl(session_id, "logs/logs.jsonl"):
            t = float(rec.get("t_video_s", 0.0))
            if t_start is not None and t < t_start:
                continue
            if t_end is not None and t > t_end:
                continue
            if not self._matches_kind(rec, kind_set):
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

        for rec in self._iter_jsonl(session_id, "inputs/inputs.jsonl"):
            t = float(rec.get("t_video_s", 0.0))
            if t_start is not None and t < t_start:
                continue
            if t_end is not None and t > t_end:
                continue
            if not self._matches_kind(rec, kind_set):
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
        samples: list[dict[str, Any]] = []
        for rec in self._iter_jsonl(session_id, "metrics/process.jsonl"):
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
        q_lo = query.lower()
        hits: list[dict[str, Any]] = []
        for rec in self._iter_jsonl(session_id, "logs/logs.jsonl"):
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
        return self._get_bytes(
            f"/api/sessions/{session_id}/frame",
            params={"t": max(0.0, float(t_video_s))},
        )

    def get_viewer_path(self, session_id: str) -> str:
        # No filesystem path for a remote session — return the share-token URL
        # would require minting a share. Returning the direct API URL is the
        # honest answer; the file is auth-protected so browser-pasting won't
        # work without the X-Trailbox-Token header.
        return f"{self.base_url}/api/sessions/{session_id}/files/viewer.html"
