"""Hybrid backend — queries both local filesystem and remote Hub.

Local-first for single-session tools; merged + deduplicated for list_sessions.
"""
from __future__ import annotations

import logging
from typing import Any

from ..errors import SessionNotFound, HubUnavailable
from .local import LocalBackend
from .hub import HubBackend

log = logging.getLogger(__name__)


class HybridBackend:
    def __init__(self, local: LocalBackend, hub: HubBackend) -> None:
        self.local = local
        self.hub = hub

    # ---- Helpers ----------------------------------------------------------

    def _try_local_then_hub(
        self, method: str, session_id: str, *args: Any, **kwargs: Any,
    ) -> Any:
        try:
            result = getattr(self.local, method)(session_id, *args, **kwargs)
            if isinstance(result, dict):
                result["source"] = "local"
            return result
        except SessionNotFound:
            pass

        result = getattr(self.hub, method)(session_id, *args, **kwargs)
        if isinstance(result, dict):
            result["source"] = "hub"
        return result

    # ---- Tools ------------------------------------------------------------

    def list_sessions(self, limit: int) -> list[dict[str, Any]]:
        local_sessions = self.local.list_sessions(limit=9999)

        hub_sessions: list[dict[str, Any]] = []
        try:
            hub_sessions = self.hub.list_sessions(limit=9999)
        except (HubUnavailable, Exception):
            log.warning("Hub unreachable for list_sessions; showing local only")

        merged: dict[str, dict[str, Any]] = {}
        for s in local_sessions:
            merged[s["session_id"]] = s
        for s in hub_sessions:
            sid = s["session_id"]
            if sid in merged:
                merged[sid]["source"] = "both"
            else:
                merged[sid] = s

        result = sorted(
            merged.values(),
            key=lambda s: s.get("started_at") or "",
            reverse=True,
        )
        return result[: max(1, int(limit))]

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._try_local_then_hub("get_session", session_id)

    def query_events(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
        kinds: list[str] | None,
        text: str | None,
        limit: int,
    ) -> dict[str, Any]:
        return self._try_local_then_hub(
            "query_events", session_id, t_start, t_end, kinds, text, limit,
        )

    def get_metrics(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]:
        return self._try_local_then_hub(
            "get_metrics", session_id, t_start, t_end,
        )

    def search_logs(
        self,
        session_id: str,
        query: str,
        limit: int,
    ) -> dict[str, Any]:
        return self._try_local_then_hub("search_logs", session_id, query, limit)

    def get_frame_jpeg(self, session_id: str, t_video_s: float) -> bytes:
        return self._try_local_then_hub("get_frame_jpeg", session_id, t_video_s)

    def get_viewer_path(self, session_id: str) -> str:
        return self._try_local_then_hub("get_viewer_path", session_id)

    def get_frame_stats(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]:
        return self._try_local_then_hub(
            "get_frame_stats", session_id, t_start, t_end,
        )
