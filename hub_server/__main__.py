"""Run with ``python -m hub_server`` (uvicorn embedded).

This module exposes two entry shapes:

* ``serve()`` — Launch the HTTP server with the env-loaded ``HubConfig``.
  Returns an exit code, ready to be wrapped in ``raise SystemExit(...)``.
* ``main()`` — Argparse dispatch wrapper. With no subcommand, equivalent
  to ``serve()``. With a subcommand (e.g. ``reset-password``), runs that
  maintenance task against the local DB and exits without binding a port.

Env vars (see hub_server/config.py):
  TRAILBOX_HUB_DATA   storage root (default: ./hub_data)
  TRAILBOX_HUB_HOST   bind host (default: 127.0.0.1)
  TRAILBOX_HUB_PORT   bind port (default: 8765)

  Bootstrap-on-first-run knobs:
  TRAILBOX_HUB_ADMIN_USER  / TRAILBOX_HUB_ADMIN_PASS
  TRAILBOX_HUB_AUTO_APPROVE
  TRAILBOX_HUB_SECRET_KEY
  TRAILBOX_HUB_TOKEN       (legacy service-token, optional)
"""
from __future__ import annotations

import sys

import uvicorn

from .app import create_app
from .config import load as load_config


def serve() -> int:
    """Run the HTTP server. Blocks until uvicorn returns."""
    cfg = load_config()

    if not cfg.auth_enabled and cfg.host not in ("127.0.0.1", "localhost"):
        # Defensive — cfg.auth_enabled is now always True, but keep the guard
        # in case future config changes reintroduce an "open" mode.
        print(
            f"refusing to bind {cfg.host}:{cfg.port} without authentication",
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


def main() -> int:
    from .cli import dispatch

    return dispatch()


if __name__ == "__main__":
    raise SystemExit(main())
