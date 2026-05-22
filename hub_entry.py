"""Entrypoint script for the Trailbox-hub.exe / Docker build.

Pure server-side: no Qt, no capture, no MCP. Imports nothing from the
recording stack so PyInstaller (and a Linux container) can ship a slim
binary with only fastapi/uvicorn/ffmpeg on disk.

Two invocation shapes:

* ``Trailbox-hub.exe`` (no args) — runs the HTTP server. Before serving,
  reads + deletes ``hub.env`` (Windows installer's bootstrap file) so the
  first-boot admin bootstrap picks up TRAILBOX_HUB_ADMIN_USER/PASS even
  when the user double-clicked the .exe directly.

* ``Trailbox-hub.exe <subcommand> ...`` — runs a maintenance command (e.g.
  ``reset-password``) against the local DB and exits. We deliberately do
  NOT consume ``hub.env`` on this path: those credentials are only meant
  for the server-startup bootstrap, not for ad-hoc tooling.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _consume_hub_env() -> None:
    here = Path(sys.argv[0]).resolve().parent
    candidates = [here / "hub.env", Path.cwd() / "hub.env"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Don't overwrite values that the user explicitly passed via env.
            if key and key not in os.environ:
                os.environ[key] = value
        try:
            path.unlink()
        except OSError:
            print(f"warning: could not remove {path}", file=sys.stderr)
        return  # only consume the first match


def main() -> int:
    from hub_server.cli import dispatch, is_subcommand

    argv = sys.argv[1:]
    if not is_subcommand(argv):
        # Server-startup path only — subcommands run against an existing DB
        # and shouldn't trigger the installer bootstrap.
        _consume_hub_env()
    return dispatch(argv)


if __name__ == "__main__":
    raise SystemExit(main())
