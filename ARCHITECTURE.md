# Trailbox Architecture

> 코드베이스 전체 구조를 한눈에 파악하기 위한 문서.
> 각 모듈이 무엇을 하고, 어떻게 연결되는지를 설명한다.

---

## 1. 전체 구조 (Top-Level)

```
Trailbox/
├── main.py                    # PyQt6 GUI 앱 진입점 (__version__ 소스)
├── core/                      # 녹화·분석 엔진 (UI 무관)
├── ui/                        # PyQt6 위젯 (main.py 전용)
├── mcp_server/                # MCP stdio 서버 (Claude 연동)
├── hub_server/                # Hub 웹 서버 (FastAPI)
├── desktop-tauri/             # Tauri 2 + React 데스크톱 앱
├── installer/                 # Inno Setup 윈도우 인스톨러
├── build.py                   # PyInstaller 빌드 스크립트
├── hub_entry.py               # Trailbox-hub.exe 진입점
├── mcp_entry.py               # Trailbox-mcp.exe 진입점
└── output/                    # 녹화 세션 출력 (gitignore)
```

### 빌드 산출물 (dist/)

| 파일 | 소스 | 설명 |
|------|------|------|
| `Trailbox-Setup.exe` | Inno Setup | 윈도우 인스톨러 (모든 바이너리 포함) |
| `trailbox-desktop.exe` | Tauri (Rust) | 데스크톱 앱 프론트엔드 (~9 MB) |
| `trailbox-bridge.exe` | PyInstaller | Python 백엔드 사이드카 (~126 MB) |
| `Trailbox-mcp.exe` | PyInstaller | MCP stdio 서버 (~44 MB) |
| `Trailbox-hub.exe` | PyInstaller | Hub 웹 서버 (~44 MB) |

---

## 2. 데이터 흐름 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                     사용자가 녹화 시작                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │   Tauri Desktop App     │
              │   (React + Rust)        │
              │                         │
              │  bridge_record.py 스폰  │
              └────────────┬────────────┘
                           │ stdin/stdout JSON
              ┌────────────▼────────────┐
              │   Python Bridge         │
              │   (bridge_record.py)    │
              │                         │
              │  core/* 모듈 호출       │
              └────────────┬────────────┘
                           │
         ┌─────────┬───────┼───────┬──────────┐
         ▼         ▼       ▼       ▼          ▼
    ScreenRec  AudioRec  LogCol  InputRec  MetricsRec
         │         │       │       │          │
         ▼         ▼       ▼       ▼          ▼
    screen.mp4  audio.wav  logs/  inputs/  metrics/
         │         │
         └────┬────┘
              ▼
         post_mux (ffmpeg)
              │
              ▼
         screen.mp4 (최종)
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
session_meta  viewer.html  .uploaded (Hub 업로드 시)
```

---

## 3. core/ — 녹화 엔진

UI에 의존하지 않는 순수 녹화·분석 모듈. PyQt6 GUI와 Tauri 데스크톱 앱 모두 이 레이어를 사용한다.

```
core/
├── screen_recorder.py     # 화면 캡처 → ffmpeg pipe
│                          #   MonitorTarget: dxcam (DXGI)
│                          #   WindowTarget: windows-capture (WGC)
│                          #   VFR 방식 — 프레임 도착 시에만 ffmpeg에 write
│
├── audio_recorder.py      # 시스템 오디오 캡처 → WAV (soundcard 라이브러리)
├── post_mux.py            # screen.video.mp4 + screen.audio.wav → screen.mp4 (ffmpeg)
│
├── log_collector.py       # 게임 로그 파일 tail → logs/logs.jsonl + logs.vtt
├── input_recorder.py      # 키보드/마우스 이벤트 → inputs/inputs.jsonl + inputs.vtt (pynput)
├── metrics_recorder.py    # 프로세스 텔레메트리 1Hz → metrics/process.jsonl (psutil)
├── gpu_monitor.py         # GPU 사용률/VRAM → metrics_recorder에 합류 (win32pdh)
│
├── session.py             # Session 데이터클래스 — ID 생성, 디렉토리 생성, finalize (meta 작성)
├── system_info.py         # 하드웨어 스냅샷 (CPU/GPU/RAM/디스플레이) → session_meta.system
├── frame_extractor.py     # screen.mp4에서 특정 시각 JPEG 프레임 추출 (ffmpeg, ≤950KB)
├── viewer_generator.py    # session_meta + JSONL → 자립형 viewer.html 생성
│
├── process_detector.py    # 창↔로그 디렉토리 양방향 자동 감지
├── window_picker.py       # 열린 창 목록 조회 (Win32 API)
├── window_clicker.py      # 클릭으로 창 선택
├── global_hotkey.py       # 시스템 전역 단축키 (Ctrl+Alt+R 등)
│
├── hub_client.py          # Hub HTTP 클라이언트 — 업로드/다운로드/인증/공유
├── hub_config.py          # Hub 연결 설정 (QSettings 기반)
│
├── adb.py                 # Android ADB 래퍼
├── android_input_recorder.py
├── android_log_collector.py
└── android_metrics_recorder.py
```

### 핵심 규칙: t_video_s

모든 레코더는 `t0_perf = time.perf_counter()`를 공유하고, 매 이벤트에 `t_video_s = perf_counter() - t0_perf`를 기록한다. 이 타임스탬프로 뷰어와 MCP 서버가 로그/입력/메트릭을 영상 위에 정렬한다.

---

## 4. desktop-tauri/ — Tauri 데스크톱 앱

Tauri 2 (Rust) + React (TypeScript) 기반 데스크톱 클라이언트.

```
desktop-tauri/
├── src/                          # React 프론트엔드
│   ├── App.tsx                   # 라우팅, 녹화 상태, sync queue, auto-cleanup
│   ├── screens/
│   │   ├── CaptureScreen.tsx     # 캡처 설정 + 녹화 제어 + 실시간 메트릭
│   │   ├── SessionsScreen.tsx    # 로컬+Hub 통합 세션 목록, 다운로드, 뷰어
│   │   └── HubSettingsScreen.tsx # Hub 로그인, 토큰 관리, 정리 정책
│   ├── components/
│   │   ├── Icon.tsx              # SVG 아이콘 컴포넌트
│   │   ├── ThemeToggle.tsx       # 다크/라이트 테마 전환
│   │   └── Sidebar.tsx           # (미사용 — tbd-tabs로 대체)
│   ├── ipc/                      # Tauri invoke 타입 래퍼
│   │   ├── capture.ts            # 녹화 관련 IPC
│   │   ├── sessions.ts           # 세션 목록/뷰어/삭제
│   │   └── hub.ts                # Hub API 호출
│   └── data/mock.ts              # 타입 정의 + 목업 데이터
│
├── src-tauri/src/                # Rust 백엔드
│   ├── lib.rs                    # Tauri 앱 설정 — 커맨드 등록, 전역 단축키
│   ├── commands.rs               # 27개 Tauri 커맨드 구현
│   └── main.rs                   # 진입점 (lib::run 호출)
│
├── bridge.py                     # Python 원샷 브릿지 (13개 서브커맨드)
├── bridge_record.py              # Python 녹화 데몬 (stdin/stdout JSON-lines)
└── bridge_entry.py               # PyInstaller 진입점 (record 분기)
```

### IPC 아키텍처

```
React (invoke)  ──→  Rust (commands.rs)  ──→  Python (bridge.py)
                                         └─→  직접 처리 (fs/open/rfd)
```

| 카테고리 | React → Rust | Rust 처리 |
|----------|-------------|-----------|
| 녹화 | start/stop_recording | bridge_record.py 서브프로세스 |
| 창 목록 | enumerate_windows | bridge.py enumerate-windows |
| Hub API | hub_upload/download/login | bridge.py hub-* |
| 파일 | open_viewer, delete_session | 직접 fs 접근 |
| 다이얼로그 | pick_file, pick_folder | rfd 크레이트 |
| 오버레이 | show/hide/sync_overlay | Tauri 윈도우 API |

### bridge_record.py 프로토콜

```
→ {"cmd":"start", "target":{...}, "exe_path":"...", ...}
← {"event":"ready"}
← {"event":"started", "session_id":"aurora_20260523_114108"}
← {"event":"status", "elapsed":1, "frames":30, "cpu_pct":35.2, "rss_mb":210, "gpu_pct":45.0, "gpu_vram_mb":1024}
← {"event":"status", ...}  (매 1초)
→ {"cmd":"stop"}
← {"event":"stopping"}
← {"event":"done", "session_id":"...", "duration":42.5, "frames":1280, ...}
← {"event":"exit"}
```

---

## 5. mcp_server/ — MCP 서버

Claude Desktop / Claude Code에서 세션 데이터를 조회하는 stdio MCP 서버.

```
mcp_server/
├── __main__.py            # FastMCP 앱 — 8개 도구 등록, 백엔드 선택, _safe_tool 데코레이터
├── filters.py             # 공통 필터링/집계 (시간범위, kind 매칭, 메트릭 요약, 프레임 통계)
├── errors.py              # 구조적 에러 (SessionNotFound, FileNotAvailable, HubUnavailable)
└── backends/
    ├── __init__.py        # Backend Protocol 정의
    ├── local.py           # 로컬 파일시스템 백엔드
    ├── hub.py             # Hub HTTP 백엔드
    └── hybrid.py          # 로컬 우선 + Hub fallback
```

### 백엔드 선택 로직

```
TRAILBOX_HUB_URL 설정됨?
  ├─ Yes + 로컬 output/ 존재 → HybridBackend (로컬 우선, Hub fallback)
  ├─ Yes + 로컬 output/ 없음 → HubBackend (HTTP only)
  └─ No                      → LocalBackend (파일시스템 only)
```

### 8개 도구

| 도구 | 설명 |
|------|------|
| `list_sessions` | 최근 세션 목록 (platform, device_kind, system_summary, owner, description 포함) |
| `get_session` | 세션 메타 + 파일 경로 + 시스템 스냅샷 |
| `query_events` | 시간/종류/텍스트 필터로 로그+입력 이벤트 조회 |
| `get_metrics` | CPU/RSS/GPU/VRAM/threads/handles 텔레메트리 + 요약 |
| `search_logs` | 로그 메시지 전문 검색 |
| `get_frame_at` | 특정 시각의 JPEG 프레임 추출 |
| `get_viewer_path` | viewer.html 경로 또는 URL |
| `get_frame_stats` | FPS/지터/스터터 분석 (frames.jsonl) |

---

## 6. hub_server/ — Hub 웹 서버

팀 공유용 FastAPI 서버. 세션 업로드/다운로드, 웹 뷰어, 사용자 관리.

```
hub_server/
├── app.py                 # FastAPI 앱 — 세션 CRUD, 파일 서빙, 프레임 추출, 공유
├── config.py              # 환경변수 → 설정 (data_root, secret_key 등)
├── storage.py             # 세션 디스크 I/O — 목록, 메타 로드, zip 생성/추출
│
├── db.py                  # SQLite — user_version 마이그레이션 래더
├── users.py               # 사용자 CRUD
├── tokens.py              # per-user API 토큰
├── web_sessions.py        # 웹 쿠키 세션
├── session_owners.py      # 세션 소유권 매핑
├── session_tags.py        # 세션 태그
├── shares.py              # 익명 공유 토큰
├── settings_store.py      # 서버 설정 key-value
├── audit.py               # 감사 로그
├── lockout.py             # 로그인 시도 제한
│
├── auth.py                # 인증 미들웨어 (cookie → API token → legacy token)
├── bootstrap.py           # 첫 부팅 시 관리자 계정 생성
│
├── uploads.py             # 청크 업로드 관리
├── thumbnails.py          # 세션 썸네일 생성
├── retention.py           # 보존 정책 실행
├── view_helpers.py        # 경로 탐색 방지 + 파일 서빙
├── regen_viewers.py       # viewer.html 일괄 재생성
│
├── routes/
│   ├── api_auth.py        # /api/auth/* — 로그인, 등록, 토큰 발급
│   ├── api_admin.py       # /api/admin/* — 사용자/설정/감사/정리
│   └── web.py             # 웹 UI 라우트 (Jinja2 템플릿)
│
├── templates/             # Jinja2 HTML 템플릿
├── static/                # CSS + JS
└── cli.py                 # reset-password CLI
```

### 주요 API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/sessions` | 세션 목록 (소유자 필터, owner/description 포함) |
| GET | `/api/sessions/{id}` | 세션 상세 (owner/description 포함) |
| POST | `/api/sessions/{id}` | 세션 업로드 (zip) |
| PATCH | `/api/sessions/{id}` | 세션 설명 수정 (`{"description": "..."}`) |
| GET | `/api/sessions/{id}/zip` | 세션 다운로드 |
| GET | `/api/sessions/{id}/files/{path}` | 개별 파일 조회 |
| GET | `/api/sessions/{id}/frame?t=N` | JPEG 프레임 추출 |
| POST | `/api/sessions/{id}/share` | 공유 토큰 발급 |
| GET | `/v/{token}/` | 공개 뷰어 (토큰 인증) |

### 인증 체인

```
요청 수신 → 쿠키 세션 확인
           ├─ 있으면 → 사용자 확인
           └─ 없으면 → X-Trailbox-Token 헤더 확인
                       ├─ per-user API 토큰 → 사용자 확인
                       └─ legacy 서비스 토큰 → 첫 번째 관리자로 매핑
```

---

## 7. 세션 데이터 구조

```
output/{session_id}/
├── screen.mp4                    # 영상+오디오 (post-mux 후 최종)
├── .uploaded                     # Hub 업로드 완료 마커 (빈 파일)
├── logs/
│   ├── logs.jsonl                # 게임 로그 (t_video_s, level, message)
│   ├── logcat.jsonl              # Android logcat (있을 경우)
│   ├── logs.vtt                  # WebVTT 자막
│   └── raw/                      # 원본 로그 파일 복사
├── inputs/
│   ├── inputs.jsonl              # 키보드/마우스 (t_video_s, type, key/pos)
│   └── inputs.vtt
├── metrics/
│   ├── process.jsonl             # 1Hz 텔레메트리
│   └── frames.jsonl              # 프레임 타이밍 (delta_ms)
├── viewer.html                   # 자립형 뷰어 (JSON 인라인)
└── session_meta.json             # 메타데이터 스냅샷
```

### process.jsonl 샘플

```json
{
  "@timestamp": "2026-05-23T11:49:43.944Z",
  "t_video_s": 1.045,
  "process": {
    "cpu_pct": 32.1,
    "cpu_pct_per_core": 128.4,
    "rss_mb": 270.3,
    "vms_mb": 123.7,
    "threads": 51,
    "handles": 2101,
    "gpu_pct": 45.0,
    "gpu_vram_mb": 2048.0,
    "gpu_engines": {"3D": 45.0, "VideoDecode": 12.1}
  },
  "ecs": {"version": "8.11"}
}
```

### session_meta.json 주요 필드

```json
{
  "session_id": "aurora_20260523_114108",
  "exe_path": "C:\\Games\\Aurora\\Aurora.exe",
  "started_at": "2026-05-23T11:41:08",
  "duration_seconds": 487.2,
  "screen_frames": 14610,
  "effective_fps": 30.0,
  "frame_stats": { "intervals": 14609, "avg_ms": 33.3, "p95_ms": 35.1, "p99_ms": 42.0 },
  "log_lines": 4281,
  "input_events": 12840,
  "metric_samples": 487,
  "metrics_target_name": "Aurora.exe",
  "system": {
    "os": { "platform": "Windows-11-10.0.26200-SP0" },
    "cpu": { "name": "AMD Ryzen 7 5800X3D", "logical_cores": 16 },
    "gpus": ["NVIDIA GeForce RTX 4080"],
    "ram": { "total_mb": 32768 }
  }
}
```

---

## 8. 동기화 흐름

```
                    ┌──────────────────────────────┐
                    │   앱 시작                      │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │  sync queue 실행              │
                    │  .uploaded 마커 없는 세션 탐색  │
                    │  → Hub에 순차 업로드            │
                    │  → 성공 시 .uploaded 마커 생성  │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │  cleanup 실행 (정책에 따라)     │
                    │  keep: 아무것도 안 함           │
                    │  when_synced: 즉시 삭제        │
                    │  after7d/30d: 마커 mtime 기준  │
                    └──────────────────────────────┘

녹화 종료 시:
  auto-upload ON → hub_upload 호출 → .uploaded 마커 생성
  auto-upload OFF → 로컬에만 저장 (다음 앱 시작 시 sync queue에서 처리)

다운로드 (Hub → 로컬):
  hub_download → zip 스트리밍 → output/{session_id}/ 추출 → .uploaded 마커 생성
```

---

## 9. 빌드 파이프라인

```
build.py
  │
  ├─ PyInstaller --onedir  main.py           → dist/Trailbox/        (GUI 번들)
  ├─ PyInstaller --onefile  mcp_entry.py     → dist/Trailbox-mcp.exe
  ├─ PyInstaller --onefile  hub_entry.py     → dist/Trailbox-hub.exe
  ├─ PyInstaller --onefile  bridge_entry.py  → dist/trailbox-bridge.exe
  └─ ISCC.exe installer/Trailbox-installer.iss → dist/Trailbox-Setup.exe

desktop-tauri/
  └─ npm run tauri:build
       ├─ vite build (React → dist/)
       └─ cargo build --release (Rust → trailbox-desktop.exe)

릴리즈:
  1. __version__ (main.py) + MyAppVersion (installer .iss) 범프
  2. 커밋 + 태그 (vX.Y.Z) + 푸시
  3. build.py 실행
  4. npm run tauri:build 실행
  5. trailbox-desktop.exe → dist/ 복사
  6. ISCC 인스톨러 빌드
  7. gh release create/upload
```

---

## 10. 배포 환경

| 환경 | 구성 | 비고 |
|------|------|------|
| **데스크톱** | Trailbox-Setup.exe 설치 | trailbox-desktop.exe + trailbox-bridge.exe |
| **MCP** | Trailbox-mcp.exe 단독 | Claude Desktop/Code에서 stdio 연결 |
| **Hub (Windows)** | Trailbox-hub.exe 단독 | 콘솔 앱, LAN 배포용 |
| **Hub (Docker)** | docker-compose.hub.yml | Synology NAS 등 Linux 환경 |
| **Hub (외부)** | Caddy 리버스 프록시 | Caddyfile 참조 |
