"""ADB / scrcpy binary locator + thin Android device helpers.

Two distinct concerns live here:

1. **Binary location** — `get_adb_path()` / `get_scrcpy_path()` resolve the
   bundled executables. In a PyInstaller-frozen build the binaries sit under
   ``_MEIPASS/bin/`` (added via ``--add-binary``); from a source checkout we
   look at ``tools/android/{platform-tools,scrcpy}/`` next to the repo root,
   then fall back to PATH. Pattern mirrors ``imageio_ffmpeg.get_ffmpeg_exe()``.

2. **Device probes** — short, explicitly-bounded ``adb`` calls used by the UI
   (device listing, refresh) and the orchestrator at session start
   (foreground package, screen size, cpu count, build props). Every call has
   a timeout and captures stderr so a hung/missing adb doesn't freeze the GUI.

Everything is best-effort: probe failures return ``None`` / empty rather than
raising, so a flaky device or partial root jail doesn't block the rest of
the session.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# Default short timeout for one-shot adb shell probes. Long enough for slow USB
# hubs / older devices, short enough that the UI doesn't lock up if the device
# is unresponsive.
_PROBE_TIMEOUT_S = 5.0
_DEVICES_TIMEOUT_S = 4.0

# Hide consoles on Windows.
_CREATIONFLAGS = (
    subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
)


def _frozen_base() -> Path | None:
    """``_MEIPASS`` when running from a PyInstaller bundle, else None."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return None


def _repo_tools_dir() -> Path:
    """``<repo>/tools/android`` for source-tree dev runs."""
    return Path(__file__).resolve().parent.parent / "tools" / "android"


def _exe_name(name: str) -> str:
    return f"{name}.exe" if sys.platform.startswith("win") else name


def get_adb_path() -> Path:
    """Resolve the adb executable.

    Order: frozen-bundle ``bin/`` → ``tools/android/platform-tools/`` →
    ``PATH``. Raises FileNotFoundError if none of those have it — that means
    the installer was tampered with, or the dev forgot to drop platform-tools
    into ``tools/android/``.
    """
    candidates: list[Path] = []
    base = _frozen_base()
    if base is not None:
        candidates.append(base / "bin" / _exe_name("adb"))
    candidates.append(_repo_tools_dir() / "platform-tools" / _exe_name("adb"))
    on_path = shutil.which("adb")
    if on_path:
        candidates.append(Path(on_path))
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "adb.exe not found. Drop platform-tools into tools/android/platform-tools/ "
        "or ensure the installer bundled it under bin/."
    )


def get_scrcpy_path() -> Path:
    """Resolve the scrcpy executable.

    Same search order as ``get_adb_path``. scrcpy *must* sit next to its
    ``scrcpy-server.jar``; both ship in the upstream zip together, so we
    don't verify the jar explicitly — the scrcpy binary will complain at
    spawn time if it can't find it.
    """
    candidates: list[Path] = []
    base = _frozen_base()
    if base is not None:
        candidates.append(base / "bin" / _exe_name("scrcpy"))
    candidates.append(_repo_tools_dir() / "scrcpy" / _exe_name("scrcpy"))
    on_path = shutil.which("scrcpy")
    if on_path:
        candidates.append(Path(on_path))
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "scrcpy.exe not found. Drop the scrcpy release into tools/android/scrcpy/ "
        "or ensure the installer bundled it under bin/."
    )


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str           # "device" / "unauthorized" / "offline" / ...
    model: str = ""
    product: str = ""
    transport_id: str = ""

    @property
    def online(self) -> bool:
        return self.state == "device"

    @property
    def label(self) -> str:
        """Short human label for the device picker combo."""
        bits = [self.model or self.serial]
        if self.serial != (self.model or ""):
            bits.append(f"({self.serial})")
        if not self.online:
            bits.append(f"[{self.state}]")
        return " ".join(bits)


def _run_adb(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Shell out to adb with stderr captured. Caller handles non-zero returns."""
    adb = get_adb_path()
    return subprocess.run(
        [str(adb), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_CREATIONFLAGS,
    )


def list_devices() -> list[AdbDevice]:
    """Parse ``adb devices -l`` into typed records.

    Returns an empty list on adb-not-found or call failure; the UI treats
    that the same as 'no devices' and shows a hint.
    """
    try:
        result = _run_adb(["devices", "-l"], timeout=_DEVICES_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []

    devices: list[AdbDevice] = []
    # First line is the "List of devices attached" header; subsequent lines:
    #   <serial>\t<state> [key:value]*
    # e.g. "RFCN20XXXX     device product:dream2qltechn model:SM_G955N transport_id:3"
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        state = parts[1]
        meta: dict[str, str] = {}
        for tok in parts[2:]:
            if ":" in tok:
                k, _, v = tok.partition(":")
                meta[k] = v
        devices.append(
            AdbDevice(
                serial=serial,
                state=state,
                model=meta.get("model", "").replace("_", " "),
                product=meta.get("product", ""),
                transport_id=meta.get("transport_id", ""),
            )
        )
    return devices


def _shell(serial: str, command: str, timeout: float = _PROBE_TIMEOUT_S) -> str | None:
    """Run a single shell command on the device. Returns stdout or None."""
    try:
        result = _run_adb(["-s", serial, "shell", command], timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


_FOCUS_RE = re.compile(r"[uU]=\d+\s+([^\s/]+)/")
_RESUMED_RE = re.compile(r"ResumedActivity[:=].*?\bu\d+\s+([^\s/]+)/", re.IGNORECASE)


def get_foreground_package(serial: str) -> str | None:
    """Best-effort foreground package via three fallback strategies.

    Tried in order, returning the first non-empty hit:

    1. ``dumpsys activity activities`` — yields ``topResumedActivity=...
       <pkg>/<activity>`` on Android 10+. Most reliable in modern AOSP.
    2. ``dumpsys window`` (no ``windows`` subarg) — Samsung One UI 8 / 16+
       returns ``mCurrentFocus`` here but NOT under ``dumpsys window
       windows``, which is why the previous single-source query was empty
       on Galaxy Tab S9 / One UI 8.
    3. ``dumpsys window windows`` — legacy AOSP path, kept as last resort
       for older or stripped Android variants.

    Returns None only if every probe failed.
    """
    out = _shell(serial, "dumpsys activity activities")
    if out:
        for line in out.splitlines():
            if "ResumedActivity" in line or "topResumedActivity" in line:
                m = _RESUMED_RE.search(line)
                if m:
                    return m.group(1)
                m = _FOCUS_RE.search(line)
                if m:
                    return m.group(1)

    for cmd in ("dumpsys window", "dumpsys window windows"):
        out = _shell(serial, cmd)
        if not out:
            continue
        for line in out.splitlines():
            s = line.strip()
            if "mCurrentFocus" in s or "mFocusedApp" in s:
                m = _FOCUS_RE.search(s)
                if m:
                    return m.group(1)
    return None


_SIZE_RE = re.compile(r"(?:Override size|Physical size):\s*(\d+)x(\d+)")


def get_screen_size(serial: str) -> tuple[int, int] | None:
    """Device display size in pixels via ``wm size``.

    Prefers "Override size" when present (user-changed) over "Physical size".
    Returns None on probe failure.
    """
    out = _shell(serial, "wm size")
    if not out:
        return None
    override: tuple[int, int] | None = None
    physical: tuple[int, int] | None = None
    for line in out.splitlines():
        m = _SIZE_RE.search(line)
        if not m:
            continue
        wh = (int(m.group(1)), int(m.group(2)))
        if "Override" in line:
            override = wh
        else:
            physical = wh
    return override or physical


def get_cpu_count(serial: str) -> int | None:
    """Logical CPU count on the device (`nproc`). Used to normalize cpu_pct."""
    out = _shell(serial, "nproc")
    if not out:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def getprop(serial: str, name: str) -> str | None:
    """Read a single Android system property."""
    out = _shell(serial, f"getprop {name}")
    if out is None:
        return None
    val = out.strip()
    return val or None


def get_android_version(serial: str) -> str | None:
    """User-facing Android version string (e.g. ``13``)."""
    return getprop(serial, "ro.build.version.release")


def get_android_sdk(serial: str) -> int | None:
    """API level (e.g. 33 for Android 13). Used for audio-capture gating."""
    val = getprop(serial, "ro.build.version.sdk")
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def get_device_model(serial: str) -> str | None:
    return getprop(serial, "ro.product.model")


def get_device_manufacturer(serial: str) -> str | None:
    return getprop(serial, "ro.product.manufacturer")
