"""Tail-follow log files in one or more watched folders and emit
video-synchronized output.

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

Multi-root + recursive: callers can pass several base directories
(e.g. client log dir + remote server log dir mounted locally) and an
optional ``recursive`` flag so subfolders are also watched. ``log.file.path``
in each record is the path relative to whichever watched root contains the
file, so subfolder structure is preserved in the viewer label.

Strategy:
- Snapshot existing log files at session start (recursive if requested) and
  remember their EOF positions; we only emit content APPENDED during the
  session.
- Poll those files (and any newly-created ones via watchdog) for new bytes.
  watchdog's ``modified`` event is unreliable across editors and ignored
  here in favor of a 100 ms poll loop.
- Each file is decoded UTF-8 first, falling back to cp949 then latin-1.
- On stop, archive each watched file as-is into ``logs/raw/<root_name>/...``
  preserving relative paths so two roots with the same file name don't clash.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


DEFAULT_EXTENSIONS = frozenset({".log", ".txt"})

# When the user opts into wildcard capture (empty extensions = "every file"),
# these well-known binary/media/archive suffixes still get skipped so the
# viewer isn't flooded with mojibake from .exe, .zip, image bytes, etc.
# Users who deliberately add one of these to their extension list (e.g. they
# really do want to tail a custom .dat log) override this — explicit beats
# implicit.
_BINARY_EXTENSIONS = frozenset({
    # Executables / libraries
    ".exe", ".dll", ".so", ".dylib", ".sys", ".bin", ".obj", ".o",
    ".a", ".lib", ".class", ".jar", ".pdb",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif",
    ".heic", ".raw", ".psd",
    # Audio / video
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac",
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm", ".flv",
    # Archives / packed
    ".zip", ".gz", ".tar", ".7z", ".rar", ".xz", ".bz2", ".tgz", ".tbz2",
    ".pak", ".pck", ".upk", ".asset", ".bundle",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Databases / dumps
    ".db", ".sqlite", ".sqlite3", ".mdb", ".dat", ".dump",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
})

# Bytes read off disk when sniffing a fresh file for binary content.
# 4 KB is large enough to catch null-byte markers in any executable / image
# header while staying cheap on directory bursts.
_BINARY_SNIFF_BYTES = 4096

POLL_INTERVAL_S = 0.1
# How often the poll loop re-walks the watched roots to discover files
# watchdog never reported. Watchdog can drop events under heavy create-bursts
# (its event queue overflows) so this is the safety net that keeps capture
# eventually consistent. 2s keeps the rescan cost negligible even on large
# log trees while staying close enough that a missed file is still mostly
# captured from its first lines.
RESCAN_INTERVAL_S = 2.0
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
    # The watched root this file lives under; used to derive the relative
    # display path written into log.file.path and the raw-archive layout.
    root: Path
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
        log_dir: Path | list[Path] | None = None,
        output_dir: Path | None = None,
        t0_perf: float | None = None,
        extensions: frozenset[str] = DEFAULT_EXTENSIONS,
        *,
        log_dirs: list[Path] | None = None,
        recursive: bool = True,
        sink: Callable[[dict, "str | None", float], None] | None = None,
    ) -> None:
        # log_dir kept as a positional alias for back-compat with older
        # callers/tests. Accepts a single Path or a list.
        if log_dirs is None:
            if log_dir is None:
                raise ValueError("log_dir or log_dirs must be provided")
            if isinstance(log_dir, (str, Path)):
                log_dirs = [Path(log_dir)]
            else:
                log_dirs = list(log_dir)
        else:
            log_dirs = list(log_dirs)
        if not log_dirs:
            raise ValueError("at least one log directory is required")
        if output_dir is None or t0_perf is None:
            raise ValueError("output_dir and t0_perf are required")

        # Resolve once + dedupe; keep insertion order so display paths stay
        # predictable for the user.
        resolved: list[Path] = []
        seen: set[str] = set()
        for d in log_dirs:
            p = Path(d).resolve()
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            resolved.append(p)
        self.log_dirs = resolved
        self.output_dir = Path(output_dir)
        self.t0_perf = float(t0_perf)
        self.extensions = frozenset(e.lower() for e in extensions)
        self.recursive = bool(recursive)
        # Lookback mode: route finished records to the sink instead of writing
        # logs.jsonl / logs.vtt. The raw-file archive is also skipped — a
        # captured clip is a time window, not a snapshot of whole log files.
        self._sink = sink

        # Precompute a display label per watched root. Default to the leaf
        # folder name; if two roots share a leaf (e.g. C:\GameA\Logs and
        # D:\Server\Logs are both "Logs"), fall back to the full path for
        # the colliding entries so the viewer source filter stays unambiguous.
        name_counts: dict[str, int] = {}
        for r in resolved:
            name_counts[r.name] = name_counts.get(r.name, 0) + 1
        self._source_labels: dict[Path, str] = {
            r: (str(r) if name_counts[r.name] > 1 else r.name) for r in resolved
        }

        # Per-root subfolder name for the raw archive. Always filesystem-safe
        # (just the leaf, or leaf_2 / leaf_3 on collision) — separate from
        # the human-facing source label which can be a full path with colons.
        self._raw_subdir: dict[Path, str] = {}
        used: dict[str, int] = {}
        for r in resolved:
            base = r.name or "root"
            if base in used:
                used[base] += 1
                self._raw_subdir[r] = f"{base}_{used[base]}"
            else:
                used[base] = 1
                self._raw_subdir[r] = base

        self._tailers: dict[Path, _Tailer] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._observers: list[Observer] = []
        self._jsonl_fh = None
        self._vtt_fh = None
        self._lines_written = 0
        self._error: BaseException | None = None
        self._raw_dir = self.output_dir / "raw"

    # ---- Back-compat property: callers used to read .log_dir -------------
    @property
    def log_dir(self) -> Path | None:
        return self.log_dirs[0] if self.log_dirs else None

    # ---- Public API -------------------------------------------------------

    def start(self) -> None:
        missing = [d for d in self.log_dirs if not d.is_dir()]
        if missing:
            raise FileNotFoundError(
                "log_dir not found: " + ", ".join(str(d) for d in missing)
            )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self._sink is None:
            self._jsonl_fh = open(
                self.output_dir / "logs.jsonl", "w", encoding="utf-8", newline="\n"
            )
            self._vtt_fh = open(
                self.output_dir / "logs.vtt", "w", encoding="utf-8", newline="\n"
            )
            self._vtt_fh.write("WEBVTT\n\n")

        # Snapshot existing log files at EOF; only new appended content is
        # captured. Walk recursively if requested so nested folders (e.g. a
        # server-log mirror with sub-buckets per day) are picked up.
        for root in self.log_dirs:
            for entry in self._iter_candidates(root):
                try:
                    pos = entry.stat().st_size
                except OSError:
                    pos = 0
                self._tailers[entry.resolve()] = _Tailer(
                    path=entry, root=root, pos=pos
                )

        # One Observer per root keeps event attribution simple (we know which
        # root produced the create/move) and avoids cross-root path lookups.
        for root in self.log_dirs:
            obs = Observer()
            obs.schedule(
                _RootEventHandler(self, root),
                str(root),
                recursive=self.recursive,
            )
            obs.start()
            self._observers.append(obs)

        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="LogPoller", daemon=True
        )
        self._poll_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for obs in self._observers:
            try:
                obs.stop()
                obs.join(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass
        self._observers = []
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=timeout)
            self._poll_thread = None

        # One last rescan + drain to catch a file created in the moments
        # between the final poll tick and stop() — without this a log line
        # written to a brand-new file just before the user hit stop would
        # silently disappear.
        self._rescan_for_missed_files()
        self._drain_all()

        # Flush partial trailing lines (writers that didn't end with \n).
        with self._lock:
            for tailer in self._tailers.values():
                tail = tailer.flush_partial()
                if tail is not None:
                    self._write_line(tailer, tail)

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

    # ---- File discovery ---------------------------------------------------

    def _matches_extension(self, path: Path) -> bool:
        """True if ``path``'s suffix is in the configured set.

        An empty ``self.extensions`` is interpreted as "every file" so that
        users who want to capture arbitrary log formats (``.json``, ``.out``,
        extension-less log files, ...) can opt in by clearing the field.
        In wildcard mode well-known binary suffixes still get rejected so
        the viewer isn't drowned in mojibake — see ``_BINARY_EXTENSIONS``.
        Explicit extension lists override the deny list (users get exactly
        what they asked for).
        """
        if not self.extensions:
            return path.suffix.lower() not in _BINARY_EXTENSIONS
        return path.suffix.lower() in self.extensions

    def _looks_binary(self, path: Path) -> bool:
        """Return True if ``path`` smells like a binary file.

        Sniffing test: if the first 4 KB contains a NUL byte we treat it as
        binary. Text logs essentially never carry NUL bytes; executables and
        media files start with NUL-heavy headers. Empty files return False
        so a log file that's still being created (size 0 at registration
        time) is tailed normally as text content arrives.

        Only called in wildcard mode — explicit extension lists are trusted.
        """
        try:
            with open(path, "rb") as fh:
                chunk = fh.read(_BINARY_SNIFF_BYTES)
        except OSError:
            # If we can't read it, leave the decision to the read path
            # (which decodes with errors='replace' as a last resort).
            return False
        if not chunk:
            return False
        return b"\x00" in chunk

    def _should_tail(self, path: Path) -> bool:
        """Final gate before registering a tailer for ``path``."""
        if not self._matches_extension(path):
            return False
        if not self.extensions and self._looks_binary(path):
            return False
        return True

    def _iter_candidates(self, root: Path):
        """Yield files under ``root`` that pass the tail-eligibility gate."""
        try:
            it = root.rglob("*") if self.recursive else root.iterdir()
        except OSError:
            return
        for entry in it:
            try:
                if entry.is_file() and self._should_tail(entry):
                    yield entry
            except OSError:
                continue

    def _root_for_path(self, path: Path) -> Path | None:
        """Find the watched root (deepest match) that contains ``path``."""
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        best: Path | None = None
        for root in self.log_dirs:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if best is None or len(str(root)) > len(str(best)):
                best = root
        return best

    # ---- watchdog callbacks (called from observer thread) -----------------

    def _handle_created(self, root: Path, path: Path) -> None:
        if not self._should_tail(path):
            return
        with self._lock:
            key = path.resolve()
            if key not in self._tailers:
                self._tailers[key] = _Tailer(path=path, root=root, pos=0)

    def _handle_moved(self, root: Path, src: Path, dst: Path) -> None:
        with self._lock:
            tailer = self._tailers.pop(src.resolve(), None)
            if tailer is not None and self._should_tail(dst):
                # If the move crossed roots (rare but possible with manual
                # mv) re-anchor to whichever watched root now contains it.
                new_root = self._root_for_path(dst) or root
                tailer.path = dst
                tailer.root = new_root
                self._tailers[dst.resolve()] = tailer

    # ---- Poll + write -----------------------------------------------------

    def _poll_loop(self) -> None:
        try:
            last_rescan = time.monotonic()
            while not self._stop.is_set():
                self._drain_all()
                now = time.monotonic()
                if now - last_rescan >= RESCAN_INTERVAL_S:
                    self._rescan_for_missed_files()
                    last_rescan = now
                time.sleep(POLL_INTERVAL_S)
        except BaseException as e:  # noqa: BLE001
            self._error = e

    def _rescan_for_missed_files(self) -> None:
        """Find files watchdog never reported and register them.

        Two scenarios this catches:

        1. **Event queue overflow** — a sudden burst of file creations
           (e.g. log rotation that spawns dozens of files at once) can
           overrun watchdog's internal queue, silently dropping create
           events. Without this rescan those files would never be tailed.
        2. **Subfolder created on a non-recursive root** — irrelevant in
           the default config but defensive if a caller opts out of
           recursion later.

        New tailers start at ``pos=0`` so the file's content from creation
        is captured, mirroring the ``_handle_created`` path. Already-tracked
        files are skipped under the lock to stay race-free against watchdog
        registering the same path concurrently.
        """
        for root in self.log_dirs:
            for entry in self._iter_candidates(root):
                try:
                    key = entry.resolve()
                except OSError:
                    continue
                with self._lock:
                    if key in self._tailers:
                        continue
                    self._tailers[key] = _Tailer(path=entry, root=root, pos=0)

    def _drain_all(self) -> None:
        with self._lock:
            tailers = list(self._tailers.values())
        for tailer in tailers:
            try:
                lines = tailer.read_new()
            except Exception:  # noqa: BLE001
                continue
            for raw in lines:
                self._write_line(tailer, raw)

    def _display_path(self, tailer: _Tailer) -> str:
        """Relative path written into log.file.path.

        Always relative to the file's watched root (forward slashes, no root
        prefix). The root itself is recorded separately under
        ``log.source.name`` so the viewer can filter by source.
        """
        try:
            rel = tailer.path.resolve().relative_to(tailer.root)
        except (ValueError, OSError):
            return tailer.path.name
        return str(rel).replace("\\", "/")

    def _write_line(self, tailer: _Tailer, raw: bytes) -> None:
        text = _decode(raw).rstrip()
        if not text:
            return

        t_video = max(0.0, time.perf_counter() - self.t0_perf)
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        display = self._display_path(tailer)
        source = self._source_labels.get(tailer.root, tailer.root.name)
        record = {
            "@timestamp": ts_utc,
            "t_video_s": round(t_video, 3),
            "log": {
                "file": {"path": display},
                "source": {"name": source},
            },
            "message": text,
            "ecs": {"version": ECS_VERSION},
        }
        # VTT cue label: when there are 2+ sources, prefix "source/file"
        # so the subtitle overlay is unambiguous; otherwise just the file.
        if len(self.log_dirs) > 1:
            cue_label = f"{source}/{display}" if display else source
        else:
            cue_label = display
        cue_text = f"[{cue_label}] {_vtt_escape(text)}"

        if self._sink is not None:
            # Lookback mode: ring-buffer the record + its cue.
            self._sink(record, cue_text, VTT_CUE_DURATION_S)
            self._lines_written += 1
            return

        try:
            if self._jsonl_fh is not None:
                self._jsonl_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

        try:
            if self._vtt_fh is not None:
                start = _format_vtt_time(t_video)
                end = _format_vtt_time(t_video + VTT_CUE_DURATION_S)
                self._vtt_fh.write(f"{start} --> {end}\n{cue_text}\n\n")
        except OSError:
            pass

        self._lines_written += 1

    def _archive_raw(self) -> None:
        # Lookback mode buffers a rolling window, not whole files — archiving
        # the full source logs would defeat the point, so skip it.
        if self._sink is not None:
            return
        if not self._tailers:
            return
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        multi = len(self.log_dirs) > 1
        for tailer in list(self._tailers.values()):
            src = tailer.path
            if not src.exists():
                continue
            try:
                rel = src.resolve().relative_to(tailer.root)
                rel_path = Path(str(rel))
            except (ValueError, OSError):
                rel_path = Path(src.name)
            # Prefix with the per-root subfolder name when multiple roots are
            # watched so files with identical names from different roots don't
            # collide. _raw_subdir already handles leaf-name collisions.
            if multi:
                rel_path = Path(self._raw_subdir.get(tailer.root, tailer.root.name)) / rel_path
            dest = self._raw_dir / rel_path
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            except OSError:
                pass


class _RootEventHandler(FileSystemEventHandler):
    """Per-root watchdog handler so each create/move event already knows
    which watched root it came from. Avoids resolving the root on each
    callback (which would be racy if a watched root were itself renamed).
    """

    def __init__(self, collector: LogCollector, root: Path) -> None:
        super().__init__()
        self._collector = collector
        self._root = root

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._collector._handle_created(self._root, Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = Path(event.src_path)
        dst = Path(getattr(event, "dest_path", "") or "")
        if not dst.parts:
            return
        self._collector._handle_moved(self._root, src, dst)
