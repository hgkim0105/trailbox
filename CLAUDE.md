# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Trailbox is a Windows-only PyQt6 desktop app that captures a synchronized QA recording (screen + system audio + game logs + keyboard/mouse input + process telemetry) into `output/{session_id}/`, generates a self-contained `viewer.html` for playback, and exposes the captured data to AI clients via an MCP server.

Python 3.11+. ffmpeg ships bundled via `imageio-ffmpeg` — never assume PATH-installed ffmpeg.

## Commands

```powershell
# Setup
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run the GUI
.\.venv\Scripts\python.exe main.py

# Run the MCP server (stdio transport; for Claude Desktop / Claude Code)
.\.venv\Scripts\python.exe -m mcp_server

# Build a single-file Trailbox.exe (~120 MB) into dist/
.\.venv\Scripts\python.exe build.py

# Hub maintenance — reset a user's password without going through the web UI.
# Runs against the local hub.db; works even when the Hub server is down.
.\dist\Trailbox-hub.exe reset-password -u <username>
```

There is currently no test suite. Verification is via the GUI or by running a session and inspecting `output/{session_id}/`.

If you spawn the GUI to test, prefer `run_in_background=true` — it's a blocking event loop. Confirm it came up with `Get-Process python | Where-Object { $_.MainWindowTitle -like "*Trailbox*" }`.

## Releasing (keep `__version__`, tag, and binaries in lockstep)

`main.py.__version__` is the source of truth for the running app — `session_info.system.trailbox_version` in `session_meta.json` (via `core/system_info.py`) and the viewer header overlay both read from it. If it lags behind the latest git tag, every session recorded with that build reports the wrong version in its own meta. This has already happened once (the v0.1.7→v0.2.3 drift) — don't let it recur.

There are TWO version strings that must move together:

- `main.py.__version__` — baked into the .exe by PyInstaller; surfaces in `session_meta.json` (via `core/system_info.py`) and the viewer header.
- `MyAppVersion` in `installer/Trailbox-installer.iss` — surfaces in the Windows installer banner and "Programs & Features" entry.

Release flow, in this order:

1. Bump BOTH `__version__` in `main.py` and `MyAppVersion` in `installer/Trailbox-installer.iss` to the target version (`"0.2.5"`, no `v` prefix).
2. Commit the bumps.
3. `git tag vX.Y.Z` on that commit, push commit + tag together.
4. `build.py` to produce `dist/Trailbox{,-mcp,-hub,-Setup}.exe` — **must run after step 1** so the bundled `main.py` carries the new version AND the installer banner shows the new version. Build artifacts created before the bump will report the old version forever.
5. `gh release create vX.Y.Z` attaching the binaries — see the note below about GUI packaging.

If you find `__version__` already lagging the latest tag, fix forward (bump + new release) rather than retroactively moving the existing tag — published .exe SHA-sums shouldn't change under a fixed tag name.

GUI is `--onedir` (since the startup-perf pass): `build.py` produces `dist/Trailbox/Trailbox.exe + _internal/` instead of a single `dist/Trailbox.exe`. The Inno Setup installer absorbs that automatically (it now copies `dist\Trailbox\*` with `recursesubdirs`). For GitHub Releases, ship the installer (`Trailbox-Setup.exe`) as the user-facing GUI artifact; if you also want a raw GUI bundle attached, zip `dist/Trailbox/` first (`Compress-Archive dist\Trailbox Trailbox-vX.Y.Z.zip`) — uploading the loose .exe alone won't work because it needs `_internal/` next to it. `Trailbox-mcp.exe` and `Trailbox-hub.exe` stay `--onefile` and can still be attached directly.

Hub-specific release notes:

- When the release touches `hub_server/db.py`, bump `_LATEST_VERSION` and add a new branch to `migrate()`. Existing `hub.db` files in the wild auto-upgrade on next boot.
- Existing deployments may still be running the legacy `TRAILBOX_HUB_TOKEN` shared-token model — they keep working as the first admin's service-token after upgrade, so don't remove that compat path without a deprecation cycle.
- The installer's «Hub 관리자 계정» page writes `hub.env` next to the .exe; `hub_entry.py` consumes + deletes it on first boot. If you ever change the env-var contract for first-admin bootstrap, update both `installer/Trailbox-installer.iss` and `hub_entry.py:_consume_hub_env`.

## Architecture: the single rule that holds everything together

**Every recorder is keyed off a single `t0_perf` captured by `TrailboxWindow._on_start_requested` and is identified to downstream tools by `t_video_s = perf_counter() - t0_perf`.**

That field is written into every JSONL line from every recorder. It's how the viewer overlays input/log/metric events on the video, and how the MCP server answers cross-source time queries. If you add a new recorder, it MUST accept `t0_perf` and emit `t_video_s` in the same shape — anything else breaks the contract.

## Session lifecycle (main.py orchestrates everything)

`TrailboxWindow._on_start_requested` resolves the capture target, creates a `Session`, captures `t0_perf`, and starts each recorder in this order:

1. **ScreenRecorder** writes to `screen.video.mp4` (intermediate, no audio yet)
2. **AudioRecorder** writes to `screen.audio.wav` (intermediate, optional)
3. **LogCollector** snapshots EOF of each watched log file, then tails appends → `logs/logs.jsonl` + `logs/logs.vtt`
4. **InputRecorder** spins up pynput listeners → `inputs/inputs.jsonl` + `inputs/inputs.vtt`
5. **MetricsRecorder** samples target PID at 1 Hz → `metrics/process.jsonl`

`_on_stop_requested` reverses this, then runs `post_mux.mux_av()` to combine `screen.video.mp4 + screen.audio.wav → screen.mp4` (deletes the intermediates on success), then `session.finalize()` writes `session_meta.json`, then `viewer_generator.generate_viewer()` produces `viewer.html`. Every step is best-effort: failure of one recorder doesn't abort the others, and errors are surfaced into the meta as `*_error` fields.

## Screen recording: two backends, one ffmpeg pipe

`core/screen_recorder.py` dispatches on the `CaptureTarget` discriminated union:

- `MonitorTarget(index)` → dxcam (DXGI Desktop Duplication). Pull model: `camera.grab()` returns None when nothing changed.
- `WindowTarget(hwnd, title)` → windows-capture (Windows Graphics Capture). Push model: frames arrive via WGC callback. The recorder caches the latest frame bytes under a lock and waits on a `new_frame_event` in the writer loop.

Both paths feed the same ffmpeg subprocess. **Critical**: ffmpeg is spawned with `-use_wallclock_as_timestamps 1` + `-fps_mode passthrough`. We write to ffmpeg's stdin **only when a new frame is available** (subject to `max_fps` rate cap). Do not reintroduce a fixed-cadence ticker — the prior version did, and the resulting duplicate-frame judder was the bug that drove the VFR redesign.

## COM threading order (per-thread now; was per-module before v0.8.x startup work)

Historically `core.screen_recorder` (dxcam → comtypes) HAD TO import before `core.audio_recorder` (soundcard) at main-thread module level, because the second one to load would crash with `OSError [WinError -2147417850] "스레드 모드가 설정된 후에는 바꿀 수 없습니다"`.

That constraint has been resolved structurally: `dxcam`, `windows_capture`, `soundcard`, and `pynput` are no longer imported at module scope. Each recorder imports its heavy dep **inside its own background thread** (`ScreenRecorder._run_monitor`, `ScreenRecorder._run_window`, `AudioRecorder._run`, `InputRecorder.start`). Per-thread COM apartments stay independent, so the cross-mode collision can't happen.

This was worth ~1.2 s off cold-start app launch (dxcam alone was 900 ms+). If you reintroduce module-level imports of any of those four libraries you'll both bring back the startup cost AND resurrect the COM-mode collision — keep them inside their consumer methods.

## Bidirectional auto-detection (window ↔ log dir)

`core/process_detector.py` provides both directions, both via async `QThread` workers in `ui/launcher_panel.py` so the UI never blocks:

- **Log dir → matching window**: `find_pids_for_log_dir` uses an install-dir heuristic (exe_dir and log_dir share an ancestor within `_HEURISTIC_MAX_COMBINED=4`, drive roots excluded as too loose), then verifies via `open_files()` on those PIDs. Open-files-as-primary doesn't work on Windows for most processes — the heuristic is the workhorse.
- **Window → log dir**: `find_log_dir_for_pid` walks parent processes (up to `_PARENT_WALK_DEPTH=2` skipping System32) so games launched via Ubisoft Connect / Steam / EGS resolve to the launcher's log folder, not the (often empty) game install dir.

When wiring these signals: `currentIndexChanged` fires for `setCurrentIndex` calls AND for programmatic addItem mutations during `clear() + addItem()`. The combo is refreshed often (clicks, hotkeys, picker), so `refresh_window_list` uses `blockSignals(True/False)`. If you add another auto-fill, follow the same pattern or you'll get the wrong-window-during-refresh bug back.

## Viewer: self-contained, file:// safe

`viewer.html` is generated once at session end and references `screen.mp4` / `logs.vtt` / `inputs.vtt` as relative paths (file:// is fine for `<video>` and `<track>` elements). All JSONL events and metrics are **inlined** as `<script type="application/json">` — fetch() to local files is blocked under file:// in Chromium, so don't try to load jsonl at runtime.

The template uses `__SESSION_ID__` / `__EVENTS_JSON__` / `__META_JSON__` / `__METRICS_JSON__` / `__TRACKS_HTML__` token replacement (not `.format()`) because the embedded JS/CSS has many `{}` characters. Don't switch to format strings.

## MCP server

`mcp_server/__main__.py` is a FastMCP stdio server exposing 8 read-only tools. Architecture:

- `mcp_server/filters.py` — shared filtering/aggregation (time range, kind matching, text search, metrics summary, frame stats). Both backends delegate here instead of duplicating logic.
- `mcp_server/errors.py` — structured error types (`SessionNotFound`, `FileNotAvailable`, `HubUnavailable`). Tools return `{"error": "...", "code": "..."}` instead of raising raw exceptions.
- `mcp_server/backends/local.py` — reads `$TRAILBOX_OUTPUT/{session_id}/` from the local filesystem.
- `mcp_server/backends/hub.py` — reads from a remote Hub via HTTP API.
- `mcp_server/backends/hybrid.py` — local-first + Hub fallback. Activated automatically when both `TRAILBOX_HUB_URL` and a local output directory exist.

Backend selection (`__main__.py:_pick_backend`):
- `TRAILBOX_HUB_URL` set + local output dir exists → `HybridBackend` (local-first, Hub fallback for sessions not found locally; `list_sessions` merges both, deduplicates by session_id)
- `TRAILBOX_HUB_URL` set, no local output → `HubBackend` (HTTP-only)
- No env var → `LocalBackend` (filesystem-only)

Tools: `list_sessions`, `get_session`, `query_events`, `get_metrics`, `search_logs`, `get_frame_at`, `get_viewer_path`, `get_frame_stats`. The last one reads `metrics/frames.jsonl` for FPS/jitter/stutter analysis. `get_metrics` summary includes GPU (gpu_max/avg, vram_max_mb) and thread/handle counts alongside CPU/RSS.

Capture control via MCP (start/stop a session from an AI) is deliberately not implemented. Adding it requires either a headless recording mode or IPC to a running Trailbox — both are nontrivial.

## Hub: auth + DB (v0.5.0+)

`hub_server/` is a separate FastAPI app that hosts uploaded sessions, exposes them to the MCP server, and serves a small Jinja2 web UI. As of v0.8.0 it carries its own SQLite metadata layer at `{data_root}/hub.db` — accounts, per-user API tokens, web sessions, session ownership, and an append-only audit log.

The session payload on disk (mp4/jsonl/meta) is **untouched** by all of this — the contract in "Output convention" still holds. Ownership is a server-side mapping (`session_owners` table), not a field in `session_meta.json`, so the meta stays portable.

Auth dependencies (`hub_server/auth.py`):

- `require_user` / `require_admin` — resolve the caller via cookie session → per-user API token (`X-Trailbox-Token`) → legacy service token (`TRAILBOX_HUB_TOKEN`, maps to first admin for back-compat).
- `require_user_active` / `require_admin_active` — same as above plus a `must_change_password` gate. Use these by default; the relaxed variants exist only for `/api/auth/me` and `/api/auth/password` so a force-reset user can still self-recover.

DB schema lives in `hub_server/db.py` with a `user_version`-based migration ladder (v1 created all tables, v2 added `must_change_password`). The migration helper is idempotent — second boot on the same DB is a no-op. **Add new schema versions by appending to the `if version < N` ladder, never by editing prior steps.**

Web UI templates are at `hub_server/templates/` and bundled into `Trailbox-hub.exe` via `--add-data` in `build.py`. Both `hub_server/app.py` and `hub_server/routes/web.py` resolve their directories via a `_MEIPASS` fallback so the same code works in source and frozen.

CLI: `Trailbox-hub.exe reset-password` (see Commands) is the escape hatch when a single-admin install loses its password. The web UI's «reset password» button on `/admin/users` handles the multi-admin case but explicitly refuses to act on the caller (self-reset must go through `/account/password`).

## CPU% normalization

`MetricsRecorder` writes both `cpu_pct` (0-100, normalized by `psutil.cpu_count(logical=True)`) and `cpu_pct_per_core` (raw psutil value, can exceed 100 on multi-threaded workloads). This was a deliberate fix — psutil's `Process.cpu_percent()` returns per-core percentage by convention (matches Unix `top`), but users expect 0-100. If you touch metric serialization, preserve both fields. The session meta also carries `cpu_cores` so older sessions remain interpretable.

## Output convention (don't break this)

```
output/{session_id}/        # session_id = "{safe_app_name}_{YYYYMMDD_HHMMSS}"
├── screen.mp4              # video+audio after post-mux (intermediates deleted)
├── logs/{logs.jsonl, logs.vtt, raw/*}
├── inputs/{inputs.jsonl, inputs.vtt}
├── metrics/{process.jsonl, frames.jsonl}
├── viewer.html
└── session_meta.json       # carries `system` snapshot + `frame_stats`
```

The MCP server, viewer generator, and `_smoketest_*` scripts all assume this layout. JSONL lines across recorders share `@timestamp` (UTC ISO), `t_video_s`, and `ecs.version` fields — keep that schema stable, callers index on it.

## GPU monitoring via PDH (counter quirks that will bite you)

`core/gpu_monitor.py` uses `win32pdh` against `\GPU Engine(*)\Utilization Percentage` and `\GPU Process Memory(*)\Dedicated Usage`. Two things to remember:

1. **Delta counter first-sample rule** — PDH utilization counters are computed from a delta between consecutive `CollectQueryData` calls. The very first read after `AddCounter` always returns 0 (no prior sample). We call `CollectQueryData` once at the end of `start()` to prime; the first real `sample()` read returns valid data only on the *second* `CollectQueryData`. Don't move the priming call.
2. **`PDH_CALC_NEGATIVE_DENOMINATOR`** — for an engine with zero activity over the sample window, `GetFormattedCounterValue` can raise. We catch and skip (engine treated as absent). That's why `gpu_engines` filters out near-zero values — they're not zero readings, they're absent readings.

`gpu_pct` is the MAX engine percentage (Task Manager convention), not the sum. Summing would exceed 100 routinely since engines run in parallel on different GPU blocks. If you change this, also update the viewer's `gpuMax = Math.max(100, ...)` floor logic.

## Tauri desktop app (desktop-tauri/)

`desktop-tauri/` is a Tauri 2 + React frontend that wraps the Python recording stack. It communicates with Python via two bridge subprocesses:

- `bridge.py` — one-shot commands (enumerate windows, Hub API calls, sync queue, download). Tauri spawns it, reads JSON stdout, exits.
- `bridge_record.py` — long-running recording daemon. Tauri holds its stdin/stdout open; sends `{"cmd":"start",...}` / `{"cmd":"stop"}` via stdin, reads `{"event":"status",...}` at 1 Hz via stdout.

Key flows:
- **Auto-upload**: after recording stops, if enabled, `hub_upload` is called immediately. `.uploaded` marker is written on success.
- **Background sync queue**: on app start, `hub_sync_queue` scans for sessions without `.uploaded` marker and uploads them all. Then `cleanup_synced_sessions` runs per the user's cleanup policy.
- **On-demand download**: `hub_download` fetches a Hub-only session zip, extracts to `output/`, writes `.uploaded` marker.
- **Hub viewer**: cloud/synced sessions can open the Hub viewer URL (`/sessions/{id}/v/`) in the default browser.
- **Real-time GPU metrics**: `bridge_record.py` starts a `GpuMonitor` alongside the recording loop and emits `gpu_pct` + `gpu_vram_mb` in status events.

Build: `npm run tauri:build` in `desktop-tauri/`. Produces `trailbox-desktop.exe` (Rust/Tauri, ~9 MB) + `trailbox-bridge.exe` (PyInstaller, ~126 MB). The Inno Setup installer bundles both as `Trailbox.exe` (renamed from trailbox-desktop.exe).

## Known constraint footprint

- DRM-protected video (Netflix) is OS-blanked on capture; audio is not. This is enforced and unavoidable.
- Anti-cheat may block process telemetry on a small number of titles (psutil's perf-counter path is more permissive than handle enumeration, so it usually works).
- Fullscreen Exclusive games may fail WGC; Borderless mode is the documented workaround.
- AC/Anvil and Frostbite engines write no disk logs in retail — `parent process walk` in the log-dir detector is what lets those sessions still pick up something useful (launcher logs).
