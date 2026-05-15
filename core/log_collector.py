"""Tail-follow log files in a watched folder and emit video-synchronized output.

For each new line that appears in a watched log file during the session, we
emit two records:

- A line in ``logs.jsonl`` with ECS-friendly fields and ``t_video_s`` offset
  for direct Elasticsearch ingestion or AI consumption.
- A WebVTT cue in ``logs.vtt`` so reviewers can watch ``screen.mp4`` with the
  log text overlaid as subtitles.

Sync model: ``t_video_s`` is the wall-clock delta between line receipt and
``t0_perf`` — typically the moment the screen recorder was started. The delta
is computed from ``time.perf_counter()`` (monotonic), so it isn't affected by
NTP adjustments mid-session. Lines that appear before t0 are clamped to 0.

Strategy:
- Snapshot existing log files at session start and remember their EOF
  positions; we only emit content APPENDED during the session.
- Poll those files (and any newly-created ones via watchdog) for new bytes.
  watchdog's ``modified`` event is unreliable across editors and ignored
  here in favor of a 100 ms poll loop.
- Each file is decoded UTF-8 first, falling back to cp949 then latin-1.
- On stop, archive each watched file as-is into ``logs/raw/`` for traceability.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


DEFAULT_EXTENSIONS = frozenset({".log", ".txt"})
POLL_INTERVAL_S = 0.1
VTT_CUE_DURATION_S = 3.0
ECS_VERSION = "8.11"


def _format_vtt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class _Tailer:
    path: Path
    pos: int = 0
    partial: bytes = b""

    def read_new(self) -> list[bytes]:
        """Read newly-appended content; return complete-line byte sequences."""
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.pos:
            # Truncated or rotated: re-read from the start.
            self.pos = 0
            self.partial = b""
        if size == self.pos:
            return []
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.pos)
                data = fh.read(size - self.pos)
            self.pos = size
        except OSError:
            return []
        buf = self.partial + data
        parts = buf.split(b"\n")
        self.partial = parts.pop()
        return [p.rstrip(b"\r") for p in parts if p]

    def flush_partial(self) -> bytes | None:
        if self.partial:
            tail = self.partial
            self.partial = b""
            return tail
        return None


class LogCollector(FileSystemEventHandler):
    def __init__(
        self,
        log_dir: Path,
        output_dir: Path,
        t0_perf: float,
        extensions: frozenset[str] = DEFAULT_EXTENSIONS,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.output_dir = Path(output_dir)
        self.t0_perf = float(t0_perf)
        self.extensions = frozenset(e.lower() for e in extensions)

        self._tailers: dict[Path, _Tailer] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._observer: Observer | None = None
        self._jsonl_fh = None
        self._vtt_fh = None
        self._lines_written = 0
        self._error: BaseException | None = None
        self._raw_dir = self.output_dir / "raw"

    # ---- Public API -------------------------------------------------------

    def start(self) -> None:
        if not self.log_dir.is_dir():
            raise FileNotFoundError(f"log_dir not found: {self.log_dir}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_fh = open(
            self.output_dir / "logs.jsonl", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh = open(
            self.output_dir / "logs.vtt", "w", encoding="utf-8", newline="\n"
        )
        self._vtt_fh.write("WEBVTT\n\n")

        # Snapshot existing log files at EOF; only new appended content is captured.
        for entry in self.log_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() in self.extensions:
                try:
                    pos = entry.stat().st_size
                except OSError:
                    pos = 0
                self._tailers[entry] = _Tailer(path=entry, pos=pos)

        self._observer = Observer()
        self._observer.schedule(self, str(self.log_dir), recursive=False)
        self._observer.start()

        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="LogPoller", daemon=True
        )
        self._poll_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass
            self._observer = None
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=timeout)
            self._poll_thread = None

        # Final drain of any bytes appended after the last poll tick.
        self._drain_all()

        # Flush partial trailing lines (writers that didn't end with \n).
        with self._lock:
            for tailer in self._tailers.values():
                tail = tailer.flush_partial()
                if tail is not None:
                    self._write_line(tailer.path, tail)

        self._archive_raw()

        for fh in (self._jsonl_fh, self._vtt_fh):
            if fh is not None:
                try:
                    fh.close()
                except OSError:
                    pass
        self._jsonl_fh = None
        self._vtt_fh = None

        if self._error is not None:
            raise self._error

    def lines_written(self) -> int:
        return self._lines_written

    # ---- watchdog handlers (called from observer thread) ------------------

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in self.extensions:
            return
        with self._lock:
            # New file: capture from byte 0.
            self._tailers[path] = _Tailer(path=path, pos=0)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = Path(event.src_path)
        dst = Path(getattr(event, "dest_path", ""))
        with self._lock:
            tailer = self._tailers.pop(src, None)
            if tailer is not None and dst.suffix.lower() in self.extensions:
                tailer.path = dst
                self._tailers[dst] = tailer

    # ---- Poll + write -----------------------------------------------------

    def _poll_loop(self) -> None:
        try:
            while not self._stop.is_set():
                self._drain_all()
                time.sleep(POLL_INTERVAL_S)
        except BaseException as e:  # noqa: BLE001
            self._error = e

    def _drain_all(self) -> None:
        with self._lock:
            tailers = list(self._tailers.values())
        for tailer in tailers:
            try:
                lines = tailer.read_new()
            except Exception:  # noqa: BLE001
                continue
            for raw in lines:
                self._write_line(tailer.path, raw)

    def _write_line(self, path: Path, raw: bytes) -> None:
        text = _decode(raw).rstrip()
        if not text:
            return

        t_video = max(0.0, time.perf_counter() - self.t0_perf)
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        record = {
            "@timestamp": ts_utc,
            "t_video_s": round(t_video, 3),
            "log": {"file": {"path": path.name}},
            "message": text,
            "ecs": {"version": ECS_VERSION},
        }
        try:
            if self._jsonl_fh is not None:
                self._jsonl_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

        try:
            if self._vtt_fh is not None:
                start = _format_vtt_time(t_video)
                end = _format_vtt_time(t_video + VTT_CUE_DURATION_S)
                self._vtt_fh.write(
                    f"{start} --> {end}\n[{path.name}] {_vtt_escape(text)}\n\n"
                )
        except OSError:
            pass

        self._lines_written += 1

    def _archive_raw(self) -> None:
        if not self._tailers:
            return
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        for path in list(self._tailers.keys()):
            if path.exists():
                try:
                    shutil.copy2(path, self._raw_dir / path.name)
                except OSError:
                    pass
