"""FastAPI app for the Hub.

Phase 1: token-auth REST (upload/list/get/zip/delete).
Phase 2: share tokens + `/v/{token}/*` static viewer routes (no API auth).
Phase 0.5.0: SQLite-backed user accounts, per-user API tokens,
             session ownership. Legacy ``TRAILBOX_HUB_TOKEN`` retained as an
             admin service-token shim.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.frame_extractor import extract_frame_jpeg

from .audit import AuditLog
from .auth import AuthContext, require_admin_active, require_user_active
from .bootstrap import bootstrap
from .config import HubConfig, load as load_config
from .db import Database
from .lockout import LoginLockout
from .retention import start_background_sweep, sweep_once
from .routes import api_admin as api_admin_routes
from .routes import api_auth as api_auth_routes
from .routes import web as web_routes
from .session_owners import SessionOwnerStore
from .settings_store import SettingsStore
from .shares import ShareStore
from .storage import Storage, is_valid_session_id
from .thumbnails import ensure_thumbnail
from .tokens import ApiTokenStore
from .uploads import UploadStore
from .users import User, UserStore
from .web_sessions import WebSessionStore

def _static_dir() -> Path:
    """Resolve static/ in source vs PyInstaller bundles (see routes/web.py)."""
    here = Path(__file__).resolve().parent / "static"
    if here.is_dir():
        return here
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "hub_server" / "static"
        if bundled.is_dir():
            return bundled
    return here


_STATIC_DIR = _static_dir()


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")


def create_app(cfg: HubConfig | None = None) -> FastAPI:
    cfg = cfg or load_config()

    # --- DB + stores ------------------------------------------------------
    db = Database(cfg.data_root / "hub.db")
    users = UserStore(db)
    tokens = ApiTokenStore(db, users)
    web_sessions = WebSessionStore(db, users, cfg.secret_key)
    settings = SettingsStore(db)
    owners = SessionOwnerStore(db)
    audit = AuditLog(db)
    lockout = LoginLockout()

    # --- disk-backed stores -----------------------------------------------
    storage = Storage(cfg.data_root, owners=owners)
    shares = ShareStore(cfg.data_root / "_tokens.json")
    uploads = UploadStore(cfg.data_root / "_uploads")

    # --- first-boot bootstrap (admin, settings seed, owner backfill) -------
    bootstrap(cfg, db, users, settings, storage, owners)

    auth_ctx = AuthContext(cfg=cfg, users=users, tokens=tokens, sessions=web_sessions)
    # *_active variants reject users whose admin force-reset set
    # must_change_password=True. They must hit /api/auth/password (or the
    # /account/password web form) before doing anything else.
    user_dep = require_user_active(auth_ctx)
    admin_dep = require_admin_active(auth_ctx)

    app = FastAPI(
        title="Trailbox Hub",
        version="0.7.0",
        description="Session-sharing backend for Trailbox QA recordings.",
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="static",
    )
    # Expose stores for tests and external composition.
    app.state.db = db
    app.state.users = users
    app.state.tokens = tokens
    app.state.web_sessions = web_sessions
    app.state.settings = settings
    app.state.owners = owners
    app.state.audit = audit
    app.state.lockout = lockout
    app.state.auth_ctx = auth_ctx

    app.include_router(
        api_auth_routes.build_router(
            auth_ctx=auth_ctx,
            users=users,
            tokens=tokens,
            sessions=web_sessions,
            settings=settings,
            audit=audit,
            lockout=lockout,
        )
    )
    app.include_router(
        api_admin_routes.build_router(
            cfg=cfg,
            auth_ctx=auth_ctx,
            users=users,
            tokens=tokens,
            settings=settings,
            audit=audit,
            owners=owners,
            storage=storage,
        )
    )
    web_router, _templates = web_routes.build_router(
        cfg=cfg,
        auth_ctx=auth_ctx,
        users=users,
        tokens=tokens,
        sessions=web_sessions,
        settings=settings,
        audit=audit,
        owners=owners,
        storage=storage,
        shares=shares,
        lockout=lockout,
    )
    app.include_router(web_router)

    # ---- helpers ----------------------------------------------------------

    def _is_visible(user: User, session_id: str) -> bool:
        if user.role == "admin":
            return True
        return owners.is_owned_by(session_id, user.id)

    def _require_visible(user: User, session_id: str) -> None:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        if not _is_visible(user, session_id):
            # 404 (not 403) — don't reveal that the session exists.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    # ---- public/healthcheck ----------------------------------------------

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "ok": True,
            "data_root": str(cfg.data_root),
            "auth_enabled": cfg.auth_enabled,
            "retention_days": cfg.retention_days,
            "admin_count": users.count_admins(),
        }

    # ---- retention --------------------------------------------------------

    @app.post("/api/admin/prune")
    def prune_now(_: User = Depends(admin_dep), dry_run: bool = False) -> dict:
        """Trigger the retention sweep on demand. ``dry_run=true`` previews only."""
        if not cfg.retention_enabled:
            return {"deleted": [], "retention_days": 0, "dry_run": dry_run}
        if dry_run:
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.retention_days)
            previewed: list[str] = []
            from .retention import _is_expired
            for s in storage.list_summaries():
                if _is_expired(s.started_at, storage.session_dir(s.session_id), cutoff):
                    previewed.append(s.session_id)
            return {"would_delete": previewed, "retention_days": cfg.retention_days, "dry_run": True}
        deleted = sweep_once(storage, shares, cfg.retention_days)
        return {"deleted": deleted, "retention_days": cfg.retention_days, "dry_run": False}

    # ---- sessions ---------------------------------------------------------

    @app.get("/api/sessions")
    def list_sessions(user: User = Depends(user_dep)) -> dict:
        summaries = storage.list_summaries()
        if user.role != "admin":
            mine = set(owners.list_for_owner(user.id))
            summaries = [s for s in summaries if s.session_id in mine]
        items = [asdict(s) for s in summaries]
        return {"count": len(items), "sessions": items}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, user: User = Depends(user_dep)) -> dict:
        _require_visible(user, session_id)
        summaries = {s.session_id: s for s in storage.list_summaries()}
        s = summaries.get(session_id)
        if s is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        return asdict(s)

    @app.post(
        "/api/sessions/{session_id}",
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_session(
        session_id: str,
        file: UploadFile = File(...),
        user: User = Depends(user_dep),
    ) -> JSONResponse:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")

        # If session_id already exists and isn't ours, refuse rather than overwriting.
        existing_owner = owners.get(session_id)
        if existing_owner is not None and existing_owner != user.id and user.role != "admin":
            raise HTTPException(status.HTTP_409_CONFLICT, "session_id taken by another user")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        tmp_path = Path(tmp.name)
        try:
            written = 0
            try:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > cfg.max_upload_bytes:
                        raise HTTPException(
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"upload exceeds {cfg.max_upload_bytes} bytes",
                        )
                    tmp.write(chunk)
            finally:
                tmp.close()
            try:
                summary = storage.ingest_zip(session_id, tmp_path, owner_id=user.id)
            except (ValueError, OSError) as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ingest failed: {e}")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        audit.record("session_upload", actor_id=user.id, target=session_id)
        return JSONResponse(asdict(summary), status_code=status.HTTP_201_CREATED)

    @app.get("/api/sessions/{session_id}/zip")
    def download_zip(session_id: str, user: User = Depends(user_dep)):
        _require_visible(user, session_id)
        return StreamingResponse(
            storage.stream_zip(session_id),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}.zip"'
            },
        )

    @app.get("/api/sessions/{session_id}/thumb.jpg")
    def session_thumbnail(session_id: str, user: User = Depends(user_dep)):
        """Lazy-generated session thumbnail (5-second frame from screen.mp4).

        First request triggers ffmpeg extraction and caches thumb.jpg in
        the session dir; subsequent requests serve the cached file.
        Returns 404 when no thumbnail can be produced (no video, ffmpeg
        unavailable, or decode failure) so the UI can fall back to its
        gradient+icon placeholder via <img onerror>.
        """
        _require_visible(user, session_id)
        thumb = ensure_thumbnail(storage.session_dir(session_id))
        if thumb is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no thumbnail")
        return FileResponse(
            thumb,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.delete(
        "/api/sessions/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_session(session_id: str, user: User = Depends(user_dep)):
        _require_visible(user, session_id)
        if not storage.delete(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        shares.revoke_for_session(session_id)
        audit.record("session_delete", actor_id=user.id, target=session_id)
        return None

    # ---- File + frame fetch for MCP backend (Phase 3) --------------------

    def _resolve_in_session(user: User, session_id: str, rel: str) -> Path:
        _require_visible(user, session_id)
        session_dir = storage.session_dir(session_id).resolve()
        target = (session_dir / rel).resolve()
        try:
            target.relative_to(session_dir)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if not target.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        return target

    @app.get("/api/sessions/{session_id}/files/{path:path}")
    def fetch_file(
        session_id: str,
        path: str,
        user: User = Depends(user_dep),
    ) -> FileResponse:
        return FileResponse(_resolve_in_session(user, session_id, path))

    @app.get("/api/sessions/{session_id}/frame")
    def fetch_frame(
        session_id: str,
        t: float = Query(0.0, ge=0.0),
        user: User = Depends(user_dep),
    ) -> Response:
        video = _resolve_in_session(user, session_id, "screen.mp4")
        try:
            jpeg = extract_frame_jpeg(video, t)
        except RuntimeError as e:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
        return Response(content=jpeg, media_type="image/jpeg")

    # ---- Resumable uploads (Phase 4) -------------------------------------

    @app.post(
        "/api/uploads",
        status_code=status.HTTP_201_CREATED,
    )
    def upload_start(
        payload: dict = Body(...),
        user: User = Depends(user_dep),
    ) -> dict:
        sid = str(payload.get("session_id") or "").strip()
        total = int(payload.get("total_size") or 0)
        if not is_valid_session_id(sid):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if total <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "total_size must be > 0")
        if total > cfg.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"total_size exceeds cap {cfg.max_upload_bytes}",
            )
        existing_owner = owners.get(sid)
        if existing_owner is not None and existing_owner != user.id and user.role != "admin":
            raise HTTPException(status.HTTP_409_CONFLICT, "session_id taken by another user")
        state = uploads.create(sid, total, owner_id=user.id)
        return uploads.to_dict(state)

    @app.get("/api/uploads/{upload_id}")
    def upload_state(upload_id: str, user: User = Depends(user_dep)) -> dict:
        state = uploads.get(upload_id)
        if state is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        if not _upload_visible(state, user):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        return uploads.to_dict(state)

    @app.put("/api/uploads/{upload_id}")
    async def upload_chunk(
        upload_id: str,
        request: Request,
        offset: int = Query(..., ge=0),
        user: User = Depends(user_dep),
    ) -> dict:
        state = uploads.get(upload_id)
        if state is None or not _upload_visible(state, user):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        body = await request.body()
        if not body:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty chunk")
        try:
            state = uploads.append(upload_id, offset, body)
        except FileNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        except ValueError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
        return uploads.to_dict(state)

    @app.post(
        "/api/uploads/{upload_id}/complete",
        status_code=status.HTTP_201_CREATED,
    )
    def upload_complete(upload_id: str, user: User = Depends(user_dep)) -> dict:
        state = uploads.get(upload_id)
        if state is None or not _upload_visible(state, user):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        try:
            state, zip_path = uploads.complete(upload_id)
        except FileNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        try:
            summary = storage.ingest_zip(state.session_id, zip_path, owner_id=user.id)
        except (ValueError, OSError) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ingest failed: {e}")
        finally:
            uploads.abort(upload_id)
        return {
            "upload_id": upload_id,
            "session": asdict(summary),
        }

    @app.delete(
        "/api/uploads/{upload_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def upload_abort(upload_id: str, user: User = Depends(user_dep)):
        state = uploads.get(upload_id)
        if state is None or not _upload_visible(state, user):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        if not uploads.abort(upload_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        return None

    def _upload_visible(state, user: User) -> bool:
        if user.role == "admin":
            return True
        # Uploads created before 0.5.0 have owner_id=None — treat them as
        # owned by the first admin, so non-admins can't grab them.
        owner = getattr(state, "owner_id", None)
        return owner is not None and owner == user.id

    # ---- Share tokens (Phase 2) ------------------------------------------

    @app.post(
        "/api/sessions/{session_id}/share",
        status_code=status.HTTP_201_CREATED,
    )
    def create_share(session_id: str, user: User = Depends(user_dep)) -> dict:
        _require_visible(user, session_id)
        token = shares.create(session_id)
        audit.record(
            "share_created", actor_id=user.id, target=session_id,
            detail={"token_prefix": token[:8]},
        )
        return {
            "token": token,
            "session_id": session_id,
            "path": f"/v/{token}/",
        }

    @app.get("/api/sessions/{session_id}/shares")
    def list_shares(session_id: str, user: User = Depends(user_dep)) -> dict:
        _require_visible(user, session_id)
        items = shares.list_for_session(session_id)
        return {"count": len(items), "shares": items}

    @app.delete(
        "/api/shares/{token}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def revoke_share(token: str, user: User = Depends(user_dep)):
        if not _TOKEN_RE.match(token):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid token")
        # Only the owning user (or admin) can revoke a session's share token.
        sid = shares.resolve(token)
        if sid is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
        if user.role != "admin" and not owners.is_owned_by(sid, user.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
        if not shares.revoke(token):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
        audit.record(
            "share_revoked", actor_id=user.id, target=sid,
            detail={"token_prefix": token[:8]},
        )
        return None

    # ---- Browser viewer routes (no API auth — token IS the auth) ---------

    def _serve_share_path(token: str, path: str) -> FileResponse:
        if not _TOKEN_RE.match(token):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "share not found")
        sid = shares.resolve(token)
        if sid is None or not storage.exists(sid):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "share not found")
        rel = path or "viewer.html"
        if rel.endswith("/"):
            rel = rel + "viewer.html"
        session_dir = storage.session_dir(sid).resolve()
        target = (session_dir / rel).resolve()
        try:
            target.relative_to(session_dir)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if not target.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        return FileResponse(target)

    @app.get("/v/{token}")
    @app.get("/v/{token}/")
    def view_root(token: str) -> FileResponse:
        return _serve_share_path(token, "viewer.html")

    @app.get("/v/{token}/{path:path}")
    def view_static(token: str, path: str) -> FileResponse:
        return _serve_share_path(token, path)

    if cfg.retention_enabled:
        start_background_sweep(storage, shares, cfg.retention_days)

    return app
