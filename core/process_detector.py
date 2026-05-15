"""Map between log directories and the processes likely producing the logs.

Primary strategy: scan ``psutil.Process.open_files()`` for handles inside the
folder. Catches the common case where the app keeps its log file open.

Fallback heuristic: many apps put their log folder at ``<install_dir>/Logs``,
so any running process whose executable directory is an ancestor (or sibling)
of the log folder is a likely match. This catches games that close their log
handle after each flush.

Both functions return PIDs, not Process objects, because cross-thread Process
references can become stale.
"""
from __future__ import annotations

import os
from pathlib import Path

import psutil


_LOG_EXTENSIONS = frozenset({".log", ".txt"})
# Subfolders to probe relative to install_dir and install_dir.parent.
_CONVENTIONAL_LOG_SUBFOLDERS = (
    "Logs",
    "logs",
    "Log",
    "log",
    "LogFiles",
    "Saved/Logs",      # Unreal Engine
    "Data/Logs",
    "diag",
    "diagnostics",
)
# AppData subfolder suffixes after $APPDATA\$AppStem or $LOCALAPPDATA\$AppStem.
_APPDATA_LOG_SUFFIXES = (
    "Logs",
    "logs",
    "Log",
    "log",
    "Saved/Logs",
)


def exe_for_pid(pid: int) -> str:
    """Best-effort full executable path for a PID; empty string on failure."""
    try:
        return psutil.Process(pid).exe() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return ""


def _is_path_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def find_pids_writing_to(folder: Path) -> list[int]:
    """PIDs that currently have open file handles inside ``folder``."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    matches: list[int] = []
    for proc in psutil.process_iter(["pid"]):
        try:
            for of in proc.open_files():
                if _is_path_under(Path(of.path), folder):
                    matches.append(proc.info["pid"])
                    break
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return matches


_HEURISTIC_MAX_DEPTH = 4         # max ancestor distance to consider on each side
_HEURISTIC_MAX_COMBINED = 4      # max sum of distances (exe_side + log_side)


def _is_drive_root(p: Path) -> bool:
    """True for paths like 'C:\\' or 'D:\\' — too coarse to use as a match anchor."""
    return p == p.parent


def find_pids_by_install_heuristic(folder: Path) -> list[int]:
    """Find running processes whose install location is near the log folder.

    Matches when ``exe_dir`` and ``log_dir`` share a near common ancestor — i.e.
    walking up from each, they meet within ``_HEURISTIC_MAX_DEPTH`` levels.
    This covers both the trivial case where the log folder sits next to the
    exe (``<install>/MyGame.exe`` + ``<install>/Logs``) and the common case
    where the exe lives one level deeper (``<install>/bin/MyGame.exe`` +
    ``<install>/Logs``). Lower combined distance = better match.
    """
    folder = Path(folder)
    try:
        folder = folder.resolve()
    except OSError:
        return []

    # Map each ancestor of log_dir to its depth from log_dir.
    # Drive roots are excluded — "same drive" is too loose to be a useful match.
    log_depth: dict[Path, int] = {}
    if not _is_drive_root(folder):
        log_depth[folder] = 0
    for i, parent in enumerate(folder.parents, start=1):
        if i > _HEURISTIC_MAX_DEPTH or _is_drive_root(parent):
            break
        log_depth[parent] = i

    scored: list[tuple[int, int]] = []  # (combined_distance, pid)
    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            exe = proc.info.get("exe")
            if not exe:
                continue
            exe_dir = Path(exe).resolve().parent
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue

        # Walk up from exe_dir until we hit one of log_dir's near ancestors.
        node = exe_dir
        best: tuple[int, int] | None = None
        for j in range(_HEURISTIC_MAX_DEPTH + 1):
            if _is_drive_root(node):
                break
            d_log = log_depth.get(node)
            if d_log is not None and j + d_log <= _HEURISTIC_MAX_COMBINED:
                best = (j + d_log, proc.info["pid"])
                break
            if node.parent == node:
                break
            node = node.parent
        if best is not None:
            scored.append(best)

    scored.sort()
    return [pid for _, pid in scored]


def _looks_like_log_file(p: Path) -> bool:
    if p.suffix.lower() in _LOG_EXTENSIONS:
        return True
    return "log" in p.name.lower()


def _dir_has_log_files(folder: Path) -> bool:
    try:
        for entry in folder.iterdir():
            if entry.is_file() and _looks_like_log_file(entry):
                return True
    except (OSError, PermissionError):
        return False
    return False


_SYSTEM_DIRS_LOWER = ("\\windows\\system32", "\\windows\\syswow64", "\\windows\\winsxs")
_PARENT_WALK_DEPTH = 2


def _is_system_exe(exe: str) -> bool:
    """Skip System32/service-host processes when walking the parent chain."""
    lo = exe.lower()
    return any(s in lo for s in _SYSTEM_DIRS_LOWER)


def _try_log_dir_for_pid(pid: int) -> Path | None:
    """Run the per-PID detection strategies once and return the first match."""
    try:
        proc = psutil.Process(pid)
        exe = proc.exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None
    if not exe:
        return None

    exe_path = Path(exe).resolve()
    install_dir = exe_path.parent
    app_stem = exe_path.stem

    # 1) Active file handles — strongest signal when it works.
    try:
        for of in proc.open_files():
            p = Path(of.path)
            if _looks_like_log_file(p):
                parent = p.parent
                if parent.is_dir():
                    return parent
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        pass

    # 2) Conventional dirs near the install location.
    candidates: list[Path] = []
    for base in (install_dir, install_dir.parent):
        if _is_drive_root(base):
            continue
        for sub in _CONVENTIONAL_LOG_SUBFOLDERS:
            candidates.append(base / sub)

    # 3) AppData / LocalAppData
    for env_var in ("LOCALAPPDATA", "APPDATA"):
        root = os.environ.get(env_var)
        if not root:
            continue
        base = Path(root) / app_stem
        for sub in _APPDATA_LOG_SUFFIXES:
            candidates.append(base / sub)

    # 4) Documents / My Games (common for older Windows games)
    home = os.environ.get("USERPROFILE")
    if home:
        docs = Path(home) / "Documents"
        candidates.append(docs / app_stem / "Logs")
        candidates.append(docs / "My Games" / app_stem / "Logs")

    for c in candidates:
        try:
            resolved = c.resolve()
        except OSError:
            continue
        if resolved.is_dir() and _dir_has_log_files(resolved):
            return resolved
    return None


def _walk_parents_inclusive(pid: int, max_depth: int = _PARENT_WALK_DEPTH) -> list[int]:
    """Yield ``pid`` then up to ``max_depth`` ancestors, skipping system services."""
    out: list[int] = []
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return out
    out.append(pid)
    for _ in range(max_depth):
        try:
            parent = proc.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        if parent is None:
            break
        try:
            exe = parent.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            break
        if not exe or _is_system_exe(exe):
            break
        out.append(parent.pid)
        proc = parent
    return out


def find_log_dir_for_pid(pid: int) -> Path | None:
    """Best-effort guess at the log folder for a running process.

    Tries detection strategies on the PID itself first, then walks up the
    parent process chain (up to ``_PARENT_WALK_DEPTH`` ancestors, skipping
    Windows services). This handles the common launcher pattern where a
    game's logs are actually written by its parent (e.g. AC Odyssey's logs
    live next to Ubisoft Connect, not next to ``ACOdyssey.exe``).
    """
    for candidate_pid in _walk_parents_inclusive(pid):
        result = _try_log_dir_for_pid(candidate_pid)
        if result is not None:
            return result
    return None


def find_pids_for_log_dir(folder: Path) -> list[int]:
    """Combined detection optimized for Windows.

    Strategy: install-dir heuristic runs first (a few ms, iterates all processes
    but only reads ``exe`` which is cheap). If we get candidates, try to verify
    with ``open_files()`` on JUST those PIDs — that's fast and tells us which
    of the install-dir candidates currently has the log file open. Verified
    candidates float to the top; unverified heuristic matches remain as
    fallback. If the heuristic returns nothing at all, do a full ``open_files()``
    sweep as a last resort.
    """
    heuristic = find_pids_by_install_heuristic(folder)
    if heuristic:
        folder_resolved = Path(folder).resolve()
        verified: list[int] = []
        for pid in heuristic:
            try:
                ofs = psutil.Process(pid).open_files()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            for of in ofs:
                if _is_path_under(Path(of.path), folder_resolved):
                    verified.append(pid)
                    break
        if verified:
            # Stable-merge: verified PIDs first, then any heuristic matches not
            # yet listed (in original heuristic order).
            seen = set(verified)
            return verified + [p for p in heuristic if p not in seen]
        return heuristic
    return find_pids_writing_to(folder)
