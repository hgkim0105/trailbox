"""SQLite-backed metadata store for the Hub (users, tokens, ownership).

The file lives at ``{data_root}/hub.db``. Schema changes are gated through
``PRAGMA user_version`` — each migration step is idempotent so repeated boots
on the same DB are a no-op. The session payload on disk (mp4/jsonl/meta) is
untouched; this DB only stores the *metadata* that doesn't fit there
(ownership, accounts, web sessions, audit log).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email         TEXT,
  pw_hash       TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN ('admin','user')),
  status        TEXT NOT NULL CHECK(status IN ('pending','active','disabled')),
  created_at    TEXT NOT NULL,
  approved_at   TEXT,
  approved_by   INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS api_tokens (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL UNIQUE,
  label       TEXT,
  created_at  TEXT NOT NULL,
  last_used   TEXT,
  revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS web_sessions (
  sid         TEXT PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_owners (
  session_id  TEXT PRIMARY KEY,
  owner_id    INTEGER NOT NULL REFERENCES users(id),
  uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hub_settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY,
  ts         TEXT NOT NULL,
  actor_id   INTEGER,
  action     TEXT NOT NULL,
  target     TEXT,
  detail     TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_session_owners_owner ON session_owners(owner_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);
"""

_LATEST_VERSION = 4


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the hub DB with the conventions we rely on everywhere."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=False,
        isolation_level=None,  # autocommit; we manage transactions explicitly
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the final user_version."""
    cur = conn.execute("PRAGMA user_version")
    version = int(cur.fetchone()[0])
    if version >= _LATEST_VERSION:
        return version

    if version < 1:
        # executescript() runs its own transaction internally and commits on
        # success, so we can't wrap it in our own BEGIN/COMMIT.
        conn.executescript(_SCHEMA_V1)
        conn.execute("PRAGMA user_version = 1")
        version = 1

    if version < 2:
        # v2: must_change_password flag. Set when admin force-resets a user's
        # password — forces that user to /account/password on next login
        # before they can touch any other page.
        conn.execute(
            "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute("PRAGMA user_version = 2")
        version = 2

    if version < 3:
        # v3: session_tags — small per-session tag table. Owners (or admins)
        # can attach lowercase kebab-case-ish labels for filtering / search.
        # Tags are normalized at write time; UNIQUE keeps duplicates out.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS session_tags (
              id          INTEGER PRIMARY KEY,
              session_id  TEXT NOT NULL,
              tag         TEXT NOT NULL COLLATE NOCASE,
              created_at  TEXT NOT NULL,
              created_by  INTEGER REFERENCES users(id),
              UNIQUE(session_id, tag)
            );
            CREATE INDEX IF NOT EXISTS idx_session_tags_session ON session_tags(session_id);
            CREATE INDEX IF NOT EXISTS idx_session_tags_tag ON session_tags(tag);
            """
        )
        conn.execute("PRAGMA user_version = 3")
        version = 3

    if version < 4:
        conn.execute(
            "ALTER TABLE session_owners ADD COLUMN description TEXT NOT NULL DEFAULT ''"
        )
        conn.execute("PRAGMA user_version = 4")
        version = 4

    return version


@contextmanager
def _tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


class Database:
    """Thin wrapper that owns a single sqlite3.Connection plus a write lock.

    sqlite3 in WAL mode handles concurrent readers fine, but writers must be
    serialized. The lock here guards write transactions; read paths can skip
    it.
    """

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self.conn = connect(db_path)
        self._write_lock = threading.Lock()
        migrate(self.conn)

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, _tx(self.conn):
            yield self.conn

    def read(self) -> sqlite3.Connection:
        return self.conn

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass


def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
