# Handoff: Trailbox Desktop UI (Tauri Port)

## Overview

This handoff bundles the **HTML/React design prototype** for porting the Trailbox desktop app from PyQt6 to a **Tauri + React** (or similar webview-based) frontend.

The current Trailbox client lives in `ui/launcher_panel.py`, `ui/recorder_panel.py`, `ui/session_picker.py`, `ui/remote_session_picker.py`, `ui/hub_dialogs.py`, and `ui/recording_overlay.py` — all PyQt6. This design replaces those panels with a single web frontend running inside a Tauri shell.

> **Hub web frontend is out of scope** — handled in a separate iteration. This handoff covers only the desktop client.

---

## About the Design Files

The HTML/JSX files in this bundle are **design references** created in this design-tool environment. They are NOT production code to copy directly.

The task is to **recreate these designs in a real Tauri + React project**, using:
- Tauri 1.5+ (or Tauri 2.0) as the shell
- React 18 + TypeScript (recommended) for the UI
- The existing Trailbox Python backend invoked via `tauri::command` IPC (subprocess for v1, native Rust ports later)
- A real component library only if needed — these designs are intentionally written with hand-rolled CSS/components so the visual system is fully visible

The prototype files use plain JSX + Babel-in-browser; you should re-author them as proper TSX modules with a bundler (Vite recommended) in the real project.

---

## Fidelity

**High-fidelity.** All colors, typography, spacing, layouts, and interactions are final. Recreate pixel-perfectly using the design tokens listed below. The mock data shapes match the real Python backend's JSON output (see `core/screen_recorder.py`, `core/window_picker.py`, `core/adb.py`, `core/hub_client.py`).

---

## Architecture Recommendation

```
trailbox/
├── src-tauri/                # Tauri Rust shell
│   ├── src/
│   │   ├── main.rs           # Tauri setup, window config
│   │   ├── commands.rs       # IPC commands → Python subprocess
│   │   └── overlay.rs        # Always-on-top recording widget (separate window)
│   └── tauri.conf.json
├── src/                      # React frontend
│   ├── main.tsx
│   ├── App.tsx
│   ├── theme/
│   │   ├── tokens.css        # Design tokens (extracted from hub styles.css)
│   │   └── desktop.css       # Desktop-specific styles
│   ├── components/
│   │   ├── Button.tsx, Badge.tsx, Card.tsx, Input.tsx, ...
│   │   └── Icon.tsx          # Inline SVG icon set
│   ├── chrome/
│   │   ├── CustomTitlebar.tsx
│   │   └── NativeTitlebar.tsx
│   ├── screens/
│   │   ├── CaptureScreen.tsx
│   │   ├── SessionsScreen.tsx
│   │   └── HubSettingsScreen.tsx
│   └── ipc/
│       ├── capture.ts        # invoke('start_recording', ...) etc.
│       ├── sessions.ts
│       └── hub.ts
├── recording-overlay/        # Separate Tauri window (transparent, always-on-top)
│   └── index.html
└── (existing Python code stays — invoked as subprocess for v1)
```

For the initial port, **keep the Python backend running as a subprocess** that Tauri spawns and talks to via stdin/stdout JSON-RPC. Migrate capture engines to Rust crates incrementally (e.g., `windows-capture-rs`, `cpal` for audio, `enigo` for input).

---

## Window Configuration

**Main window (`main`):**
- Default size: 1200×800
- Min size: 900×600
- Title: "Trailbox"
- Decorations: choose between native (`decorations: true`) and custom (`decorations: false`) — see Chrome Variants below
- Resizable: true

**Recording overlay (`overlay`):**
- Size: ~220×40 (sized to content)
- Position: top-right of primary monitor, 16px margin
- `decorations: false`
- `always_on_top: true`
- `transparent: true`
- `skip_taskbar: true`
- `focus: false` (don't steal focus)
- `accept_first_mouse: false` + `cursor_events: false` (Tauri 1.5+ — click-through)
- Toggle visibility via `overlay.show()` / `overlay.hide()` from main window

---

## Screens

### 1. Window Chrome — Two Variants

Both variants surround the same content (sidebar + main). Pick one based on platform conventions OR offer it as a user setting.

#### Variant A — Native Chrome
- Standard OS titlebar (32px Windows / 28px macOS) with native window controls
- Trailbox icon + "Trailbox" label in titlebar (drag area)
- App body below: 200px left sidebar + main content area
- Sidebar holds nav (Capture / Sessions / Hub) + user/hub status footer
- Best for: users who expect native OS behavior, screen readers, accessibility

#### Variant B — Custom Chrome (Recommended for cross-platform consistency)
- 44px tall custom titlebar with: brand mark + "Trailbox" + nav tabs + actions + window controls
- `data-tauri-drag-region` on titlebar background; explicit `style="-webkit-app-region: no-drag"` on tabs, buttons, controls
- No separate sidebar — nav tabs replace it
- Window controls are custom-drawn (use the SVG paths in the prototype) with hover states
- Close button: hover background = red (`oklch(0.55 0.22 25)`)
- Best for: modern Discord/Linear/Notion-like aesthetic

When recording, both variants show a pulsing red `REC mm:ss` pill in the titlebar/actions area.

### 2. Capture Screen (`/capture`)

Replaces: `ui/launcher_panel.py` + `ui/recorder_panel.py`

**Layout:** Two-column grid — main config area (flexible) + right sidebar (280px)

**Left column — config cards:**

1. **Card: 대상 애플리케이션 (Target Application)**
   - Row: 실행 파일 (exe path) — text input + "찾기" (file picker) + "앱 실행" button (primary, launches exe via Tauri)
   - Row: 로그 폴더 (log folder) — text input + "찾기" + "🔍 창 찾기" (find window writing to this dir)
   - Row: 추가 폴더 (extra log folders) — scrollable list (max-height 88px) + add/remove buttons
   - Row: "하위 폴더까지 스캔" checkbox + "확장자" text input (default `log, txt`)

2. **Card: 캡처 대상 (Capture Target)**
   - Segmented radio control (3 options): 전체 모니터 / 특정 창 (WGC) / Android 디바이스 (scrcpy)
   - **When "특정 창":** Window picker dropdown (populated from `enumerate_windows()`) + refresh + "🎯 창 클릭으로 선택" button + `Ctrl+Shift+P` hotkey hint
   - **When "Android":** Device dropdown (from `adb.list_devices()`) + refresh + connection status line + video backend selector (auto/scrcpy/screenrecord)
   - **When "모니터":** Static info about DXGI Desktop Duplication
   - Below: 2×2 grid of checkboxes — Max fps (with inline selector 10/15/24/30/60), System sound, Input recording, Process telemetry. Each has a `.tbd-check__desc` muted description.

**Right column — status panel:**

1. **Large record button** (92px tall, full width)
   - Idle: red dot + "녹화 시작" + "Ctrl+Alt+R"
   - Recording: red square + "녹화 중지" + live timer (`02:48`). Pulsing shadow animation.
   - Transitioning ("starting" or "stopping"): yellow spinning dot + "준비 중…" / "마무리 중…"
   - State machine: idle → starting (900ms) → recording → stopping (1200ms) → idle

2. **Card: Auto-upload toggle** — checkbox + description

3. **Card: 현재 세션 (Current Session)** — when recording, shows live metrics (session ID, elapsed, frame count, event count, CPU%, RAM GB) + 30-second CPU sparkline. When idle: placeholder message.

4. **Card: 마지막 세션 (Last Session)** — most recent session ID + relative time + duration + 뷰어/공유 buttons

### 3. Sessions Screen (`/sessions`)

Replaces: `ui/session_picker.py` + `ui/remote_session_picker.py`

**Layout:** Section header with source toggle + search/refresh; table below with sticky bottom action bar.

**Section header:**
- Title "세션"
- Segmented control: 로컬 · N | Hub · N (icons: PC monitor / link)
- Right side: search input (placeholder "session_id 검색…") + 새로고침

**Table:**
- Columns (local): icon | Session ID + relative time | EXE name (mono) | 길이 | 크기 | 프레임 | 이벤트 | shares badge
- Columns (Hub): icon | Session ID + started time | 소유자 (owner) | 길이 | 크기 | 시작 시각 (HH:MM) | 뷰어 ✓ | (empty)
- Grid template: `28px minmax(180px, 1.5fr) 1fr 80px 90px 90px 90px 70px`
- Row hover: `var(--surface-2)` background
- Selected row: `var(--accent-soft)` background + accent border-bottom-color
- Click row → select; double-click → open viewer

**Bottom action bar** (always visible, action set depends on source + selection):
- Local + selected: "Hub 업로드" (disabled if already uploaded), "공유 링크" (disabled if not uploaded), "삭제" (danger), "뷰어 열기" (primary)
- Remote + selected: "다운로드", "다운로드 + 뷰어 열기" (primary)
- Local: shows badges next to selected ID — `업로드됨` (success) or `로컬만` (warning)

**Upload progress popover** (bottom-right when uploading):
- 320px wide, fixed bottom-right with shadow
- Title row: download-icon + "Hub 업로드 중…" + "X / Y MB" (mono, right)
- Progress bar (6px tall, accent color)
- Session ID at bottom (mono, muted)

### 4. Hub Screen (`/hub`)

Replaces: `ui/hub_dialogs.py` (HubSettingsDialog)

**Layout:** Two-column — left tabs (flexible) + right info (280px)

**Left:**
- Card with tabs: 상태 / 로그인 / 회원가입 / 고급 (수동 토큰)
- "Hub URL" input is always visible above the tabs (shared across all)
- **상태 tab** (only enabled if configured): green ok banner + key-value table (Hub 버전, 클라이언트 버전, 토큰 라벨, 마지막 동기화, 청크 크기) + "브라우저에서 열기" link + "연결 해제" danger button
- **로그인 tab:** username + password fields + "로그인 + 토큰 발급" primary button. Status text below changes during async flow (로그인 중… → 토큰 발급 중… → ✓ 완료). Demo-mode info box at bottom.
- **회원가입 tab:** username + email + password + "회원가입 신청" + warning box about approval flow
- **고급 tab:** API Token password field + "연결 테스트" + "저장" + description

**Right (info panel):**
- Card "Hub로 할 수 있는 일" — 4 feature rows with accent-soft icon squares: 공유 링크, 자동 백업, AI 분석, 팀 협업
- Card "Hub 미설치?" — explanatory text

### 5. Recording Overlay (separate Tauri window)

Replaces: `ui/recording_overlay.py`

- Background: `oklch(0.1 0.01 270 / 0.82)` + `backdrop-filter: blur(12px)`
- Padding: 8px 14px
- Border-radius: 8px
- Shadow: `0 6px 20px oklch(0 0 0 / 0.4)`
- Content (flex row, gap 10px):
  - Pulsing red dot (10px, glow shadow, 1.4s ease-in-out pulse)
  - Time (Geist Mono, 14px, 600 weight, mm:ss or h:mm:ss)
  - Separator: 1px vertical line + 10px left padding
  - Hint: `<kbd>Ctrl+Alt+R</kbd> 정지` (small, muted)
- Window is transparent + always-on-top + cursor-events-passthrough

### 6. Session Viewer (separate HTML file: `viewer.html`)

This is the **existing self-contained HTML viewer** generated when a recording finishes. The bundled `Session Viewer.html` shows the redesigned version.

**Layout:** Top bar (48px) + main split (video left, side panel 420px right).

**Top bar:**
- Brand (mark + "Trailbox" + "Viewer" muted)
- Session ID pill (surface-2 background, mono, 13px)
- Stats row (6 mini-stats: Duration, Frames, Logs, Inputs, Δ p99, CPU cores) — each is value (mono, 12.5px, 600) + label (10px, uppercase, letter-spacing)
- Right: "zip", "공유 링크", theme toggle

**Video pane (left):**
- Stage: aspect-ratio 16:9 ish, fills available space, `oklch(0.05 0.01 270)` background
- Actual `<video>` element loads `screen.mp4` from the session folder (HTML5 native)
- Fake cursor overlay positioned by replaying `inputs/inputs.jsonl` mouse coordinates
- Controls bar (10px padding, dark `oklch(0.1 0.01 270)`):
  - Prev event / Play-pause / Next event (32px square buttons)
  - Time display (mono): `mm:ss.d / mm:ss.d`
  - Scrub bar (flex, 5px tall, rounded, accent fill, white circle handle 14px)
  - Event markers on scrub: red 2px lines for errors, yellow 2px lines for warnings (opacity 0.5)
  - Speed selector: 0.5× / 1× / 2× / 4× (active = surface-2 background)

**Side panel (right, 420px):**
- **Metrics block** (top, ~180px):
  - Header: `메트릭 · t=<current_time>` + `N samples`
  - 5 rows: CPU, GPU, RAM (GB), VRAM, FPS
  - Each row: 48px label + sparkline (28px tall) + 70px value (mono, with `<small>` unit)
  - Sparkline: full data path (1.3px stroke, 85% opacity) + vertical accent line at current t (50% opacity) + filled dot at current t
- **Events block** (rest of height):
  - Tabs: 이벤트 (all) / 로그만 / 입력만 (with counts)
  - Toolbar: search input (left icon) + filter pills (전체/log/in/warn/err with colored dots, active = accent-soft background)
  - List: mono-font 11.5px, each row has time pill (10.5px with colored dot prefix matching kind) + message (ellipsis on overflow)
  - Active row (closest event ≤ current t): accent-soft background; auto-scroll into view
  - Click row → seek to that t
- **Spec collapsible** at bottom (collapsed by default):
  - Click summary to expand
  - Body: 70px-1fr grid with OS / CPU / RAM / GPU / Display / EXE / Trailbox

**Keyboard shortcuts:** Space (play/pause), ← (prev event), → (next event)

---

## Interactions & Behavior

### Recording State Machine
```
idle ──(click 녹화 시작)──> starting (900ms)
                                │
                                ▼
recording ◄──(spawn capture engines + start RecordingOverlay window)
   │
   (click 녹화 중지)
   │
   ▼
stopping (1200ms) — show "마무리 중…" because ffmpeg mux is slow
   │
   ▼
idle (overlay hidden, last_session updated, optional auto-upload)
```

While recording, run a 1Hz timer in main window to:
- Update elapsed counter in REC pill + right-panel session info
- Append latest CPU/RAM sample to the 30-second sparkline buffer

### Window Picker
- "🔍 창 찾기" button: takes current log_dir, calls `find_pids_for_log_dir(path)` via IPC, then matches against `enumerate_windows()`, auto-selects the first match. Shows status in toast/statusbar.
- "🎯 창 클릭으로 선택": minimize main window, start global click listener (ClickPicker), on click pass the HWND back, restore main window.
- `Ctrl+Shift+P` global hotkey: same behavior without needing to click the button first.

### Hub Login Flow
1. User fills URL + username + password, clicks "로그인 + 토큰 발급"
2. Status: "로그인 중…" → POST /api/auth/login
3. If `must_change_password=true`: open password-change modal inline
4. Status: "토큰 발급 중…" → POST /api/auth/tokens with label `trailbox-<hostname>`
5. Save token to platform keychain (Tauri `tauri-plugin-store` or OS keychain)
6. Switch to 상태 tab, show ✓ ok banner

### Session Operations
- **Upload:** spawn worker, show progress popover, refresh row on completion. Use chunked upload for files >64MB (matches `hub_client.upload_session`).
- **Download:** same popover pattern, lands in `output/`, refreshes local list when done.
- **Share link:** opens system clipboard immediately; show success badge for 1.5s. If session isn't uploaded yet, prompt to upload first.
- **Delete:** confirm dialog, then DELETE on disk + remote.
- **Open viewer:** spawn OS default browser to file:// URL of `output/<session_id>/viewer.html`.

---

## Design Tokens

All colors use **OKLCH** for perceptual uniformity. Define as CSS custom properties on `:root` and `[data-theme="dark"]`.

### Light Mode
```css
--bg:        oklch(0.985 0.003 270);
--bg-2:      oklch(0.975 0.004 270);
--surface:   oklch(1 0 0);
--surface-2: oklch(0.975 0.004 270);
--surface-hover: oklch(0.965 0.005 270);

--border:        oklch(0.91 0.006 270);
--border-muted:  oklch(0.94 0.005 270);
--border-strong: oklch(0.85 0.01 270);

--fg:        oklch(0.22 0.018 275);
--fg-2:      oklch(0.38 0.015 275);
--muted:     oklch(0.55 0.014 275);
--subtle:    oklch(0.7 0.012 275);

--accent:        oklch(0.55 0.18 282);    /* indigo/purple — primary brand */
--accent-hover:  oklch(0.49 0.19 282);
--accent-soft:   oklch(0.96 0.035 282);
--accent-fg:     oklch(0.4 0.18 282);

--success:      oklch(0.55 0.14 150);
--success-soft: oklch(0.95 0.05 150);
--danger:       oklch(0.55 0.19 25);      /* recording red */
--danger-soft:  oklch(0.96 0.04 25);
--warning:      oklch(0.7 0.16 75);
--warning-soft: oklch(0.96 0.05 75);
--info:         oklch(0.6 0.13 240);
--info-soft:    oklch(0.95 0.04 240);
```

### Dark Mode
```css
--bg:        oklch(0.165 0.012 275);
--bg-2:      oklch(0.19 0.013 275);
--surface:   oklch(0.215 0.014 275);
--surface-2: oklch(0.245 0.014 275);
--surface-hover: oklch(0.27 0.015 275);

--border:        oklch(0.3 0.016 275);
--border-muted:  oklch(0.255 0.014 275);
--border-strong: oklch(0.38 0.018 275);

--fg:        oklch(0.96 0.006 275);
--fg-2:      oklch(0.86 0.008 275);
--muted:     oklch(0.66 0.012 275);
--subtle:    oklch(0.5 0.012 275);

--accent:        oklch(0.7 0.17 282);
--accent-soft:   oklch(0.3 0.08 282);
--accent-fg:     oklch(0.82 0.15 282);
```

### Typography
- **Sans:** Geist (Google Font, weights 400/500/600/700)
- **Mono:** Geist Mono (weights 400/500/600)
- **Base size:** 13px (desktop is denser than Hub's 14px)
- **Line-height:** 1.42
- **Font-feature-settings:** `'ss01', 'cv11'` on body for Geist's stylistic alternates
- **font-variant-numeric:** `tabular-nums` on all metric values for stable column alignment

### Spacing & Sizing
- **Radii:** `--r-sm: 4px`, `--r-md: 6px`, `--r-lg: 10px`, `--r-xl: 14px`, `--r-pill: 999px`
- **Buttons:** 26px (sm), 32px (default), 38px (lg) tall
- **Inputs:** 26px (compact form), 34px (auth/large)
- **Card padding:** 12px 14px (body), 9px 14px (header)
- **Sidebar:** 200px wide (vs Hub's 240px — desktop is denser)
- **Section header:** 14px 20px 10px padding
- **Main content padding:** 14px 20px 20px

### Shadows
```css
--shadow-sm:  0 1px 2px oklch(0.2 0.02 270 / 0.04);
--shadow-md:  0 4px 12px oklch(0.2 0.02 270 / 0.06), 0 1px 3px oklch(0.2 0.02 270 / 0.04);
--shadow-lg:  0 20px 40px oklch(0.2 0.02 270 / 0.08), 0 4px 12px oklch(0.2 0.02 270 / 0.05);
--shadow-pop: 0 8px 28px oklch(0.2 0.02 270 / 0.12);
```

Dark mode: replace all shadows with pure black at higher opacity (`0.3-0.45`).

---

## Component Patterns

### Buttons
- `.tbd-btn` baseline; modifiers: `--primary`, `--danger`, `--success`, `--ghost`, `--sm`, `--lg`, `--icon`
- Primary uses `--accent` background, white text, no border
- Danger and success: foreground color + 30%-mixed border color, hover paints with soft-color background
- Ghost: transparent border + background, hover gets surface-hover
- Icon-only: same height, square width

### Inputs
- `.tbd-input` baseline at 26px (compact) — 13px font, 8px horizontal padding, 5px radius
- Focus: accent border + 2px accent-soft ring (`box-shadow: 0 0 0 2px var(--accent-soft)`)
- Mono variant for paths/IDs/tokens — `font-family: Geist Mono`

### Cards
- `.tbd-card` — `var(--surface)` background, 1px border, 8px radius, overflow hidden
- `.tbd-card__head` — 9px 14px padding, bg-2 background, bottom border. h3 is uppercase 11.5px label.
- `.tbd-card__body` — 12px 14px padding

### Badges (`.tbd-badge`)
- 18px tall pills, 6px horizontal padding, 10.5px font
- Variants: neutral (default), success, accent, danger, warning — all with their `*-soft` background + main color foreground
- Optional `<span class="dot">` for status-style badges

### Segmented Radio (`.tbd-radio-group` + `.tbd-radio`)
- Container: surface-2 background, 1px border, 6px radius, 3px padding
- Active item: surface background + shadow-sm + 1px-border shadow ring
- Inactive: muted color, hover → fg

### Modal
- `.tbd-modal-bg` — fixed overlay, `oklch(0.15 0.01 270 / 0.45)` + `backdrop-filter: blur(1px)`, flex centered
- `.tbd-modal` — 480px max-width, surface background, 10px radius, shadow-lg
- 3 parts: `__head` (12px 16px, bottom border), `__body` (16px), `__foot` (10px 16px, bg-2 top border, flex-end buttons)

### Recording Pill
- Pulsing red dot (7px) + `REC mm:ss` text
- Background: `oklch(0.55 0.22 25 / 0.12)`, foreground `oklch(0.5 0.22 25)`
- Animation: `tbd-pulse 1.4s ease-in-out infinite` (opacity 1 → 0.35 → 1)

---

## Mock Data Shapes (match these to backend JSON)

```typescript
// Window enumeration — from core/window_picker.py
type WindowInfo = {
  hwnd: number;
  label: string;       // "Aurora — build 412 (Aurora.exe)"
  exe_path: string;
  pid: number;
  process_name: string;
  title: string;
};

// Android device — from core/adb.py AdbDevice
type AdbDevice = {
  serial: string;
  label: string;       // "Galaxy S24 · Android 14"
  model: string;
  online: boolean;
  sdk: number;
};

// Session metadata — from session_meta.json
type Session = {
  session_id: string;     // "20260523-114108-7af3"
  started_at: string;     // ISO 8601
  duration_seconds: number;
  size_bytes: number;
  log_lines: number;
  input_events: number;
  metric_samples: number;
  screen_frames: number;
  exe_path: string;
  device: 'PC' | 'Android';
  device_label?: string;
  has_viewer: boolean;
  shares: Array<{ token: string; created_at: string }>;
  uploaded?: boolean;     // local-only field
};

// Hub config — core/hub_config.py HubSettings
type HubSettings = {
  url: string;
  token: string;          // store in OS keychain, not plain settings
  username: string;
  configured: boolean;    // derived: bool(url && token)
};

// Capture target — core/screen_recorder.py
type CaptureTarget =
  | { kind: 'monitor'; index: number }
  | { kind: 'window'; hwnd: number; title: string }
  | { kind: 'android'; serial: string; capture_audio: boolean; backend: 'auto' | 'scrcpy' | 'screenrecord' };
```

---

## Assets

No external image assets. All icons are inline SVGs (16×16 viewBox, 1.5 stroke, currentColor) — copy the icon set from `src/icons.jsx` in the bundle, or use Lucide Icons if you prefer a library (the shapes are similar).

The brand mark is a CSS gradient + clip-path "T" letterform — see `.sidebar__brand-mark` in `src/styles.css`. Drop it into a 22-26px box.

---

## Files in This Bundle

```
design_handoff_trailbox_desktop/
├── README.md                      # This file
├── Trailbox Desktop.html          # Design canvas with all artboards
├── Session Viewer.html            # Standalone session viewer page
├── src/                           # Shared Hub design system files (imported by desktop)
│   ├── styles.css                 # Source of design tokens (light + dark)
│   ├── data.js                    # Hub-side mock data (sessions, users)
│   ├── icons.jsx                  # Inline SVG icon set
│   └── ...
└── src-desktop/                   # Desktop-specific files
    ├── desktop.css                # Desktop density overrides + chrome + screen styles
    ├── desktop-data.js            # Desktop mock data (windows, devices, local sessions)
    ├── desktop-app.jsx            # WindowChrome + Sidebar + App router
    ├── recording-overlay.jsx      # Overlay artboard demo
    ├── canvas-root.jsx            # Design canvas composition (artboard layout)
    └── screens/
        ├── capture.jsx            # CaptureScreen
        ├── sessions.jsx           # SessionsScreen (local + remote merged)
        └── hub-settings.jsx       # HubSettingsScreen
```

### How to view the design locally
1. Unzip the bundle
2. Serve the folder with any static file server, e.g.:
   ```
   python -m http.server 8000
   ```
3. Open `http://localhost:8000/Trailbox%20Desktop.html` for the canvas, or `http://localhost:8000/Session%20Viewer.html` for the viewer.

---

## Mapping to Existing Python Code

| Desktop screen | Replaces | Backend hooks needed |
|---|---|---|
| Capture screen — Target app card | `LauncherPanel._build_ui()` lines 99-170 | `enumerate_windows()`, `find_log_dir_for_pid()`, `find_pids_for_log_dir()`, `subprocess.Popen([exe])` |
| Capture screen — Capture target card | `LauncherPanel._build_ui()` lines 172-245 | `adb.list_devices()`, `ClickPicker`, `HotkeyPicker` global listener |
| Capture screen — Record button + status | `RecorderPanel` | Recording orchestrator (`main.py` `MainWindow._start_recording`/`_stop_recording`) |
| Sessions — Local table | `SessionPickerDialog` | Read `output/*/session_meta.json` |
| Sessions — Remote tab | `RemoteSessionPickerDialog` | `HubClient.list_sessions()`, `HubClient.download_session()` |
| Sessions — Upload action | `_UploadWorker` + `_UploadProgressDialog` | `HubClient.upload_session()` with progress callback |
| Sessions — Share action | `_show_share_url` | `HubClient.create_share()` + clipboard |
| Hub screen — Login tab | `HubSettingsDialog._build_login_tab` + `_on_login` | `HubClient.login()`, `HubClient.issue_token()` |
| Hub screen — Register tab | `_build_register_tab` + `_on_register` + `_poll_pending` | `HubClient.register()` + polling |
| Hub screen — Advanced tab | `_build_advanced_tab` | `HubClient.healthz()` |
| Recording overlay | `RecordingOverlay` | Separate Tauri window |

---

## Implementation Order (suggested)

1. **Scaffold** Tauri + React + Vite project. Configure two windows (main + overlay) in `tauri.conf.json`.
2. **Theme + tokens** — copy CSS custom properties, set up `[data-theme]` toggle, persist to localStorage.
3. **Shared components** — Button, Input, Card, Badge, Segmented, Icon. Test in Storybook or a `/dev` route.
4. **Chrome** — pick variant A or B, wire up `data-tauri-drag-region`, custom window controls calling `window.minimize()` / `window.toggleMaximize()` / `window.close()`.
5. **Capture screen** — static UI first, then wire Python IPC commands one by one.
6. **Recording state machine** — start with mock timers (like the prototype), then plug in real subprocess calls.
7. **Sessions screen** — local list first (read filesystem), then add Hub remote tab.
8. **Hub screen** — login flow with token storage in keychain.
9. **Recording overlay** — separate window, hook to recording start/stop events.
10. **Session viewer** — port existing `viewer.html` generator on the Python side to emit the new HTML structure; the player JS in `Session Viewer.html` can be lifted nearly verbatim.

---

## Open Questions for the Implementer

- **Token storage:** Use `tauri-plugin-store` (file-based, encrypted) or platform keychain (`tauri-plugin-stronghold`)? Strongly recommend keychain for the Hub token.
- **Process supervision:** When recording, Python subprocess needs lifecycle management. Consider `tauri-plugin-shell` with stdout streaming for progress events.
- **Global hotkey:** Tauri's `globalShortcut` API for `Ctrl+Alt+R` (stop recording) and `Ctrl+Shift+P` (window picker).
- **Click-through overlay on Windows:** Tauri 1.5 has `setIgnoreCursorEvents` — confirm it survives DWM compositor edge cases (the same one PyQt's `WindowTransparentForInput` flag handles today).
- **Drag-and-drop file/folder selection:** Tauri exposes drop events on windows; consider wiring "drop a folder here" UX for log folders alongside the file picker.
- **Theme system preference:** Listen to `window.matchMedia('(prefers-color-scheme: dark)')` and `Tauri.window.onThemeChanged()` so the app follows the OS theme by default.

Hub web frontend redesign is tracked separately and will follow.
