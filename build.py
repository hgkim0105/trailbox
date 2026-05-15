"""Build the v0.1.1 release artifacts via PyInstaller.

Produces TWO single-file binaries side by side in ``dist/``:

  - ``Trailbox.exe``      — windowed GUI (no console window)
  - ``Trailbox-mcp.exe``  — console build that runs ``main.py --mcp-server``
                            so Claude Desktop / Claude Code can register the
                            MCP server without a Python install.

Both build from the same ``main.py``; the MCP variant dispatches early in the
entry point (before Qt is imported) when ``--mcp-server`` is in argv. The GUI
variant uses ``--windowed`` to suppress a console window; the MCP variant is
``--console`` because stdio transport needs stdin/stdout intact, which
PyInstaller closes in windowed mode.

Run from the venv:  ``.\\.venv\\Scripts\\python.exe build.py``
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg


_GUI_FLAGS = [
    "--onefile",
    "--windowed",
    "--name", "Trailbox",
    "--collect-data", "soundcard",
    "--collect-data", "windows_capture",
    "--collect-data", "imageio_ffmpeg",
    "--collect-submodules", "comtypes",
    "--collect-submodules", "pynput",
]

# MCP build pulls in only what the stdio server needs — much leaner.
# ``mcp.cli`` requires optional ``typer``; skip it via targeted submodule pulls.
_MCP_FLAGS = [
    "--onefile",
    "--console",
    "--name", "Trailbox-mcp",
    "--collect-submodules", "mcp_server",
    "--collect-submodules", "mcp.server",
    "--collect-submodules", "mcp.shared",
    "--collect-submodules", "mcp.types",
]


def _run_pyinstaller(
    entry: str, flags: list[str], ffmpeg_exe: Path, repo_root: Path
) -> Path:
    cmd = [sys.executable, "-m", "PyInstaller", *flags]
    # ffmpeg is only useful to the GUI build; keep the MCP build minimal.
    if "--name" in flags and flags[flags.index("--name") + 1] == "Trailbox":
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

    print("\n=== done ===")
    for path in (gui_exe, mcp_exe):
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"  {path}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
