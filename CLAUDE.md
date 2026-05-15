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
```

There is currently no test suite. Verification is via the GUI or by running a session and inspecting `output/{session_id}/`.

If you spawn the GUI to test, prefer `run_in_background=true` — it's a blocking event loop. Confirm it came up with `Get-Process python | Where-Object { $_.MainWindowTitle -like "*Trailbox*" }`.

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

## MCP server

`mcp_server/__main__.py` is a FastMCP stdio server exposing 6 read-only tools that operate against the same `output/{session_id}/` tree. Tools are intentionally simple readers — they don't decode the video or anything heavy. The output root resolves via the `TRAILBOX_OUTPUT` env var, falling back to `../output` relative to the module.

Capture control via MCP (start/stop a session from an AI) is deliberately NOT in v0.1.0. Adding it requires either a headless recording mode or IPC to a running Trailbox — both are nontrivial.

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

## CPU% normalization

## Known constraint footprint

- DRM-protected video (Netflix) is OS-blanked on capture; audio is not. This is enforced and unavoidable.
- Anti-cheat may block process telemetry on a small number of titles (psutil's perf-counter path is more permissive than handle enumeration, so it usually works).
- Fullscreen Exclusive games may fail WGC; Borderless mode is the documented workaround.
- AC/Anvil and Frostbite engines write no disk logs in retail — `parent process walk` in the log-dir detector is what lets those sessions still pick up something useful (launcher logs).
