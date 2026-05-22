"""Per-user API tokens (X-Trailbox-Token replacement).

Tokens are 32-byte URL-safe strings (43 chars), backward-compatible with the
``_TOKEN_RE = ^[A-Za-z0-9_\\-]{16,64}$`` regex the rest of the app uses for
share tokens. We store only the sha256 hex digest — the plaintext is shown
once at issue time and never again.

Why sha256 (not argon2) here: these tokens are high-entropy random secrets,
not user-chosen passwords, so a fast hash is fine. The lookup path runs on
every authenticated request, so it has to stay cheap.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional

from .db import Database, utc_now_iso
from .users import User, UserStore


@dataclass
class TokenRecord:
    id: int
    user_id: int
    label: Optional[str]
    created_at: str
    last_used: Optional[str]
    revoked_at: Optional[str]


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


class ApiTokenStore:
    def __init__(self, db: Database, users: UserStore) -> None:
        self.db = db
        self.users = users

    def issue(self, user_id: int, label: Optional[str] = None) -> tuple[str, TokenRecord]:
        """Generate, store, and return ``(plaintext, record)`` for a new token."""
        plain = secrets.token_urlsafe(32)
        token_hash = _hash_token(plain)
        now = utc_now_iso()
        with self.db.write() as conn:
            cur = conn.execute(
                "INSERT INTO api_tokens(user_id,token_hash,label,created_at)"
                " VALUES(?,?,?,?)",
                (user_id, token_hash, label, now),
            )
            tid = int(cur.lastrowid)
        return plain, TokenRecord(
            id=tid,
            user_id=user_id,
            label=label,
            created_at=now,
            last_used=None,
            revoked_at=None,
        )

    def verify(self, plaintext: str) -> Optional[User]:
        """Return the owning ``User`` if the token is valid + user is active."""
        if not plaintext:
            return None
        token_hash = _hash_token(plaintext)
        row = self.db.read().execute(
            "SELECT id, user_id, revoked_at FROM api_tokens WHERE token_hash=?",
            (token_hash,),
        ).fetchone()
        if row is None or row["revoked_at"] is not None:
            return None
        # Constant-time confirmation — sqlite's `=` already discriminates, but
        # we match the constant-time mindset of the previous shared-token path.
        if not hmac.compare_digest(token_hash, _hash_token(plaintext)):
            return None
        user = self.users.get_by_id(int(row["user_id"]))
        if user is None or user.status != "active":
            return None
        # last_used touch — best-effort; failure here must not deny the request.
        try:
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE api_tokens SET last_used=? WHERE id=?",
                    (utc_now_iso(), int(row["id"])),
                )
        except Exception:  # noqa: BLE001 - DB hiccup must not break auth
            pass
        return user

    def list_for_user(self, user_id: int) -> list[TokenRecord]:
        rows = self.db.read().execute(
            "SELECT * FROM api_tokens WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [
            TokenRecord(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                label=r["label"],
                created_at=str(r["created_at"]),
                last_used=r["last_used"],
                revoked_at=r["revoked_at"],
            )
            for r in rows
        ]

    def revoke(self, token_id: int, user_id: Optional[int] = None) -> bool:
        """Revoke one token. If ``user_id`` is given, scope to that owner."""
        now = utc_now_iso()
        with self.db.write() as conn:
            if user_id is None:
                cur = conn.execute(
                    "UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                    (now, token_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE api_tokens SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                    (now, token_id, user_id),
                )
            return cur.rowcount > 0

    def revoke_all_for_user(self, user_id: int) -> int:
        now = utc_now_iso()
        with self.db.write() as conn:
            cur = conn.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )
            return int(cur.rowcount)
