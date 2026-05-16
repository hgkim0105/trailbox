"""Pluggable backends behind the Trailbox MCP tools.

Either the local filesystem (default — reads ``output/{sid}/``) or a remote
Hub HTTP API (when ``TRAILBOX_HUB_URL`` is set).
"""
from __future__ import annotations

from typing import Any, Protocol


class Backend(Protocol):
    def list_sessions(self, limit: int) -> list[dict[str, Any]]: ...

    def get_session(self, session_id: str) -> dict[str, Any]: ...

    def query_events(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
        kinds: list[str] | None,
        text: str | None,
        limit: int,
    ) -> dict[str, Any]: ...

    def get_metrics(
        self,
        session_id: str,
        t_start: float | None,
        t_end: float | None,
    ) -> dict[str, Any]: ...

    def search_logs(
        self,
        session_id: str,
        query: str,
        limit: int,
    ) -> dict[str, Any]: ...

    def get_frame_jpeg(self, session_id: str, t_video_s: float) -> bytes: ...

    def get_viewer_path(self, session_id: str) -> str: ...
