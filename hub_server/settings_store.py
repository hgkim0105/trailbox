"""Key/value settings persisted in ``hub_settings``.

Bool values are stored as the strings ``"0"``/``"1"`` so the table stays a
simple ``TEXT`` schema across all keys. Future numeric/json values can use
the same TEXT column.

Current keys:
    auto_approve_registration : bool — when 1, new /api/auth/register users
                                       go straight to status='active'.
"""
from __future__ import annotations

from typing import Optional

from .db import Database


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- raw KV -----------------------------------------------------------

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.db.read().execute(
            "SELECT value FROM hub_settings WHERE key=?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else default

    def set(self, key: str, value: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO hub_settings(key,value) VALUES(?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def set_if_absent(self, key: str, value: str) -> bool:
        """Seed a key only when it has no row yet. Returns True if inserted."""
        with self.db.write() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO hub_settings(key,value) VALUES(?,?)",
                (key, value),
            )
            return cur.rowcount > 0

    def all(self) -> dict[str, str]:
        rows = self.db.read().execute(
            "SELECT key,value FROM hub_settings ORDER BY key"
        ).fetchall()
        return {str(r["key"]): str(r["value"]) for r in rows}

    # ---- typed helpers ----------------------------------------------------

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return raw not in ("", "0", "false", "False", "no", "off")

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, "1" if value else "0")
