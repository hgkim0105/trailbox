# Handoff: Trailbox Hub Web Frontend Redesign

## Overview

This handoff bundles the React design prototype for **redesigning the Trailbox Hub web frontend** (the team-collaboration backend at `hub_server/`).

Current state: FastAPI app serving Jinja2 templates with a thin CSS file (`hub_server/static/app.css`, 3.7 KB). Functional but minimal — Username/Email forms, basic tables, light-mode-only.

Target state: a modern, dense, GitHub-style developer-collab UI with light/dark themes, session card grids, embedded viewer mock, full admin panels, and live in-page tweaks.

> **Hub-first decision:** The Trailbox desktop client (Tauri port) handoff is staged separately — finish Hub first, then desktop.

---

## About the Design Files

The HTML/JSX files in this bundle are **design references**, not production code. They use plain React + Babel-in-browser for fast prototyping. The implementation should re-author them in whichever rendering model fits the existing backend.

**Two implementation paths to choose from:**

### Path A — Modernize templates (recommended for minimal risk)
Keep the existing FastAPI + Jinja2 backend. Rewrite `hub_server/static/app.css` to match the new design tokens, rewrite each template in `hub_server/templates/` to match the new markup, and add a small vanilla JS file for the interactive bits (theme toggle, segmented controls, copy-to-clipboard, session detail tabs, AI analysis collapse).

**Pros:** No backend changes. Session cookies / CSRF / flash messages all work as-is. Each template stays a single self-contained file.
**Cons:** Some interactions are clunkier in vanilla JS (the session detail viewer scrubber, live metric updates).

### Path B — SPA migration (bigger lift, more polish)
Move `hub_server/routes/web.py` HTML routes to JSON API endpoints (or expose data through existing `api_admin.py` / `api_auth.py`). Build a React SPA (Vite + TS) that consumes the JSON, served from `/` as a static bundle.

**Pros:** All the React interactions transfer directly. Cleaner code separation. Easier to add features later (real-time updates via SSE, etc.).
**Cons:** Need to set up build pipeline, handle auth in SPA (cookie-based session is still fine), implement client-side routing, write more tests.

**Suggested path:** Start with Path A for the visual redesign — ship the new look quickly with the existing backend. Then evaluate Path B for v2 once the look is locked in.

The rest of this README is structured to support either path.

---

## Fidelity

**High-fidelity.** All colors, typography, spacing, shadows, and interactions are final. The mock data shapes match the existing `hub_server/db.py` and route signatures so the wiring is 1:1.

---

## Screens (8 total)

All screens live under a shared app shell (sidebar + topbar), except the auth screens which use a different two-column layout.

### 1. Login (`/login`)
Replaces: `hub_server/templates/login.html`

**Layout:** Two-column. Left half = centered 360px form. Right half = decorative visual (gradient + grid pattern + floating mock cards).

**Left form:**
- Brand mark + "Trailbox Hub" (top-left, 28px from edge)
- H1 "다시 만나서 반가워요" (26px, 600 weight, -0.02em letter-spacing)
- Subtitle "Trailbox Hub에 로그인하고 팀이 캡처한 세션을 확인하세요." (14px, muted)
- Username field (large variant, 40px tall) — autofocus
- Password field with inline "잊으셨나요?" link in label row
- Primary button "로그인" (large, full width)
- Footer "계정이 없나요? 회원가입" — links to `/register`
- Demo-mode info box at bottom (warning-soft background) — remove this on real impl, it's just for prototype

**Right visual:**
- Background: radial gradients in accent hues + 36px grid mask
- Three floating cards (rotated ±3deg) showing:
  1. Session preview card with mini CPU chart + metrics row
  2. Share-link card with code block
  3. Event-row badge with "00:34.5 · gpu device hung" (small, danger color)

**Error state:** flash above the form (danger-soft background)
**Loading state:** button shows "로그인 중…", disabled

### 2. Register (`/register`)
Replaces: `hub_server/templates/register.html`

Same left/right layout as login. Form has Username, Email (optional), Password (min 8). On submit, swap form for "신청 접수됨" panel with green check icon + "관리자 승인을 기다리고 있어요" + return-to-login button.

### 3. Sessions List (`/sessions`)
Replaces: `hub_server/templates/sessions/list.html`

**Section header:**
- H1 "세션" + subtitle ("전체 사용자" or "본인" — based on role)
- Right: "모두 zip" button + primary "업로드" button

**Stat row** (4 cards): 세션 수, 총 길이, 스토리지 (with quota %), 활성 공유

**Toolbar:**
- Search input (left search icon, 360px max-width)
- Admin-only: 전체 / 내 세션 segmented control
- 모두 / PC / Android segmented control
- Right: sort dropdown

**Three layout modes** (chosen via Tweaks panel — see below):
1. **Cards** (default) — responsive grid, `repeat(auto-fill, minmax(280px, 1fr))`. Each card:
   - Procedural abstract thumbnail (16:10 aspect) — gradient bg based on session kind (game/mobile/code) + abstract HUD/UI elements + chart line overlay
   - Top-left badges (device type, outline style on dark)
   - Bottom title (session_id, mono, white text-shadow)
   - Bottom-right duration pill (dark, mono)
   - Hover: shows white play button center, larger shadow
   - Body: session_id row + meta row (device label, relative time) + tag chips + 3-up event count metrics (Logs/Inputs/Samples)
2. **Table** — full data table with thumb column, EXE name, timestamps, sizes, event counts, owner avatar (admin), shares badge, row actions (zip/delete)
3. **Compact** — single-line rows with mini thumb + session_id + meta + duration + event counts + shares badge

**Empty state:** centered icon + "표시할 세션이 없습니다" + helper text

### 4. Session Detail (`/sessions/{session_id}`)
Replaces: `hub_server/templates/sessions/detail.html`

**Header row** (flex wrap, gap 12px):
- Breadcrumb "세션 / " + session_id (mono, 18px, 600 weight)
- Device badge (info for PC, success for Android) + device label
- Tag chips (outline style)
- Right side: "zip 다운로드" + primary "공유 링크 발급"

**Two-column grid** (1fr 360px, stacks on narrow):

**Left column:**
1. **Viewer mock** — embedded inline (NOT a separate page like the desktop client). Mocks the viewer.html content:
   - 16:9 video stage with animated mock game/mobile UI based on session kind
   - Animated cursor (sin/cos motion)
   - Dark controls bar: prev/play/next + time display + scrub bar + speed button
   - Scrub click → seek; play button → auto-advance
2. **Tabs card** below viewer: 이벤트 타임라인 | 시스템 사양 | 공유 링크 | AI 분석
   - **이벤트 타임라인:** filter segments (전체/Logs/Inputs/Errors/Warn with counts) + search input + scrolling event list. Each row: 6px colored dot + mono timestamp + ellipsis-truncated message. Click row → seek viewer to that time.
   - **시스템 사양:** dl/dt/dd grid showing OS, CPU, RAM, GPU, VRAM, Display, Python, Trailbox version, EXE path
   - **공유 링크:** table of active shares with token, full URL (with copy button + "복사됨" badge), created time, revoke button. Empty state with helper text.
   - **AI 분석:** Claude analysis card — accent-soft icon square + "Claude · session.analyze" header + "재분석" button + formatted analysis text (summary, noteworthy moments with code timestamps, suggestion). (See Note below.)

**Right column (sidebar):**
1. **Metrics panel** — dark header "메트릭 · t=mm:ss.s" + 5 rows (CPU/GPU/RAM/VRAM/FPS), each with: label, full-width sparkline (with cursor at current t), value+unit. Sparkline cursor updates live as you scrub.
2. **Session info card** — kv list (시작/길이/크기/로그/입력/샘플/소유자 with avatar). Footer with danger "세션 삭제" button.

> **Note on AI analysis tab:** This is NOT currently in the trailbox codebase. It was added as a forward-looking design placeholder (Hub itself doesn't run Claude — that's the Desktop MCP's job). Options when implementing:
> - **Remove the tab** to match current scope (4 → 3 tabs)
> - **Keep as "Experimental"** with a clear empty state pointing to MCP setup
> - **Implement for real** — Hub calls Claude via `window.claude.complete(...)` API or backend OpenAI/Anthropic SDK with session metadata as context. Decide before shipping.

### 5. Account (`/account`)
Replaces: `hub_server/templates/account.html` + `account_password.html`

**Profile card** (top): large avatar + username (18px, 600) + role badge + status badge (success-dot for active) + email muted. Right: "비밀번호 변경" button — clicking expands an inline form (3 password fields in a 3-column grid).

**API Tokens card:**
- Header with "API 토큰" title + description ("Trailbox 클라이언트 / MCP 백엔드가 X-Trailbox-Token 헤더에 실어 보냅니다.")
- If a new token was just issued: success flash with "다시 표시되지 않습니다" warning + code block with copy button
- New-token form: label input + primary "새 토큰 발급"
- Tokens table: ID (#mono muted) / 라벨 / 발급 / 마지막 사용 / 상태 badge / revoke action

**MCP setup card:** title with robot icon + description + `pre` code block with the JSON config example (escaped backslashes for Windows paths)

### 6. Admin · Users (`/admin/users`)
Replaces: `hub_server/templates/admin/users.html`

**Header:** "사용자 관리" + "사용자 초대" button

**Temp password banner** (when reset): success flash with code block + copy button — `이 페이지에서만 한 번 표시됩니다`

**Pending approvals card** (only shown if any pending):
- Border-color = warning-mix
- Header background = warning-soft
- Title with clock icon + count + "자동 승인 OFF" indicator + "설정 변경" link
- Table: Username (with avatar), Email, created_at (mono muted), action buttons (primary "승인" + ghost-danger "거절")

**All users table:**
- Search input in header
- Columns: User (avatar + username + email below) / Role badge (accent for admin, neutral for user) / Status badge / 가입 / 승인 / Actions
- Actions per row (skip the current user row): disable/enable, promote/demote, reset pw — all confirm via `confirm()` dialog
- Show "· 나" suffix next to current user's row

### 7. Admin · Settings (`/admin/settings`)
Replaces: `hub_server/templates/admin/settings.html`

**Header:** "시스템 설정" + saved indicator (success-dot badge appears for 1.8s on change)

**2×2 grid of cards:**
- **계정 정책:** toggle rows for auto_approve_registration, require_strong_password (each row has title + desc + toggle on right)
- **공유 정책:** allow_public_share toggle + share_expiry_days numeric input (with "일" suffix)
- **저장 · 보관:** retention_days, max_session_mb, upload_chunk_mb numeric inputs
- **현재 환경값 (read-only):** kv list of Hub version, DB, Storage, Bind, TLS, Python, Uptime

Change → debounce-save → toast appears.

### 8. Admin · Audit (`/admin/audit`)
Replaces: `hub_server/templates/admin/audit.html`

**Header:** "감사 로그" + "CSV 내보내기" button

**Toolbar:** search input + segmented filter (전체/Auth/Session/User/Settings)

**Table:**
- 시각 (mono, muted) / Actor (avatar + name; "system" gets a bolt icon square) / Action badge (color depends on action prefix: red for `auth.login.fail`, warning for `*.delete`/`*.disable`/`*.revoke`, success for `*.approve`/`*.upload`, accent for `session.share.*`, neutral otherwise) / Target (mono) / Detail (mono muted)

**Empty state:** centered search icon + "일치하는 감사 로그가 없습니다"

---

## App Shell (sidebar + topbar)

Wraps screens 3-8 (auth screens have their own layout).

**Sidebar (240px wide, sticky):**
- Brand: gradient-square logo with clip-path "T" + "Trailbox" / "HUB" small uppercase
- Section labels (10.5px, uppercase, letter-spacing 0.06em)
- Nav items: 14px icon + 13.5px label + optional count badge
  - 워크스페이스 / 세션
  - 관리자 (only for admins) / 사용자 (badge with pending count) / 시스템 설정 / 감사 로그
- Bottom user card: small avatar + username + role label + account button (icon-only ghost)

**Topbar (sticky, blur backdrop):**
- Breadcrumbs (12px chevron separators, current bolded)
- Right actions: search button with ⌘K kbd hint, theme toggle (sun/moon icon), logout button

Active nav item: `var(--accent-soft)` background, accent foreground.

---

## Tweaks Panel

The prototype includes a floating "Tweaks" panel (bottom-right) for live design exploration:
- Theme: 라이트 / 다크
- Accent color: 6 hue swatches (282 indigo / 250 blue / 200 cyan / 150 emerald / 30 orange / 350 pink)
- Session list layout: 카드 / 테이블 / 컴팩트

For the production implementation:
- **Theme toggle** → keep as a topbar button, persist to user preferences (server-side per user, or localStorage)
- **Accent color** → expose as user preference if desired; otherwise hardcode indigo (282)
- **List layout** → expose as user preference (saved to localStorage or `/api/users/me/prefs`)

The dev-time Tweaks panel itself doesn't need to ship.

---

## Design Tokens

Drop these into `hub_server/static/app.css` (Path A) or `src/theme/tokens.css` (Path B). All colors use OKLCH for perceptual uniformity. Hue is parameterized via `--accent-h` so accent color is configurable.

### Light Mode
```css
:root, [data-theme="light"] {
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
  --on-accent: oklch(0.99 0.005 280);

  --accent-h: 282;  /* indigo/purple — change to retheme */
  --accent:        oklch(0.55 0.18 var(--accent-h));
  --accent-hover:  oklch(0.49 0.19 var(--accent-h));
  --accent-soft:   oklch(0.96 0.035 var(--accent-h));
  --accent-soft-2: oklch(0.92 0.06 var(--accent-h));
  --accent-fg:     oklch(0.4 0.18 var(--accent-h));

  --success:      oklch(0.55 0.14 150);
  --success-soft: oklch(0.95 0.05 150);
  --danger:       oklch(0.55 0.19 25);
  --danger-soft:  oklch(0.96 0.04 25);
  --warning:      oklch(0.7 0.16 75);
  --warning-soft: oklch(0.96 0.05 75);
  --info:         oklch(0.6 0.13 240);
  --info-soft:    oklch(0.95 0.04 240);

  --shadow-sm: 0 1px 2px oklch(0.2 0.02 270 / 0.04);
  --shadow-md: 0 4px 12px oklch(0.2 0.02 270 / 0.06), 0 1px 3px oklch(0.2 0.02 270 / 0.04);
  --shadow-lg: 0 20px 40px oklch(0.2 0.02 270 / 0.08), 0 4px 12px oklch(0.2 0.02 270 / 0.05);
  --shadow-pop: 0 8px 28px oklch(0.2 0.02 270 / 0.12);

  --r-sm: 4px;
  --r-md: 6px;
  --r-lg: 10px;
  --r-xl: 14px;
  --r-pill: 999px;

  color-scheme: light;
}
```

### Dark Mode
```css
[data-theme="dark"] {
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

  --accent:        oklch(0.7 0.17 var(--accent-h));
  --accent-hover:  oklch(0.76 0.17 var(--accent-h));
  --accent-soft:   oklch(0.3 0.08 var(--accent-h));
  --accent-soft-2: oklch(0.36 0.1 var(--accent-h));
  --accent-fg:     oklch(0.82 0.15 var(--accent-h));

  --success:      oklch(0.72 0.14 150);
  --success-soft: oklch(0.27 0.05 150);
  --danger:       oklch(0.72 0.18 25);
  --danger-soft:  oklch(0.3 0.07 25);
  --warning:      oklch(0.8 0.14 75);
  --warning-soft: oklch(0.3 0.06 75);
  --info:         oklch(0.75 0.13 240);
  --info-soft:    oklch(0.28 0.05 240);

  --shadow-sm: 0 1px 2px oklch(0 0 0 / 0.3);
  --shadow-md: 0 4px 12px oklch(0 0 0 / 0.35), 0 1px 3px oklch(0 0 0 / 0.25);
  --shadow-lg: 0 20px 40px oklch(0 0 0 / 0.4), 0 4px 12px oklch(0 0 0 / 0.3);
  --shadow-pop: 0 8px 28px oklch(0 0 0 / 0.45);

  color-scheme: dark;
}
```

### Typography
- **Sans:** Geist (Google Font, weights 400/500/600/700)
- **Mono:** Geist Mono (weights 400/500/600)
- **Base size:** 14px (web density — denser than typical SaaS but lighter than Trailbox Desktop's 13px)
- **Line-height:** 1.5
- **font-feature-settings:** `'ss01', 'cv11'` for Geist's stylistic alternates
- **font-variant-numeric:** `tabular-nums` on all metric values

### Spacing
- Container max-width: 1280px
- Card padding: 18px (default), 14px 18px (header)
- Button heights: 26px (sm), 32px (default), 38px (lg)
- Input heights: 34px (default), 40px (lg, used in auth)

---

## Component Patterns

Full reference impl in `src/components.jsx` and `src/styles.css`. Patterns to port:

- **Button** — `.btn` baseline + `--primary`, `--danger`, `--ghost`, `--sm`, `--lg`, `--icon` modifiers. Primary uses accent bg, white text, no border.
- **Input** — 34px tall, 6px radius, focus = accent border + 3px accent-soft ring
- **Card** — surface bg + border + 10px radius. `__header` + `__body` + `__footer` (bg-2)
- **Badge** — 20px pill with 6 tones (neutral/accent/success/danger/warning/info/outline); optional `.dot`
- **Avatar** — gradient based on username initial; sizes sm/default/lg (lg uses 12px radius square)
- **Tabs** — bottom-border on container; active = accent border + foreground color; counts shown as nested pills
- **Segmented control** — `.seg` container with `.seg__btn`s; active uses surface bg + shadow-sm (looks "raised")
- **Toggle** — 32×18 pill with 14px white knob; on state = accent bg
- **Stat card** — label (uppercase 11px) + value (mono 22px tabular) + delta (12px, with `--up`/`--down` colors)
- **Sparkline** — SVG path with optional fill, currentColor stroke 1.4px

---

## Mock Data → Real Data

The prototype's `src/data.js` mocks shapes that already match `hub_server`'s database tables (see `hub_server/db.py` for schemas and `hub_server/routes/web.py` for what each template gets).

| Mock array in prototype | Real source |
|---|---|
| `CURRENT_USER` | `request.session` + `users` table row, exposed as `current_user` in templates |
| `SESSIONS` | `hub_server.storage.list_sessions(user_id)` — already returns the fields used |
| `USERS` | `hub_server.users.list_all()` — for admin/users |
| `PENDING_USERS` | filter `status == 'pending'` from `users` |
| `TOKENS` | `hub_server.tokens.list_for_user(user_id)` |
| `AUDIT_ENTRIES` | `hub_server.audit.list_recent(limit=100)` |
| `SAMPLE_EVENTS` | NOT REAL — replaced by streaming events from `output/<sid>/logs/logs.jsonl` + `inputs/inputs.jsonl` when the viewer mock is wired up |
| `SAMPLE_SYSTEM` | `session_meta.json` `system` field |
| `HUB_SETTINGS` | `hub_server.settings_store.all()` |

For session list cards: the `thumb_seed` + `thumb_kind` fields are purely cosmetic (procedural thumbnail generation). Derive `thumb_kind` from `exe_path` heuristics or `session_meta.json` device type:
- `.exe` paths containing `Games`, `steamapps`, etc. → `'game'`
- Android packages (no extension, has `.`) → `'mobile'`
- Everything else → `'code'`

For `thumb_seed`, hash the session_id deterministically (any fast string hash).

---

## Route Map

| Screen | Current route | HTTP | Backend stays |
|---|---|---|---|
| Login | `GET /login` | unchanged | `hub_server.routes.web.login_page` |
| Register | `GET /register` | unchanged | `hub_server.routes.web.register_page` |
| Sessions list | `GET /sessions` | unchanged | `hub_server.routes.web.sessions_list` |
| Session detail | `GET /sessions/{sid}` | unchanged | `hub_server.routes.web.session_detail` |
| Share viewer | `GET /v/{token}/` | unchanged | `hub_server.routes.web.viewer_via_share` |
| Account | `GET /account` | unchanged | `hub_server.routes.web.account_page` |
| Password change | `GET /account/password` | unchanged → **inline in account page** | merge into account |
| Admin users | `GET /admin/users` | unchanged | `hub_server.routes.web.admin_users` |
| Admin settings | `GET /admin/settings` | unchanged | `hub_server.routes.web.admin_settings` |
| Admin audit | `GET /admin/audit` | unchanged | `hub_server.routes.web.admin_audit` |

For Path A, the form POST endpoints stay the same. For Path B, convert each form POST to a JSON endpoint matching the existing patterns in `api_admin.py` / `api_auth.py`.

---

## Implementation Notes

### Path A specifics (Jinja templates)
1. **Replace `hub_server/static/app.css`** with the full token set + component classes. Reference `src/styles.css` from this bundle — it's ~30KB and contains everything needed except React-specific bits.
2. **Add `hub_server/static/app.js`** for interactivity:
   - Theme toggle (read `localStorage.theme`, set `data-theme` on `<html>`, persist)
   - Tab switching on session detail
   - Segmented controls on session list (layout switcher, device filter)
   - Copy-to-clipboard buttons (delegate to `navigator.clipboard.writeText`)
   - Session detail viewer mock — can be a pure-CSS animation or skipped initially (the real `viewer.html` still works for now)
   - Auto-refresh of pending users count on admin pages (poll every 30s)
3. **Rewrite each template** to match the new markup. Use Jinja `{% block %}` for shared chrome (base.html updates significantly — sidebar moves there).
4. **Procedural thumbnail SVG** — generate server-side in the template based on session_id + exe_path, OR inline-generate via JS on page load. Either is fine.

### Path B specifics (SPA)
1. Set up Vite + React + TS in a new `web/` directory. Add a build step to FastAPI that serves `web/dist/` as static.
2. Add `api/sessions/`, `api/users/`, `api/audit/`, `api/settings/` JSON endpoints matching the current HTML routes.
3. Use TanStack Query (or SWR) for data fetching. Use Wouter or React Router for client-side routing.
4. Keep cookie-based session auth — fetch with `credentials: 'include'`.
5. The Tweaks panel can stay as a dev-only feature (gated by `NODE_ENV === 'development'`).

### Both paths
- **Theme persistence:** read from cookie (`hub_theme=dark`) OR localStorage. Cookie is better for FOUC-free initial render.
- **Accent customization:** if exposed as a user pref, set `--accent-h` on `<html>` server-side from the user row.
- **List layout pref:** localStorage `hub_session_layout` or a `users.prefs JSON` column.
- **Compatibility:** the existing `viewer.html` generation in the recording pipeline (see `main.py`'s `_finalize_session`) doesn't need to change — the new session detail page just embeds/links to it the same way.

---

## Files in This Bundle

```
design_handoff_trailbox_hub/
├── README.md                        # This file
├── Trailbox Hub.html                # Main prototype — open this first
├── src/
│   ├── styles.css                   # All design tokens + component CSS (~30 KB)
│   ├── data.js                      # Mock data layer
│   ├── icons.jsx                    # Inline SVG icon set (40+ icons)
│   ├── components.jsx               # Button, Badge, Avatar, Flash, Field, Sparkline, SessionThumb, Segmented, useCopy, format helpers
│   ├── chrome.jsx                   # Sidebar, Topbar
│   ├── app.jsx                      # Root + router + theme + tweaks
│   ├── tweaks-panel.jsx             # Dev-time Tweaks panel (skip on impl)
│   └── screens/
│       ├── auth.jsx                 # Login + Register
│       ├── sessions-list.jsx        # 3 layout modes
│       ├── sessions-detail.jsx      # Viewer mock + tabs + metrics + share mgmt + AI analysis
│       ├── account.jsx              # Profile + tokens + MCP setup
│       └── admin.jsx                # Users + Settings + Audit
```

### How to view locally
1. Unzip the bundle
2. Serve the folder with any static file server:
   ```
   python -m http.server 8000
   ```
3. Open `http://localhost:8000/Trailbox%20Hub.html`
4. Toolbar → Tweaks toggle (top-right) reveals the dev-time controls panel

---

## Implementation Order (suggested)

1. **Theme + tokens** — replace `app.css` with new token set, ensure all existing pages still load (just with new colors). Validate light/dark toggle.
2. **App shell (base.html)** — new sidebar + topbar; nav items + active state.
3. **Login + Register** — biggest visual departure, ship it to validate the visual language.
4. **Sessions list (cards layout only)** — get one layout right first; add table + compact later.
5. **Session detail** — start without viewer mock; just header + metadata + tabs (shares/system). Add viewer mock + metrics panel after.
6. **Account + token management** — pretty straightforward port of existing forms.
7. **Admin · Users** — most complex admin page (pending banner + main table + temp-pw flash).
8. **Admin · Settings + Audit** — simpler, finish last.

Decide on Path A vs B before step 1. Then go.

---

## Open Questions

- **AI analysis tab:** ship as v1 (with real LLM call), ship as placeholder ("실험적 기능"), or omit? Recommendation: omit for v1, add later as a separate feature ticket.
- **User preferences storage:** add a `users.prefs JSONB` column for theme/accent/layout, or stick with localStorage? JSONB column lets prefs follow the user across devices.
- **Procedural thumbnails:** are they worth the effort, or just show device-icon-on-gradient like the table view does? Cards-with-thumbnails is the most visually rich option but adds ~1ms of SVG render per card; consider lazy-rendering or pre-generating + caching.
- **Mobile breakpoint:** current design assumes desktop browser. Add a `<1100px` breakpoint that stacks the session detail grid? Sessions list is already grid-responsive.
- **Real-time updates:** session detail + admin users could benefit from SSE updates (new uploads, pending registrations). Decide based on traffic patterns — for small teams polling every 30s is fine.

---

## After Hub: Desktop

Once the Hub redesign ships, return to the staged Tauri port of the desktop client. The desktop design uses the same token set (with denser sizing — 13px base vs 14px) so the visual system is already validated.
