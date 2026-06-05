"""Trim a finished session to a sub-range and produce a new session folder.

Given an existing ``output/{session_id}/`` and a ``[t_start, t_end]`` window
expressed in ``t_video_s`` seconds, build a fully self-contained second session
that looks byte-for-byte like a normal recording — same on-disk layout
(`screen.mp4`, `logs/`, `inputs/`, `metrics/`, `viewer.html`, `session_meta.json`),
same `t_video_s` contract (every record's `t_video_s` is rebased so the trimmed
clip starts at 0), same viewer + MCP compatibility.

This is the post-hoc analog of ``core/lookback.py``:

  - lookback ``RingEventBuffer.flush`` filters + rebases an in-memory deque.
  - we do the same to *finished JSONL files* — see :func:`_filter_jsonl_window`.

For the video / audio, lookback gets to assume it owns rolling mpegts segments
and a PCM ring; here the source is already a single muxed ``screen.mp4`` so we
hand the whole window to ffmpeg in one re-encode pass (`-c:v libx264 -c:a aac`).
We pay a few CPU-seconds per clip in exchange for frame-accurate cuts that
line up exactly with the event rebase — no GOP-boundary surprises.

Public entrypoint: :func:`trim_session`. Used both by the Hub trim endpoint
and by the Tauri ``trim_session`` bridge command, so the two paths can't
diverge.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from imageio_ffmpeg import get_ffmpeg_exe

from core.timeline_utils import format_vtt_time
from core.viewer_generator import generate_viewer

MIN_DURATION_S = 0.1

# Serializes the {src}_trim_NNN scan/increment across threads so two concurrent
# trims of the same source don't race on the same NNN.
_ID_LOCK = threading.Lock()


@dataclass
class TrimResult:
    session_dir: Path
    meta_path: Path
    new_session_id: str
    duration_seconds: float
    warnings: list[str] = field(default_factory=list)


def trim_session(
    src_dir: Path,
    output_root: Path,
    t_start: float,
    t_end: float,
    *,
    overwrite: bool = False,
) -> TrimResult:
    """Trim ``src_dir`` to ``[t_start, t_end]``.

    With ``overwrite=False`` writes to ``{output_root}/{src_id}_trim_NNN/``
    where NNN is the next free 3-digit number. With ``overwrite=True`` builds
    into a sibling temp dir and atomically replaces ``src_dir``.

    Raises ``ValueError`` if inputs are out of range or the source session
    is missing its meta. Per-stream failures are collected into
    ``TrimResult.warnings`` rather than aborting the whole trim (mirrors the
    best-effort stop / capture paths elsewhere in the codebase).
    """
    src_dir = Path(src_dir)
    output_root = Path(output_root)
    if not src_dir.is_dir():
        raise ValueError(f"source session not found: {src_dir}")

    src_meta_path = src_dir / "session_meta.json"
    if not src_meta_path.is_file():
        raise ValueError(f"session_meta.json missing in {src_dir}")
    src_meta: dict[str, Any] = json.loads(src_meta_path.read_text(encoding="utf-8"))

    # Trust the actual mp4 over session_meta.json — the meta's duration_seconds
    # has historically drifted when the recorder didn't get a clean stop, and a
    # stale meta would silently clamp the user's [t_end] before the trim ever
    # runs. ffprobing is fast (~50 ms) and pinpoints the real upper bound.
    src_video = src_dir / "screen.mp4"
    if not src_video.is_file():
        raise ValueError("source screen.mp4 missing")
    src_duration = _probe_video_duration(src_video)
    if src_duration <= 0:
        # Fall back to meta if ffprobe couldn't read the duration.
        src_duration = float(src_meta.get("duration_seconds") or 0.0)
    if src_duration <= 0:
        raise ValueError("source session has zero duration; nothing to trim")

    t_start = max(0.0, min(src_duration, float(t_start)))
    t_end = max(0.0, min(src_duration, float(t_end)))
    if t_end - t_start < MIN_DURATION_S:
        raise ValueError(
            f"trim window too small: [{t_start:.3f}, {t_end:.3f}] "
            f"in {src_duration:.3f}s session (min {MIN_DURATION_S}s)"
        )

    src_session_id = str(src_meta.get("session_id") or src_dir.name)

    # Resolve destination layout: either a sibling sibling dir or a temp dir
    # that we'll atomically swap into src_dir at the end.
    if overwrite:
        # tempdir as a *sibling* of src_dir so the final rename stays on the
        # same drive (cheap rename, not a copy).
        tmp_parent = src_dir.parent
        dst_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{src_dir.name}.trim_tmp_",
                dir=str(tmp_parent),
            )
        )
        new_session_id = src_session_id
    else:
        new_session_id, dst_dir = _allocate_new_session_dir(
            output_root, src_session_id
        )

    warnings: list[str] = []

    try:
        # --- Video + audio: single ffmpeg re-encode pass over screen.mp4 ----
        # (existence already checked above when probing the duration)
        dst_video = dst_dir / "screen.mp4"
        _trim_video(src_video, dst_video, t_start, t_end)

        # --- Event streams: filter + rebase the finished JSONLs -------------
        log_lines = _filter_jsonl_window(
            src_dir / "logs" / "logs.jsonl",
            dst_dir / "logs" / "logs.jsonl",
            t_start,
            t_end,
            vtt_dst=dst_dir / "logs" / "logs.vtt",
            vtt_cue=_log_vtt_cue,
            warnings=warnings,
        )
        input_events = _filter_jsonl_window(
            src_dir / "inputs" / "inputs.jsonl",
            dst_dir / "inputs" / "inputs.jsonl",
            t_start,
            t_end,
            vtt_dst=dst_dir / "inputs" / "inputs.vtt",
            vtt_cue=_input_vtt_cue,
            warnings=warnings,
        )
        metric_samples = _filter_jsonl_window(
            src_dir / "metrics" / "process.jsonl",
            dst_dir / "metrics" / "process.jsonl",
            t_start,
            t_end,
            warnings=warnings,
        )
        screen_frames = _filter_jsonl_window(
            src_dir / "metrics" / "frames.jsonl",
            dst_dir / "metrics" / "frames.jsonl",
            t_start,
            t_end,
            warnings=warnings,
            on_record=_reindex_frame,
        )

        # --- session_meta.json: rebuild from source, recompute volatile bits
        duration = round(t_end - t_start, 3)
        frame_stats = _recompute_frame_stats(
            dst_dir / "metrics" / "frames.jsonl"
        )
        new_meta = _build_trimmed_meta(
            src_meta=src_meta,
            new_session_id=new_session_id,
            t_start=t_start,
            t_end=t_end,
            duration=duration,
            screen_frames=screen_frames,
            log_lines=log_lines,
            input_events=input_events,
            metric_samples=metric_samples,
            frame_stats=frame_stats,
            overwrite=overwrite,
            src_session_id=src_session_id,
        )

        # files list is computed after writes complete but before meta is
        # persisted, since session_meta.json itself is excluded.
        new_meta["files"] = sorted(
            str(p.relative_to(dst_dir)).replace("\\", "/")
            for p in dst_dir.rglob("*")
            if p.is_file() and p.name != "session_meta.json"
        )

        meta_path = dst_dir / "session_meta.json"
        meta_path.write_text(
            json.dumps(new_meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # --- viewer.html: re-generate against the trimmed dir ----------------
        try:
            generate_viewer(dst_dir, new_meta)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"viewer: {e}")

        # --- atomic swap if overwriting --------------------------------------
        if overwrite:
            final_dir = src_dir
            backup_dir = src_dir.with_name(f".{src_dir.name}.trim_old_{os.getpid()}")
            os.rename(src_dir, backup_dir)
            try:
                os.rename(dst_dir, final_dir)
            except Exception:
                # Restore on failure
                os.rename(backup_dir, src_dir)
                raise
            shutil.rmtree(backup_dir, ignore_errors=True)
            dst_dir = final_dir
            # The meta_path / file paths under dst_dir are now under final_dir
            meta_path = dst_dir / "session_meta.json"

        return TrimResult(
            session_dir=dst_dir,
            meta_path=meta_path,
            new_session_id=new_session_id,
            duration_seconds=duration,
            warnings=warnings,
        )

    except Exception:
        # Cleanup on hard failure so we don't leave partial dirs around.
        if overwrite:
            shutil.rmtree(dst_dir, ignore_errors=True)
        else:
            shutil.rmtree(dst_dir, ignore_errors=True)
        raise


# ---- Video --------------------------------------------------------------


def _probe_video_duration(video: Path) -> float:
    """Return mp4 duration in seconds via ffmpeg (no separate ffprobe binary).

    Returns 0.0 if probing fails — callers fall back to session_meta.json's
    ``duration_seconds`` in that case.
    """
    try:
        proc = subprocess.run(
            [
                get_ffmpeg_exe(),
                "-hide_banner",
                "-i", str(video),
            ],
            capture_output=True,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except OSError:
        return 0.0
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    # ffmpeg prints e.g. "  Duration: 00:00:12.42, start: 0.000000, bitrate: ..."
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("Duration:"):
            try:
                ts = stripped.split(",")[0].split(":", 1)[1].strip()
                hh, mm, ss = ts.split(":")
                return int(hh) * 3600 + int(mm) * 60 + float(ss)
            except (IndexError, ValueError):
                return 0.0
    return 0.0


def _trim_video(src: Path, dst: Path, t_start: float, t_end: float) -> None:
    """Re-encode the [t_start, t_end] window of src into dst.

    Input-side ``-ss`` would be faster but snaps to keyframes; we put -ss/-to
    AFTER -i so ffmpeg seeks frame-accurately. CRF 20 + preset fast keeps
    quality close to the source for a short clip without blowing out CPU.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    log_path = dst.with_suffix(dst.suffix + ".trim.log")
    cmd = [
        get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel", "warning",
        "-y",
        "-i", str(src),
        "-ss", f"{t_start:.3f}",
        "-to", f"{t_end:.3f}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dst),
    ]
    with open(log_path, "wb") as log:
        subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    # Drop the empty sidecar on success; only useful when ffmpeg printed warnings.
    try:
        if log_path.stat().st_size == 0:
            log_path.unlink()
    except OSError:
        pass


# ---- JSONL filter + rebase ----------------------------------------------


def _filter_jsonl_window(
    src: Path,
    dst: Path,
    t_start: float,
    t_end: float,
    *,
    vtt_dst: Path | None = None,
    vtt_cue: Callable[[dict], tuple[str, float] | None] | None = None,
    warnings: list[str],
    on_record: Callable[[dict, int], dict] | None = None,
) -> int:
    """Stream ``src`` into ``dst``, keeping records with t_start ≤ t_video_s ≤ t_end.

    Each kept record's ``t_video_s`` is rebased to ``t_video_s - t_start`` (so
    the trimmed clip starts at 0 — matches the lookback contract). Missing src
    is a no-op (returns 0) since not every session has every stream (e.g. no
    audio means no logs in some configs, no metrics if disabled).

    Returns the count of kept records.
    """
    if not src.is_file():
        return 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    vtt_fh = None
    if vtt_dst is not None and vtt_cue is not None:
        vtt_dst.parent.mkdir(parents=True, exist_ok=True)
        vtt_fh = open(vtt_dst, "w", encoding="utf-8", newline="\n")
        vtt_fh.write("WEBVTT\n\n")

    count = 0
    try:
        with open(src, "r", encoding="utf-8") as fin, \
             open(dst, "w", encoding="utf-8", newline="\n") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError) as e:
                    warnings.append(f"{src.name}: skipped malformed line ({e})")
                    continue
                try:
                    t_video = float(rec.get("t_video_s", 0.0))
                except (TypeError, ValueError):
                    continue
                if t_video < t_start or t_video > t_end:
                    continue
                new_t = round(t_video - t_start, 3)
                rec["t_video_s"] = new_t
                if on_record is not None:
                    rec = on_record(rec, count)
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if vtt_fh is not None and vtt_cue is not None:
                    cue = vtt_cue(rec)
                    if cue is not None:
                        text, dur = cue
                        start_ts = format_vtt_time(new_t)
                        end_ts = format_vtt_time(new_t + (dur or 1.0))
                        vtt_fh.write(f"{start_ts} --> {end_ts}\n{text}\n\n")
                count += 1
    finally:
        if vtt_fh is not None:
            vtt_fh.close()
    return count


def _log_vtt_cue(rec: dict) -> tuple[str, float] | None:
    msg = rec.get("message") or ""
    if not msg:
        return None
    # First line only, cap at ~120 chars, same approach the original log
    # collector takes — keeps the subtitle track readable.
    text = str(msg).splitlines()[0][:120]
    return text, 1.5


def _input_vtt_cue(rec: dict) -> tuple[str, float] | None:
    inp = rec.get("input") or {}
    kind = inp.get("type") or inp.get("kind") or "input"
    if kind == "key":
        key = inp.get("key", "?")
        action = inp.get("action", "press")
        return f"key {action}: {key}", 0.5
    if kind in ("mouse", "click"):
        btn = inp.get("button", "?")
        act = "press" if inp.get("pressed") else "release"
        return f"mouse {btn} {act}", 0.5
    if kind == "scroll":
        return f"scroll {inp.get('dx', 0)},{inp.get('dy', 0)}", 0.5
    return None


def _reindex_frame(rec: dict, new_index: int) -> dict:
    """Rewrite ``frame.index`` to be 0-based within the trimmed clip.

    The first frame in the window also has its ``delta_ms`` cleared, because
    the prior delta spans across the cut boundary and would be nonsense.
    """
    frame = dict(rec.get("frame") or {})
    frame["index"] = new_index
    if new_index == 0:
        frame["delta_ms"] = None
    rec["frame"] = frame
    return rec


def _recompute_frame_stats(frames_path: Path) -> dict[str, Any]:
    """Recompute the frame_stats sub-object from the trimmed frames.jsonl.

    Same shape Trailbox writes during a normal recording (min / avg / max /
    p50 / p95 / p99 / std on delta_ms), so the viewer's top-stat panel keeps
    working without conditionals.
    """
    if not frames_path.is_file():
        return {}
    deltas: list[float] = []
    for line in frames_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        d = (rec.get("frame") or {}).get("delta_ms")
        if d is None:
            continue
        try:
            fd = float(d)
        except (TypeError, ValueError):
            continue
        if fd > 0:
            deltas.append(fd)
    if not deltas:
        return {}
    deltas.sort()
    n = len(deltas)

    def pct(p: float) -> float:
        if n == 1:
            return deltas[0]
        idx = max(0, min(n - 1, int(round(p / 100.0 * (n - 1)))))
        return deltas[idx]

    mean = sum(deltas) / n
    var = sum((x - mean) ** 2 for x in deltas) / n
    return {
        "samples": n,
        "delta_ms_min": round(deltas[0], 3),
        "delta_ms_avg": round(mean, 3),
        "delta_ms_max": round(deltas[-1], 3),
        "delta_ms_p50": round(pct(50), 3),
        "delta_ms_p95": round(pct(95), 3),
        "delta_ms_p99": round(pct(99), 3),
        "delta_ms_std": round(var ** 0.5, 3),
    }


# ---- Meta ---------------------------------------------------------------


# Fields that describe the original capture and stay valid in the trimmed clip.
# Anything not in this list is recomputed or dropped (lookback/error fields).
_PRESERVE_META_KEYS = {
    "exe_path",
    "log_dir",
    "log_dirs",
    "log_recursive",
    "log_extensions",
    "target_pid",
    "system",
    "audio_enabled",
    "audio_device",
    "input_enabled",
    "metrics_enabled",
    "metrics_target_pid",
    "metrics_target_name",
    "cpu_cores",
    "max_fps",
}


def _build_trimmed_meta(
    *,
    src_meta: dict[str, Any],
    new_session_id: str,
    t_start: float,
    t_end: float,
    duration: float,
    screen_frames: int,
    log_lines: int,
    input_events: int,
    metric_samples: int,
    frame_stats: dict[str, Any],
    overwrite: bool,
    src_session_id: str,
) -> dict[str, Any]:
    now_iso = datetime.now().isoformat()
    meta: dict[str, Any] = {
        k: src_meta[k] for k in _PRESERVE_META_KEYS if k in src_meta
    }
    meta["session_id"] = new_session_id
    if overwrite:
        meta["started_at"] = src_meta.get("started_at")
    else:
        meta["started_at"] = now_iso
    meta["ended_at"] = now_iso
    meta["duration_seconds"] = duration

    meta["screen_frames"] = screen_frames
    meta["log_lines"] = log_lines
    meta["input_events"] = input_events
    meta["metric_samples"] = metric_samples
    meta["effective_fps"] = round(
        (screen_frames / duration) if duration > 0 else 0.0, 2
    )
    meta["frame_stats"] = frame_stats

    audio_seconds = src_meta.get("audio_seconds")
    if audio_seconds is not None:
        # Best-effort: the trimmed audio is exactly (t_end - t_start) since
        # ffmpeg cuts both streams together. If the source had no audio,
        # leave the field absent.
        meta["audio_seconds"] = duration

    meta["trim"] = {
        "source_session_id": src_session_id,
        "t_start": round(t_start, 3),
        "t_end": round(t_end, 3),
        "trimmed_at": now_iso,
        "overwrite": overwrite,
    }
    return meta


# ---- New-session id allocation ------------------------------------------


def _allocate_new_session_dir(
    output_root: Path,
    src_session_id: str,
) -> tuple[str, Path]:
    """Pick the next free ``{src}_trim_NNN`` and create the empty dir.

    The scan + mkdir is held under ``_ID_LOCK`` so two concurrent trims of
    the same source can't collide on the same NNN.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    prefix = f"{src_session_id}_trim_"
    with _ID_LOCK:
        # Find the highest existing NNN for this prefix.
        max_n = 0
        for child in output_root.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if not name.startswith(prefix):
                continue
            tail = name[len(prefix):]
            if len(tail) == 3 and tail.isdigit():
                max_n = max(max_n, int(tail))
        # Race-safe increment: try mkdir, bump on collision.
        for _ in range(64):
            max_n += 1
            new_id = f"{prefix}{max_n:03d}"
            new_dir = output_root / new_id
            try:
                new_dir.mkdir(parents=False, exist_ok=False)
                return new_id, new_dir
            except FileExistsError:
                continue
        raise RuntimeError("could not allocate a free trim session id")
