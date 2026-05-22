"""Admin-only endpoints (Phase 0.6.0).

These cover the operator workflows that the web UI in Phase 0.7.0 will be
built on top of:
    - approving / disabling users, changing roles
    - forcing a logout (revoke all tokens for a user)
    - toggling ``auto_approve_registration`` at runtime
    - one-shot ``/api/setup`` for claiming the first admin when env-bootstrap
      wasn't used
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, status

from ..audit import AuditLog
from ..auth import AuthContext, require_admin_active
from ..bootstrap import consume_setup_token
from ..config import HubConfig
from ..session_owners import SessionOwnerStore
from ..settings_store import SettingsStore
from ..storage import Storage
from ..tokens import ApiTokenStore
from ..users import (
    PasswordPolicyError,
    User,
    UserStore,
    generate_temp_password,
    validate_username,
)


_ALLOWED_SETTINGS = {"auto_approve_registration"}


def build_router(
    *,
    cfg: HubConfig,
    auth_ctx: AuthContext,
    users: UserStore,
    tokens: ApiTokenStore,
    settings: SettingsStore,
    audit: AuditLog,
    owners: SessionOwnerStore,
    storage: Storage,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["admin"])
    admin_dep = require_admin_active(auth_ctx)

    def _user_public(u: User) -> dict:
        return {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "status": u.status,
            "created_at": u.created_at,
            "approved_at": u.approved_at,
            "approved_by": u.approved_by,
            "must_change_password": u.must_change_password,
        }

    # ---- users -----------------------------------------------------------

    @router.get("/admin/users")
    def list_users(admin: User = Depends(admin_dep)) -> dict:
        items = [_user_public(u) for u in users.list_all()]
        return {"count": len(items), "users": items}

    @router.post("/admin/users/{user_id}/approve")
    def approve_user(user_id: int, admin: User = Depends(admin_dep)) -> dict:
        target = users.get_by_id(user_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        if target.status != "pending":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"user is {target.status}, not pending",
            )
        updated = users.approve(user_id, by_admin_id=admin.id)
        audit.record(
            "approve", actor_id=admin.id, target=updated.username,
            detail={"user_id": user_id},
        )
        return {"user": _user_public(updated)}

    @router.post("/admin/users/{user_id}/disable")
    def disable_user(user_id: int, admin: User = Depends(admin_dep)) -> dict:
        target = users.get_by_id(user_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        if target.id == admin.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot disable yourself")
        if target.role == "admin" and users.count_admins() <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "cannot disable the last active admin"
            )
        updated = users.disable(user_id)
        revoked = tokens.revoke_all_for_user(user_id)
        audit.record(
            "disable", actor_id=admin.id, target=updated.username,
            detail={"revoked_tokens": revoked},
        )
        return {"user": _user_public(updated), "revoked_tokens": revoked}

    @router.post("/admin/users/{user_id}/role")
    def change_role(
        user_id: int,
        payload: dict = Body(...),
        admin: User = Depends(admin_dep),
    ) -> dict:
        role = str(payload.get("role") or "")
        if role not in ("admin", "user"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be admin or user")
        target = users.get_by_id(user_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        if target.role == role:
            return {"user": _user_public(target), "changed": False}
        # Demoting the last admin is a footgun — refuse.
        if target.role == "admin" and role == "user" and users.count_admins() <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "cannot demote the last active admin"
            )
        updated = users.set_role(user_id, role)
        audit.record(
            "role_change", actor_id=admin.id, target=updated.username,
            detail={"from": target.role, "to": role},
        )
        return {"user": _user_public(updated), "changed": True}

    @router.delete(
        "/admin/users/{user_id}/tokens",
        status_code=status.HTTP_200_OK,
    )
    def revoke_user_tokens(user_id: int, admin: User = Depends(admin_dep)) -> dict:
        target = users.get_by_id(user_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        revoked = tokens.revoke_all_for_user(user_id)
        audit.record(
            "token_revoked", actor_id=admin.id, target=target.username,
            detail={"forced": True, "count": revoked},
        )
        return {"revoked": revoked}

    @router.post("/admin/users/{user_id}/password")
    def force_password_reset(
        user_id: int,
        payload: dict = Body(default_factory=dict),
        admin: User = Depends(admin_dep),
    ) -> dict:
        """Force-reset a user's password.

        Two modes:
          - ``{"password": "..."}`` — admin supplies the temp password
            explicitly (must pass policy).
          - empty body / ``{"generate": true}`` — server generates a 12-char
            random temp password, returns the plaintext exactly once.

        Either path sets ``must_change_password=1`` so the user is forced
        to /account/password on next login, and revokes all of their API
        tokens (their old tokens shouldn't survive a reset).
        """
        target = users.get_by_id(user_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

        provided = str(payload.get("password") or "").strip()
        generated_password: str | None = None
        if not provided:
            # Retry a couple of times on the (vanishingly unlikely) chance
            # the random output trips the policy (e.g. random substring
            # matching the username).
            for _ in range(4):
                candidate = generate_temp_password()
                try:
                    users.set_password(user_id, candidate, must_change=True)
                    generated_password = candidate
                    break
                except PasswordPolicyError:
                    continue
            if generated_password is None:
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "failed to generate a policy-compliant temp password",
                )
        else:
            try:
                users.set_password(user_id, provided, must_change=True)
            except PasswordPolicyError as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

        revoked = tokens.revoke_all_for_user(user_id)
        audit.record(
            "password_reset", actor_id=admin.id, target=target.username,
            detail={"revoked_tokens": revoked, "generated": generated_password is not None},
        )
        result: dict = {"ok": True, "revoked_tokens": revoked, "must_change": True}
        if generated_password is not None:
            # Plaintext shown exactly once — admin is expected to share this
            # out-of-band (Slack/email) with the user.
            result["temp_password"] = generated_password
        return result

    # ---- settings --------------------------------------------------------

    @router.get("/admin/settings")
    def get_settings(_: User = Depends(admin_dep)) -> dict:
        return {"settings": settings.all()}

    @router.patch("/admin/settings")
    def patch_settings(
        payload: dict = Body(...),
        admin: User = Depends(admin_dep),
    ) -> dict:
        if not isinstance(payload, dict) or not payload:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "no keys provided")
        unknown = set(payload.keys()) - _ALLOWED_SETTINGS
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"unknown settings: {sorted(unknown)}",
            )
        for k, v in payload.items():
            # Normalize bools to "0"/"1" so the storage shape stays uniform.
            if isinstance(v, bool):
                v = "1" if v else "0"
            settings.set(k, str(v))
        audit.record("settings_changed", actor_id=admin.id, detail=payload)
        return {"settings": settings.all()}

    # ---- setup -----------------------------------------------------------

    @router.post("/setup", status_code=status.HTTP_201_CREATED)
    def setup_first_admin(payload: dict = Body(...)) -> dict:
        if users.count_admins() > 0:
            raise HTTPException(
                status.HTTP_410_GONE,
                "setup already completed (admin exists)",
            )
        provided = str(payload.get("setup_token") or "")
        if not provided or not consume_setup_token(cfg.data_root, provided):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid setup token")
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        try:
            validate_username(username)
            u = users.create(
                username, password,
                role="admin", status="active",
            )
        except PasswordPolicyError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        # Backfill any pre-existing sessions to this freshly minted admin.
        if storage.root.is_dir():
            for child in storage.root.iterdir():
                if not child.is_dir():
                    continue
                sid = child.name
                if sid.startswith(("_", ".")):
                    continue
                if owners.get(sid) is None:
                    owners.set(sid, u.id)
        audit.record("setup", actor_id=u.id, target=u.username)
        return {"user_id": u.id, "username": u.username}

    # ---- audit -----------------------------------------------------------

    @router.get("/admin/audit")
    def tail_audit(
        limit: int = 100,
        _: User = Depends(admin_dep),
    ) -> dict:
        limit = max(1, min(int(limit), 1000))
        return {"entries": audit.tail(limit)}

    return router
