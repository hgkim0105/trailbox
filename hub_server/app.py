"""FastAPI app for the Hub.

Phase 1: token-auth REST (upload/list/get/zip/delete).
Phase 2: share tokens + `/v/{token}/*` static viewer routes (no API auth).
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

from core.frame_extractor import extract_frame_jpeg

from .auth import require_token
from .config import HubConfig, load as load_config
from .retention import start_background_sweep, sweep_once
from .shares import ShareStore
from .storage import Storage, is_valid_session_id
from .uploads import UploadStore


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")


def create_app(cfg: HubConfig | None = None) -> FastAPI:
    cfg = cfg or load_config()
    storage = Storage(cfg.data_root)
    shares = ShareStore(cfg.data_root / "_tokens.json")
    uploads = UploadStore(cfg.data_root / "_uploads")
    auth = require_token(cfg)

    app = FastAPI(
        title="Trailbox Hub",
        version="0.1.0",
        description="Session-sharing backend for Trailbox QA recordings.",
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "ok": True,
            "data_root": str(cfg.data_root),
            "auth_enabled": cfg.auth_enabled,
            "retention_days": cfg.retention_days,
        }

    @app.post("/api/admin/prune", dependencies=[Depends(auth)])
    def prune_now(dry_run: bool = False) -> dict:
        """Trigger the retention sweep on demand. ``dry_run=true`` previews only."""
        if not cfg.retention_enabled:
            return {"deleted": [], "retention_days": 0, "dry_run": dry_run}
        if dry_run:
            # Best-effort preview: compute what _would_ go.
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

    @app.get("/api/sessions", dependencies=[Depends(auth)])
    def list_sessions() -> dict:
        items = [asdict(s) for s in storage.list_summaries()]
        return {"count": len(items), "sessions": items}

    @app.get("/api/sessions/{session_id}", dependencies=[Depends(auth)])
    def get_session(session_id: str) -> dict:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        # Re-summarize on demand; cheap for a single session.
        summaries = {s.session_id: s for s in storage.list_summaries()}
        s = summaries.get(session_id)
        if s is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        return asdict(s)

    @app.post(
        "/api/sessions/{session_id}",
        dependencies=[Depends(auth)],
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_session(session_id: str, file: UploadFile = File(...)) -> JSONResponse:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")

        # Stream the upload to a temp file, enforcing the size cap as we go.
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
                summary = storage.ingest_zip(session_id, tmp_path)
            except (ValueError, OSError) as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ingest failed: {e}")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return JSONResponse(asdict(summary), status_code=status.HTTP_201_CREATED)

    @app.get("/api/sessions/{session_id}/zip", dependencies=[Depends(auth)])
    def download_zip(session_id: str):
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        return StreamingResponse(
            storage.stream_zip(session_id),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}.zip"'
            },
        )

    @app.delete(
        "/api/sessions/{session_id}",
        dependencies=[Depends(auth)],
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_session(session_id: str):
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if not storage.delete(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        shares.revoke_for_session(session_id)
        return None

    # ---- File + frame fetch for MCP backend (Phase 3) --------------------

    def _resolve_in_session(session_id: str, rel: str) -> Path:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        session_dir = storage.session_dir(session_id).resolve()
        target = (session_dir / rel).resolve()
        try:
            target.relative_to(session_dir)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if not target.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        return target

    @app.get(
        "/api/sessions/{session_id}/files/{path:path}",
        dependencies=[Depends(auth)],
    )
    def fetch_file(session_id: str, path: str) -> FileResponse:
        """Generic file fetch within a session dir (API-token protected).

        Used by the Hub-backed MCP server to pull individual jsonl/meta files.
        """
        return FileResponse(_resolve_in_session(session_id, path))

    @app.get(
        "/api/sessions/{session_id}/frame",
        dependencies=[Depends(auth)],
    )
    def fetch_frame(session_id: str, t: float = Query(0.0, ge=0.0)) -> Response:
        """Extract a JPEG frame from ``screen.mp4`` at ``t`` seconds.

        Server-side ffmpeg avoids the MCP client having to download the whole
        mp4. Returns image/jpeg sized to fit Claude's 1MB image cap.
        """
        video = _resolve_in_session(session_id, "screen.mp4")
        try:
            jpeg = extract_frame_jpeg(video, t)
        except RuntimeError as e:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
        return Response(content=jpeg, media_type="image/jpeg")

    # ---- Resumable uploads (Phase 4) -------------------------------------

    @app.post(
        "/api/uploads",
        dependencies=[Depends(auth)],
        status_code=status.HTTP_201_CREATED,
    )
    def upload_start(payload: dict = Body(...)) -> dict:
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
        state = uploads.create(sid, total)
        return uploads.to_dict(state)

    @app.get("/api/uploads/{upload_id}", dependencies=[Depends(auth)])
    def upload_state(upload_id: str) -> dict:
        state = uploads.get(upload_id)
        if state is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        return uploads.to_dict(state)

    @app.put("/api/uploads/{upload_id}", dependencies=[Depends(auth)])
    async def upload_chunk(
        upload_id: str,
        request: Request,
        offset: int = Query(..., ge=0),
    ) -> dict:
        body = await request.body()
        if not body:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty chunk")
        try:
            state = uploads.append(upload_id, offset, body)
        except FileNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        except ValueError as e:
            # 409 lets the client know to re-query state and resume.
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
        return uploads.to_dict(state)

    @app.post(
        "/api/uploads/{upload_id}/complete",
        dependencies=[Depends(auth)],
        status_code=status.HTTP_201_CREATED,
    )
    def upload_complete(upload_id: str) -> dict:
        try:
            state, zip_path = uploads.complete(upload_id)
        except FileNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        try:
            summary = storage.ingest_zip(state.session_id, zip_path)
        except (ValueError, OSError) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ingest failed: {e}")
        finally:
            uploads.abort(upload_id)  # cleanup the tmp dir either way
        return {
            "upload_id": upload_id,
            "session": asdict(summary),
        }

    @app.delete(
        "/api/uploads/{upload_id}",
        dependencies=[Depends(auth)],
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def upload_abort(upload_id: str):
        if not uploads.abort(upload_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        return None

    # ---- Share tokens (Phase 2) ------------------------------------------

    @app.post(
        "/api/sessions/{session_id}/share",
        dependencies=[Depends(auth)],
        status_code=status.HTTP_201_CREATED,
    )
    def create_share(session_id: str) -> dict:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        token = shares.create(session_id)
        return {
            "token": token,
            "session_id": session_id,
            "path": f"/v/{token}/",
        }

    @app.get("/api/sessions/{session_id}/shares", dependencies=[Depends(auth)])
    def list_shares(session_id: str) -> dict:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        items = shares.list_for_session(session_id)
        return {"count": len(items), "shares": items}

    @app.delete(
        "/api/shares/{token}",
        dependencies=[Depends(auth)],
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def revoke_share(token: str):
        if not _TOKEN_RE.match(token):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid token")
        if not shares.revoke(token):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
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
        # Path traversal defense.
        try:
            target.relative_to(session_dir)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        if not target.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        # FileResponse honors Range requests, which is what mp4 seeking needs.
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
