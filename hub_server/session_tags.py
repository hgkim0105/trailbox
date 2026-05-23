"""Per-session tag store.

Tags are short text labels that owners or admins attach to a session so
the list view can filter / search by topic ('regression', 'build-412',
'gpu-hang', etc.). The contract is intentionally narrow:

- Tags are normalized at write time: stripped, lowercased, anything that
  isn't a letter / digit / hyphen / underscore is replaced by '-' and
  consecutive separators collapsed. Empty strings are rejected.
- The (session_id, tag) pair is UNIQUE at the schema level, so a noisy
  client re-posting the same tag won't multiply rows.
- Reads can run on the shared connection (sqlite3 in WAL handles
  concurrent readers); writes go through Database.write() to serialize.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .db import Database, utc_now_iso


_TAG_NORM = re.compile(r"[^a-z0-9_\-]+")
_TAG_COLLAPSE = re.compile(r"-{2,}")

# Display-side guardrails. UI can hint these to users.
MAX_TAG_LEN = 32
MAX_TAGS_PER_SESSION = 16


def normalize_tag(raw: str) -> Optional[str]:
    """Return a clean tag or None if the input degenerates to empty."""
    if not raw:
        return None
    cleaned = _TAG_NORM.sub("-", raw.strip().lower())
    cleaned = _TAG_COLLAPSE.sub("-", cleaned).strip("-")
    if not cleaned:
        return None
    return cleaned[:MAX_TAG_LEN]


@dataclass
class SessionTag:
    id: int
    session_id: str
    tag: str
    created_at: str
    created_by: Optional[int]


class SessionTagStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, session_id: str, raw_tag: str, *, created_by: Optional[int]) -> Optional[SessionTag]:
        tag = normalize_tag(raw_tag)
        if not tag:
            return None
        # Enforce the per-session cap before inserting so a runaway loop
        # client can't bury the row count.
        existing = self.list_for_session(session_id)
        if any(t.tag == tag for t in existing):
            return next((t for t in existing if t.tag == tag), None)
        if len(existing) >= MAX_TAGS_PER_SESSION:
            return None
        now = utc_now_iso()
        with self.db.write() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO session_tags(session_id, tag, created_at, created_by)"
                " VALUES(?, ?, ?, ?)",
                (session_id, tag, now, created_by),
            )
            if cur.lastrowid:
                return SessionTag(cur.lastrowid, session_id, tag, now, created_by)
        # INSERT OR IGNORE collided despite our check (race) — fetch the
        # existing row to keep the caller's mental model consistent.
        return self._lookup(session_id, tag)

    def remove(self, tag_id: int, *, session_id: str) -> bool:
        """Delete a tag row, but only when it actually belongs to the
        passed session_id. Returns True on a successful delete."""
        with self.db.write() as conn:
            cur = conn.execute(
                "DELETE FROM session_tags WHERE id = ? AND session_id = ?",
                (tag_id, session_id),
            )
            return cur.rowcount > 0

    def list_for_session(self, session_id: str) -> list[SessionTag]:
        rows = self.db.read().execute(
            "SELECT id, session_id, tag, created_at, created_by FROM session_tags"
            " WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        return [SessionTag(r["id"], r["session_id"], r["tag"], r["created_at"], r["created_by"]) for r in rows]

    def tags_by_session(self, session_ids: Iterable[str]) -> dict[str, list[str]]:
        """Batched lookup for the list view. Returns {sid: [tag, ...]} with
        tags ordered by their insertion order."""
        sids = list(session_ids)
        if not sids:
            return {}
        # SQLite's parameter limit is generous (~999) but we keep batches
        # modest anyway by chunking.
        out: dict[str, list[str]] = {sid: [] for sid in sids}
        chunk = 200
        for i in range(0, len(sids), chunk):
            batch = sids[i:i + chunk]
            placeholders = ",".join("?" * len(batch))
            rows = self.db.read().execute(
                f"SELECT session_id, tag FROM session_tags"
                f" WHERE session_id IN ({placeholders})"
                f" ORDER BY created_at ASC",
                batch,
            ).fetchall()
            for r in rows:
                out.setdefault(r["session_id"], []).append(r["tag"])
        return out

    def _lookup(self, session_id: str, tag: str) -> Optional[SessionTag]:
        row = self.db.read().execute(
            "SELECT id, session_id, tag, created_at, created_by FROM session_tags"
            " WHERE session_id = ? AND tag = ?",
            (session_id, tag),
        ).fetchone()
        if row is None:
            return None
        return SessionTag(row["id"], row["session_id"], row["tag"], row["created_at"], row["created_by"])
