"""Build Trailbox.exe via PyInstaller.

Run from the venv: ``.\\.venv\\Scripts\\python.exe build.py``.

Bundles the ffmpeg binary from imageio-ffmpeg, plus the cffi/comtypes data
needed by soundcard, windows-capture, dxcam, and pynput.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    ffmpeg_exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    print(f"ffmpeg: {ffmpeg_exe}")

    # Clean previous build artifacts so we never ship stale binaries.
    for p in [repo_root / "build", repo_root / "dist"]:
        if p.exists():
            print(f"  cleaning {p}")
            shutil.rmtree(p, ignore_errors=True)
    spec = repo_root / "Trailbox.spec"
    if spec.exists():
        spec.unlink()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        "Trailbox",
        "--add-binary",
        f"{ffmpeg_exe};imageio_ffmpeg/binaries",
        # Libraries whose data/DLLs PyInstaller's analyzer misses.
        "--collect-data",
        "soundcard",
        "--collect-data",
        "windows_capture",
        "--collect-data",
        "imageio_ffmpeg",
        # Dynamic-import-heavy packages.
        "--collect-submodules",
        "comtypes",
        "--collect-submodules",
        "pynput",
        "main.py",
    ]
    print("$ " + " ".join(c if ";" not in c else f'"{c}"' for c in cmd))
    subprocess.run(cmd, check=True, cwd=repo_root)
    out = repo_root / "dist" / "Trailbox.exe"
    if out.exists():
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"\nOK: {out}  ({size_mb:.1f} MB)")
    else:
        print("FAILED: dist/Trailbox.exe not produced")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
