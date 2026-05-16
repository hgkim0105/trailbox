"""HTTP client for the Trailbox Hub.

Sync (httpx) so it can be driven from a worker QThread without an asyncio loop.
Phase 1 surface mirrors the server's REST API: list, upload, download, delete.
Upload zips a session dir on-the-fly into a temp file and POSTs it.
"""
from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx


class HubError(RuntimeError):
    """Any non-2xx response or transport failure surfaces as this."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class HubClient:
    base_url: str
    token: str = ""
    timeout: float = 60.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    # ---- HTTP plumbing ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"X-Trailbox-Token": self.token} if self.token else {}

    def _client(self) -> httpx.Client:
        # Long timeout because uploads can be GB-scale.
        return httpx.Client(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=httpx.Timeout(self.timeout, read=self.timeout * 10),
        )

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        try:
            detail = resp.json().get("detail", resp.text)
        except (ValueError, KeyError):
            detail = resp.text
        raise HubError(f"HTTP {resp.status_code}: {detail}", status_code=resp.status_code)

    # ---- Public API -------------------------------------------------------

    def healthz(self) -> dict[str, Any]:
        with self._client() as c:
            r = c.get("/healthz")
            self._raise(r)
            return r.json()

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._client() as c:
            r = c.get("/api/sessions")
            self._raise(r)
            return r.json().get("sessions", [])

    # Files >= this threshold use resumable chunked upload; smaller ones use a
    # single POST. The chunked path is more robust on flaky links but adds
    # round-trip overhead per chunk, so small sessions stay single-shot.
    CHUNKED_UPLOAD_THRESHOLD = 64 * 1024 * 1024  # 64 MB
    CHUNK_SIZE = 4 * 1024 * 1024                  # 4 MB

    def upload_session(
        self,
        session_id: str,
        session_dir: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Zip ``session_dir`` and upload. Auto-picks chunked vs single POST.

        Returns the server's session summary.
        """
        session_dir = Path(session_dir)
        if not session_dir.is_dir():
            raise FileNotFoundError(session_dir)

        zip_path = _zip_session(session_dir)
        try:
            total = zip_path.stat().st_size
            if total >= self.CHUNKED_UPLOAD_THRESHOLD:
                return self._upload_chunked(session_id, zip_path, total, progress)
            return self._upload_single(session_id, zip_path, total, progress)
        finally:
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _upload_single(
        self,
        session_id: str,
        zip_path: Path,
        total: int,
        progress: Callable[[int, int], None] | None,
    ) -> dict[str, Any]:
        with self._client() as c, open(zip_path, "rb") as f:
            reader = _ProgressReader(f, total, progress)
            files = {
                "file": (f"{session_id}.zip", reader, "application/zip")
            }
            r = c.post(f"/api/sessions/{session_id}", files=files)
            self._raise(r)
            return r.json()

    def _upload_chunked(
        self,
        session_id: str,
        zip_path: Path,
        total: int,
        progress: Callable[[int, int], None] | None,
        max_retries_per_chunk: int = 3,
    ) -> dict[str, Any]:
        with self._client() as c:
            # 1. Open the upload session.
            r = c.post(
                "/api/uploads",
                json={"session_id": session_id, "total_size": total},
            )
            self._raise(r)
            upload_id = r.json()["upload_id"]

            try:
                offset = 0
                with open(zip_path, "rb") as f:
                    while offset < total:
                        chunk = f.read(self.CHUNK_SIZE)
                        if not chunk:
                            break
                        offset = self._put_chunk_with_retry(
                            c, upload_id, offset, chunk, max_retries_per_chunk
                        )
                        if progress:
                            try:
                                progress(offset, total)
                            except Exception:
                                pass

                r = c.post(f"/api/uploads/{upload_id}/complete")
                self._raise(r)
                return r.json()["session"]
            except Exception:
                # Best-effort abort so the server temp dir doesn't linger.
                try:
                    c.delete(f"/api/uploads/{upload_id}")
                except Exception:
                    pass
                raise

    def _put_chunk_with_retry(
        self,
        client: httpx.Client,
        upload_id: str,
        offset: int,
        chunk: bytes,
        max_retries: int,
    ) -> int:
        """Put a chunk, recovering from network errors and offset drift.

        Returns the new server-reported byte offset after the chunk lands.
        """
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                r = client.put(
                    f"/api/uploads/{upload_id}",
                    params={"offset": offset},
                    content=chunk,
                    headers={"Content-Type": "application/octet-stream"},
                )
                if r.status_code == 409:
                    # Offset drifted — re-query state and either retry from the
                    # server's current offset, or accept the chunk landed twice.
                    sr = client.get(f"/api/uploads/{upload_id}")
                    self._raise(sr)
                    server_offset = int(sr.json()["bytes_received"])
                    if server_offset == offset + len(chunk):
                        return server_offset  # our chunk actually landed; move on
                    if server_offset != offset:
                        raise HubError(
                            f"server offset {server_offset} doesn't match local {offset}",
                            status_code=409,
                        )
                    # else: same offset, real conflict — retry
                else:
                    self._raise(r)
                    return int(r.json()["bytes_received"])
            except (httpx.TransportError, httpx.RemoteProtocolError) as e:
                last_err = e
                continue
        raise HubError(
            f"chunk PUT failed after {max_retries} attempts: {last_err}",
            status_code=None,
        )

    def download_session(
        self,
        session_id: str,
        out_dir: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Stream ``session_id``'s zip and extract under ``out_dir/{session_id}/``."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / session_id
        if target.exists():
            shutil.rmtree(target)

        with self._client() as c:
            with c.stream("GET", f"/api/sessions/{session_id}/zip") as r:
                self._raise(r)
                total = int(r.headers.get("content-length") or 0)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                try:
                    written = 0
                    try:
                        for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                            tmp.write(chunk)
                            written += len(chunk)
                            if progress:
                                progress(written, total)
                    finally:
                        tmp.close()
                    with zipfile.ZipFile(tmp.name, "r") as zf:
                        zf.extractall(target)
                finally:
                    try:
                        Path(tmp.name).unlink(missing_ok=True)
                    except OSError:
                        pass
        return target

    def delete_session(self, session_id: str) -> None:
        with self._client() as c:
            r = c.delete(f"/api/sessions/{session_id}")
            self._raise(r)

    def create_share(self, session_id: str) -> dict[str, Any]:
        """Create an unguessable share token. Returns {token, session_id, path, url}.

        ``url`` is the absolute browser URL the user can paste — built by
        joining ``base_url`` with the server-reported relative ``path``.
        """
        with self._client() as c:
            r = c.post(f"/api/sessions/{session_id}/share")
            self._raise(r)
            data = r.json()
        data["url"] = f"{self.base_url}{data['path']}"
        return data

    def list_shares(self, session_id: str) -> list[dict[str, Any]]:
        with self._client() as c:
            r = c.get(f"/api/sessions/{session_id}/shares")
            self._raise(r)
            return r.json().get("shares", [])

    def revoke_share(self, token: str) -> None:
        with self._client() as c:
            r = c.delete(f"/api/shares/{token}")
            self._raise(r)


# ---- Helpers ---------------------------------------------------------------


def _iter_session_files(session_dir: Path) -> Iterable[Path]:
    for p in session_dir.rglob("*"):
        if p.is_file():
            yield p


def _zip_session(session_dir: Path) -> Path:
    """Create a temp zip whose entries are paths relative to ``session_dir``."""
    fd = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    fd.close()
    zip_path = Path(fd.name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=4) as zf:
        for p in _iter_session_files(session_dir):
            zf.write(p, arcname=p.relative_to(session_dir).as_posix())
    return zip_path


class _ProgressReader(io.RawIOBase):
    """Wrap a file-like so httpx multipart streaming can drive a progress cb."""

    def __init__(self, fp, total: int, cb: Callable[[int, int], None] | None) -> None:
        super().__init__()
        self._fp = fp
        self._total = total
        self._cb = cb
        self._read = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        chunk = self._fp.read(size if size and size > 0 else 1024 * 1024)
        if chunk and self._cb:
            self._read += len(chunk)
            try:
                self._cb(self._read, self._total)
            except Exception:
                pass
        return chunk
