"""Hub server runtime config — env vars only, no config file.

Environment:
  TRAILBOX_HUB_DATA   storage root. Default: ./hub_data
  TRAILBOX_HUB_TOKEN  required API token (X-Trailbox-Token). Empty = auth off
                      (intended for LAN-only dev; refuses to bind 0.0.0.0
                      without a token in production mode).
  TRAILBOX_HUB_HOST   bind host. Default: 127.0.0.1
  TRAILBOX_HUB_PORT   bind port. Default: 8765
  TRAILBOX_HUB_MAX_UPLOAD_MB  cap on a single upload zip. Default: 8192
  TRAILBOX_HUB_RETENTION_DAYS sessions older than this are auto-deleted by a
                              background sweep (1h cadence). 0 disables.
"""
from __future__ import annotations

import os
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

    @property
    def auth_enabled(self) -> bool:
        return bool(self.token)

    @property
    def retention_enabled(self) -> bool:
        return self.retention_days > 0


def load() -> HubConfig:
    data_root = Path(os.environ.get("TRAILBOX_HUB_DATA", "hub_data")).resolve()
    token = os.environ.get("TRAILBOX_HUB_TOKEN", "").strip()
    host = os.environ.get("TRAILBOX_HUB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("TRAILBOX_HUB_PORT", "8765"))
    max_mb = int(os.environ.get("TRAILBOX_HUB_MAX_UPLOAD_MB", "8192"))
    retention_days = max(0, int(os.environ.get("TRAILBOX_HUB_RETENTION_DAYS", "0")))
    return HubConfig(
        data_root=data_root,
        token=token,
        host=host,
        port=port,
        max_upload_bytes=max_mb * 1024 * 1024,
        retention_days=retention_days,
    )
