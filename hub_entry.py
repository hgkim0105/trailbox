"""Entrypoint script for the Trailbox-hub.exe / Docker build.

Pure server-side: no Qt, no capture, no MCP. Imports nothing from the
recording stack so PyInstaller (and a Linux container) can ship a slim
binary with only fastapi/uvicorn/ffmpeg on disk.
"""
from __future__ import annotations

from hub_server.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
