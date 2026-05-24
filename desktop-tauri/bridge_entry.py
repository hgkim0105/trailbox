"""Unified bridge entry point for PyInstaller bundling.

    trailbox-bridge.exe enumerate-windows   → JSON (one-shot)
    trailbox-bridge.exe list-devices        → JSON (one-shot)
    trailbox-bridge.exe system-info         → JSON (one-shot)
    trailbox-bridge.exe record              → stdin/stdout daemon
    trailbox-bridge.exe <hub-command> ...   → JSON (one-shot)
    ... (all commands from bridge.py)

When the subcommand is 'record', delegates to bridge_record.main().
Otherwise delegates to bridge.main().
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "record":
        sys.argv = [sys.argv[0]] + sys.argv[2:]  # strip 'record' arg
        from bridge_record import main as record_main
        sys.exit(record_main())
    else:
        from bridge import main as bridge_main
        sys.exit(bridge_main())
