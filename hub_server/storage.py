"""Filesystem-backed session storage for the Hub.

A session lives at ``{data_root}/{session_id}/`` and mirrors the Trailbox
``output/{session_id}/`` layout (screen.mp4, logs/, inputs/, metrics/,
viewer.html, session_meta.json). Uploads arrive as a single .zip whose
top-level is the session contents (or a single top-level dir we'll flatten).
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# session_id is "{safe_app_name}_{YYYYMMDD_HHMMSS}" by Trailbox convention,
# but we accept any name that can't escape the data root.
_VALID_ID = re.compile(r"^[A-Za-z0-9._\-]+$")


def is_valid_session_id(sid: str) -> bool:
    return bool(sid) and len(sid) <= 200 and bool(_VALID_ID.match(sid))


@dataclass
class SessionSummary:
    session_id: str
    started_at: str | None
    duration_seconds: float | None
    exe_path: str | None
    screen_frames: int
    log_lines: int
    input_events: int
    metric_samples: int
    size_bytes: int
    has_viewer: bool


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- Lookups ----------------------------------------------------------

    def session_dir(self, sid: str) -> Path:
        if not is_valid_session_id(sid):
            raise ValueError(f"invalid session_id: {sid!r}")
        return self.root / sid

    def exists(self, sid: str) -> bool:
        return self.session_dir(sid).is_dir()

    def list_summaries(self) -> list[SessionSummary]:
        if not self.root.is_dir():
            return []
        out: list[SessionSummary] = []
        for child in self.root.iterdir():
            if not child.is_dir() or not is_valid_session_id(child.name):
                continue
            out.append(self._summarize(child))
        # Newest first by started_at (fall back to mtime).
        out.sort(
            key=lambda s: (s.started_at or "", s.session_id),
            reverse=True,
        )
        return out

    # ---- Mutations --------------------------------------------------------

    def ingest_zip(self, sid: str, zip_path: Path) -> SessionSummary:
        """Extract ``zip_path`` into a fresh session dir, replacing any prior copy.

        The zip may either contain the session files at its root, or wrap them
        in a single top-level directory (we'll strip that prefix).
        """
        target = self.session_dir(sid)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            prefix = _detect_common_prefix(zf.namelist())
            for member in zf.infolist():
                rel = member.filename
                if prefix and rel.startswith(prefix):
                    rel = rel[len(prefix):]
                if not rel or rel.endswith("/"):
                    continue
                # Defense in depth against path traversal.
                dest = (target / rel).resolve()
                if not str(dest).startswith(str(target.resolve())):
                    raise ValueError(f"zip entry escapes session dir: {member.filename}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return self._summarize(target)

    def delete(self, sid: str) -> bool:
        target = self.session_dir(sid)
        if not target.is_dir():
            return False
        shutil.rmtree(target)
        return True

    # ---- Streaming downloads ---------------------------------------------

    def stream_zip(self, sid: str) -> Iterator[bytes]:
        """Yield a zip of the session dir as in-memory chunks."""
        target = self.session_dir(sid)
        if not target.is_dir():
            raise FileNotFoundError(sid)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=4) as zf:
            for path in target.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=path.relative_to(target).as_posix())
        buf.seek(0)
        while True:
            chunk = buf.read(64 * 1024)
            if not chunk:
                break
            yield chunk

    # ---- Helpers ----------------------------------------------------------

    def _summarize(self, session_dir: Path) -> SessionSummary:
        meta = _load_meta(session_dir)
        size = _dir_size(session_dir)
        return SessionSummary(
            session_id=meta.get("session_id") or session_dir.name,
            started_at=meta.get("started_at"),
            duration_seconds=_as_float(meta.get("duration_seconds")),
            exe_path=meta.get("exe_path"),
            screen_frames=int(meta.get("screen_frames") or 0),
            log_lines=int(meta.get("log_lines") or 0),
            input_events=int(meta.get("input_events") or 0),
            metric_samples=int(meta.get("metric_samples") or 0),
            size_bytes=size,
            has_viewer=(session_dir / "viewer.html").exists(),
        )


def _load_meta(session_dir: Path) -> dict[str, Any]:
    p = session_dir / "session_meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _as_float(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _detect_common_prefix(names: list[str]) -> str:
    """If every entry shares a single top-level dir, return it (with trailing /)."""
    tops = {n.split("/", 1)[0] for n in names if n and not n.startswith("/")}
    if len(tops) == 1:
        only = next(iter(tops))
        # All names start with "only/" — strip it.
        if all(n == only or n.startswith(only + "/") for n in names):
            return only + "/"
    return ""
