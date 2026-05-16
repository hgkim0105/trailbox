"""Share-token registry: token → session_id mapping persisted to a JSON file.

Phase 2: unguessable tokens (UUID4 hex), no expiration yet. The whole map is
loaded once at startup and rewritten atomically on each mutation. This is fine
into the low-thousands of tokens; switch to SQLite if we ever exceed that.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ShareStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = self._load()

    # ---- Public API -------------------------------------------------------

    def create(self, session_id: str) -> str:
        token = secrets.token_urlsafe(24)  # 192-bit, ~32 chars
        with self._lock:
            self._data[token] = {
                "session_id": session_id,
                "created_at": _utcnow_iso(),
            }
            self._flush_locked()
        return token

    def resolve(self, token: str) -> str | None:
        with self._lock:
            entry = self._data.get(token)
            return entry["session_id"] if entry else None

    def revoke(self, token: str) -> bool:
        with self._lock:
            if token not in self._data:
                return False
            del self._data[token]
            self._flush_locked()
            return True

    def revoke_for_session(self, session_id: str) -> int:
        """Used when a session is deleted — drop any tokens that point at it."""
        with self._lock:
            to_drop = [t for t, e in self._data.items() if e.get("session_id") == session_id]
            for t in to_drop:
                del self._data[t]
            if to_drop:
                self._flush_locked()
            return len(to_drop)

    def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"token": t, **e}
                for t, e in self._data.items()
                if e.get("session_id") == session_id
            ]

    # ---- Persistence ------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _flush_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + os.replace.
        fd, tmp = tempfile.mkstemp(
            prefix="_tokens.", suffix=".tmp", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
