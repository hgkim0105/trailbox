"""X-Trailbox-Token header check (constant-time compare)."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import HubConfig


def require_token(cfg: HubConfig):
    """Build a FastAPI dependency that validates the X-Trailbox-Token header."""

    def _dep(x_trailbox_token: str | None = Header(default=None)) -> None:
        if not cfg.auth_enabled:
            return
        if not x_trailbox_token or not hmac.compare_digest(x_trailbox_token, cfg.token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing X-Trailbox-Token",
            )

    return _dep
