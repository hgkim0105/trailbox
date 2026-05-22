"""User-facing auth endpoints (Phase 0.6.0).

Registration: anyone can apply. ``auto_approve_registration`` (DB setting)
decides whether the new user comes up ``active`` or ``pending``. Pending
users can poll ``GET /api/auth/me`` to discover when admin approves them.

Cookies: ``POST /api/auth/login`` sets ``trailbox_sid`` (HttpOnly, SameSite=Lax,
Secure when TLS — but FastAPI doesn't know what scheme the client used, so
we set Secure conservatively only when explicitly enabled in the future).
The same cookie is consumed by the require_user/require_admin dependencies.

API tokens: a user issues their own tokens via ``POST /api/auth/tokens``;
plaintext is shown once in the response. Clients store the plaintext and
send it back in ``X-Trailbox-Token`` from then on.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status

from ..audit import AuditLog
from ..auth import AuthContext, require_user
from ..lockout import LoginLockout
from ..settings_store import SettingsStore
from ..tokens import ApiTokenStore
from ..users import PasswordPolicyError, User, UserStore, validate_username
from ..web_sessions import COOKIE_NAME, SESSION_TTL_DAYS, WebSessionStore


def build_router(
    *,
    auth_ctx: AuthContext,
    users: UserStore,
    tokens: ApiTokenStore,
    sessions: WebSessionStore,
    settings: SettingsStore,
    audit: AuditLog,
    lockout: LoginLockout,
) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    user_dep = require_user(auth_ctx)

    def _user_public(u: User) -> dict:
        return {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "status": u.status,
            "created_at": u.created_at,
            "approved_at": u.approved_at,
        }

    def _set_session_cookie(resp: Response, sid: str) -> None:
        signed = sessions.sign_sid(sid)
        resp.set_cookie(
            key=COOKIE_NAME,
            value=signed,
            max_age=SESSION_TTL_DAYS * 24 * 3600,
            httponly=True,
            samesite="lax",
            # secure=False here so it works under plain HTTP in dev/intranet.
            # Deployments terminating TLS at a proxy should set this via that
            # proxy's cookie attributes if needed.
            secure=False,
            path="/",
        )

    # ---- register --------------------------------------------------------

    @router.post("/register", status_code=status.HTTP_201_CREATED)
    def register(payload: dict = Body(...)) -> dict:
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        email = payload.get("email")
        if email is not None:
            email = str(email).strip() or None
        try:
            validate_username(username)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        if users.get_by_username(username) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "username already taken")
        auto = settings.get_bool("auto_approve_registration")
        try:
            u = users.create(
                username,
                password,
                email=email,
                role="user",
                status="active" if auto else "pending",
            )
        except PasswordPolicyError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        audit.record(
            "register", actor_id=u.id, target=u.username,
            detail={"auto_approved": auto},
        )
        if auto:
            audit.record("auto_approved", actor_id=u.id, target=u.username)
        return {"user_id": u.id, "status": u.status, "auto_approved": auto}

    # ---- login / logout / me --------------------------------------------

    @router.post("/login")
    def login(payload: dict = Body(...), response: Response = None) -> dict:
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not username or not password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "username and password required")
        if lockout.is_locked(username):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many failed attempts, try again later",
            )
        u = users.verify_password(username, password)
        if u is None:
            locked = lockout.record_failure(username)
            audit.record(
                "login_failed", target=username,
                detail={"locked": locked},
            )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        if u.status != "active":
            audit.record(
                "login_failed", actor_id=u.id, target=username,
                detail={"reason": u.status},
            )
            # Distinct message so the client can show "pending approval".
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"account {u.status}",
            )
        lockout.clear(username)
        ws = sessions.create(u.id)
        _set_session_cookie(response, ws.sid)
        audit.record("login", actor_id=u.id, target=u.username)
        return {"user": _user_public(u)}

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict:
        signed = request.cookies.get(COOKIE_NAME)
        actor: Optional[int] = None
        if signed:
            sid = sessions.unsign_sid(signed)
            if sid:
                found = sessions.lookup(sid)
                if found is not None:
                    actor = found[0].id
                sessions.delete(sid)
        response.delete_cookie(COOKIE_NAME, path="/")
        if actor is not None:
            audit.record("logout", actor_id=actor)
        return {"ok": True}

    @router.get("/me")
    def me(user: User = Depends(user_dep)) -> dict:
        return {"user": _user_public(user)}

    # ---- API tokens ------------------------------------------------------

    @router.post("/tokens", status_code=status.HTTP_201_CREATED)
    def issue_token(
        payload: dict = Body(default_factory=dict),
        user: User = Depends(user_dep),
    ) -> dict:
        label = payload.get("label")
        if label is not None:
            label = str(label).strip() or None
            if label and len(label) > 80:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "label too long")
        plain, rec = tokens.issue(user.id, label=label)
        audit.record(
            "token_issued", actor_id=user.id, target=str(rec.id),
            detail={"label": label},
        )
        return {
            "id": rec.id,
            "token": plain,  # shown once
            "label": rec.label,
            "created_at": rec.created_at,
        }

    @router.get("/tokens")
    def list_tokens(user: User = Depends(user_dep)) -> dict:
        items = [
            {
                "id": t.id,
                "label": t.label,
                "created_at": t.created_at,
                "last_used": t.last_used,
                "revoked_at": t.revoked_at,
            }
            for t in tokens.list_for_user(user.id)
        ]
        return {"count": len(items), "tokens": items}

    @router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
    def revoke_token(token_id: int, user: User = Depends(user_dep)):
        if not tokens.revoke(token_id, user_id=user.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
        audit.record("token_revoked", actor_id=user.id, target=str(token_id))
        return None

    # ---- self-service password change ------------------------------------

    @router.post("/password")
    def change_own_password(
        payload: dict = Body(...),
        user: User = Depends(user_dep),
    ) -> dict:
        """Authenticated user changes their own password.

        Requires the current password — guards against a forgotten/open
        browser session being used to lock the account. Clears the
        ``must_change_password`` flag set by an admin reset. We deliberately
        do NOT revoke the user's own API tokens here: voluntary password
        rotation shouldn't break the user's running automation.
        """
        current = str(payload.get("current_password") or "")
        new = str(payload.get("new_password") or "")
        verified = users.verify_password(user.username, current)
        if verified is None or verified.id != user.id:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "current password incorrect",
            )
        from ..users import PasswordPolicyError
        try:
            users.set_password(user.id, new, must_change=False)
        except PasswordPolicyError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        audit.record("password_change", actor_id=user.id, target=user.username)
        return {"ok": True}

    return router
