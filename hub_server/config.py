"""Hub server runtime config — env vars only, no config file.

Environment:
  TRAILBOX_HUB_DATA           storage root. Default: ./hub_data
  TRAILBOX_HUB_TOKEN          legacy admin service-token. When set, requests
                              carrying this in X-Trailbox-Token authenticate
                              as the first admin (compat shim, 0.5.0-0.7.x).
  TRAILBOX_HUB_HOST           bind host. Default: 127.0.0.1
  TRAILBOX_HUB_PORT           bind port. Default: 8765
  TRAILBOX_HUB_MAX_UPLOAD_MB  cap on a single upload zip. Default: 8192
  TRAILBOX_HUB_RETENTION_DAYS sessions older than this are auto-deleted by a
                              background sweep (1h cadence). 0 disables.
  TRAILBOX_HUB_ADMIN_USER     first-admin username (created on first boot if
                              no admin exists).
  TRAILBOX_HUB_ADMIN_PASS     first-admin password (paired with the above).
  TRAILBOX_HUB_AUTO_APPROVE   "1" seeds hub_settings.auto_approve_registration
                              on first boot. Runtime toggle lives in DB.
  TRAILBOX_HUB_SECRET_KEY     secret for signing cookie sessions. If unset,
                              generated once and persisted to
                              {data_root}/.secret_key.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HubConfig:
    data_root: Path
    token: str
    host: str
    port: int
    max_upload_bytes: int
    retention_days: int
    admin_user: str
    admin_pass: str
    auto_approve_seed: bool
    secret_key: str

    @property
    def service_token_enabled(self) -> bool:
        """Legacy shared token still recognized as the first admin."""
        return bool(self.token)

    @property
    def auth_enabled(self) -> bool:
        """Hub always requires authentication now (user accounts or service token)."""
        return True

    @property
    def retention_enabled(self) -> bool:
        return self.retention_days > 0


def _load_or_generate_secret(data_root: Path) -> str:
    """Read TRAILBOX_HUB_SECRET_KEY; else persist a generated one under data_root.

    Persisting (rather than regenerating per boot) keeps existing web sessions
    valid across restarts. The file is created with restrictive perms on
    POSIX; on Windows we rely on the default ACL inherited from the data dir.
    """
    env = os.environ.get("TRAILBOX_HUB_SECRET_KEY", "").strip()
    if env:
        return env
    data_root.mkdir(parents=True, exist_ok=True)
    secret_path = data_root / ".secret_key"
    if secret_path.exists():
        try:
            value = secret_path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    generated = secrets.token_urlsafe(48)
    try:
        secret_path.write_text(generated, encoding="utf-8")
        try:
            os.chmod(secret_path, 0o600)
        except OSError:
            pass
    except OSError:
        # Fall back to in-memory only; next boot will regenerate and existing
        # cookies will no longer validate, but auth still works.
        pass
    return generated


def load() -> HubConfig:
    data_root = Path(os.environ.get("TRAILBOX_HUB_DATA", "hub_data")).resolve()
    token = os.environ.get("TRAILBOX_HUB_TOKEN", "").strip()
    host = os.environ.get("TRAILBOX_HUB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("TRAILBOX_HUB_PORT", "8765"))
    max_mb = int(os.environ.get("TRAILBOX_HUB_MAX_UPLOAD_MB", "8192"))
    retention_days = max(0, int(os.environ.get("TRAILBOX_HUB_RETENTION_DAYS", "0")))
    admin_user = os.environ.get("TRAILBOX_HUB_ADMIN_USER", "").strip()
    admin_pass = os.environ.get("TRAILBOX_HUB_ADMIN_PASS", "")
    auto_approve = os.environ.get("TRAILBOX_HUB_AUTO_APPROVE", "0").strip().lower()
    auto_approve_seed = auto_approve in ("1", "true", "yes", "on")
    secret_key = _load_or_generate_secret(data_root)
    return HubConfig(
        data_root=data_root,
        token=token,
        host=host,
        port=port,
        max_upload_bytes=max_mb * 1024 * 1024,
        retention_days=retention_days,
        admin_user=admin_user,
        admin_pass=admin_pass,
        auto_approve_seed=auto_approve_seed,
        secret_key=secret_key,
    )
