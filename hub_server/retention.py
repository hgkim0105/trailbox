"""Background retention sweep — deletes sessions older than the configured TTL.

Cadence is fixed at 1h. Each tick walks ``storage.list_summaries()`` and drops
anything whose ``started_at`` (or filesystem mtime as fallback) is older than
``retention_days`` days ago. Cascade-revokes any share tokens that pointed at
the deleted sessions.

The effective retention_days is resolved as:
  1. DB setting ``retention_days`` (admin-editable via settings page)
  2. Env-var fallback ``cfg.retention_days``
Either being 0 (or absent) means "disabled".
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .shares import ShareStore
from .storage import Storage

if TYPE_CHECKING:
    from .settings_store import SettingsStore

log = logging.getLogger("trailbox.hub.retention")

_SWEEP_INTERVAL_SECS = 3600  # 1h


def _session_age_cutoff_iso(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _is_expired(started_at: str | None, session_dir: Path, cutoff: datetime) -> bool:
    """Return True if the session predates ``cutoff``. Fall back to mtime."""
    if started_at:
        try:
            ts = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts < cutoff
        except ValueError:
            pass
    try:
        mtime = datetime.fromtimestamp(session_dir.stat().st_mtime, tz=timezone.utc)
        return mtime < cutoff
    except OSError:
        return False


def _effective_retention(
    env_days: int,
    settings: "SettingsStore | None" = None,
) -> int:
    if settings is not None:
        raw = settings.get("retention_days")
        if raw is not None:
            try:
                return max(0, int(raw))
            except ValueError:
                pass
    return env_days


def sweep_once(
    storage: Storage,
    shares: ShareStore,
    retention_days: int,
    settings: "SettingsStore | None" = None,
) -> list[str]:
    """Run a single sweep. Returns the list of deleted session_ids."""
    days = _effective_retention(retention_days, settings)
    if days <= 0:
        return []
    cutoff = _session_age_cutoff_iso(days)
    deleted: list[str] = []
    for summary in storage.list_summaries():
        session_dir = storage.session_dir(summary.session_id)
        if _is_expired(summary.started_at, session_dir, cutoff):
            try:
                if storage.delete(summary.session_id):
                    shares.revoke_for_session(summary.session_id)
                    deleted.append(summary.session_id)
            except OSError as e:
                log.warning("retention: failed to delete %s: %s", summary.session_id, e)
    if deleted:
        log.info("retention: deleted %d expired sessions", len(deleted))
    return deleted


def start_background_sweep(
    storage: Storage,
    shares: ShareStore,
    retention_days: int,
    settings: "SettingsStore | None" = None,
) -> threading.Thread:
    """Spawn a daemon thread that runs the sweep once per hour."""

    def _loop() -> None:
        while True:
            try:
                sweep_once(storage, shares, retention_days, settings)
            except Exception:  # noqa: BLE001 - never let the loop die
                log.exception("retention sweep tick failed")
            time.sleep(_SWEEP_INTERVAL_SECS)

    t = threading.Thread(target=_loop, name="trailbox-retention", daemon=True)
    t.start()
    log.info("retention sweep enabled (env TTL=%dd, cadence=1h)", retention_days)
    return t
