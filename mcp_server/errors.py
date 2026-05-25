"""Structured error types for MCP tool responses."""
from __future__ import annotations

from typing import Any


class ToolError(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.message, "code": self.code}


class SessionNotFound(ToolError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"session not found: {session_id}", "SESSION_NOT_FOUND")


class FileNotAvailable(ToolError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail, "FILE_NOT_AVAILABLE")


class HubUnavailable(ToolError):
    def __init__(self, detail: str = "Hub server is unreachable") -> None:
        super().__init__(detail, "HUB_UNAVAILABLE")
