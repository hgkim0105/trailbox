"""User account store backed by ``hub.db``.

Passwords are hashed with argon2id (argon2-cffi defaults). The hasher carries
its parameters in the encoded hash string, so we can bump cost factors later
without breaking existing accounts.

Account ``status`` lifecycle:
    pending  → created via /api/auth/register, waiting for admin approval
    active   → may log in and use the API
    disabled → blocked from login and token use (kept for audit_log foreign keys)
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from .db import Database, utc_now_iso


_USERNAME_RE = re.compile(r"^[A-Za-z0-9._\-]{2,40}$")
_MIN_PASSWORD_LEN = 8

# A small deny-list catches the most embarrassing reuses without trying to be
# a full password-strength estimator. Keep it short on purpose — anything
# fancier belongs in a separate validator behind a setting.
_COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password12", "password123", "password1234",
        "passw0rd", "qwerty12345", "qwertyuiop", "1234567890", "12345678901",
        "111111111111", "trailbox", "trailbox123", "administrator",
        "letmein12345", "welcome12345", "iloveyou1234", "admin1234567",
    }
)


@dataclass
class User:
    id: int
    username: str
    email: Optional[str]
    role: str
    status: str
    created_at: str
    approved_at: Optional[str]
    approved_by: Optional[int]
    must_change_password: bool = False


class PasswordPolicyError(ValueError):
    """Raised by ``validate_password`` when the input violates policy."""


def validate_username(username: str) -> None:
    if not _USERNAME_RE.match(username or ""):
        raise ValueError(
            "username must be 2-40 chars, letters/digits/._- only"
        )


def generate_temp_password() -> str:
    """Server-generated reset password.

    ``token_urlsafe(9)`` yields a 12-char base64-safe string. It always
    passes our policy: longer than the 8-char minimum, has high entropy,
    won't contain any plausible username (random alphabet), and cannot
    match the deny-list (deny-listed strings are all lowercase ASCII
    words / digit runs).
    """
    return secrets.token_urlsafe(9)


def validate_password(password: str, username: str = "") -> None:
    if not password or len(password) < _MIN_PASSWORD_LEN:
        raise PasswordPolicyError(
            f"password must be at least {_MIN_PASSWORD_LEN} characters"
        )
    if username and username.lower() in password.lower():
        raise PasswordPolicyError("password must not contain the username")
    if password.lower() in _COMMON_PASSWORDS:
        raise PasswordPolicyError("password is in the common-password deny list")


class UserStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.hasher = PasswordHasher()

    # ---- writes -----------------------------------------------------------

    def create(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
        role: str = "user",
        status: str = "pending",
    ) -> User:
        validate_username(username)
        validate_password(password, username)
        if role not in ("admin", "user"):
            raise ValueError(f"invalid role: {role}")
        if status not in ("pending", "active", "disabled"):
            raise ValueError(f"invalid status: {status}")
        pw_hash = self.hasher.hash(password)
        now = utc_now_iso()
        approved_at = now if status == "active" else None
        with self.db.write() as conn:
            cur = conn.execute(
                "INSERT INTO users(username,email,pw_hash,role,status,created_at,approved_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (username, email, pw_hash, role, status, now, approved_at),
            )
            uid = int(cur.lastrowid)
        return self._row_to_user(self._fetch_row("id", uid))

    def verify_password(self, username: str, password: str) -> Optional[User]:
        row = self._fetch_row("username", username)
        if row is None:
            return None
        try:
            self.hasher.verify(row["pw_hash"], password)
        except (VerifyMismatchError, InvalidHashError):
            return None
        # Opportunistic rehash if argon2 params have changed.
        if self.hasher.check_needs_rehash(row["pw_hash"]):
            new_hash = self.hasher.hash(password)
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE users SET pw_hash=? WHERE id=?",
                    (new_hash, row["id"]),
                )
        return self._row_to_user(row)

    def approve(self, user_id: int, by_admin_id: int) -> User:
        now = utc_now_iso()
        with self.db.write() as conn:
            conn.execute(
                "UPDATE users SET status='active', approved_at=?, approved_by=?"
                " WHERE id=? AND status='pending'",
                (now, by_admin_id, user_id),
            )
        return self._row_to_user(self._require_row("id", user_id))

    def disable(self, user_id: int) -> User:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE users SET status='disabled' WHERE id=?",
                (user_id,),
            )
        return self._row_to_user(self._require_row("id", user_id))

    def set_role(self, user_id: int, role: str) -> User:
        if role not in ("admin", "user"):
            raise ValueError(f"invalid role: {role}")
        with self.db.write() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        return self._row_to_user(self._require_row("id", user_id))

    def set_password(
        self,
        user_id: int,
        new_password: str,
        *,
        must_change: bool = False,
    ) -> None:
        """Hash and store a new password.

        ``must_change=True`` flags the user to be force-routed to
        /account/password on their next login (admin force-reset path).
        Self-service changes call this with ``must_change=False``, which
        also clears any previously-set flag.
        """
        row = self._require_row("id", user_id)
        validate_password(new_password, row["username"])
        pw_hash = self.hasher.hash(new_password)
        with self.db.write() as conn:
            conn.execute(
                "UPDATE users SET pw_hash=?, must_change_password=? WHERE id=?",
                (pw_hash, 1 if must_change else 0, user_id),
            )

    def clear_must_change(self, user_id: int) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE users SET must_change_password=0 WHERE id=?",
                (user_id,),
            )

    # ---- reads ------------------------------------------------------------

    def get_by_id(self, user_id: int) -> Optional[User]:
        row = self._fetch_row("id", user_id)
        return self._row_to_user(row) if row else None

    def get_by_username(self, username: str) -> Optional[User]:
        row = self._fetch_row("username", username)
        return self._row_to_user(row) if row else None

    def list_pending(self) -> list[User]:
        rows = self.db.read().execute(
            "SELECT * FROM users WHERE status='pending' ORDER BY created_at"
        ).fetchall()
        return [self._row_to_user(r) for r in rows]

    def list_all(self) -> list[User]:
        rows = self.db.read().execute(
            "SELECT * FROM users ORDER BY id"
        ).fetchall()
        return [self._row_to_user(r) for r in rows]

    def count_admins(self) -> int:
        row = self.db.read().execute(
            "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND status='active'"
        ).fetchone()
        return int(row["c"])

    def first_admin_id(self) -> Optional[int]:
        row = self.db.read().execute(
            "SELECT id FROM users WHERE role='admin' AND status='active'"
            " ORDER BY id LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None

    # ---- helpers ----------------------------------------------------------

    def _fetch_row(self, col: str, val):
        if col not in ("id", "username"):
            raise ValueError(col)
        return self.db.read().execute(
            f"SELECT * FROM users WHERE {col} = ?",
            (val,),
        ).fetchone()

    def _require_row(self, col: str, val):
        row = self._fetch_row(col, val)
        if row is None:
            raise LookupError(f"user not found: {col}={val!r}")
        return row

    @staticmethod
    def _row_to_user(row) -> User:
        # must_change_password was added in DB v2; row.keys() check keeps this
        # robust against any test path that mocks a row without the column.
        try:
            mcp = bool(int(row["must_change_password"] or 0))
        except (KeyError, IndexError, TypeError, ValueError):
            mcp = False
        return User(
            id=int(row["id"]),
            username=str(row["username"]),
            email=row["email"],
            role=str(row["role"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            approved_at=row["approved_at"],
            approved_by=row["approved_by"],
            must_change_password=mcp,
        )
