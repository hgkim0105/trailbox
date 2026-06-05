"""Lookback ("instant replay") mode: continuously buffer, save the last N seconds.

Normal Trailbox recording is start→stop: you decide up-front to record, and the
session spans the whole start..stop window. Lookback flips that: every recorder
runs continuously into a bounded *ring buffer*, and the user presses a capture
hotkey/button the moment something interesting happens. We then reach backwards
and materialize the preceding ``buffer_seconds`` into a normal, self-contained
session folder — same on-disk layout, viewer, and MCP contract as a regular
recording. Buffering keeps running afterwards, so several clips can be saved
from one buffering run (NVIDIA ShadowPlay model).

How each stream is bounded while idle-buffering:

- **Video** is the expensive one — raw BGRA can't be held in RAM (1080p60 for
  30 s is ~14 GB). So ffmpeg encodes continuously into a ring of short mpegts
  segments on disk (``ScreenRecorder`` lookback mode); a janitor prunes
  segments older than the window. On capture we concat the trailing segments
  that overlap ``[t_save - buffer_seconds, t_save]`` with ``-c copy`` (no
  re-encode) into ``screen.video.mp4``.
- **Audio** is cheap (48 kHz·2ch·s16 ≈ 0.7 MB/s) — held as an in-memory PCM
  ring in ``AudioRecorder`` lookback mode, sliced to the window on capture.
- **Logs / inputs / metrics / frame-timing** are lightweight JSONL events —
  each recorder, in lookback mode, pushes finished records to a ``sink``
  callback instead of writing files. The sink here is a :class:`RingEventBuffer`
  that prunes by ``t_video_s`` age.

The single timing rule from CLAUDE.md still holds: every record carries
``t_video_s`` measured against the buffering ``t0_perf``. On capture we pick a
new zero ``t0_new`` = the actual content-start of the trimmed video clip (the
creation time of the earliest concatenated segment), then rebase every stream
by the constant offset ``t0_new - t0_buffer`` so the saved clip starts at
``t_video_s == 0`` and video/audio/events stay aligned.

Windows desktop only (MonitorTarget / WindowTarget). Mobile capture targets
fall back to the normal start/stop path in main.py.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.audio_recorder import AudioRecorder
from core.input_recorder import InputRecorder
from core.log_collector import LogCollector
from core.metrics_recorder import MetricsRecorder
from core.post_mux import mux_av
from core.screen_recorder import (
    CaptureTarget,
    MonitorTarget,
    ScreenRecorder,
    WindowTarget,
)
from core.session import Session
from core.viewer_generator import generate_viewer

# Sink signature shared by the lightweight recorders in lookback mode:
# (full JSONL record dict, optional VTT cue text, VTT cue duration seconds).
EventSink = Callable[[dict, "str | None", float], None]

VIDEO_TMP = "screen.video.mp4"
AUDIO_TMP = "screen.audio.wav"
FINAL_NAME = "screen.mp4"

DEFAULT_BUFFER_SECONDS = 30
MIN_BUFFER_SECONDS = 5
MAX_BUFFER_SECONDS = 300


def _format_vtt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    return f"{h:02d}:{m:02d}:{s:06.3f}"


class RingEventBuffer:
    """Thread-safe, age-bounded buffer of timestamped JSONL records.

    Acts as the :data:`EventSink` for the log/input/metrics recorders while
    buffering. Records are kept only while their ``t_video_s`` is within
    ``buffer_seconds`` of the most recent record; older ones are dropped on
    every append so memory stays bounded no matter how long buffering runs.
    """

    def __init__(
        self,
        buffer_seconds: float,
        jsonl_rel: str,
        vtt_rel: str | None = None,
    ) -> None:
        self.buffer_seconds = float(buffer_seconds)
        self.jsonl_rel = jsonl_rel
        self.vtt_rel = vtt_rel
        # Each item: (t_video, record_dict, vtt_text_or_none, vtt_duration).
        self._items: deque[tuple[float, dict, str | None, float]] = deque()
        self._lock = threading.Lock()

    def sink(self, record: dict, vtt_text: str | None, vtt_dur: float) -> None:
        """Append a record; prune anything older than the window."""
        try:
            t_video = float(record.get("t_video_s", 0.0))
        except (TypeError, ValueError):
            t_video = 0.0
        with self._lock:
            self._items.append((t_video, record, vtt_text, vtt_dur))
            cutoff = t_video - self.buffer_seconds
            items = self._items
            while items and items[0][0] < cutoff:
                items.popleft()

    def flush(self, session_dir: Path, t_offset: float, t_max: float) -> int:
        """Write the buffered window into ``session_dir`` rebased to a new zero.

        ``t_offset`` / ``t_max`` are in the buffering ``t0_perf`` timeline:
        keep records with ``t_offset <= t_video <= t_max`` and shift them to
        ``t_video - t_offset`` so the saved clip starts at 0. Returns the
        number of records written.
        """
        with self._lock:
            snapshot = list(self._items)

        jsonl_path = session_dir / self.jsonl_rel
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        vtt_path = session_dir / self.vtt_rel if self.vtt_rel else None

        count = 0
        jsonl_fh = open(jsonl_path, "w", encoding="utf-8", newline="\n")
        vtt_fh = None
        if vtt_path is not None:
            vtt_path.parent.mkdir(parents=True, exist_ok=True)
            vtt_fh = open(vtt_path, "w", encoding="utf-8", newline="\n")
            vtt_fh.write("WEBVTT\n\n")
        try:
            for t_video, record, vtt_text, vtt_dur in snapshot:
                if t_video < t_offset or t_video > t_max:
                    continue
                rebased = dict(record)
                new_t = round(t_video - t_offset, 3)
                rebased["t_video_s"] = new_t
                jsonl_fh.write(json.dumps(rebased, ensure_ascii=False) + "\n")
                if vtt_fh is not None and vtt_text:
                    start = _format_vtt_time(new_t)
                    end = _format_vtt_time(new_t + (vtt_dur or 1.0))
                    vtt_fh.write(f"{start} --> {end}\n{vtt_text}\n\n")
                count += 1
        finally:
            jsonl_fh.close()
            if vtt_fh is not None:
                vtt_fh.close()
        return count


@dataclass
class LookbackConfig:
    """Everything the controller needs to buffer + materialize a clip."""

    target: CaptureTarget
    output_root: Path
    buffer_seconds: float
    max_fps: int
    audio_enabled: bool
    input_enabled: bool
    metrics_enabled: bool
    metrics_pid: int | None
    metrics_target_name: str
    log_dirs: list[Path]
    log_recursive: bool
    log_extensions: frozenset[str]
    exe_path: str | None
    window_hwnd: int | None
    system_info: dict = field(default_factory=dict)


@dataclass
class CaptureResult:
    """Outcome of one ``capture()`` call, for the caller's status line."""

    session_dir: Path
    meta_path: Path
    duration_seconds: float
    frames_written: int
    errors: list[str] = field(default_factory=list)


class LookbackController:
    """Owns the always-on buffering recorders and the capture flow.

    Lifecycle mirrors a normal recorder: :meth:`start` spins everything up into
    ring buffers, :meth:`capture` materializes the trailing window into a
    session (and may be called many times), :meth:`stop` tears down and discards
    the buffer. All capture work runs on the calling thread (the GUI's stop /
    hotkey handler) — the same place ``_on_stop_requested`` already does its
    synchronous mux/finalize, so no new threading contract is introduced.
    """

    def __init__(self, config: LookbackConfig) -> None:
        self.config = config
        self.t0_buffer: float = 0.0

        self._buffer_root: Path | None = None
        self._seg_dir: Path | None = None

        self._screen: ScreenRecorder | None = None
        self._audio: AudioRecorder | None = None
        self._log_collector: LogCollector | None = None
        self._input: InputRecorder | None = None
        self._metrics: MetricsRecorder | None = None

        # Per-stream ring buffers, registered by the recorders that feed them.
        self._rings: list[RingEventBuffer] = []
        self._capture_lock = threading.Lock()
        self._capture_seq = 0

    # ---- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        cfg = self.config
        if not isinstance(cfg.target, (MonitorTarget, WindowTarget)):
            raise RuntimeError("lookback mode supports desktop capture only")

        # Scratch area for the rolling video segments; wiped on stop(). Lives
        # under the output root so it shares the same drive as final sessions
        # (segment→mp4 concat then stays a same-volume operation).
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._buffer_root = cfg.output_root / ".lookback_buffer" / ts
        self._seg_dir = self._buffer_root / "segments"
        self._seg_dir.mkdir(parents=True, exist_ok=True)

        self.t0_buffer = time.perf_counter()

        # --- Video (segment ring) -- start first, same as the normal path so
        # the buffer's zero aligns with the first encoded frame.
        screen = ScreenRecorder(
            output_path=self._seg_dir,
            target=cfg.target,
            max_fps=cfg.max_fps,
            lookback=True,
            buffer_seconds=cfg.buffer_seconds,
        )
        screen.start()
        self._screen = screen

        # --- Audio (in-memory PCM ring) ---
        if cfg.audio_enabled:
            audio = AudioRecorder(
                output_path=self._buffer_root / "_unused.wav",
                lookback=True,
                buffer_seconds=cfg.buffer_seconds,
            )
            try:
                audio.start()
                self._audio = audio
            except Exception:  # noqa: BLE001 - audio is best-effort
                self._audio = None

        # --- Logs ---
        if cfg.log_dirs:
            ring = RingEventBuffer(
                cfg.buffer_seconds, "logs/logs.jsonl", "logs/logs.vtt"
            )
            collector = LogCollector(
                log_dirs=cfg.log_dirs,
                output_dir=self._buffer_root / "logs",
                t0_perf=self.t0_buffer,
                recursive=cfg.log_recursive,
                extensions=cfg.log_extensions,
                sink=ring.sink,
            )
            try:
                collector.start()
                self._log_collector = collector
                self._rings.append(ring)
            except Exception:  # noqa: BLE001
                self._log_collector = None

        # --- Input ---
        if cfg.input_enabled:
            ring = RingEventBuffer(
                cfg.buffer_seconds, "inputs/inputs.jsonl", "inputs/inputs.vtt"
            )
            recorder = InputRecorder(
                output_dir=self._buffer_root / "inputs",
                t0_perf=self.t0_buffer,
                window_hwnd=cfg.window_hwnd,
                sink=ring.sink,
            )
            try:
                recorder.start()
                self._input = recorder
                self._rings.append(ring)
            except Exception:  # noqa: BLE001
                self._input = None

        # --- Metrics ---
        if cfg.metrics_enabled and cfg.metrics_pid is not None:
            ring = RingEventBuffer(
                cfg.buffer_seconds, "metrics/process.jsonl", None
            )
            recorder = MetricsRecorder(
                pid=cfg.metrics_pid,
                output_path=self._buffer_root / "metrics" / "process.jsonl",
                t0_perf=self.t0_buffer,
                interval_s=1.0,
                sink=ring.sink,
            )
            try:
                recorder.start()
                self._metrics = recorder
                self._rings.append(ring)
            except Exception:  # noqa: BLE001
                self._metrics = None

    def stop(self) -> None:
        """Tear down every buffering recorder and delete the scratch buffer."""
        for rec in (self._screen, self._audio, self._input, self._metrics):
            if rec is not None:
                try:
                    rec.stop()
                except Exception:  # noqa: BLE001
                    pass
        if self._log_collector is not None:
            try:
                self._log_collector.stop()
            except Exception:  # noqa: BLE001
                pass
        self._screen = self._audio = self._input = self._metrics = None
        self._log_collector = None
        self._rings = []

        if self._buffer_root is not None:
            shutil.rmtree(self._buffer_root, ignore_errors=True)
            self._buffer_root = None
            self._seg_dir = None

    # ---- Capture ----------------------------------------------------------

    def capture(self) -> CaptureResult:
        """Materialize the trailing ``buffer_seconds`` into a full session.

        Reads the rings + video segments without disturbing them, so buffering
        continues for the next capture. Returns a :class:`CaptureResult`; any
        per-stream failure is collected into ``errors`` rather than aborting
        the whole clip (mirrors the best-effort stop path in main.py).
        """
        cfg = self.config
        screen = self._screen
        if screen is None:
            raise RuntimeError("capture() called before start()")

        # Serialize captures so two quick hotkey presses don't interleave
        # segment reads / session-id collisions.
        with self._capture_lock:
            self._capture_seq += 1
            t_save = time.perf_counter()
            errors: list[str] = []

            session = Session(
                exe_path=cfg.exe_path,
                log_dir=(str(cfg.log_dirs[0]) if cfg.log_dirs else None),
                output_root=cfg.output_root,
                target_pid=cfg.metrics_pid,
            )
            session_id = session.start()

            # --- Video: trim the trailing segments to screen.video.mp4 ---
            video_tmp = session.dir / VIDEO_TMP
            t0_new = t_save
            frames_written = 0
            effective_fps = 0.0
            frame_stats: dict = {}
            try:
                t0_new, video_dur = screen.save_window(
                    t_save, cfg.buffer_seconds, video_tmp
                )
                frames_written, effective_fps, frame_stats = screen.frame_window(
                    t0_new, t_save, session.dir / "metrics" / "frames.jsonl"
                )
            except Exception as e:  # noqa: BLE001
                errors.append(f"video: {e}")

            # offset/max in the buffering timeline shared by every event ring.
            t_offset = t0_new - self.t0_buffer
            t_max = t_save - self.t0_buffer

            # --- Audio: slice the PCM ring to the same window ---
            audio_tmp = session.dir / AUDIO_TMP
            audio_seconds = 0.0
            audio_device = ""
            have_audio = False
            if self._audio is not None:
                try:
                    audio_seconds = self._audio.flush_window(
                        t0_new, t_save, audio_tmp
                    )
                    audio_device = self._audio.device_name()
                    have_audio = audio_tmp.exists() and audio_seconds > 0
                except Exception as e:  # noqa: BLE001
                    errors.append(f"audio: {e}")

            # --- Event streams (logs / inputs / metrics) ---
            log_lines = input_events = metric_samples = 0
            for ring in self._rings:
                try:
                    n = ring.flush(session.dir, t_offset, t_max)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{ring.jsonl_rel}: {e}")
                    continue
                if ring.jsonl_rel.startswith("logs"):
                    log_lines = n
                elif ring.jsonl_rel.startswith("inputs"):
                    input_events = n
                elif ring.jsonl_rel.startswith("metrics"):
                    metric_samples = n

            # --- Mux video + audio → screen.mp4 ---
            final = session.dir / FINAL_NAME
            if video_tmp.exists():
                if have_audio:
                    try:
                        mux_av(video_tmp, audio_tmp, final)
                        video_tmp.unlink(missing_ok=True)
                        audio_tmp.unlink(missing_ok=True)
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"mux: {e}")
                else:
                    try:
                        if final.exists():
                            final.unlink()
                        video_tmp.rename(final)
                    except OSError as e:
                        errors.append(f"mux: {e}")

            duration = max(0.0, t_save - t0_new)

            # --- session_meta.json (same shape as the normal stop path) ---
            meta_path = session.finalize(
                extra={
                    "capture_mode": "lookback",
                    "lookback_buffer_seconds": cfg.buffer_seconds,
                    "max_fps": cfg.max_fps,
                    "screen_frames": frames_written,
                    "effective_fps": round(effective_fps, 2),
                    "frame_stats": frame_stats,
                    "system": cfg.system_info,
                    "audio_enabled": cfg.audio_enabled,
                    "audio_device": audio_device,
                    "audio_seconds": round(audio_seconds, 2),
                    "log_lines": log_lines,
                    "log_dirs": [str(p) for p in cfg.log_dirs],
                    "log_recursive": cfg.log_recursive,
                    "log_extensions": sorted(cfg.log_extensions) or ["*"],
                    "input_enabled": cfg.input_enabled,
                    "input_events": input_events,
                    "metrics_enabled": cfg.metrics_enabled,
                    "metric_samples": metric_samples,
                    "metrics_target_pid": cfg.metrics_pid,
                    "metrics_target_name": cfg.metrics_target_name,
                    "cpu_cores": (
                        (cfg.system_info.get("cpu") or {}).get("logical_cores")
                    ),
                    **({"lookback_errors": errors} if errors else {}),
                }
            )

            try:
                meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
                generate_viewer(session.dir, meta_obj)
            except Exception as e:  # noqa: BLE001
                errors.append(f"viewer: {e}")

            return CaptureResult(
                session_dir=session.dir,
                meta_path=meta_path,
                duration_seconds=duration,
                frames_written=frames_written,
                errors=errors,
            )
