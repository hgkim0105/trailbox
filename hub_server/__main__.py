"""Run with ``python -m hub_server`` (uvicorn embedded).

Env vars (see hub_server/config.py):
  TRAILBOX_HUB_DATA   storage root (default: ./hub_data)
  TRAILBOX_HUB_TOKEN  required API token; empty disables auth (dev only)
  TRAILBOX_HUB_HOST   bind host (default: 127.0.0.1)
  TRAILBOX_HUB_PORT   bind port (default: 8765)
"""
from __future__ import annotations

import sys

import uvicorn

from .app import create_app
from .config import load as load_config


def main() -> int:
    cfg = load_config()

    if not cfg.auth_enabled and cfg.host not in ("127.0.0.1", "localhost"):
        print(
            f"refusing to bind {cfg.host}:{cfg.port} without TRAILBOX_HUB_TOKEN",
            file=sys.stderr,
        )
        return 2

    app = create_app(cfg)
    print(
        f"Trailbox Hub serving {cfg.data_root} on http://{cfg.host}:{cfg.port} "
        f"(auth={'on' if cfg.auth_enabled else 'OFF — dev mode'})"
    )
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
