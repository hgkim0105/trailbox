"""First-boot bootstrap: admin account, settings seed, owner backfill.

Called by ``create_app`` after ``db.migrate()``. Idempotent — re-running on
an already-bootstrapped DB is a no-op.
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Optional

from .config import HubConfig
from .db import Database
from .session_owners import SessionOwnerStore
from .settings_store import SettingsStore
from .storage import Storage
from .users import PasswordPolicyError, UserStore

log = logging.getLogger("trailbox.hub.bootstrap")


def bootstrap(
    cfg: HubConfig,
    db: Database,
    users: UserStore,
    settings: SettingsStore,
    storage: Storage,
    owners: SessionOwnerStore,
) -> None:
    _seed_settings(cfg, settings)
    _bootstrap_admin(cfg, users)
    _backfill_session_owners(storage, users, owners)


def _seed_settings(cfg: HubConfig, settings: SettingsStore) -> None:
    # Only seed when missing — runtime toggles live in the DB after that.
    inserted = settings.set_if_absent(
        "auto_approve_registration", "1" if cfg.auto_approve_seed else "0"
    )
    if inserted:
        log.info(
            "seeded hub_settings.auto_approve_registration=%s",
            "1" if cfg.auto_approve_seed else "0",
        )


def _bootstrap_admin(cfg: HubConfig, users: UserStore) -> None:
    if users.count_admins() > 0:
        return
    if cfg.admin_user and cfg.admin_pass:
        try:
            users.create(
                cfg.admin_user,
                cfg.admin_pass,
                role="admin",
                status="active",
            )
            log.warning(
                "bootstrapped first admin %r from TRAILBOX_HUB_ADMIN_USER",
                cfg.admin_user,
            )
            return
        except (ValueError, PasswordPolicyError) as e:
            log.error("failed to bootstrap admin from env: %s", e)
    # No env credentials → emit a one-time setup token to the data dir + log.
    _write_setup_token(cfg.data_root)


def _write_setup_token(data_root: Path) -> None:
    token_path = data_root / ".setup_token"
    if token_path.exists():
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if token:
            log.warning(
                "no admin yet; reusing existing setup token at %s — visit /setup",
                token_path,
            )
            return
    token = secrets.token_urlsafe(32)
    try:
        token_path.write_text(token, encoding="utf-8")
    except OSError as e:
        log.error("failed to persist setup token at %s: %s", token_path, e)
    log.warning(
        "no admin configured. First-run setup token: %s "
        "(also at %s) — visit /setup to claim",
        token,
        token_path,
    )


def _backfill_session_owners(
    storage: Storage,
    users: UserStore,
    owners: SessionOwnerStore,
) -> None:
    """Assign existing session dirs (uploaded before 0.5.0) to the first admin."""
    existing = owners.list_all()
    if not storage.root.is_dir():
        return
    admin_id: Optional[int] = users.first_admin_id()
    if admin_id is None:
        # No admin yet (setup-token flow). Backfill happens on /api/setup.
        return
    backfilled = 0
    for child in storage.root.iterdir():
        if not child.is_dir():
            continue
        sid = child.name
        if sid.startswith(("_", ".")):
            continue
        if sid in existing:
            continue
        owners.set(sid, admin_id)
        backfilled += 1
    if backfilled:
        log.info("backfilled %d existing sessions to admin id=%d", backfilled, admin_id)


def consume_setup_token(data_root: Path, provided: str) -> bool:
    """Validate + delete the one-shot setup token. True iff matched."""
    token_path = data_root / ".setup_token"
    if not token_path.exists():
        return False
    try:
        stored = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not stored or stored != provided:
        return False
    try:
        token_path.unlink()
    except OSError:
        pass
    return True
