"""Per-session JSON APIs that aren't already on ``app.py``.

Today this is just the trim endpoint — viewer.html in the browser calls
``POST /api/sessions/{id}/trim`` to materialize a new trimmed session (or
overwrite the source). The actual ffmpeg + JSONL rebase work lives in
``core/trim.py``; this module is the thin auth/ownership layer in front
of it.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, status

from core.trim import trim_session

from ..audit import AuditLog
from ..auth import AuthContext, require_user_active
from ..session_owners import SessionOwnerStore
from ..storage import Storage, is_valid_session_id
from ..users import User


def build_router(
    *,
    auth_ctx: AuthContext,
    audit: AuditLog,
    owners: SessionOwnerStore,
    storage: Storage,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["sessions"])
    user_dep = require_user_active(auth_ctx)

    def _require_owner(user: User, session_id: str) -> None:
        if not is_valid_session_id(session_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session_id")
        if not storage.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        if user.role != "admin" and not owners.is_owned_by(session_id, user.id):
            # 404 (not 403) to avoid leaking the existence of other users' sessions.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    @router.post("/sessions/{session_id}/trim")
    def trim(
        session_id: str,
        body: dict = Body(...),
        user: User = Depends(user_dep),
    ) -> dict:
        _require_owner(user, session_id)
        try:
            t_start = float(body.get("t_start"))
            t_end = float(body.get("t_end"))
        except (TypeError, ValueError):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "t_start and t_end (numbers) required"
            )
        overwrite = bool(body.get("overwrite", False))

        src_dir = storage.session_dir(session_id)
        try:
            result = trim_session(
                src_dir=src_dir,
                output_root=storage.root,
                t_start=t_start,
                t_end=t_end,
                overwrite=overwrite,
            )
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

        # New session inherits the same owner; overwrite leaves ownership untouched.
        if not overwrite:
            owners.set(result.new_session_id, user.id)
            audit.record(
                "session_trim",
                actor_id=user.id,
                target=session_id,
                detail={
                    "new_session_id": result.new_session_id,
                    "t_start": round(t_start, 3),
                    "t_end": round(t_end, 3),
                    "duration_seconds": result.duration_seconds,
                },
            )
        else:
            audit.record(
                "session_trim_overwrite",
                actor_id=user.id,
                target=session_id,
                detail={
                    "t_start": round(t_start, 3),
                    "t_end": round(t_end, 3),
                    "duration_seconds": result.duration_seconds,
                },
            )

        return {
            "session_id": result.new_session_id,
            "viewer_path": f"/sessions/{result.new_session_id}/v/",
            "duration_seconds": result.duration_seconds,
            "warnings": result.warnings,
        }

    return router
