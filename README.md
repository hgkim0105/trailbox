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
| 프로세스 텔레메트리 | `psutil` 1Hz 샘플 | `metrics/process.jsonl` |
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

[Releases 페이지](https://github.com/hgkim0105/trailbox/releases/latest) 에서 **`Trailbox.exe`** 를 받으세요. Python 설치 불필요, ffmpeg/PyQt6 모두 단일 파일에 포함 (약 120 MB).

다운로드 후 임의의 폴더에 두고 더블클릭하면 됩니다. 첫 실행 시 PyInstaller 가 임시 폴더에 의존성을 풀어 약 5~10초 소요 — 이후 실행은 빠릅니다. 녹화 결과는 `Trailbox.exe` 와 같은 폴더의 `output/` 에 쌓입니다.

> ⚠️ MCP 서버 기능 (AI 연동) 은 현재 바이너리에 포함되지 않습니다. 그 부분이 필요하면 아래 소스 설치를 사용하세요.

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

소스에서 자체적으로 `Trailbox.exe` 를 빌드하려면:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe build.py
```

결과: `dist/Trailbox.exe` (단일 파일, ~120 MB).

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
│   └── process.jsonl       # CPU%, RSS, threads, handles (1Hz)
├── viewer.html             # 단일 파일 통합 뷰어
└── session_meta.json
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

메트릭 (CPU%는 시스템 전체 대비 정규화, `cpu_pct_per_core`는 raw 값):
```json
{"@timestamp":"2026-05-15T13:02:32.426259Z","t_video_s":28.4,"process":{"cpu_pct":58.28,"cpu_pct_per_core":1165.6,"rss_mb":2616.9,"threads":81,"handles":1570},"ecs":{"version":"8.11"}}
```

## 통합 뷰어 (`viewer.html`)

세션 종료 시 자동 생성되는 단일 HTML 파일. 폴더에서 더블클릭하면 기본 브라우저로 열림.

- 좌측: HTML5 비디오 (`logs.vtt`/`inputs.vtt` 가 자막 트랙으로 자동 표시 — 토글 가능)
- 우측 상단: CPU·RSS 라인 차트 (영상 currentTime 따라 playhead 이동, 현재값 legend)
- 우측 하단: logs + inputs 통합 타임라인 (필터 / 검색 / 행 클릭 → 그 시점 점프 + 재생)
- 헤더: 세션 요약 (events 수, duration, frames, fps, audio, log 라인, input 이벤트, cores)

## 아키텍처

```
main.py                       # PyQt6 진입점, 세션 라이프사이클 오케스트레이션
ui/
├── launcher_panel.py         # 캡처 대상 / 자동감지 / fps · audio · input · metrics 토글
├── recorder_panel.py         # 녹화 시작/종료 + 세션 뷰어 열기 버튼
└── session_picker.py         # 세션 목록 모달 (정렬·검색)
core/
├── session.py                # session_id, 출력 폴더, session_meta.json
├── screen_recorder.py        # dxcam / WGC 백엔드, ffmpeg VFR 파이프
├── audio_recorder.py         # WASAPI loopback → WAV
├── post_mux.py               # ffmpeg로 video+audio → screen.mp4
├── log_collector.py          # watchdog tail-follow → jsonl + vtt
├── input_recorder.py         # pynput 글로벌 리스너 → jsonl + vtt
├── metrics_recorder.py       # psutil 1Hz 샘플 → jsonl
├── window_picker.py          # 보이는 top-level 창 열거 (psutil로 exe 보강)
├── window_clicker.py         # 클릭 픽업 + Ctrl+Shift+P 단축키
├── process_detector.py       # 로그 폴더 ↔ 프로세스 양방향 매칭 (open_files + install heuristic + parent walk)
└── viewer_generator.py       # session 폴더로부터 viewer.html 생성
mcp_server/
└── __main__.py               # MCP 서버 (stdio) — AI용 읽기 전용 분석 도구 6종
```

## MCP 서버 (AI에서 세션 분석)

녹화한 세션을 AI 가 직접 들여다보고 질문에 답하게 할 수 있는 MCP (Model Context Protocol) 서버가 들어 있습니다. **읽기 전용 분석 도구**가 6개 노출됩니다 (캡처 제어는 미포함).

### 노출 도구

| 도구 | 용도 |
|---|---|
| `list_sessions(limit=20)` | 최신 세션 N개 요약 (id, 시작 시각, duration, log/input/frame 카운트 등) |
| `get_session(session_id)` | 전체 메타 + 산출물 파일 절대경로들 |
| `query_events(session_id, t_start?, t_end?, kinds?, text?, limit?)` | 로그+입력을 시간/종류/텍스트로 필터 (kinds: log/input/mouse/key) |
| `get_metrics(session_id, t_start?, t_end?)` | CPU/RSS/threads 샘플 + 윈도우 내 cpu_max/avg, rss_min/max 요약 |
| `search_logs(session_id, query, limit?)` | 로그 메시지 전문 검색 |
| `get_viewer_path(session_id)` | `viewer.html` 절대경로 (브라우저 열기용) |

모든 이벤트는 `t_video_s` 필드를 공유해서 AI 가 "12.3초 시점에 무슨 일?" 같이 시간축 기반으로 통합 질의 가능.

### 실행

MCP 서버는 **소스 설치(B)** 가 필요합니다. 바이너리(`Trailbox.exe`)는 GUI 만 포함합니다.

```powershell
# stdio 트랜스포트 — 보통은 MCP 클라이언트(Claude Desktop 등)가 subprocess로 띄웁니다
.\.venv\Scripts\python.exe -m mcp_server
```

### Claude Desktop / Claude Code 등록

`%APPDATA%\Claude\claude_desktop_config.json` (Claude Desktop) 또는 Claude Code 설정에 추가:

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

`command` 는 venv 의 `python.exe` 절대경로, `TRAILBOX_OUTPUT` 은 분석할 세션이 쌓이는 폴더 절대경로. 환경변수 미지정 시엔 `mcp_server/` 모듈 위치 기준 `../output` 을 자동 사용합니다.

> 💡 바이너리(`Trailbox.exe`) 로 녹화한 세션도 같은 `output/` 폴더를 가리키게 `TRAILBOX_OUTPUT` 만 설정해 주면 MCP 서버에서 그대로 조회 가능합니다 — Trailbox.exe 가 있는 폴더의 `output/` 경로로 지정하세요.

설정 후 Claude Desktop / Claude Code 재시작하면 `list_sessions` 등 6개 도구가 자동 인식됩니다.

### 활용 예시

AI 에 던지는 질문 예:
- "최근 세션에서 CPU 50% 넘긴 구간 알려줘"
- "이 세션 12~15초 사이에 무슨 입력이 있었나"
- "logs 에서 'error' 들어간 라인만 영상 타임코드와 같이 보여줘"
- "최근 5개 세션 중 RSS 가장 많이 늘어난 세션은?"

## 알려진 한계

- **DRM 보호 비디오**: Netflix 등은 영상이 검은 박스로 캡처됨 (OS/GPU 강제 출력 보호). 사운드는 정상 캡처.
- **Anti-cheat 게임**: 메모리 덤프류 작업 대부분 차단. **텔레메트리는 차단되지 않음** (perf counter는 별도 경로).
- **풀스크린 Exclusive 게임**: 대부분 WGC로 캡처되지만, 일부 타이틀은 백버퍼 접근이 제한될 수 있음. Borderless 모드 권장.
- **클로즈드 엔진 게임 로그**: AC Odyssey(Anvil), EA Frostbite 등은 디스크 로깅이 없어 런처 로그만 잡힘. UE/Unity 게임은 `Saved/Logs`/`Player.log`로 풍부.
- **`psutil.Process.open_files()` 신뢰성**: Windows에서 자주 빈 결과 — 자동 매칭은 install_dir 휴리스틱 우선, 핸들 매칭은 보조.

## 라이선스

MIT (필요 시 별도 명시)
