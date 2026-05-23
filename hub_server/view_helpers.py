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
import os

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


# ── Registration ─────────────────────────────────────────────────────────

def register_filters(env) -> None:
    """Attach the filters to a Jinja2 Environment."""
    env.filters["relative_time"] = relative_time
    env.filters["duration"] = duration
    env.filters["bytes_human"] = bytes_human
    env.filters["compact_number"] = compact_number
    env.filters["thumb_hue"] = thumb_hue
