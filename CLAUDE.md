# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Trailbox is a Windows-only PyQt6 desktop app that captures a synchronized QA recording (screen + system audio + game logs + keyboard/mouse input + process telemetry) into `output/{session_id}/`, generates a self-contained `viewer.html` for playback, and exposes the captured data to AI clients via an MCP server. Sessions can optionally be pushed to a self-hosted **Trailbox Hub** (FastAPI server) for team sharing and remote MCP access.

Python 3.11+. ffmpeg ships bundled via `imageio-ffmpeg` — never assume PATH-installed ffmpeg. adb/scrcpy ship bundled too (via `--add-binary` from `tools/android/`) — same rule, never assume PATH.

## Repository layout

```
main.py / mcp_entry.py / hub_entry.py    # 3 PyInstaller entry points
ui/                                       # PyQt6 panels + Hub/session dialogs
core/                                     # capture + plumbing (one module per concern)
mcp_server/                               # FastMCP stdio server + 2 backends (local | hub)
hub_server/                               # FastAPI server (uploads / shares / retention)
installer/Trailbox-installer.iss          # Inno Setup wizard (3 binaries → 1 Setup.exe)
build.py                                  # one-shot PyInstaller + Inno orchestration
tools/android/{platform-tools,scrcpy}/    # gitignored; bundled into builds if present
```

## Commands

```powershell
# Setup
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run the GUI
.\.venv\Scripts\python.exe main.py

# Run the MCP server (stdio transport; for Claude Desktop / Claude Code)
.\.venv\Scripts\python.exe -m mcp_server
# Same module is also reachable via `main.py --mcp-server` — early-dispatches
# before any Qt/dxcam import so a single .exe could in principle serve both.

# Run the Hub server (FastAPI / uvicorn)
$env:TRAILBOX_HUB_TOKEN = "<token>"
.\.venv\Scripts\python.exe -m hub_server

# Build all release binaries (~125 MB GUI, ~43 MB MCP, ~43 MB Hub) + installer if Inno Setup is present
.\.venv\Scripts\python.exe build.py
```

There is currently no test suite. Verification is via the GUI or by running a session and inspecting `output/{session_id}/`.

If you spawn the GUI to test, prefer `run_in_background=true` — it's a blocking event loop. Confirm it came up with `Get-Process python | Where-Object { $_.MainWindowTitle -like "*Trailbox*" }`.

## Releasing (keep `__version__`, tag, installer version, and binaries in lockstep)

`main.py.__version__` is the source of truth for the running app — `session_info.system.trailbox_version` in `session_meta.json` (via `core/system_info.py`) and the viewer header overlay both read from it. If it lags behind the latest git tag, every session recorded with that build reports the wrong version in its own meta. This already happened once (the v0.1.7→v0.2.3 drift) — don't let it recur.

There are TWO version strings that must move together:

- `main.py.__version__` — baked into all three .exes by PyInstaller; surfaces in `session_meta.json` (via `core/system_info.py`) and the viewer header.
- `MyAppVersion` in `installer/Trailbox-installer.iss` — surfaces in the Windows installer banner and "Programs & Features" entry.

Release flow, in this order:

1. Bump BOTH `__version__` in `main.py` and `MyAppVersion` in `installer/Trailbox-installer.iss` to the target version (`"0.2.5"`, no `v` prefix).
2. Commit the bumps.
3. `git tag vX.Y.Z` on that commit, push commit + tag together.
4. `build.py` to produce `dist/Trailbox{,-mcp,-hub,-Setup}.exe` — **must run after step 1** so the bundled `main.py` carries the new version AND the installer banner shows the new version. Build artifacts created before the bump will report the old version forever.
5. `gh release create vX.Y.Z` attaching all 4 binaries.

If you find `__version__` already lagging the latest tag, fix forward (bump + new release) rather than retroactively moving the existing tag — published .exe SHA-sums shouldn't change under a fixed tag name.

## Architecture: the single rule that holds everything together

**Every recorder is keyed off a single `t0_perf` captured by `TrailboxWindow._on_start_requested` and is identified to downstream tools by `t_video_s = perf_counter() - t0_perf`.**

That field is written into every JSONL line from every recorder. It's how the viewer overlays input/log/metric events on the video, and how the MCP server answers cross-source time queries. If you add a new recorder, it MUST accept `t0_perf` and emit `t_video_s` in the same shape — anything else breaks the contract.

## Session lifecycle (main.py orchestrates everything)

`TrailboxWindow._on_start_requested` branches on capture target: **Android** (scrcpy) takes a short path that only starts a `ScreenRecorder`; **desktop** (monitor/window) goes through the full recorder chain. In both cases it creates a `Session`, captures `t0_perf` right before starting the screen recorder, and the recorders launch in this order:

1. **ScreenRecorder** — writes to `screen.video.mp4` for dxcam/WGC (intermediate, no audio yet), or directly to `screen.mp4` for scrcpy (which already remuxes a combined container).
2. **AudioRecorder** — `screen.audio.wav` (intermediate, optional, desktop only).
3. **LogCollector** — snapshots EOF of each watched log file, then tails appends → `logs/logs.jsonl` + `logs/logs.vtt` (desktop only).
4. **InputRecorder** — pynput listeners → `inputs/inputs.jsonl` + `inputs/inputs.vtt` (desktop only).
5. **MetricsRecorder** — samples target PID at 1 Hz → `metrics/process.jsonl` (desktop only; Android phase 1 has no on-device metrics).

`_on_stop_requested` reverses this, runs `post_mux.mux_av()` to combine `screen.video.mp4 + screen.audio.wav → screen.mp4` (deletes the intermediates on success; **skipped naturally on the Android path because `screen.video.mp4` never exists there**), then `session.finalize()` writes `session_meta.json`, then `viewer_generator.generate_viewer()` produces `viewer.html`. Every step is best-effort: failure of one recorder doesn't abort the others, and errors are surfaced into the meta as `*_error` fields. Finally, if the **"auto-upload"** toggle is on, `ui.hub_dialogs.auto_upload_session` pushes the finished session to the configured Hub.

## Screen recording: three backends, one ffmpeg pipe

`core/screen_recorder.py` dispatches on the `CaptureTarget` discriminated union:

- `MonitorTarget(index)` → **dxcam** (DXGI Desktop Duplication). Pull model: `camera.grab()` returns None when nothing changed.
- `WindowTarget(hwnd, title)` → **windows-capture** (Windows Graphics Capture). Push model: frames arrive via WGC callback. The recorder caches the latest frame bytes under a lock and waits on a `new_frame_event` in the writer loop.
- `AndroidDeviceTarget(serial, package, capture_audio)` → **scrcpy** subprocess. scrcpy emits a complete MKV bytestream on stdout (encoded on the device); we pipe that into a second ffmpeg subprocess with `-c copy` to remux to mp4 without re-encoding. Two processes must be torn down in order: **scrcpy first → ffmpeg sees EOF → MP4 finalizes cleanly**.

For dxcam/WGC, both paths feed the same ffmpeg subprocess. **Critical**: that ffmpeg is spawned with `-use_wallclock_as_timestamps 1` + `-fps_mode passthrough`. We write to ffmpeg's stdin **only when a new frame is available** (subject to `max_fps` rate cap). Do not reintroduce a fixed-cadence ticker — the prior version did, and the resulting duplicate-frame judder was the bug that drove the VFR redesign. For scrcpy, `max_fps` is passed through as `--max-fps`.

### Android audio gating (Android 11 / SDK 30+)

`main.py._on_start_requested` probes `adb.get_android_sdk(serial)` before constructing the final `AndroidDeviceTarget` and sets `capture_audio=False` when SDK < 30 (scrcpy's `--audio-source=output` requires Android 11). The session_id stem for Android is `android_<serial>_<package>` via `Session(app_name=...)`; `Session._safe_app_name` strips anything outside `[A-Za-z0-9_.-]`.

## COM threading order (import-order bug, will resurface if you reorder)

In `main.py`, `core.screen_recorder` (which imports dxcam → comtypes) MUST import before `core.audio_recorder` (which imports soundcard). soundcard initializes COM with a different threading mode; if it goes first, comtypes' init raises `OSError [WinError -2147417850] "스레드 모드가 설정된 후에는 바꿀 수 없습니다"`. The current import order in `main.py` is deliberate — there's a comment guarding it. Don't sort imports here blindly.

## Bidirectional auto-detection (window ↔ log dir)

`core/process_detector.py` provides both directions, both via async `QThread` workers in `ui/launcher_panel.py` so the UI never blocks:

- **Log dir → matching window**: `find_pids_for_log_dir` uses an install-dir heuristic (exe_dir and log_dir share an ancestor within `_HEURISTIC_MAX_COMBINED=4`, drive roots excluded as too loose), then verifies via `open_files()` on those PIDs. Open-files-as-primary doesn't work on Windows for most processes — the heuristic is the workhorse.
- **Window → log dir**: `find_log_dir_for_pid` walks parent processes (up to `_PARENT_WALK_DEPTH=2` skipping System32) so games launched via Ubisoft Connect / Steam / EGS resolve to the launcher's log folder, not the (often empty) game install dir.

When wiring these signals: `currentIndexChanged` fires for `setCurrentIndex` calls AND for programmatic addItem mutations during `clear() + addItem()`. The combo is refreshed often (clicks, hotkeys, picker), so `refresh_window_list` uses `blockSignals(True/False)`. If you add another auto-fill, follow the same pattern or you'll get the wrong-window-during-refresh bug back.

## Viewer: self-contained, file:// safe

`viewer.html` is generated once at session end and references `screen.mp4` / `logs.vtt` / `inputs.vtt` as relative paths (file:// is fine for `<video>` and `<track>` elements). All JSONL events and metrics are **inlined** as `<script type="application/json">` — fetch() to local files is blocked under file:// in Chromium, so don't try to load jsonl at runtime.

The template uses `__SESSION_ID__` / `__EVENTS_JSON__` / `__META_JSON__` / `__METRICS_JSON__` / `__TRACKS_HTML__` token replacement (not `.format()`) because the embedded JS/CSS has many `{}` characters. Don't switch to format strings.

## MCP server (two backends, one stdio surface)

`mcp_server/__main__.py` is a FastMCP stdio server exposing **7 read-only tools**: `list_sessions`, `get_session`, `query_events`, `get_metrics`, `search_logs`, `get_frame_at`, `get_viewer_path`. They operate against a backend chosen at startup:

- **LocalBackend** (`mcp_server/backends/local.py`) — reads `$TRAILBOX_OUTPUT/{session_id}/` directly. Default: `../output` relative to the module in source, or `<exe_dir>/output` when frozen.
- **HubBackend** (`mcp_server/backends/hub.py`) — kicks in iff `TRAILBOX_HUB_URL` is set; uses `TRAILBOX_HUB_TOKEN` for the API token. The Hub serves `/api/sessions/.../files/...` for jsonl/meta reads and `/api/sessions/.../frame?t=` for server-side ffmpeg frame extraction (so the MCP client never has to download the whole mp4).

Frame extraction logic is shared between both backends and the Hub server via `core/frame_extractor.py.extract_frame_jpeg` — auto-tunes resolution + quality to stay under Claude's ~1 MB image input cap.

Capture control via MCP (start/stop a session from an AI) is deliberately NOT in scope. Adding it requires either a headless recording mode or IPC to a running Trailbox — both are nontrivial.

## Trailbox Hub (FastAPI server)

`hub_server/` is a standalone FastAPI app shipped as `Trailbox-hub.exe` (PyInstaller) or via the `Dockerfile.hub` image. **Token-only auth** (`X-Trailbox-Token` header) for the `/api/*` surface; share routes `/v/{token}/*` use the URL token as auth and serve `viewer.html` + associated mp4/jsonl files directly with `FileResponse` (which honors Range, so mp4 seeking works in the browser).

Key invariants in the Hub:

- `hub_server/storage.py` mirrors the local `output/{session_id}/` layout 1:1 under `{data_root}/{session_id}/`. Uploads are zips whose entries are paths relative to the session dir (or wrapped in a single top-level dir — `_detect_common_prefix` flattens). Always validate `session_id` with `is_valid_session_id` (regex enforced, leading `_`/`.` reserved for hub-internal dirs like `_uploads`, `_tokens.json`).
- **Resumable chunked uploads** at `/api/uploads/*` (`hub_server/uploads.py`). `core/hub_client.py` auto-picks single-shot POST for <64 MB and chunked PUT for ≥64 MB, with retry + offset-drift recovery on 409. The threshold lives at `HubClient.CHUNKED_UPLOAD_THRESHOLD` / `CHUNK_SIZE`.
- **Path traversal defense** — every `/v/{token}/{path}` and `/api/sessions/{id}/files/{path}` request resolves the target and `.relative_to(session_dir)` before returning. Don't bypass this.
- **Retention sweep** — if `TRAILBOX_HUB_RETENTION_DAYS > 0`, a background thread runs `retention.sweep_once` hourly. `hub_server/retention.py` is the single source of truth for "expired"; `_is_expired` also clears associated share tokens.
- **Config is env-vars-only** (`hub_server/config.py`): `TRAILBOX_HUB_DATA`, `TRAILBOX_HUB_TOKEN`, `TRAILBOX_HUB_HOST`, `TRAILBOX_HUB_PORT`, `TRAILBOX_HUB_MAX_UPLOAD_MB`, `TRAILBOX_HUB_RETENTION_DAYS`. No config file. Empty token = auth disabled (LAN-dev only).

The GUI side talks to the Hub through `core/hub_client.py` (sync httpx, driven from QThread workers). Persisted URL/token are in QSettings via `core/hub_config.py`. UI surfaces: `ui/hub_dialogs.py` (config + upload progress + share link modals) and `ui/remote_session_picker.py` (remote session list + download).

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

This same layout is mirrored under `{TRAILBOX_HUB_DATA}/{session_id}/` on the Hub. The MCP server (both backends), viewer generator, hub storage, regen scripts, and the installer's "Programs & Features" uninstall hooks all assume this layout. JSONL lines across recorders share `@timestamp` (UTC ISO), `t_video_s`, and `ecs.version` fields — keep that schema stable, callers index on it.

When resolving the output root in code, **frozen vs source matters**: `main.py._output_root()` and `mcp_server.backends.local._output_root()` both fall back to `Path(sys.executable).parent / "output"` when `sys.frozen` is True, because `__file__` lives inside the wiped-on-exit `_MEIPASS` temp dir. Don't replace those with naive `Path(__file__).parent` — sessions would land in tempdirs and disappear.

## GPU monitoring via PDH (counter quirks that will bite you)

`core/gpu_monitor.py` uses `win32pdh` against `\GPU Engine(*)\Utilization Percentage` and `\GPU Process Memory(*)\Dedicated Usage`. Two things to remember:

1. **Delta counter first-sample rule** — PDH utilization counters are computed from a delta between consecutive `CollectQueryData` calls. The very first read after `AddCounter` always returns 0 (no prior sample). We call `CollectQueryData` once at the end of `start()` to prime; the first real `sample()` read returns valid data only on the *second* `CollectQueryData`. Don't move the priming call.
2. **`PDH_CALC_NEGATIVE_DENOMINATOR`** — for an engine with zero activity over the sample window, `GetFormattedCounterValue` can raise. We catch and skip (engine treated as absent). That's why `gpu_engines` filters out near-zero values — they're not zero readings, they're absent readings.

`gpu_pct` is the MAX engine percentage (Task Manager convention), not the sum. Summing would exceed 100 routinely since engines run in parallel on different GPU blocks. If you change this, also update the viewer's `gpuMax = Math.max(100, ...)` floor logic.

## Bundled binaries (ffmpeg + adb + scrcpy)

The build produces three binaries that each need different bundles:

- **All three** carry ffmpeg (via `--add-binary` against `imageio_ffmpeg.get_ffmpeg_exe()`). The MCP and Hub builds need it for `get_frame_at` / `/api/sessions/{id}/frame` — server-side frame extraction.
- **Only `Trailbox.exe`** carries adb + scrcpy. `build.py._android_binary_flags()` looks for `tools/android/platform-tools/` and `tools/android/scrcpy/` and flattens their files into `_MEIPASS/bin/` via `--add-binary`. `core/adb.py.get_adb_path()` / `get_scrcpy_path()` resolve in this order: frozen-bundle `bin/` → repo `tools/android/{platform-tools,scrcpy}/` → PATH. If neither directory is populated at build time, the .exe still builds — the Android radio just fails at runtime with "adb.exe not found".

The two subtrees are gitignored. Drop them in from upstream zips before building if you want Android in the release.

## Known constraint footprint

- **DRM-protected video** (Netflix) is OS-blanked on capture; audio is not. Enforced and unavoidable.
- **Anti-cheat** may block process telemetry on a small number of titles (psutil's perf-counter path is more permissive than handle enumeration, so it usually works).
- **Fullscreen Exclusive** games may fail WGC; Borderless mode is the documented workaround.
- **AC/Anvil and Frostbite engines** write no disk logs in retail — the `parent process walk` in the log-dir detector is what lets those sessions still pick up something useful (launcher logs).
- **Android <11 (SDK <30)** can't do output audio capture — `main.py` falls back to `--no-audio` automatically and notes the reason in the status bar. The `AndroidDeviceTarget(capture_audio=...)` field reflects the gated decision, not the user's raw toggle.
