"""FastAPI dependencies for resolving the calling user.

There are three identities a request can carry, in order of precedence:

1. **Web session cookie** — set by ``/api/auth/login`` (Phase 0.6.0). Signed
   with the configured secret, decoded to a ``sid``, looked up in
   ``web_sessions`` for the active ``User``.
2. **Per-user API token** in ``X-Trailbox-Token`` — sha256-hashed and matched
   against ``api_tokens.token_hash`` for the owning ``User``.
3. **Legacy service token** in ``X-Trailbox-Token`` — when configured via
   ``TRAILBOX_HUB_TOKEN``, matches that exact value and authenticates as the
   first admin user. Backward-compat shim only; new deployments shouldn't
   set this.

``require_user`` accepts any of the three. ``require_admin`` further demands
``role == 'admin'``. ``require_token`` is preserved as a one-line shim for
existing route declarations — it resolves to ``require_user`` and discards
the result.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request, status

from .config import HubConfig
from .tokens import ApiTokenStore
from .users import User, UserStore
from .web_sessions import COOKIE_NAME, WebSessionStore


@dataclass
class AuthContext:
    cfg: HubConfig
    users: UserStore
    tokens: ApiTokenStore
    sessions: WebSessionStore


def _resolve_user(
    ctx: AuthContext,
    request: Request,
    header_token: Optional[str],
) -> Optional[User]:
    """Try cookie → API token → service token. Return None if all fail."""
    # 1) cookie
    signed = request.cookies.get(COOKIE_NAME)
    if signed:
        sid = ctx.sessions.unsign_sid(signed)
        if sid:
            found = ctx.sessions.lookup(sid)
            if found is not None:
                return found[0]
    # 2) per-user API token
    if header_token:
        user = ctx.tokens.verify(header_token)
        if user is not None:
            return user
        # 3) legacy service token (constant-time compare)
        if ctx.cfg.service_token_enabled and hmac.compare_digest(
            header_token, ctx.cfg.token
        ):
            admin_id = ctx.users.first_admin_id()
            if admin_id is not None:
                admin = ctx.users.get_by_id(admin_id)
                if admin is not None and admin.status == "active":
                    return admin
    return None


def require_user(ctx: AuthContext):
    """Build a FastAPI dependency that resolves the calling User or 401s."""

    def _dep(
        request: Request,
        x_trailbox_token: Optional[str] = Header(default=None),
    ) -> User:
        user = _resolve_user(ctx, request, x_trailbox_token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            )
        return user

    return _dep


def require_admin(ctx: AuthContext):
    """Like ``require_user``, but rejects non-admins with 403."""

    def _dep(
        request: Request,
        x_trailbox_token: Optional[str] = Header(default=None),
    ) -> User:
        user = _resolve_user(ctx, request, x_trailbox_token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            )
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="admin role required",
            )
        return user

    return _dep


_MUST_CHANGE_DETAIL = (
    "password change required: POST /api/auth/password before using this endpoint"
)


def require_user_active(ctx: AuthContext):
    """Like ``require_user`` but rejects users with ``must_change_password=True``.

    This is the default user dependency for everything except the
    password-change flow itself (``/api/auth/me``, ``/api/auth/password``).
    Without this guard, an admin force-reset wouldn't actually force
    anything for API callers — they could just keep using the API after
    reissuing a token.
    """
    base = require_user(ctx)

    def _dep(
        request: Request,
        x_trailbox_token: Optional[str] = Header(default=None),
    ) -> User:
        user = base(request=request, x_trailbox_token=x_trailbox_token)
        if user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_MUST_CHANGE_DETAIL,
            )
        return user

    return _dep


def require_admin_active(ctx: AuthContext):
    """Admin + active (must_change_password=False) gate."""
    base = require_admin(ctx)

    def _dep(
        request: Request,
        x_trailbox_token: Optional[str] = Header(default=None),
    ) -> User:
        user = base(request=request, x_trailbox_token=x_trailbox_token)
        if user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_MUST_CHANGE_DETAIL,
            )
        return user

    return _dep


def require_token(ctx: AuthContext):
    """Back-compat shim for routes that just want auth, not the User object.

    Resolves to ``require_user`` and discards the returned ``User``. Existing
    ``dependencies=[Depends(auth)]`` declarations keep working; new routes
    that need to act on the caller's identity should depend on
    ``require_user`` directly.
    """
    dep = require_user(ctx)

    def _dep(
        request: Request,
        x_trailbox_token: Optional[str] = Header(default=None),
    ) -> None:
        dep(request=request, x_trailbox_token=x_trailbox_token)
        return None

    return _dep
