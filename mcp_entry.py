"""Entrypoint script for the Trailbox-mcp.exe build.

Runs the MCP stdio server with zero Qt / capture imports — PyInstaller's
analysis follows the actual ``from mcp_server...`` import, so the resulting
binary doesn't pull PyQt6 / dxcam / soundcard data into the bundle path
used at runtime.
"""
from __future__ import annotations

from mcp_server.__main__ import mcp


if __name__ == "__main__":
    mcp.run()
