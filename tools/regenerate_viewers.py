"""Re-emit viewer.html for every session under an output root.

The viewer template was redesigned in v0.9.1 (OKLCH tokens + Geist + 2-column
side-panel layout). Existing sessions captured against older Trailbox builds
still carry a viewer.html that was frozen at recording-finish time, so they
keep the old dark-grey look forever. This script walks the output root and
regenerates each viewer in place using ``core.viewer_generator.generate_viewer``
and the session's own ``session_meta.json`` — no DB access, works against
both local recordings and Hub-extracted session dirs.

Usage:

    py -3.11 tools/regenerate_viewers.py [ROOT] [--dry-run] [--filter SUBSTR]

ROOT defaults to ``./output``. Pass ``--dry-run`` to preview without writing.
``--filter`` substring-matches against session_id and only regenerates hits.

Exit codes:
    0   every targeted session re-emitted successfully (or dry-run)
    1   one or more sessions failed; details printed to stderr
    2   the root path doesn't exist or contains no sessions
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the script runnable from the repo root without `pip install -e .`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.viewer_generator import generate_viewer  # noqa: E402


def _iter_sessions(root: Path):
    """Yield (session_dir, meta_dict) for every subdir that looks like a
    session — i.e. has a readable session_meta.json. Directories without
    that file are skipped silently (it's how _uploads / .secret_key / etc.
    are filtered out)."""
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(("_", ".")):
            continue
        meta_path = child / "session_meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  WARN: {child.name}: cannot read session_meta.json ({e})", file=sys.stderr)
            continue
        yield child, meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "root",
        nargs="?",
        default="output",
        help="output root containing session_id/ subdirs (default: ./output)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be regenerated without writing",
    )
    ap.add_argument(
        "--filter",
        default=None,
        metavar="SUBSTR",
        help="only regenerate sessions whose id contains SUBSTR",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    sessions = list(_iter_sessions(root))
    if args.filter:
        needle = args.filter.lower()
        sessions = [(d, m) for d, m in sessions if needle in d.name.lower()]
    if not sessions:
        print(f"no sessions found under {root}" + (f" matching '{args.filter}'" if args.filter else ""))
        return 2

    print(f"{'(dry-run) ' if args.dry_run else ''}root={root}  sessions={len(sessions)}")
    print()

    ok = 0
    fail = 0
    for session_dir, meta in sessions:
        existing = session_dir / "viewer.html"
        size_before = existing.stat().st_size if existing.is_file() else 0
        if args.dry_run:
            print(f"  would regen  {session_dir.name}  (current {size_before} B)")
            ok += 1
            continue
        try:
            out = generate_viewer(session_dir, meta)
            size_after = out.stat().st_size
            delta = size_after - size_before
            sign = "+" if delta >= 0 else ""
            print(f"  ok           {session_dir.name}  ({size_before:,} → {size_after:,} B, {sign}{delta:,})")
            ok += 1
        except Exception as e:  # noqa: BLE001 - we want the script to keep going
            print(f"  FAIL         {session_dir.name}: {type(e).__name__}: {e}", file=sys.stderr)
            fail += 1

    print()
    print(f"summary: ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
