"""Build the release artifacts via PyInstaller.

Produces THREE single-file binaries side by side in ``dist/``:

  - ``Trailbox.exe``      — windowed GUI (no console window)
  - ``Trailbox-mcp.exe``  — console MCP stdio server. With env var
                            ``TRAILBOX_HUB_URL`` it routes the 7 tools to a
                            remote Hub; without, it reads local ``output/``.
  - ``Trailbox-hub.exe``  — standalone Hub web server (fastapi/uvicorn).
                            Single-file alternative to the Docker image for
                            LAN deployments where a Linux container is overkill.

Plus, if Inno Setup is installed, a fourth artifact:

  - ``Trailbox-Setup.exe`` — installer bundling all three binaries with a
                             component-selection wizard, Hub config page
                             (with token generator), QSettings registry
                             pre-population, Start-Menu shortcuts, and
                             uninstaller. The installer step is skipped
                             gracefully if ``ISCC.exe`` isn't on PATH (or
                             at the default per-user install location).

GUI uses ``--windowed`` to suppress a console window; MCP & Hub are
``--console`` because both need stdin/stdout (stdio transport / log output).

Run from the venv:  ``.\\.venv\\Scripts\\python.exe build.py``
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg


_ICON = "assets/trailbox.ico"

_GUI_FLAGS = [
    "--onefile",
    "--windowed",
    "--name", "Trailbox",
    "--icon", _ICON,
    # Bundle the icon as data so Qt can load it at runtime for the window/taskbar.
    "--add-data", f"{_ICON};assets",
    "--collect-data", "soundcard",
    "--collect-data", "windows_capture",
    "--collect-data", "imageio_ffmpeg",
    "--collect-submodules", "comtypes",
    "--collect-submodules", "pynput",
    # ffmpeg binary added by _run_pyinstaller for both builds.
]

# MCP build pulls in only what the stdio server needs.
# ``mcp.cli`` requires optional ``typer``; skip it via targeted submodule pulls.
# ffmpeg is bundled so the ``get_frame_at`` tool can extract video frames
# from screen.mp4 — that single feature is why this exe isn't 13 MB anymore.
# httpx is needed when TRAILBOX_HUB_URL is set (HubBackend HTTP calls).
_MCP_FLAGS = [
    "--onefile",
    "--console",
    "--name", "Trailbox-mcp",
    "--icon", _ICON,  # file icon only (no Qt window)
    "--collect-data", "imageio_ffmpeg",
    "--collect-submodules", "mcp_server",
    "--collect-submodules", "mcp.server",
    "--collect-submodules", "mcp.shared",
    "--collect-submodules", "mcp.types",
    "--hidden-import", "httpx",
]

# Hub build is the FastAPI/uvicorn server bundled standalone. No Qt, no mcp,
# no capture stack. ffmpeg is bundled for the /api/sessions/{id}/frame route.
_HUB_FLAGS = [
    "--onefile",
    "--console",
    "--name", "Trailbox-hub",
    "--icon", _ICON,
    "--collect-data", "imageio_ffmpeg",
    "--collect-submodules", "hub_server",
    "--collect-submodules", "uvicorn",
    "--collect-submodules", "fastapi",
    "--hidden-import", "python_multipart",
]


def _find_iscc() -> Path | None:
    """Locate the Inno Setup compiler. Returns None if not installed."""
    # winget installs Inno Setup per-user under AppData\Local\Programs.
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    return Path(found) if found else None


def _build_installer(repo_root: Path) -> Path | None:
    """Compile the Inno Setup installer if ISCC.exe is available.

    Requires Trailbox.exe / Trailbox-mcp.exe / Trailbox-hub.exe in dist/.
    """
    iscc = _find_iscc()
    iss = repo_root / "installer" / "Trailbox-installer.iss"
    if iscc is None or not iss.is_file():
        print("\n=== skipping installer (ISCC.exe or .iss not found) ===")
        return None

    print(f"\n=== building Trailbox-Setup.exe ({iss.name}) ===")
    print(f"$ {iscc} {iss}")
    subprocess.run([str(iscc), str(iss)], check=True, cwd=iss.parent)
    out = repo_root / "dist" / "Trailbox-Setup.exe"
    if not out.is_file():
        raise RuntimeError(f"Inno Setup did not produce {out}")
    return out


def _run_pyinstaller(
    entry: str, flags: list[str], ffmpeg_exe: Path, repo_root: Path
) -> Path:
    cmd = [sys.executable, "-m", "PyInstaller", *flags]
    # ffmpeg goes into both builds — GUI uses it for recording, MCP uses it
    # for get_frame_at (single-frame extraction from screen.mp4).
    cmd += ["--add-binary", f"{ffmpeg_exe};imageio_ffmpeg/binaries"]
    cmd += [entry]
    name = flags[flags.index("--name") + 1]
    print(f"\n=== building {name}.exe ({entry}) ===")
    print("$ " + " ".join(c if ";" not in c else f'"{c}"' for c in cmd))
    subprocess.run(cmd, check=True, cwd=repo_root)
    out = repo_root / "dist" / f"{name}.exe"
    if not out.exists():
        raise RuntimeError(f"PyInstaller did not produce {out}")
    return out


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    ffmpeg_exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    print(f"ffmpeg: {ffmpeg_exe}")

    # Wipe everything so the two builds don't share stale work/PYZ caches.
    for p in [repo_root / "build", repo_root / "dist"]:
        if p.exists():
            print(f"cleaning {p}")
            shutil.rmtree(p, ignore_errors=True)
    for spec in repo_root.glob("*.spec"):
        spec.unlink()

    gui_exe = _run_pyinstaller("main.py", _GUI_FLAGS, ffmpeg_exe, repo_root)
    mcp_exe = _run_pyinstaller("mcp_entry.py", _MCP_FLAGS, ffmpeg_exe, repo_root)
    hub_exe = _run_pyinstaller("hub_entry.py", _HUB_FLAGS, ffmpeg_exe, repo_root)

    installer_exe = _build_installer(repo_root)

    print("\n=== done ===")
    outputs = [gui_exe, mcp_exe, hub_exe]
    if installer_exe is not None:
        outputs.append(installer_exe)
    for path in outputs:
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"  {path}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
