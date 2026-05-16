"""Resumable upload sessions — append-only zip accumulator.

The client opens an upload, PUTs chunks at increasing byte offsets, and
finalizes when done. Out-of-order or duplicate chunks are rejected so the
client can recover from network errors by querying the current offset.

Each upload lives at ``{data_root}/_uploads/{upload_id}/``:
  data.zip  — the accumulating zip (will be ingested on complete)
  meta.json — {session_id, total_size, bytes_received, created_at, ...}
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class UploadState:
    upload_id: str
    session_id: str
    total_size: int
    bytes_received: int
    created_at: str
    completed: bool = False


class UploadStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        # Per-upload locks so two chunks for the same upload can't race.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_master = threading.Lock()

    # ---- Internal ---------------------------------------------------------

    def _lock_for(self, upload_id: str) -> threading.Lock:
        with self._locks_master:
            if upload_id not in self._locks:
                self._locks[upload_id] = threading.Lock()
            return self._locks[upload_id]

    def _dir(self, upload_id: str) -> Path:
        return self.root / upload_id

    def _meta_path(self, upload_id: str) -> Path:
        return self._dir(upload_id) / "meta.json"

    def _data_path(self, upload_id: str) -> Path:
        return self._dir(upload_id) / "data.zip"

    def _read_meta(self, upload_id: str) -> UploadState | None:
        p = self._meta_path(upload_id)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return UploadState(**d)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def _write_meta(self, state: UploadState) -> None:
        p = self._meta_path(state.upload_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish: write to tmp then rename.
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
        os.replace(tmp, p)

    # ---- Public API -------------------------------------------------------

    def create(self, session_id: str, total_size: int) -> UploadState:
        upload_id = secrets.token_urlsafe(16)  # 128-bit
        state = UploadState(
            upload_id=upload_id,
            session_id=session_id,
            total_size=int(total_size),
            bytes_received=0,
            created_at=_utcnow_iso(),
        )
        d = self._dir(upload_id)
        d.mkdir(parents=True, exist_ok=False)
        # Pre-create empty data file so append-mode opens cleanly.
        self._data_path(upload_id).touch()
        self._write_meta(state)
        return state

    def get(self, upload_id: str) -> UploadState | None:
        return self._read_meta(upload_id)

    def append(self, upload_id: str, offset: int, chunk: bytes) -> UploadState:
        """Append ``chunk`` at the expected next offset. Returns the new state.

        Raises:
            FileNotFoundError: upload_id doesn't exist
            ValueError: offset mismatch or would overflow total_size
        """
        lock = self._lock_for(upload_id)
        with lock:
            state = self._read_meta(upload_id)
            if state is None:
                raise FileNotFoundError(upload_id)
            if state.completed:
                raise ValueError("upload already completed")
            if offset != state.bytes_received:
                raise ValueError(
                    f"offset mismatch: expected {state.bytes_received}, got {offset}"
                )
            new_total = state.bytes_received + len(chunk)
            if new_total > state.total_size:
                raise ValueError(
                    f"chunk would exceed total_size {state.total_size}"
                )
            with open(self._data_path(upload_id), "ab") as f:
                f.write(chunk)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass  # best-effort durability
            state.bytes_received = new_total
            self._write_meta(state)
            return state

    def complete(self, upload_id: str) -> tuple[UploadState, Path]:
        """Mark upload finalized, return the path to the assembled zip."""
        lock = self._lock_for(upload_id)
        with lock:
            state = self._read_meta(upload_id)
            if state is None:
                raise FileNotFoundError(upload_id)
            if state.bytes_received != state.total_size:
                raise ValueError(
                    f"incomplete: {state.bytes_received}/{state.total_size}"
                )
            state.completed = True
            self._write_meta(state)
            return state, self._data_path(upload_id)

    def abort(self, upload_id: str) -> bool:
        lock = self._lock_for(upload_id)
        with lock:
            d = self._dir(upload_id)
            if not d.is_dir():
                return False
            shutil.rmtree(d, ignore_errors=True)
        with self._locks_master:
            self._locks.pop(upload_id, None)
        return True

    def to_dict(self, state: UploadState) -> dict[str, Any]:
        return asdict(state)
