"""One-shot: rebuild every session's viewer.html under TRAILBOX_HUB_DATA.

Useful after a viewer template bugfix — the .html lives next to mp4/jsonl
on the Hub and won't auto-regenerate. Run on the host as:

    python -m hub_server.regen_viewers
or, frozen:
    Trailbox-hub.exe --regen-viewers   (not wired today; use the module form)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from core.viewer_generator import generate_viewer

from .config import load as load_config


def main() -> int:
    cfg = load_config()
    root = cfg.data_root
    if not root.is_dir():
        print(f"no such data root: {root}", file=sys.stderr)
        return 2

    n_ok = n_skip = n_err = 0
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        meta_path = child / "session_meta.json"
        if not meta_path.exists():
            print(f"  SKIP {child.name}: no session_meta.json")
            n_skip += 1
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            generate_viewer(child, meta)
            print(f"  OK   {child.name}")
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR  {child.name}: {e}", file=sys.stderr)
            n_err += 1

    print(f"\ndone: {n_ok} regenerated, {n_skip} skipped, {n_err} errors")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
