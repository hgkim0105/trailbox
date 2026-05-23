"""Server-rendered Jinja2 pages (Phase 0.7.0).

These pages are *thin* — they exercise the same stores as the JSON API, but
render HTML so an operator can do day-to-day chores (approve users, browse
sessions, fetch a share link) without spinning up curl. They live alongside
the JSON API on the same FastAPI app.

Auth model: cookies only. The same ``require_user``/``require_admin``
dependencies that gate ``/api/*`` resolve a cookie session, so a logged-in
browser sees the right pages automatically. Tokens aren't accepted here —
they belong on programmatic clients.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..audit import AuditLog
from ..auth import AuthContext
from ..bootstrap import consume_setup_token
from ..config import HubConfig
from ..lockout import LoginLockout
from ..session_owners import SessionOwnerStore
from ..settings_store import SettingsStore
from ..shares import ShareStore
from ..storage import Storage
from ..tokens import ApiTokenStore
from ..users import PasswordPolicyError, User, UserStore, validate_username
from ..view_helpers import (
    derive_device,
    derive_device_label,
    derive_thumb_kind,
    register_filters,
)
from ..web_sessions import COOKIE_NAME, SESSION_TTL_DAYS, WebSessionStore

log = logging.getLogger("trailbox.hub.web")

HUB_VERSION = "0.7.0"


def _resource_dir(name: str) -> Path:
    """Locate a packaged resource dir in both source and PyInstaller layouts.

    In source: ``hub_server/{name}`` next to this file's package.
    In PyInstaller one-file build: bundled under ``sys._MEIPASS/hub_server/{name}``
    via the ``datas`` entries in Trailbox-hub.spec.
    """
    here = Path(__file__).resolve().parent.parent / name
    if here.is_dir():
        return here
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "hub_server" / name
        if bundled.is_dir():
            return bundled
    return here  # fall through — Jinja2 will raise a clear error


TEMPLATES_DIR = _resource_dir("templates")


def _resolve_current_user(
    request: Request,
    sessions: WebSessionStore,
) -> Optional[User]:
    """Cookie-only resolution. Returns None when not logged in."""
    signed = request.cookies.get(COOKIE_NAME)
    if not signed:
        return None
    sid = sessions.unsign_sid(signed)
    if not sid:
        return None
    found = sessions.lookup(sid)
    if found is None:
        return None
    return found[0]


def _set_session_cookie(response, sid: str, signer: WebSessionStore) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=signer.sign_sid(sid),
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def build_router(
    *,
    cfg: HubConfig,
    auth_ctx: AuthContext,
    users: UserStore,
    tokens: ApiTokenStore,
    sessions: WebSessionStore,
    settings: SettingsStore,
    audit: AuditLog,
    owners: SessionOwnerStore,
    storage: Storage,
    shares: ShareStore,
    lockout: LoginLockout,
) -> tuple[APIRouter, Jinja2Templates]:
    router = APIRouter(tags=["web"])
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    register_filters(templates.env)

    def _pending_user_count() -> int:
        return sum(1 for u in users.list_all() if u.status == "pending")

    def _ctx(request: Request, **extra) -> dict:
        user = _resolve_current_user(request, sessions)
        pending = _pending_user_count() if user and user.role == "admin" else 0
        return {
            "request": request,
            "current_user": user,
            "hub_version": HUB_VERSION,
            "pending_user_count": pending,
            **extra,
        }

    # Paths a `must_change_password` user is still allowed to hit. Everything
    # else routes them to /account/password until they change it.
    _MUST_CHANGE_ALLOW = {
        "/account/password",
        "/logout",
        "/static",  # matched as a prefix below
    }

    def _enforce_must_change(request: Request, user: User) -> None:
        if not user.must_change_password:
            return
        path = request.url.path
        if path in _MUST_CHANGE_ALLOW or path.startswith("/static/"):
            return
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/account/password"},
        )

    def _require_user(request: Request) -> User:
        user = _resolve_current_user(request, sessions)
        if user is None:
            next_url = request.url.path
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": f"/login?next={next_url}"},
            )
        _enforce_must_change(request, user)
        return user

    def _require_admin(request: Request) -> User:
        user = _require_user(request)
        if user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
        return user

    # ---- public pages ----------------------------------------------------

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html", _ctx(request))

    @router.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str | None = None):
        # If no admin exists yet, redirect to setup.
        if users.count_admins() == 0:
            return RedirectResponse("/setup", status_code=status.HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(
            request,
            "login.html", _ctx(request, error=None, username=None, next=next)
        )

    @router.post("/login", response_class=HTMLResponse)
    def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        next: str | None = Form(default=None),
    ):
        username = username.strip()
        if lockout.is_locked(username):
            return templates.TemplateResponse(
            request,
            "login.html",
                _ctx(request, error="시도 횟수 초과 — 잠시 후 다시 시도하세요.", username=username, next=next),
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        u = users.verify_password(username, password)
        if u is None:
            lockout.record_failure(username)
            audit.record("login_failed", target=username, detail={"via": "web"})
            return templates.TemplateResponse(
            request,
            "login.html",
                _ctx(request, error="아이디 또는 비밀번호가 올바르지 않습니다.", username=username, next=next),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        if u.status != "active":
            audit.record("login_failed", actor_id=u.id, target=username, detail={"via": "web", "reason": u.status})
            return templates.TemplateResponse(
            request,
            "login.html",
                _ctx(request, error=f"계정이 {u.status} 상태입니다.", username=username, next=next),
                status_code=status.HTTP_403_FORBIDDEN,
            )
        lockout.clear(username)
        ws = sessions.create(u.id)
        target = next if (next and next.startswith("/")) else "/sessions"
        resp = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
        _set_session_cookie(resp, ws.sid, sessions)
        audit.record("login", actor_id=u.id, target=u.username, detail={"via": "web"})
        return resp

    @router.post("/logout")
    def logout_submit(request: Request):
        signed = request.cookies.get(COOKIE_NAME)
        actor: Optional[int] = None
        if signed:
            sid = sessions.unsign_sid(signed)
            if sid:
                found = sessions.lookup(sid)
                if found is not None:
                    actor = found[0].id
                sessions.delete(sid)
        resp = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        resp.delete_cookie(COOKIE_NAME, path="/")
        if actor is not None:
            audit.record("logout", actor_id=actor, detail={"via": "web"})
        return resp

    @router.get("/register", response_class=HTMLResponse)
    def register_form(request: Request):
        return templates.TemplateResponse(
            request,
            "register.html", _ctx(request, error=None, pending=False)
        )

    @router.post("/register", response_class=HTMLResponse)
    def register_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        email: str = Form(default=""),
    ):
        username = username.strip()
        email_clean = email.strip() or None
        try:
            validate_username(username)
        except ValueError as e:
            return templates.TemplateResponse(
            request,
            "register.html",
                _ctx(request, error=str(e), pending=False),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if users.get_by_username(username) is not None:
            return templates.TemplateResponse(
            request,
            "register.html",
                _ctx(request, error="이미 사용 중인 username 입니다.", pending=False),
                status_code=status.HTTP_409_CONFLICT,
            )
        auto = settings.get_bool("auto_approve_registration")
        try:
            u = users.create(
                username, password,
                email=email_clean,
                role="user",
                status="active" if auto else "pending",
            )
        except (PasswordPolicyError, ValueError) as e:
            return templates.TemplateResponse(
            request,
            "register.html",
                _ctx(request, error=str(e), pending=False),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        audit.record("register", actor_id=u.id, target=u.username, detail={"via": "web", "auto_approved": auto})
        if auto:
            # Log them straight in.
            ws = sessions.create(u.id)
            resp = RedirectResponse("/sessions", status_code=status.HTTP_303_SEE_OTHER)
            _set_session_cookie(resp, ws.sid, sessions)
            audit.record("auto_approved", actor_id=u.id, target=u.username)
            return resp
        return templates.TemplateResponse(
            request,
            "register.html", _ctx(request, error=None, pending=True)
        )

    # ---- setup -----------------------------------------------------------

    @router.get("/setup", response_class=HTMLResponse)
    def setup_form(request: Request):
        if users.count_admins() > 0:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(
            request,
            "setup.html",
            _ctx(request, error=None, done=False, data_root=str(cfg.data_root)),
        )

    @router.post("/setup", response_class=HTMLResponse)
    def setup_submit(
        request: Request,
        setup_token: str = Form(...),
        username: str = Form(...),
        password: str = Form(...),
    ):
        if users.count_admins() > 0:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if not consume_setup_token(cfg.data_root, setup_token):
            return templates.TemplateResponse(
            request,
            "setup.html",
                _ctx(request, error="setup token 이 올바르지 않습니다.", done=False, data_root=str(cfg.data_root)),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        username = username.strip()
        try:
            validate_username(username)
            u = users.create(username, password, role="admin", status="active")
        except (PasswordPolicyError, ValueError) as e:
            return templates.TemplateResponse(
            request,
            "setup.html",
                _ctx(request, error=str(e), done=False, data_root=str(cfg.data_root)),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        # Backfill any pre-existing sessions to this new admin.
        if storage.root.is_dir():
            for child in storage.root.iterdir():
                if not child.is_dir():
                    continue
                sid = child.name
                if sid.startswith(("_", ".")):
                    continue
                if owners.get(sid) is None:
                    owners.set(sid, u.id)
        audit.record("setup", actor_id=u.id, target=u.username, detail={"via": "web"})
        return templates.TemplateResponse(
            request,
            "setup.html", _ctx(request, error=None, done=True, data_root=str(cfg.data_root))
        )

    # ---- sessions --------------------------------------------------------

    @router.get("/sessions", response_class=HTMLResponse)
    def sessions_list(request: Request):
        user = _require_user(request)
        summaries = storage.list_summaries()
        if user.role != "admin":
            mine = set(owners.list_for_owner(user.id))
            summaries = [s for s in summaries if s.session_id in mine]

        owner_map: dict[str, str] = {}
        if user.role == "admin":
            id_to_name = {u.id: u.username for u in users.list_all()}
            for s in summaries:
                oid = owners.get(s.session_id)
                if oid is not None:
                    owner_map[s.session_id] = id_to_name.get(oid, str(oid))

        view_sessions = []
        total_size = 0
        total_dur = 0.0
        total_shares = 0
        for s in summaries:
            share_count = len(shares.list_for_session(s.session_id))
            total_shares += share_count
            total_size += s.size_bytes
            total_dur += s.duration_seconds or 0.0
            view_sessions.append({
                "summary": s,
                "owner": owner_map.get(s.session_id),
                "shares_count": share_count,
                "device": derive_device(s.exe_path),
                "thumb_kind": derive_thumb_kind(s.exe_path),
                "device_label": derive_device_label(s.exe_path),
            })

        # Quota: hub_settings may carry a real number later; for now show against
        # the prototype's 4 GiB reference so the % chip has something to display.
        storage_quota = 4 * 1024 * 1024 * 1024

        return templates.TemplateResponse(
            request,
            "sessions/list.html",
            _ctx(
                request,
                view_sessions=view_sessions,
                total_count=len(view_sessions),
                total_duration=total_dur,
                total_size=total_size,
                storage_quota=storage_quota,
                total_shares=total_shares,
                owners=owner_map,
                active_nav="sessions",
            ),
        )

    @router.get("/sessions/{session_id}", response_class=HTMLResponse)
    def session_detail(request: Request, session_id: str, new_share: str | None = None):
        user = _require_user(request)
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if user.role != "admin" and not owners.is_owned_by(session_id, user.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        summaries = {s.session_id: s for s in storage.list_summaries()}
        s = summaries.get(session_id)
        if s is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        share_items = shares.list_for_session(session_id)

        # Owner lookup for admin display.
        owner_name = None
        oid = owners.get(session_id)
        if oid is not None:
            row = users.get_by_id(oid)
            if row is not None:
                owner_name = row.username

        # Pull system info out of session_meta.json for the 사양 tab. The meta
        # schema is whatever the recording client wrote; we surface the common
        # fields and pass the raw dict so the template can fall back gracefully.
        import json as _json
        meta_path = storage.session_dir(session_id) / "session_meta.json"
        session_meta: dict = {}
        if meta_path.is_file():
            try:
                session_meta = _json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, _json.JSONDecodeError):
                session_meta = {}

        view = {
            "summary": s,
            "owner": owner_name,
            "device": derive_device(s.exe_path),
            "device_label": derive_device_label(s.exe_path),
            "thumb_kind": derive_thumb_kind(s.exe_path),
        }

        return templates.TemplateResponse(
            request,
            "sessions/detail.html",
            _ctx(
                request,
                session=s,
                view=view,
                shares=share_items,
                session_meta=session_meta,
                new_share=new_share if new_share and any(sh["token"] == new_share for sh in share_items) else None,
                active_nav="sessions",
            ),
        )

    @router.post("/sessions/{session_id}/delete")
    def session_delete(request: Request, session_id: str):
        user = _require_user(request)
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if user.role != "admin" and not owners.is_owned_by(session_id, user.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        storage.delete(session_id)
        shares.revoke_for_session(session_id)
        audit.record("session_delete", actor_id=user.id, target=session_id, detail={"via": "web"})
        return RedirectResponse("/sessions", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/sessions/{session_id}/share")
    def session_share(request: Request, session_id: str):
        user = _require_user(request)
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if user.role != "admin" and not owners.is_owned_by(session_id, user.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        token = shares.create(session_id)
        audit.record(
            "share_created", actor_id=user.id, target=session_id,
            detail={"via": "web", "token_prefix": token[:8]},
        )
        # Pass the token via query param so the detail page can flash it once.
        return RedirectResponse(
            f"/sessions/{session_id}?new_share={token}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @router.post("/sessions/{session_id}/share/{token}/revoke")
    def session_share_revoke(request: Request, session_id: str, token: str):
        user = _require_user(request)
        sid_for_token = shares.resolve(token)
        if sid_for_token != session_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if user.role != "admin" and not owners.is_owned_by(session_id, user.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        shares.revoke(token)
        audit.record("share_revoked", actor_id=user.id, target=session_id, detail={"via": "web", "token_prefix": token[:8]})
        return RedirectResponse(
            f"/sessions/{session_id}", status_code=status.HTTP_303_SEE_OTHER
        )

    # ---- account ---------------------------------------------------------

    @router.get("/account", response_class=HTMLResponse)
    def account_view(request: Request):
        user = _require_user(request)
        return templates.TemplateResponse(
            request,
            "account.html",
            _ctx(request, tokens=tokens.list_for_user(user.id), new_token=None),
        )

    @router.post("/account/tokens", response_class=HTMLResponse)
    def account_issue_token(request: Request, label: str = Form(default="")):
        user = _require_user(request)
        label_clean = label.strip() or None
        if label_clean and len(label_clean) > 80:
            label_clean = label_clean[:80]
        plain, _rec = tokens.issue(user.id, label=label_clean)
        audit.record("token_issued", actor_id=user.id, target=str(_rec.id), detail={"via": "web", "label": label_clean})
        return templates.TemplateResponse(
            request,
            "account.html",
            _ctx(request, tokens=tokens.list_for_user(user.id), new_token=plain),
        )

    @router.post("/account/tokens/{token_id}/revoke")
    def account_revoke_token(request: Request, token_id: int):
        user = _require_user(request)
        tokens.revoke(token_id, user_id=user.id)
        audit.record("token_revoked", actor_id=user.id, target=str(token_id), detail={"via": "web"})
        return RedirectResponse("/account", status_code=status.HTTP_303_SEE_OTHER)

    # ---- self-service password change -----------------------------------

    @router.get("/account/password", response_class=HTMLResponse)
    def password_form(request: Request):
        # Resolve without the must_change guard so the user can actually
        # reach this form when they're being force-routed here.
        user = _resolve_current_user(request, sessions)
        if user is None:
            return RedirectResponse(
                "/login?next=/account/password",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        return templates.TemplateResponse(
            request,
            "account_password.html",
            _ctx(request, error=None, forced=user.must_change_password),
        )

    @router.post("/account/password", response_class=HTMLResponse)
    def password_submit(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        new_password2: str = Form(...),
    ):
        user = _resolve_current_user(request, sessions)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if new_password != new_password2:
            return templates.TemplateResponse(
                request,
                "account_password.html",
                _ctx(
                    request,
                    error="새 비밀번호 확인이 일치하지 않습니다.",
                    forced=user.must_change_password,
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        verified = users.verify_password(user.username, current_password)
        if verified is None or verified.id != user.id:
            return templates.TemplateResponse(
                request,
                "account_password.html",
                _ctx(
                    request,
                    error="현재 비밀번호가 올바르지 않습니다.",
                    forced=user.must_change_password,
                ),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            users.set_password(user.id, new_password, must_change=False)
        except PasswordPolicyError as e:
            return templates.TemplateResponse(
                request,
                "account_password.html",
                _ctx(
                    request, error=str(e),
                    forced=user.must_change_password,
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        audit.record(
            "password_change", actor_id=user.id, target=user.username,
            detail={"via": "web", "was_forced": user.must_change_password},
        )
        return RedirectResponse("/account", status_code=status.HTTP_303_SEE_OTHER)

    # ---- admin -----------------------------------------------------------

    @router.get("/admin/users", response_class=HTMLResponse)
    def admin_users(request: Request):
        _require_admin(request)
        return templates.TemplateResponse(
            request,
            "admin/users.html",
            _ctx(
                request,
                pending=users.list_pending(),
                users=users.list_all(),
                active_nav="admin-users",
            ),
        )

    @router.post("/admin/users/{user_id}/approve")
    def admin_approve(request: Request, user_id: int):
        admin = _require_admin(request)
        target = users.get_by_id(user_id)
        if target is not None and target.status == "pending":
            users.approve(user_id, by_admin_id=admin.id)
            audit.record("approve", actor_id=admin.id, target=target.username, detail={"via": "web"})
        return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/admin/users/{user_id}/disable")
    def admin_disable(request: Request, user_id: int):
        admin = _require_admin(request)
        target = users.get_by_id(user_id)
        if target is None or target.id == admin.id:
            return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
        if target.role == "admin" and users.count_admins() <= 1:
            return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
        users.disable(user_id)
        revoked = tokens.revoke_all_for_user(user_id)
        audit.record("disable", actor_id=admin.id, target=target.username, detail={"via": "web", "revoked_tokens": revoked})
        return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/admin/users/{user_id}/role")
    def admin_role(request: Request, user_id: int, role: str = Form(...)):
        admin = _require_admin(request)
        target = users.get_by_id(user_id)
        if target is None or role not in ("admin", "user") or target.role == role:
            return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
        if target.role == "admin" and role == "user" and users.count_admins() <= 1:
            return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
        users.set_role(user_id, role)
        audit.record("role_change", actor_id=admin.id, target=target.username, detail={"via": "web", "from": target.role, "to": role})
        return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/admin/users/{user_id}/tokens")
    def admin_revoke_tokens(request: Request, user_id: int):
        admin = _require_admin(request)
        target = users.get_by_id(user_id)
        if target is None:
            return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
        revoked = tokens.revoke_all_for_user(user_id)
        audit.record("token_revoked", actor_id=admin.id, target=target.username, detail={"via": "web", "forced": True, "count": revoked})
        return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/admin/users/{user_id}/password/reset", response_class=HTMLResponse)
    def admin_password_reset(request: Request, user_id: int):
        """Server-generates a temp password, returns to the users page with the
        plaintext shown exactly once. Sets ``must_change_password=1`` on the
        target so they can't go anywhere except /account/password on next login.
        """
        from ..users import generate_temp_password, PasswordPolicyError as _PPE
        admin = _require_admin(request)
        target = users.get_by_id(user_id)
        if target is None:
            return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
        if target.id == admin.id:
            # Admins should rotate their own password via /account/password,
            # not by force-reset (which forces them to change again on next login).
            return RedirectResponse(
                "/admin/users", status_code=status.HTTP_303_SEE_OTHER
            )

        generated: str | None = None
        for _ in range(4):
            candidate = generate_temp_password()
            try:
                users.set_password(user_id, candidate, must_change=True)
                generated = candidate
                break
            except _PPE:
                continue
        if generated is None:
            return RedirectResponse(
                "/admin/users", status_code=status.HTTP_303_SEE_OTHER
            )
        revoked = tokens.revoke_all_for_user(user_id)
        audit.record(
            "password_reset", actor_id=admin.id, target=target.username,
            detail={"via": "web", "generated": True, "revoked_tokens": revoked},
        )
        return templates.TemplateResponse(
            request,
            "admin/users.html",
            _ctx(
                request,
                pending=users.list_pending(),
                users=users.list_all(),
                temp_password_for=target.username,
                temp_password=generated,
                active_nav="admin-users",
            ),
        )

    @router.get("/admin/settings", response_class=HTMLResponse)
    def admin_settings(request: Request):
        _require_admin(request)
        return templates.TemplateResponse(
            request,
            "admin/settings.html",
            _ctx(request, settings=settings.all()),
        )

    @router.post("/admin/settings")
    def admin_settings_save(
        request: Request,
        auto_approve_registration: str = Form(default=""),
    ):
        admin = _require_admin(request)
        new_value = "1" if auto_approve_registration == "1" else "0"
        old = settings.get("auto_approve_registration")
        settings.set("auto_approve_registration", new_value)
        if old != new_value:
            audit.record(
                "settings_changed", actor_id=admin.id,
                detail={"via": "web", "auto_approve_registration": new_value},
            )
        return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)

    @router.get("/admin/audit", response_class=HTMLResponse)
    def admin_audit(request: Request, limit: int = 200):
        _require_admin(request)
        limit = max(1, min(int(limit), 1000))
        entries = audit.tail(limit)
        usernames = {u.id: u.username for u in users.list_all()}
        return templates.TemplateResponse(
            request,
            "admin/audit.html",
            _ctx(request, entries=entries, usernames=usernames),
        )

    return router, templates
