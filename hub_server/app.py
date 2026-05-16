"""FastAPI app for the Hub.

Phase 1: token-auth REST (upload/list/get/zip/delete).
Phase 2: share tokens + `/v/{token}/*` static viewer routes (no API auth).
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .auth import require_token
from .config import HubConfig, load as load_config
from .shares import ShareStore
from .storage import Storage, is_valid_session_id


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")


def create_app(cfg: HubConfig | None = None) -> FastAPI:
    cfg = cfg or load_config()
    storage = Storage(cfg.data_root)
    shares = ShareStore(cfg.data_root / "_tokens.json")
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
        }

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

    return app
