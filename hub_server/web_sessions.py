"""Cookie-backed web session store.

Sessions live in ``web_sessions(sid, user_id, created_at, expires_at)``. The
sid itself is a 32-byte random token; we send it inside an HMAC-signed cookie
so a tampered cookie is rejected before we even hit the DB.

Lifetime: 30-day sliding — every successful lookup pushes ``expires_at`` out
to ``now + 30d`` so an active user never has to log in mid-session, but
abandoned cookies still expire on their own.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer

from .db import Database, utc_now_iso
from .users import User, UserStore


COOKIE_NAME = "trailbox_sid"
SESSION_TTL_DAYS = 30
_SIGNER_SALT = "trailbox-hub-web-session-v1"


@dataclass
class WebSession:
    sid: str
    user_id: int
    expires_at: str


class WebSessionStore:
    def __init__(self, db: Database, users: UserStore, secret_key: str) -> None:
        self.db = db
        self.users = users
        self._signer = URLSafeSerializer(secret_key, salt=_SIGNER_SALT)

    # ---- signing ----------------------------------------------------------

    def sign_sid(self, sid: str) -> str:
        return self._signer.dumps(sid)

    def unsign_sid(self, signed: str) -> Optional[str]:
        try:
            value = self._signer.loads(signed)
        except BadSignature:
            return None
        return str(value) if isinstance(value, str) else None

    # ---- mutations --------------------------------------------------------

    def create(self, user_id: int) -> WebSession:
        sid = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=SESSION_TTL_DAYS)
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO web_sessions(sid,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                (sid, user_id, now.isoformat(), expires.isoformat()),
            )
        return WebSession(sid=sid, user_id=user_id, expires_at=expires.isoformat())

    def lookup(self, sid: str) -> Optional[tuple[User, WebSession]]:
        """Resolve a sid to ``(user, session)``, sliding the expiry forward."""
        if not sid:
            return None
        row = self.db.read().execute(
            "SELECT sid,user_id,expires_at FROM web_sessions WHERE sid=?",
            (sid,),
        ).fetchone()
        if row is None:
            return None
        try:
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            self.delete(sid)
            return None
        user = self.users.get_by_id(int(row["user_id"]))
        if user is None or user.status != "active":
            self.delete(sid)
            return None
        # Sliding window — only push the row when more than 1h has elapsed
        # since the last touch to avoid a DB write on every request.
        new_expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
        if (new_expires - expires_at) > timedelta(hours=1):
            try:
                with self.db.write() as conn:
                    conn.execute(
                        "UPDATE web_sessions SET expires_at=? WHERE sid=?",
                        (new_expires.isoformat(), sid),
                    )
                expires_at = new_expires
            except Exception:  # noqa: BLE001
                pass
        return user, WebSession(
            sid=sid, user_id=user.id, expires_at=expires_at.isoformat()
        )

    def delete(self, sid: str) -> bool:
        with self.db.write() as conn:
            cur = conn.execute("DELETE FROM web_sessions WHERE sid=?", (sid,))
            return cur.rowcount > 0

    def purge_expired(self) -> int:
        with self.db.write() as conn:
            cur = conn.execute(
                "DELETE FROM web_sessions WHERE expires_at <= ?",
                (utc_now_iso(),),
            )
            return int(cur.rowcount)
