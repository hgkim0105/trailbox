"""Append-only audit log.

Every security-relevant action goes through ``log_action``. Failures here
must not block the action itself — auditing is for forensics, not gating.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .db import Database, utc_now_iso

log = logging.getLogger("trailbox.hub.audit")


# Whitelist of action names. Keeping this in code (not enforced in SQL)
# lets us evolve it without migrations, but a typo at a call site is still
# obvious in the audit table.
ACTIONS = frozenset(
    {
        "register",
        "login",
        "login_failed",
        "logout",
        "approve",
        "disable",
        "role_change",
        "password_reset",
        "password_change",
        "token_issued",
        "token_revoked",
        "auto_approved",
        "settings_changed",
        "session_upload",
        "session_delete",
        "share_created",
        "share_revoked",
        "setup",
    }
)


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        action: str,
        *,
        actor_id: Optional[int] = None,
        target: Optional[str] = None,
        detail: Optional[Any] = None,
    ) -> None:
        if action not in ACTIONS:
            log.warning("audit: unknown action %r recorded anyway", action)
        if detail is not None and not isinstance(detail, str):
            try:
                detail = json.dumps(detail, ensure_ascii=False)
            except (TypeError, ValueError):
                detail = str(detail)
        try:
            with self.db.write() as conn:
                conn.execute(
                    "INSERT INTO audit_log(ts,actor_id,action,target,detail)"
                    " VALUES(?,?,?,?,?)",
                    (utc_now_iso(), actor_id, action, target, detail),
                )
        except Exception:  # noqa: BLE001
            log.exception("audit: failed to record action %s", action)

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.read().execute(
            "SELECT id, ts, actor_id, action, target, detail FROM audit_log"
            " ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
