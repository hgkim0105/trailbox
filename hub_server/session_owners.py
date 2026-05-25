"""Maps session_id → owning user. Lives in ``session_owners`` table.

Why an out-of-band mapping (instead of writing owner into session_meta.json):
session_meta.json is *Trailbox-owned* — recorded by the GUI and the on-disk
layout contract in CLAUDE.md is to leave it untouched. The Hub adds the
owner relationship server-side so the meta file stays portable.
"""
from __future__ import annotations

from typing import Optional

from .db import Database, utc_now_iso


class SessionOwnerStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def set(self, session_id: str, owner_id: int) -> None:
        """Upsert. Re-uploading the same session_id transfers ownership to the new uploader."""
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO session_owners(session_id,owner_id,uploaded_at) VALUES(?,?,?)"
                " ON CONFLICT(session_id) DO UPDATE SET"
                "   owner_id=excluded.owner_id,"
                "   uploaded_at=excluded.uploaded_at",
                (session_id, owner_id, utc_now_iso()),
            )

    def get(self, session_id: str) -> Optional[int]:
        row = self.db.read().execute(
            "SELECT owner_id FROM session_owners WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return int(row["owner_id"]) if row else None

    def delete(self, session_id: str) -> bool:
        with self.db.write() as conn:
            cur = conn.execute(
                "DELETE FROM session_owners WHERE session_id=?",
                (session_id,),
            )
            return cur.rowcount > 0

    def list_for_owner(self, owner_id: int) -> list[str]:
        rows = self.db.read().execute(
            "SELECT session_id FROM session_owners WHERE owner_id=? ORDER BY uploaded_at DESC",
            (owner_id,),
        ).fetchall()
        return [str(r["session_id"]) for r in rows]

    def list_all(self) -> dict[str, int]:
        rows = self.db.read().execute(
            "SELECT session_id, owner_id FROM session_owners"
        ).fetchall()
        return {str(r["session_id"]): int(r["owner_id"]) for r in rows}

    def is_owned_by(self, session_id: str, user_id: int) -> bool:
        owner = self.get(session_id)
        return owner is not None and owner == user_id

    def get_description(self, session_id: str) -> str:
        row = self.db.read().execute(
            "SELECT description FROM session_owners WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return str(row["description"]) if row else ""

    def set_description(self, session_id: str, description: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE session_owners SET description=? WHERE session_id=?",
                (description.strip(), session_id),
            )

    def list_descriptions(self) -> dict[str, str]:
        rows = self.db.read().execute(
            "SELECT session_id, description FROM session_owners WHERE description != ''"
        ).fetchall()
        return {str(r["session_id"]): str(r["description"]) for r in rows}
