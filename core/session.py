"""Session metadata: id, output folder, start/end times, finalization."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_app_name(exe_path: str) -> str:
    """Derive a filesystem-safe app name from the executable path."""
    stem = Path(exe_path).stem or "app"
    cleaned = _SAFE_NAME_RE.sub("_", stem).strip("_-.")
    return cleaned or "app"


@dataclass
class Session:
    exe_path: str
    log_dir: str | None
    output_root: Path
    target_pid: int | None = None

    session_id: str = field(init=False, default="")
    dir: Path = field(init=False, default=Path())
    started_at: datetime | None = field(init=False, default=None)
    ended_at: datetime | None = field(init=False, default=None)

    def start(self) -> str:
        """Generate session id, create output folder, mark start time."""
        self.started_at = datetime.now()
        timestamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        self.session_id = f"{_safe_app_name(self.exe_path)}_{timestamp}"
        self.dir = Path(self.output_root) / self.session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        return self.session_id

    def logs_dir(self) -> Path:
        """Subfolder for log files collected from the target app."""
        path = self.dir / "logs"
        path.mkdir(exist_ok=True)
        return path

    def finalize(self, extra: dict | None = None) -> Path:
        """Write session_meta.json listing the artifacts produced this session."""
        self.ended_at = datetime.now()
        meta = {
            "session_id": self.session_id,
            "exe_path": self.exe_path,
            "log_dir": self.log_dir,
            "target_pid": self.target_pid,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat(),
            "duration_seconds": (
                (self.ended_at - self.started_at).total_seconds()
                if self.started_at
                else None
            ),
            "files": sorted(
                str(p.relative_to(self.dir)).replace("\\", "/")
                for p in self.dir.rglob("*")
                if p.is_file() and p.name != "session_meta.json"
            ),
        }
        if extra:
            meta.update(extra)

        meta_path = self.dir / "session_meta.json"
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return meta_path
