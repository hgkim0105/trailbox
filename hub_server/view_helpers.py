"""View-side helpers for the Jinja templates: human formatters and derived
session metadata (device kind, thumbnail palette, etc.).

These are pure functions that take SessionSummary / primitive values and
return display-ready strings. The route handlers register them as Jinja
filters so templates can stay thin.

Anything that requires schema persistence (e.g. tags, captured device type)
lives in storage.py / db.py and is added to SessionSummary; this module
only handles formatting and reversible derivations from existing fields.
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import os
import re as _re
from pathlib import Path as _Path
from typing import Iterator as _Iterator

# ── Relative time ────────────────────────────────────────────────────────

def relative_time(iso: str | None) -> str:
    """ISO 8601 → "방금" / "N분 전" / "N시간 전" / "N일 전" / "YYYY-MM-DD"."""
    if not iso:
        return "—"
    try:
        dt = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return str(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    now = _dt.datetime.now(_dt.timezone.utc)
    delta = (now - dt).total_seconds()
    if delta < 0:
        return dt.strftime("%Y-%m-%d %H:%M")
    if delta < 60:
        return "방금"
    if delta < 3600:
        return f"{int(delta // 60)}분 전"
    if delta < 86400:
        return f"{int(delta // 3600)}시간 전"
    if delta < 86400 * 7:
        return f"{int(delta // 86400)}일 전"
    if delta < 86400 * 30:
        return f"{int(delta // (86400 * 7))}주 전"
    return dt.strftime("%Y-%m-%d")


# ── Duration ─────────────────────────────────────────────────────────────

def duration(secs: float | int | None) -> str:
    """Seconds → "M:SS" or "H:MM:SS"."""
    if secs is None:
        return "—"
    try:
        s = int(round(float(secs)))
    except (TypeError, ValueError):
        return "—"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


# ── Sizes ────────────────────────────────────────────────────────────────

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")

def bytes_human(b: int | float | None) -> str:
    """Bytes → "1.4 MB" / "612 KB" / etc."""
    if b is None:
        return "—"
    try:
        n = float(b)
    except (TypeError, ValueError):
        return "—"
    for i, u in enumerate(_SIZE_UNITS):
        if n < 1024 or i == len(_SIZE_UNITS) - 1:
            if u == "B":
                return f"{int(n)} {u}"
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


# ── Compact numbers ──────────────────────────────────────────────────────

def compact_number(n: int | float | None) -> str:
    """1234 → "1.2k", 1500000 → "1.5M"."""
    if n is None:
        return "—"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}k"
    return str(int(v))


# ── Derived from session_meta + exe_path ─────────────────────────────────
#
# All three derivations prefer the authoritative signals from session_meta
# (capture.target.kind and system.platform) when present, falling back to an
# exe_path substring heuristic when the meta is missing those fields. The
# fallback exists so sessions captured by older Trailbox clients (pre-meta
# enrichment) still get reasonable badges.

def derive_device(
    exe_path: str | None,
    device_kind: str | None = None,
    platform: str | None = None,
) -> str:
    """Returns 'Android' or 'PC' for the top-level device badge.

    Priority: device_kind == 'android' > platform contains 'Android' >
    exe_path heuristic.
    """
    if device_kind == "android":
        return "Android"
    if platform and "android" in platform.lower():
        return "Android"
    if exe_path:
        s = exe_path.lower()
        if "scrcpy" in s or "android" in s or s.endswith(".apk"):
            return "Android"
    return "PC"


def derive_thumb_kind(
    exe_path: str | None,
    device_kind: str | None = None,
) -> str:
    """Returns 'game' | 'mobile' | 'code'. Controls the card thumb's gradient hue.

    'mobile' is anchored to the authoritative device_kind when present;
    'game' vs 'code' is still exe_path-based since the meta has no
    notion of game-ness.
    """
    if device_kind == "android":
        return "mobile"
    if not exe_path:
        return "code"
    s = exe_path.lower()
    if "scrcpy" in s or "android" in s:
        return "mobile"
    if any(k in s for k in ("games", "steamapps", "epic games", "ubisoft", "ea games", "battle.net")):
        return "game"
    return "code"


def derive_device_label(
    exe_path: str | None,
    platform: str | None = None,
    device_kind: str | None = None,
) -> str:
    """Human-facing label below the device badge.

    Prefers the platform string from session_meta ('Windows 11', 'macOS 14',
    'Android 14'); falls back to the exe filename without extension.
    """
    if platform:
        # Trim long platform strings to keep card layouts tidy.
        p = platform.strip()
        if len(p) <= 32:
            return p
        return p[:30] + "…"
    if device_kind == "android":
        return "Android"
    if not exe_path:
        return "—"
    name = os.path.basename(exe_path.replace("\\", "/"))
    base = os.path.splitext(name)[0]
    return base or name


# ── Hue per thumb_kind (kept here so the template doesn't carry palette logic) ──

_THUMB_HUE = {"game": 280, "code": 220, "mobile": 150}

def thumb_hue(kind: str | None) -> int:
    return _THUMB_HUE.get(kind or "code", 220)


# ── Event stream loader (logs.jsonl + inputs.jsonl) ──────────────────────
#
# Reads the first N lines of each file, classifies them, and returns one
# merged list ordered by t_video_s so the Detail page's Events tab can
# render without doing any client-side fetching. Hard cap on lines keeps
# the page payload bounded even for noisy sessions.

_ERR_RE = _re.compile(r"\b(error|fatal|exception|traceback)\b", _re.IGNORECASE)
_WARN_RE = _re.compile(r"\b(warn(ing)?|deprecat)\b", _re.IGNORECASE)


def _classify_log(message: str) -> str:
    if not message:
        return "log"
    if _ERR_RE.search(message):
        return "error"
    if _WARN_RE.search(message):
        return "warn"
    return "log"


def _input_label(payload: dict) -> str:
    """Make a one-line human description out of an input record's payload."""
    if not isinstance(payload, dict):
        return "input"
    kind = payload.get("type") or payload.get("kind") or "input"
    if kind == "key":
        action = payload.get("action", "press")
        key = payload.get("key", "?")
        return f"key {action} · {key}"
    if kind in ("mouse", "click"):
        btn = payload.get("button", "?")
        act = "press" if payload.get("pressed") else "release"
        x, y = payload.get("x"), payload.get("y")
        if x is not None and y is not None:
            return f"mouse {btn} {act} @ ({x},{y})"
        return f"mouse {btn} {act}"
    if kind == "scroll":
        dx, dy = payload.get("dx", 0), payload.get("dy", 0)
        return f"scroll dx={dx} dy={dy}"
    if kind == "move":
        x, y = payload.get("x"), payload.get("y")
        return f"move @ ({x},{y})"
    return f"{kind}"


def _iter_jsonl(path: _Path, limit: int) -> _Iterator[dict]:
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= limit:
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    yield _json.loads(line)
                except _json.JSONDecodeError:
                    continue
    except OSError:
        return


def load_events(session_dir: _Path, *, per_file_limit: int = 500) -> dict:
    """Read both logs.jsonl and inputs.jsonl up to ``per_file_limit`` lines
    each, classify, merge, and return ``{events, counts, truncated_logs,
    truncated_inputs, total_logs, total_inputs}``.

    The truncation flags surface to the template so it can show 'showing
    first N of M' when a session is large enough to exceed the cap.
    """
    out: list[dict] = []
    counts = {"log": 0, "input": 0, "error": 0, "warn": 0, "all": 0}

    logs_path = session_dir / "logs" / "logs.jsonl"
    inputs_path = session_dir / "inputs" / "inputs.jsonl"

    def _file_total(p: _Path) -> int:
        if not p.is_file():
            return 0
        try:
            with p.open("rb") as f:
                # Cheap line count — good enough for the truncated-warning UX
                return sum(1 for _ in f)
        except OSError:
            return 0

    total_logs = _file_total(logs_path)
    total_inputs = _file_total(inputs_path)

    for rec in _iter_jsonl(logs_path, per_file_limit):
        msg = rec.get("message") or ""
        kind = _classify_log(msg)
        counts[kind] += 1
        log_info = rec.get("log") if isinstance(rec.get("log"), dict) else {}
        src = log_info.get("source") if isinstance(log_info.get("source"), dict) else {}
        out.append({
            "t_video_s": float(rec.get("t_video_s") or 0.0),
            "kind": kind,
            "source": src.get("name") or "log",
            "message": msg,
        })

    for rec in _iter_jsonl(inputs_path, per_file_limit):
        payload = rec.get("input") if isinstance(rec.get("input"), dict) else {}
        counts["input"] += 1
        out.append({
            "t_video_s": float(rec.get("t_video_s") or 0.0),
            "kind": "input",
            "source": payload.get("type") or "input",
            "message": _input_label(payload),
        })

    out.sort(key=lambda e: e["t_video_s"])
    counts["all"] = len(out)

    return {
        "events": out,
        "counts": counts,
        "total_logs": total_logs,
        "total_inputs": total_inputs,
        "truncated_logs": total_logs > per_file_limit,
        "truncated_inputs": total_inputs > per_file_limit,
        "per_file_limit": per_file_limit,
    }


def format_t_video(secs: float) -> str:
    """Seconds → 'MM:SS.d' (tenths) matching viewer.html / events row format."""
    if secs is None:
        return "00:00.0"
    s = max(0.0, float(secs))
    m = int(s // 60)
    sec = int(s % 60)
    tenths = int((s - int(s)) * 10)
    return f"{m:02d}:{sec:02d}.{tenths}"


# ── Registration ─────────────────────────────────────────────────────────

def register_filters(env) -> None:
    """Attach the filters to a Jinja2 Environment."""
    env.filters["relative_time"] = relative_time
    env.filters["duration"] = duration
    env.filters["bytes_human"] = bytes_human
    env.filters["compact_number"] = compact_number
    env.filters["thumb_hue"] = thumb_hue
    env.filters["t_video"] = format_t_video
