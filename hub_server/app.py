"""FastAPI app for the Hub. Phase 1: REST only, no /v viewer routes yet."""
from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import require_token
from .config import HubConfig, load as load_config
from .storage import Storage, is_valid_session_id


def create_app(cfg: HubConfig | None = None) -> FastAPI:
    cfg = cfg or load_config()
    storage = Storage(cfg.data_root)
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
        return None

    return app
