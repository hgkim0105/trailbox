# Trailbox

Windows QA 세션 레코더 — 한 번의 녹화로 **영상·시스템 사운드·게임 로그·키보드/마우스 입력·프로세스 텔레메트리** 를 한 타임라인에 정렬해 캡처하고, 브라우저에서 통합 검토할 수 있는 데스크탑 도구.

PyQt6 기반 단일 앱. 게임/일반 앱 모두 대상.

## 무엇을 캡처하는가

| 신호 | 백엔드 | 출력 |
|---|---|---|
| 화면 (모니터 전체) | `dxcam` (DXGI Desktop Duplication) | `screen.mp4` |
| 화면 (특정 창) | `windows-capture` (Windows Graphics Capture) — 가려진 창·HW 가속 게임 OK | `screen.mp4` |
| 시스템 오디오 | `soundcard` (WASAPI loopback) | `screen.mp4` 내 AAC 스트림 |
| 게임 로그 | `watchdog` + tail-follow | `logs/logs.jsonl`, `logs/logs.vtt`, `logs/raw/` |
| 키보드 + 마우스 | `pynput` 글로벌 리스너 | `inputs/inputs.jsonl`, `inputs/inputs.vtt` |
| 프로세스 텔레메트리 (CPU + **GPU** + RAM + VRAM + threads) | `psutil` + Windows PDH (`win32pdh`) 1Hz 샘플 | `metrics/process.jsonl` |
| 프레임 타이밍 | 매 프레임 인스턴트 fps + Δ | `metrics/frames.jsonl` |
| PC 사양 스냅샷 | OS / CPU / RAM / GPU / 디스플레이 / Python / Trailbox 버전 | `session_meta.json` 의 `system` 필드 |
| 통합 뷰어 | 자체 생성 HTML | `viewer.html` |

전부 동일한 `t_video_s` (영상 시작 기준 초) 로 동기화. AI/Elasticsearch에 그대로 던지거나 viewer.html에서 사람이 보면서 검토 가능.

## 주요 특징

- **VFR 비디오 인코딩**: WGC/dxcam이 새 프레임을 줄 때만 ffmpeg에 push. 고정 fps 틱이 만들어내던 duplicate-frame judder 없음. ffmpeg `-use_wallclock_as_timestamps 1`로 실제 도착 시각 PTS 보존.
- **창 자동 매칭**: 로그 폴더 입력 → 그 폴더에 쓰는 프로세스 자동 감지 → 창 자동 선택. 부모 프로세스 트리도 탐색해서 런처가 로그를 쓰는 케이스(AC Odyssey ↔ Ubisoft Connect 등) 대응.
- **로그 폴더 자동 추론**: 창 선택 → 실행 파일 추론 → 컨벤션 폴더(`<install>/Logs`, `Saved/Logs`, `%LOCALAPPDATA%/<app>/Logs` 등) 자동 검색.
- **창 선택 UX**: 콤보박스 / 🎯 클릭 픽업 / `Ctrl+Shift+P` 전역 단축키 (게임 풀스크린 안에서도 사용 가능).
- **자체완결 뷰어**: 세션 폴더 통째 압축해 다른 PC로 보내면 `viewer.html` 더블클릭만으로 모두 재생됨. 외부 의존 0.

## 설치

요구사항: Windows 10 1903 이상.

### A. 바이너리 (권장 — 일반 사용자)

[Releases 페이지](https://github.com/hgkim0105/trailbox/releases/latest) 에서 필요한 파일을 받아 **같은 폴더**에 두세요:

- **`Trailbox.exe`** (~125 MB) — GUI 본체 (녹화·뷰어 생성). 항상 필요
- **`Trailbox-mcp.exe`** (~43 MB) — MCP 서버 (AI 연동용). AI에서 세션 분석할 때만 필요
- **`Trailbox-hub.exe`** (~43 MB) — Hub 서버 (세션 공유·원격 MCP). 세션을 다른 사람/AI 와 공유할 때만 필요. [Trailbox Hub 섹션](#trailbox-hub--세션-공유--원격-분석) 참조

Python 설치 불필요. `Trailbox.exe` 더블클릭으로 GUI 실행. 첫 실행 시 PyInstaller 가 의존성을 임시 폴더에 풀어 5~10초 소요 — 이후 실행은 빠릅니다. 녹화 결과는 `Trailbox.exe` 와 같은 폴더의 `output/` 에 쌓이며, `Trailbox-mcp.exe` 가 자동으로 같은 폴더의 `output/` 을 읽습니다.

### B. 소스 설치 (개발자 / MCP 서버 사용)

Python 3.11+ 필요. venv 권장.

```powershell
git clone https://github.com/hgkim0105/trailbox.git
cd trailbox
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 실행

### A. 바이너리 — `Trailbox.exe` 더블클릭

### B. 소스

```powershell
.\.venv\Scripts\python.exe main.py
```

### 사용 흐름 (양쪽 동일)

1. **캡처 대상** 선택 — `전체 모니터` 또는 `특정 창 (WGC)` (창 선택 시 콤보/🎯 클릭 픽업/`Ctrl+Shift+P` 전역 단축키 중 택일)
2. (선택) **실행 파일** + **로그 폴더** — 둘 중 하나만 입력해도 다른 쪽 자동 추론 시도
3. **시스템 사운드 녹음** · **키보드/마우스 입력 기록** · **프로세스 텔레메트리** 토글 (기본 모두 ON)
4. **최대 fps** 선택 (10/15/24/30/60, 기본 60). VFR이라 실제 fps는 소스 따라 변함
5. **녹화 시작** → 녹화 → **녹화 종료**
6. **📂 세션 뷰어 열기…** → 목록에서 골라 더블클릭하면 브라우저로 통합 뷰어 열림

### 바이너리 빌드 (개발자용)

소스에서 자체적으로 바이너리를 빌드하려면:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe build.py
```

결과: `dist/Trailbox.exe` (GUI, ~125 MB), `dist/Trailbox-mcp.exe` (MCP, ~43 MB), `dist/Trailbox-hub.exe` (Hub, ~43 MB).

## 출력 구조

```
output/{session_id}/
├── screen.mp4              # H.264 + AAC, VFR
├── logs/
│   ├── logs.jsonl          # ECS-style 한 줄 한 이벤트 (@timestamp, t_video_s, log.file.path, message)
│   ├── logs.vtt            # WebVTT 자막 (영상에 오버레이 가능)
│   └── raw/<원본>           # 감시 폴더의 원본 파일 통째 아카이브
├── inputs/
│   ├── inputs.jsonl        # 키·마우스 이벤트 (이동은 100ms 다운샘플)
│   └── inputs.vtt
├── metrics/
│   ├── process.jsonl       # CPU%, GPU%, RSS, VRAM, threads, handles (1Hz)
│   └── frames.jsonl        # 매 프레임 t_video_s + delta_ms (인스턴트 fps)
├── viewer.html             # 단일 파일 통합 뷰어
└── session_meta.json       # 메타 + system 정보 + frame_stats
```

`session_id` 형식: `{앱명}_{YYYYMMDD_HHMMSS}` (예: `ACOdyssey_20260515_213131`)

### JSONL 한 줄 예시 (모두 ECS-style)

로그:
```json
{"@timestamp":"2026-05-15T12:23:20.380988Z","t_video_s":9.765,"log":{"file":{"path":"launcher_log.txt"}},"message":"[INFO] PlaySession.cpp ...","ecs":{"version":"8.11"}}
```

입력:
```json
{"@timestamp":"2026-05-15T12:31:32.919990Z","t_video_s":1.225,"input":{"type":"mouse","action":"click","button":"left","pressed":true,"x":1232,"y":1616,"window_x":1232,"window_y":566},"ecs":{"version":"8.11"}}
```

메트릭 (CPU%는 시스템 전체 대비 정규화 / `cpu_pct_per_core`는 raw / `gpu_pct`는 Task Manager 컨벤션의 busiest-engine):
```json
{"@timestamp":"...","t_video_s":28.4,"process":{"cpu_pct":58.28,"cpu_pct_per_core":1165.6,"rss_mb":2616.9,"threads":81,"handles":1570,"gpu_pct":92.4,"gpu_vram_mb":6840.2,"gpu_engines":{"3D":92.4,"Copy":0.3}},"ecs":{"version":"8.11"}}
```

프레임 타이밍:
```json
{"@timestamp":"...","t_video_s":1.234,"frame":{"index":74,"delta_ms":16.7},"ecs":{"version":"8.11"}}
```

## 통합 뷰어 (`viewer.html`)

세션 종료 시 자동 생성되는 단일 HTML 파일. 폴더에서 더블클릭하면 기본 브라우저로 열림.

- 좌측: HTML5 비디오 (`logs.vtt`/`inputs.vtt` 가 자막 트랙으로 자동 표시 — 토글 가능)
- 우측 상단: 통합 라인 차트 — **CPU**(빨강) / **GPU**(초록) / **RSS**(파랑) / **VRAM**(보라) / **fps**(노랑) 5개 라인 + 영상 playhead 수직선
- 우측 중간: logs + inputs 통합 타임라인 (필터 / 검색 / 행 클릭 → 그 시점 점프 + 재생)
- 헤더 summary: events 수, duration, frames, effective_fps, **Δ avg/p99**, cores 등 한눈 요약
- 헤더 `PC 사양 ▶` 토글: OS / CPU / RAM / GPU / Display(해상도+scaling) / Python / Trailbox 버전

## 아키텍처

```
main.py                       # PyQt6 진입점, 세션 라이프사이클 오케스트레이션
hub_entry.py                  # Trailbox-hub.exe 진입점 (Qt/캡처 없는 순수 서버)
mcp_entry.py                  # Trailbox-mcp.exe 진입점 (stdio)
ui/
├── launcher_panel.py         # 캡처 대상 / 자동감지 / fps · audio · input · metrics 토글
├── recorder_panel.py         # 녹화 시작/종료 + 허브 자동 업로드 토글
├── session_picker.py         # 로컬 세션 목록 + 허브 업로드/공유링크/가져오기 버튼
├── hub_dialogs.py            # Hub 설정 / 업로드 진행률 / 공유링크 모달
└── remote_session_picker.py  # Hub 원격 세션 목록 + 다운로드
core/
├── session.py                # session_id, 출력 폴더, session_meta.json
├── screen_recorder.py        # dxcam / WGC 백엔드, ffmpeg VFR 파이프
├── audio_recorder.py         # WASAPI loopback → WAV
├── post_mux.py               # ffmpeg로 video+audio → screen.mp4
├── log_collector.py          # watchdog tail-follow → jsonl + vtt
├── input_recorder.py         # pynput 글로벌 리스너 → jsonl + vtt
├── metrics_recorder.py       # psutil + GPU 1Hz 샘플 → metrics/process.jsonl
├── gpu_monitor.py            # PDH(win32pdh) 기반 per-PID GPU% + VRAM (vendor-agnostic)
├── system_info.py            # OS/CPU/RAM/GPU/디스플레이 스냅샷 (세션 시작 시)
├── window_picker.py          # 보이는 top-level 창 열거 (psutil로 exe 보강)
├── window_clicker.py         # 클릭 픽업 + Ctrl+Shift+P 단축키
├── process_detector.py       # 로그 폴더 ↔ 프로세스 양방향 매칭 (open_files + install heuristic + parent walk)
├── viewer_generator.py       # session 폴더로부터 viewer.html 생성
├── hub_client.py             # Hub HTTP 클라이언트 (업로드/다운로드/공유, 청크 재개)
├── hub_config.py             # Hub URL + 토큰 QSettings 영속화
└── frame_extractor.py        # ffmpeg 단일 프레임 JPEG 추출 (local + hub 양쪽 공유)
hub_server/                   # FastAPI Hub 서버 (Trailbox-hub.exe)
├── __main__.py               # uvicorn 진입점 (TRAILBOX_HUB_HOST/PORT/TOKEN 등 env)
├── app.py                    # 라우트 — REST + /v 뷰어 + /api/uploads 청크 + /api/admin
├── auth.py                   # X-Trailbox-Token 헤더 검증
├── config.py                 # 환경변수 → HubConfig 데이터클래스
├── storage.py                # hub_data/{sid}/ 디스크 저장 + zip ingest/stream
├── shares.py                 # 공유 토큰 ↔ session_id 매핑 (atomic JSON 파일)
├── uploads.py                # 재개 가능 청크 업로드 누산기
├── retention.py              # TTL 기반 background sweep (1h cadence)
└── regen_viewers.py          # 일괄 viewer.html 재생성 (운영 도구)
mcp_server/
├── __main__.py               # MCP 서버 (stdio) — 7개 도구 등록 + 백엔드 dispatch
└── backends/
    ├── local.py              # output/{sid}/ 파일시스템 백엔드 (기본)
    └── hub.py                # Hub HTTP 백엔드 (TRAILBOX_HUB_URL 설정 시)
```

## MCP 서버 (AI에서 세션 분석)

녹화한 세션을 AI 가 직접 들여다보고 질문에 답하게 할 수 있는 MCP (Model Context Protocol) 서버가 들어 있습니다. **읽기 전용 분석 도구**가 7개 노출됩니다 (캡처 제어는 미포함).

### 노출 도구

| 도구 | 용도 |
|---|---|
| `list_sessions(limit=20)` | 최신 세션 N개 요약 (id, 시작 시각, duration, log/input/frame 카운트 등) |
| `get_session(session_id)` | 전체 메타 + 산출물 파일 절대경로들 |
| `query_events(session_id, t_start?, t_end?, kinds?, text?, limit?)` | 로그+입력을 시간/종류/텍스트로 필터 (kinds: log/input/mouse/key) |
| `get_metrics(session_id, t_start?, t_end?)` | CPU/RSS/threads 샘플 + 윈도우 내 cpu_max/avg, rss_min/max 요약 |
| `search_logs(session_id, query, limit?)` | 로그 메시지 전문 검색 |
| `get_frame_at(session_id, t_video_s)` | 영상에서 단일 프레임을 JPEG 로 추출 (ffmpeg seek + JPEG, 1MB 캡 자동 다운스케일) |
| `get_viewer_path(session_id)` | `viewer.html` 경로/URL (로컬 모드: 절대경로, Hub 모드: HTTP URL) |

모든 이벤트는 `t_video_s` 필드를 공유해서 AI 가 "12.3초 시점에 무슨 일?" 같이 시간축 기반으로 통합 질의 가능.

### 로컬 모드 vs Hub 모드

`Trailbox-mcp.exe` 는 환경변수 하나로 백엔드가 갈립니다:

| 환경변수 | 동작 |
|---|---|
| (미설정) | **로컬 모드** — `output/{session_id}/` 파일시스템 직접 읽기 |
| `TRAILBOX_HUB_URL` 설정 | **Hub 모드** — 원격 Hub HTTP API 로 같은 7개 도구 동작 |

Hub 모드에서는 `TRAILBOX_HUB_TOKEN` 도 함께 설정해야 인증됩니다. 자세한 건 [Trailbox Hub 섹션](#trailbox-hub--세션-공유--원격-분석).

### 실행

stdio 트랜스포트 — 보통은 MCP 클라이언트(Claude Desktop 등)가 subprocess 로 자동으로 띄웁니다. 직접 실행할 일은 없습니다.

### Claude Desktop / Claude Code 등록

`%APPDATA%\Claude\claude_desktop_config.json` (Claude Desktop) 또는 Claude Code 설정에 추가.

**바이너리 사용자 (A 설치 방식)** — `Trailbox-mcp.exe` 경로만 지정하면 자동으로 옆 폴더의 `output/` 을 읽습니다:

```json
{
  "mcpServers": {
    "trailbox": {
      "command": "C:\\path\\to\\Trailbox-mcp.exe"
    }
  }
}
```

**소스 사용자 (B 설치 방식)** — venv 의 python.exe 로 모듈 실행:

```json
{
  "mcpServers": {
    "trailbox": {
      "command": "C:\\path\\to\\trailbox\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server"],
      "env": {
        "TRAILBOX_OUTPUT": "C:\\path\\to\\trailbox\\output"
      }
    }
  }
}
```

`TRAILBOX_OUTPUT` 환경변수로 분석 대상 폴더를 명시적으로 지정 가능합니다. 미지정 시:
- 바이너리 빌드: `Trailbox-mcp.exe` 가 있는 폴더의 `output/`
- 소스 실행: `mcp_server/` 모듈 위치 기준 `../output`

설정 후 Claude Desktop / Claude Code 재시작하면 `list_sessions` 등 6개 도구가 자동 인식됩니다.

### 활용 예시

AI 에 던지는 질문 예:
- "최근 세션에서 CPU 50% 넘긴 구간 알려줘"
- "이 세션 12~15초 사이에 무슨 입력이 있었나"
- "logs 에서 'error' 들어간 라인만 영상 타임코드와 같이 보여줘"
- "최근 5개 세션 중 RSS 가장 많이 늘어난 세션은?"

## Trailbox Hub — 세션 공유 + 원격 분석

녹화한 세션을 *링크로 공유* 하거나 *AI가 원격으로 조회* 할 수 있는 단일 파일 웹 서비스. Hub 는 옵션 — 안 깔아도 모든 기존 기능 정상 동작.

### 왜 Hub가 필요한가

| 시나리오 | Hub 없이 | Hub로 |
|---|---|---|
| 다른 사람에게 세션 보여주기 | 폴더 통째 zip → 전송 → 압축풀기 → viewer.html 더블클릭 | 「공유 링크」 버튼 → URL 복사 → 붙여넣기 |
| AI 가 원격 세션 분석 | 불가 (로컬 파일만 봄) | `TRAILBOX_HUB_URL` 만 설정하면 동일 7개 도구 그대로 |
| 자동 백업 / 보존 | 수동 | 녹화 종료 시 자동 업로드 + N일 만료 정책 |

`viewer.html` 이 이미 *자체완결형* 이라 Hub 서버는 "세션 폴더를 HTTP 로 서빙" 만 하면 됨. 별도 백엔드 거의 없이 동작.

### 빠른 시작 — 같은 PC (LAN-only)

[Releases](https://github.com/hgkim0105/trailbox/releases/latest) 에서 `Trailbox-hub.exe` 추가로 받아 같은 폴더에 두기.

**1. 토큰 생성** (PowerShell 한 줄):

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | % {[char]$_})
```

**2. `start-hub.bat` 만들기** (Trailbox-hub.exe 옆에):

```bat
@echo off
set TRAILBOX_HUB_TOKEN=여기에-1번에서-생성한-토큰
set TRAILBOX_HUB_DATA=D:\trailbox\hub_data
set TRAILBOX_HUB_HOST=127.0.0.1
set TRAILBOX_HUB_PORT=8765
set TRAILBOX_HUB_RETENTION_DAYS=30
"D:\trailbox\Trailbox-hub.exe"
pause
```

더블클릭 → `Trailbox Hub serving ... (auth=on)` 출력되면 성공. 콘솔 창은 그대로 두기 (닫으면 서버 종료). 부팅 시 자동 실행하려면 `shell:startup` 폴더에 바로가기 등록.

**3. Trailbox 클라이언트 연결**:
1. `Trailbox.exe` → **세션 뷰어 열기…** → **허브 설정** → URL `http://127.0.0.1:8765` + 토큰 입력 → **연결 테스트** 「OK」 확인
2. 메인 화면 **「녹화 종료 시 허브 자동 업로드」** 체크 (선택)
3. 짧게 녹화 → 자동 업로드 모달 뜨면 완료
4. 세션 뷰어 → 세션 선택 → **공유 링크** → URL 클립보드 자동 복사 → 다른 브라우저에 붙여넣기

**4. AI MCP Hub 모드** (선택, Claude Desktop):

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trailbox": {
      "command": "D:\\trailbox\\Trailbox-mcp.exe",
      "env": {
        "TRAILBOX_HUB_URL": "http://127.0.0.1:8765",
        "TRAILBOX_HUB_TOKEN": "위와-동일한-토큰"
      }
    }
  }
}
```

`env` 블록을 빼면 자동으로 로컬 `output/` 폴더 모드로 동작 (Hub 미사용).

**다른 PC / 인터넷 / Docker / Caddy / TLS 등 자세한 배포**: [DEPLOYMENT.md](DEPLOYMENT.md)

### 환경변수 (Hub 서버)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `TRAILBOX_HUB_TOKEN` | (없음) | API 토큰. 미설정이면 인증 비활성화 + 0.0.0.0 바인드 거부 |
| `TRAILBOX_HUB_DATA` | `hub_data` | 세션 저장 루트 |
| `TRAILBOX_HUB_HOST` | `127.0.0.1` | 바인드 호스트. LAN 전체 노출은 `0.0.0.0` |
| `TRAILBOX_HUB_PORT` | `8765` | 바인드 포트 |
| `TRAILBOX_HUB_MAX_UPLOAD_MB` | `8192` | 단일 세션 업로드 캡 |
| `TRAILBOX_HUB_RETENTION_DAYS` | `0` (영구) | N일 지난 세션 자동 삭제. background sweep 1h cadence |

### REST 엔드포인트 요약

| 메서드 + 경로 | 인증 | 용도 |
|---|---|---|
| `GET /healthz` | X | 상태 확인 |
| `GET /api/sessions` | 토큰 | 세션 목록 |
| `GET /api/sessions/{id}` | 토큰 | 단건 메타 |
| `POST /api/sessions/{id}` | 토큰 | 업로드 (단일 zip) |
| `GET /api/sessions/{id}/zip` | 토큰 | zip 다운로드 |
| `DELETE /api/sessions/{id}` | 토큰 | 삭제 (공유 토큰도 cascade revoke) |
| `POST /api/sessions/{id}/share` | 토큰 | 공유 토큰 발급 |
| `GET /api/sessions/{id}/shares` | 토큰 | 활성 공유 토큰 조회 |
| `DELETE /api/shares/{token}` | 토큰 | 공유 토큰 폐기 |
| `GET /v/{token}/...` | 토큰이 URL | 브라우저 뷰어 (mp4 Range 지원) |
| `POST /api/uploads` + 4개 | 토큰 | 청크 업로드 (64MB 이상 자동 분기, 4MB 청크, 재개 가능) |
| `GET /api/sessions/{id}/files/{path}` | 토큰 | (MCP backend) 임의 파일 fetch |
| `GET /api/sessions/{id}/frame?t=N` | 토큰 | (MCP backend) ffmpeg 단일 프레임 추출 |
| `POST /api/admin/prune?dry_run=` | 토큰 | 만료 정책 수동 트리거 / 미리보기 |

### 저장 레이아웃

```
hub_data/
├── _tokens.json              # 공유 토큰 → session_id 매핑 (atomic write)
├── _uploads/{upload_id}/     # 청크 누산 중인 업로드 (완료 시 ingest 후 정리)
└── {session_id}/             # Trailbox output/ 구조 그대로 (viewer.html 포함)
```

DB 없음. **flat files + filesystem enumeration** 으로 수천 세션까지 충분. 운영 도구 `python -m hub_server.regen_viewers` 로 viewer 템플릿 변경 후 일괄 재생성 가능.

## 알려진 한계

- **DRM 보호 비디오**: Netflix 등은 영상이 검은 박스로 캡처됨 (OS/GPU 강제 출력 보호). 사운드는 정상 캡처.
- **Anti-cheat 게임**: 메모리 덤프류 작업 대부분 차단. **텔레메트리는 차단되지 않음** (perf counter는 별도 경로).
- **풀스크린 Exclusive 게임**: 대부분 WGC로 캡처되지만, 일부 타이틀은 백버퍼 접근이 제한될 수 있음. Borderless 모드 권장.
- **클로즈드 엔진 게임 로그**: AC Odyssey(Anvil), EA Frostbite 등은 디스크 로깅이 없어 런처 로그만 잡힘. UE/Unity 게임은 `Saved/Logs`/`Player.log`로 풍부.
- **`psutil.Process.open_files()` 신뢰성**: Windows에서 자주 빈 결과 — 자동 매칭은 install_dir 휴리스틱 우선, 핸들 매칭은 보조.

## 라이선스

MIT (필요 시 별도 명시)
