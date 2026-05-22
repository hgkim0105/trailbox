"""Command-line dispatch for ``Trailbox-hub.exe`` / ``python -m hub_server``.

Without a subcommand the dispatcher falls through to the uvicorn server
(current behavior). With a subcommand it runs maintenance tasks directly
against the local ``hub.db`` and exits — no HTTP, no uvicorn.

The trust boundary here is **disk access to hub.db**. Anyone who can run
this tool can already edit the SQLite directly, so we don't try to add
authentication. (A multi-tenant deployment would obviously be different.)

Subcommands:
    reset-password   — Restore access when admin loses their password.
                       Works for any user, including the last remaining admin.

Add new subcommands by registering them in ``_SUBCOMMANDS`` so
``hub_entry.py`` knows not to consume ``hub.env`` for those paths.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from typing import Sequence

# Names of subcommands argparse knows about. hub_entry.py checks this set
# to decide whether to consume hub.env (only on the serve path) — keeping
# the source of truth here means new subcommands don't have to touch the
# entrypoint too.
_SUBCOMMANDS = frozenset({"reset-password"})


def is_subcommand(argv: Sequence[str]) -> bool:
    return bool(argv) and argv[0] in _SUBCOMMANDS


def dispatch(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="Trailbox-hub",
        description="Trailbox Hub server + maintenance commands.",
    )
    sub = parser.add_subparsers(dest="cmd", title="commands", metavar="<command>")

    # ---- reset-password ---------------------------------------------------
    rp = sub.add_parser(
        "reset-password",
        help="Reset a user's password (admin recovery; runs against local hub.db).",
    )
    rp.add_argument("-u", "--username", required=True, help="Account to reset.")
    rp.add_argument(
        "-p",
        "--password",
        default=None,
        help="New password. If omitted, prompt interactively (recommended -- "
        "the prompted form doesn't appear in shell history).",
    )
    rp.add_argument(
        "--require-change",
        action="store_true",
        help="Force the user to change the password again on their next login. "
        "Useful when an operator sets a temporary password for another user; "
        "leave off for self-recovery.",
    )

    args = parser.parse_args(argv)

    if args.cmd == "reset-password":
        return _cmd_reset_password(args)

    # No subcommand → fall through to the HTTP server.
    from .__main__ import serve  # lazy: keeps `import cli` cheap for CLI calls

    return serve()


def _cmd_reset_password(args: argparse.Namespace) -> int:
    # Late imports so `--help` / argparse errors don't drag in the auth stack.
    from .audit import AuditLog
    from .config import load as load_config
    from .db import Database
    from .tokens import ApiTokenStore
    from .users import PasswordPolicyError, UserStore

    cfg = load_config()
    db_path = cfg.data_root / "hub.db"
    if not db_path.exists():
        print(
            f"error: no hub.db at {db_path}. Has the Hub ever started? "
            "Set TRAILBOX_HUB_DATA to the right directory.",
            file=sys.stderr,
        )
        return 2

    db = Database(db_path)  # ctor runs pending migrations
    try:
        users = UserStore(db)
        tokens = ApiTokenStore(db, users)
        audit = AuditLog(db)

        target = users.get_by_username(args.username)
        if target is None:
            print(f"error: user {args.username!r} not found", file=sys.stderr)
            return 2

        new_pw = args.password
        if new_pw is None:
            try:
                new_pw = getpass.getpass("New password: ")
                confirm = getpass.getpass("Confirm:      ")
            except (EOFError, KeyboardInterrupt):
                print("\naborted", file=sys.stderr)
                return 1
            if new_pw != confirm:
                print("error: passwords do not match", file=sys.stderr)
                return 2

        try:
            users.set_password(
                target.id, new_pw, must_change=args.require_change
            )
        except PasswordPolicyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        revoked = tokens.revoke_all_for_user(target.id)
        audit.record(
            "password_reset",
            actor_id=None,  # CLI has no logged-in actor
            target=target.username,
            detail={
                "via": "cli",
                "revoked_tokens": revoked,
                "must_change": bool(args.require_change),
            },
        )

        bits = [f"OK: password reset for {target.username!r}"]
        bits.append(f"(role={target.role}, status={target.status})")
        if revoked:
            bits.append(f"— {revoked} API token(s) revoked")
        if args.require_change:
            bits.append("— must change on next login")
        print(" ".join(bits))
        return 0
    finally:
        db.close()
