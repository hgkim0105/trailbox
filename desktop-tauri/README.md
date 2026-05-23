# Trailbox Desktop (Tauri 포팅)

PyQt6 데스크톱 클라이언트를 Tauri 2 + React + TypeScript 로 옮기는 작업.
디자인 스펙은 `design_handoff_trailbox_desktop/` 폴더(레포 루트) 참고.

> 현재 상태: **scaffolding only**. 빌드되는 빈 셸 + 디자인 토큰 +
> 사이드바와 3개 화면 stub 만 들어있음. 실제 캡처/세션/Hub 기능은
> 아직 IPC 로 연결되지 않았음 — 기존 PyQt6 클라이언트가 그대로 메인.

## 디렉토리

```
desktop-tauri/
├── package.json              Vite + React + TS + Tauri CLI
├── vite.config.ts            포트 1420 (Tauri 관례)
├── tsconfig.json
├── index.html                FOUC-safe 테마 init + Geist 폰트 <link>
├── src/
│   ├── main.tsx              React 엔트리
│   ├── App.tsx               사이드바 + 화면 라우팅
│   ├── theme/
│   │   ├── tokens.css        OKLCH 토큰 (light + dark) — Hub 와 동일
│   │   └── desktop.css       데스크톱 밀도 베이스 (13px / 200px 사이드바)
│   ├── components/
│   │   ├── Icon.tsx          inline SVG 아이콘 세트
│   │   ├── Sidebar.tsx
│   │   └── ThemeToggle.tsx
│   └── screens/
│       ├── CaptureScreen.tsx    stub — ui/launcher_panel.py + recorder_panel.py 대체 예정
│       ├── SessionsScreen.tsx   stub — ui/session_picker.py + remote_session_picker.py 대체 예정
│       └── HubSettingsScreen.tsx stub — ui/hub_dialogs.py 대체 예정
└── src-tauri/
    ├── Cargo.toml
    ├── build.rs
    ├── tauri.conf.json       main window 만 정의 (overlay 는 후속)
    ├── capabilities/
    │   └── default.json      Tauri 2 보안 모델 (현재는 core:default 만)
    └── src/
        ├── main.rs
        └── lib.rs             tauri::Builder — IPC 명령은 아직 비어있음
```

## 개발 환경

- Node 20+ (verified with 24.15)
- npm 10+
- Rust 1.77+ (verified with 1.95)
- Windows MSVC 툴체인 (Tauri Rust 빌드용)
- `tauri-build` 가 처음 빌드 시 추가 도구를 받아옴

## 시작

```powershell
cd desktop-tauri

# 1. JS 의존성 설치
npm install

# 2. Vite (React) 빌드만 검증 — Rust 안 건드림
npm run build

# 3. Tauri dev 모드 (React + Rust 같이) — 첫 실행은 cargo 컴파일 때문에 느림
npm run tauri:dev
```

## 알려진 todo

- **아이콘 파일** 아직 없음. `tauri.conf.json#bundle.icon` 경로의 파일들이
  실제 존재해야 `npm run tauri:build` 가 성공. 임시 생성:
  ```powershell
  # 32×32 이상 PNG 한 장 준비한 뒤
  npx tauri icon path\to\logo.png
  ```
  생성된 `src-tauri/icons/` 는 commit 함 (dev 환경 의존성 줄이려고).

- **Recording overlay window** — 현재 conf 에서 빠짐.
  `design_handoff_trailbox_desktop/src-desktop/recording-overlay.jsx`
  스펙대로 별도 entry HTML + Vite multi-page + tauri.conf 에 windows 한 줄
  추가해서 살릴 예정.

- **IPC 명령** — `tauri::command` 핸들러 0 개. 첫 명령 후보:
  `enumerate_windows`, `find_log_dir_for_pid`, `start_recording`,
  `stop_recording`, `list_local_sessions`. 백엔드는 일단 기존 Python
  subprocess 로 호출하고, 단계적으로 Rust crate 로 이관 (windows-capture-rs,
  cpal, enigo 등).

- **Hub 클라이언트** — `core/hub_client.py` 와 동일한 API 를 호출하는 wrapper.
  토큰은 `tauri-plugin-stronghold` (OS keychain) 에 저장.

- **글로벌 단축키** `Ctrl+Alt+R` (녹화 중지) / `Ctrl+Shift+P` (창 선택) —
  `tauri-plugin-global-shortcut` 추가.

자세한 화면별 컴포넌트 명세 + 컬러/사이즈 토큰은
`design_handoff_trailbox_desktop/README.md` 참고.
