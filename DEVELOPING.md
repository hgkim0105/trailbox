# DEVELOPING — Trailbox 개발자 가이드

엔드유저 가이드는 [README.md](README.md), 운영자 가이드는 [DEPLOYMENT.md](DEPLOYMENT.md). 여기는 소스에서 빌드하거나, 기여하거나, Hub / MCP / 스키마를 *정확히* 이해해야 할 때 보는 문서.

---

## 소스 셋업

요구사항: Python 3.11+, Windows 10 1903+. venv 권장.

```powershell
git clone https://github.com/hgkim0105/trailbox.git
cd trailbox
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

실행:

```powershell
# GUI
.\.venv\Scripts\python.exe main.py

# MCP 서버 (stdio)
.\.venv\Scripts\python.exe -m mcp_server

# Hub 서버 (uvicorn)
$env:TRAILBOX_HUB_TOKEN = "<token>"
.\.venv\Scripts\python.exe -m hub_server
```

테스트 스위트는 없음. 검증은 GUI 띄워서 직접 녹화하거나, `output/{session_id}/` 폴더를 들여다보거나, `mcp_server` 도구를 호출하는 식.

---

## 빌드

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe build.py
```

결과 (`dist/` 폴더):

| 파일 | 크기 | 진입점 | 용도 |
|---|---|---|---|
| `Trailbox.exe` | ~125 MB | `main.py` (`--windowed`) | GUI |
| `Trailbox-mcp.exe` | ~43 MB | `mcp_entry.py` (`--console`) | MCP stdio (env 으로 로컬/Hub 분기) |
| `Trailbox-hub.exe` | ~43 MB | `hub_entry.py` (`--console`) | Hub 서버 단일 .exe |
| `Trailbox-Setup.exe` | ~212 MB | Inno Setup 6 | 위 3개를 통합한 인스톨러 |

`build.py` 는 PyInstaller 로 3개 .exe 를 빌드한 뒤, Inno Setup 의 `ISCC.exe` 가 PATH 또는 `%LOCALAPPDATA%\Programs\Inno Setup 6\` 에 있으면 인스톨러도 자동 빌드. 없으면 skip (3개 .exe 만 나옴).

ffmpeg 바이너리는 `imageio-ffmpeg` 가 번들 — `Trailbox.exe` 는 녹화에, `Trailbox-mcp.exe` / `Trailbox-hub.exe` 는 `get_frame_at` 프레임 추출에 사용.

---

## 출력 구조

```
output/{session_id}/        # session_id = "{safe_app_name}_{YYYYMMDD_HHMMSS}"
├── screen.mp4              # H.264 + AAC, VFR (post_mux 결과)
├── logs/
│   ├── logs.jsonl          # ECS-style 한 줄 한 이벤트
│   ├── logs.vtt            # WebVTT 자막 (브라우저 토글 가능)
│   └── raw/<원본>           # 감시 폴더의 원본 파일 통째 아카이브
├── inputs/
│   ├── inputs.jsonl        # 키·마우스 (mousemove는 100ms 다운샘플)
│   └── inputs.vtt
├── metrics/
│   ├── process.jsonl       # CPU%, GPU%, RSS, VRAM, threads, handles (1Hz)
│   └── frames.jsonl        # 매 프레임 t_video_s + delta_ms
├── viewer.html             # 자체완결 통합 뷰어
└── session_meta.json       # 메타 + system 정보 + frame_stats
```

### JSONL 한 줄 예시 (모두 ECS-style)

로그:
```json
{"@timestamp":"2026-05-15T12:23:20.380988Z","t_video_s":9.765,"log":{"file":{"path":"launcher_log.txt"}},"message":"[INFO] PlaySession.cpp ...","ecs":{"version":"8.11"}}
```

입력:
```json
{"@timestamp":"2026-05-15T12:31:32.919990Z","t_video_s":1.225,"input":{"type":"mouse","action":"click","button":"left","pressed":true,"x":1232,"y":1616,"window_x":1232,"window_y":566},"ecs":{"version":"8.11"}}
```

메트릭 (`cpu_pct`는 시스템 전체 대비 정규화 / `cpu_pct_per_core`는 raw / `gpu_pct`는 Task Manager 컨벤션의 busiest-engine):
```json
{"@timestamp":"...","t_video_s":28.4,"process":{"cpu_pct":58.28,"cpu_pct_per_core":1165.6,"rss_mb":2616.9,"threads":81,"handles":1570,"gpu_pct":92.4,"gpu_vram_mb":6840.2,"gpu_engines":{"3D":92.4,"Copy":0.3}},"ecs":{"version":"8.11"}}
```

프레임 타이밍:
```json
{"@timestamp":"...","t_video_s":1.234,"frame":{"index":74,"delta_ms":16.7},"ecs":{"version":"8.11"}}
```

모든 JSONL 라인은 **`@timestamp` (UTC ISO)** 와 **`t_video_s` (영상 시작 기준 초)** 를 공유. `t_video_s` 가 핵심 동기화 키 — 모든 viewer 와 MCP 도구가 이 필드로 시간축 정렬합니다.

---

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
├── process_detector.py       # 로그 폴더 ↔ 프로세스 양방향 매칭
├── viewer_generator.py       # session 폴더로부터 viewer.html 생성
├── hub_client.py             # Hub HTTP 클라이언트 (업로드/다운로드/공유, 청크 재개)
├── hub_config.py             # Hub URL + 토큰 QSettings 영속화
└── frame_extractor.py        # ffmpeg 단일 프레임 JPEG 추출 (local + hub 양쪽 공유)
hub_server/                   # FastAPI Hub 서버 (Trailbox-hub.exe)
├── __main__.py               # uvicorn 진입점
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
installer/
└── Trailbox-installer.iss    # Inno Setup 6 스크립트 (컴포넌트 선택 + Hub config 위저드)
```

### 단일 룰

> **모든 레코더는 `TrailboxWindow._on_start_requested` 가 캡처한 단일 `t0_perf` 기준으로 동작하고, 모든 JSONL 라인에 `t_video_s = perf_counter() - t0_perf` 를 기록.**

이게 영상·로그·입력·메트릭의 시간축 정렬을 만드는 유일한 규칙. 새 레코더를 추가할 거면 반드시 `t0_perf` 인자를 받아 `t_video_s` 를 같은 형식으로 emit 해야 함. 안 그러면 viewer / MCP 의 시간 동기화가 깨짐.

### Screen capture: 두 백엔드, 하나의 ffmpeg 파이프

`core/screen_recorder.py` 가 `CaptureTarget` 디스크리미네이티드 유니온으로 분기:

- `MonitorTarget(index)` → **dxcam** (DXGI Desktop Duplication). Pull 모델
- `WindowTarget(hwnd, title)` → **windows-capture** (WGC). Push 모델

둘 다 같은 ffmpeg 서브프로세스에 frame 을 던짐. **ffmpeg 옵션 `-use_wallclock_as_timestamps 1 + -fps_mode passthrough` 가 핵심** — 새 frame 이 올 때만 ffmpeg stdin 에 씀 (`max_fps` 캡 적용). 고정 cadence ticker 절대 도입 금지 (예전에 introduce 한 적 있었고 dup-frame judder 가 났음).

### COM 스레딩 순서 (import 순서 버그)

`main.py` 에서 `core.screen_recorder` (dxcam → comtypes 가져옴) 가 `core.audio_recorder` (soundcard) **보다 먼저** 임포트 되어야 함. soundcard 가 다른 threading 모드로 COM 초기화하기 때문 — 순서 바뀌면 `OSError WinError -2147417850` 뜸. main.py 임포트 순서에 보호 코멘트 있음, 변경 금지.

---

## Hub Server REST API

서버 코드는 `hub_server/app.py`. 모든 `/api/*` 는 `X-Trailbox-Token` 헤더 필수 (단, `/healthz` 제외). `/v/{token}/*` 는 URL 의 토큰이 인증.

| 메서드 + 경로 | 용도 |
|---|---|
| `GET /healthz` | 상태 (인증 X) |
| `GET /api/sessions` | 목록 |
| `GET /api/sessions/{id}` | 단건 메타 |
| `POST /api/sessions/{id}` | 업로드 (multipart, 단일 zip) |
| `GET /api/sessions/{id}/zip` | zip 다운로드 |
| `DELETE /api/sessions/{id}` | 삭제 (공유 토큰 cascade revoke) |
| `POST /api/sessions/{id}/share` | 공유 토큰 발급 |
| `GET /api/sessions/{id}/shares` | 활성 토큰 조회 |
| `DELETE /api/shares/{token}` | 토큰 폐기 |
| `GET /v/{token}` · `GET /v/{token}/{path}` | 브라우저 뷰어 (mp4 Range 지원) |
| `POST /api/uploads` | 청크 업로드 세션 시작 |
| `GET /api/uploads/{upload_id}` | 진행률 조회 (재개용) |
| `PUT /api/uploads/{upload_id}?offset=N` | 청크 PUT (offset 드리프트 시 409 → 재조회) |
| `POST /api/uploads/{upload_id}/complete` | 완료 + ingest |
| `DELETE /api/uploads/{upload_id}` | 폐기 |
| `GET /api/sessions/{id}/files/{path}` | (MCP backend) 임의 파일 fetch |
| `GET /api/sessions/{id}/frame?t=N` | (MCP backend) ffmpeg 프레임 추출 |
| `POST /api/admin/prune?dry_run=` | 만료 정책 수동 트리거 / 미리보기 |

### Hub 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `TRAILBOX_HUB_TOKEN` | (없음) | API 토큰. 미설정이면 인증 비활성화 + 0.0.0.0 바인드 거부 |
| `TRAILBOX_HUB_DATA` | `hub_data` | 세션 저장 루트 |
| `TRAILBOX_HUB_HOST` | `127.0.0.1` | 바인드 호스트. LAN 전체 노출은 `0.0.0.0` |
| `TRAILBOX_HUB_PORT` | `8765` | 바인드 포트 |
| `TRAILBOX_HUB_MAX_UPLOAD_MB` | `8192` | 단일 세션 업로드 캡 |
| `TRAILBOX_HUB_RETENTION_DAYS` | `0` (영구) | N일 지난 세션 자동 삭제 (1h cadence sweep) |

### Hub 저장 레이아웃

```
hub_data/
├── _tokens.json              # 공유 토큰 → session_id 매핑 (atomic write)
├── _uploads/{upload_id}/     # 청크 누산 중 (완료 시 ingest 후 정리)
└── {session_id}/             # output/ 구조 그대로 (viewer.html 포함)
```

DB 없음. flat files + filesystem enumeration. `is_valid_session_id` 가 `_` 시작 이름을 거부하므로 hub-internal 디렉토리는 세션 목록에 안 끼임.

운영 도구:

```powershell
# viewer 템플릿 변경 후 모든 업로드된 세션 viewer.html 일괄 재생성
python -m hub_server.regen_viewers
```

---

## MCP 서버

`mcp_server/__main__.py` — FastMCP stdio 서버. 7개 read-only 도구. **백엔드는 환경변수로 분기**:

- `TRAILBOX_HUB_URL` 미설정 → `LocalBackend` (`output/{sid}/` 파일시스템 직접)
- 설정 → `HubBackend` (HTTP API 호출, `TRAILBOX_HUB_TOKEN` 도 함께)

두 백엔드는 동일 7개 도구 메서드를 동일 응답 스키마로 구현. 양쪽이 같은 세션에 대해 byte-identical 응답 (프레임 JPEG 포함) 을 내는지 매번 검증.

| 도구 | 용도 |
|---|---|
| `list_sessions(limit=20)` | 최신 세션 N개 요약 |
| `get_session(session_id)` | 전체 메타 + 산출물 경로/URL |
| `query_events(session_id, t_start?, t_end?, kinds?, text?, limit?)` | 로그+입력을 시간/종류/텍스트 필터 (kinds: log/input/mouse/key) |
| `get_metrics(session_id, t_start?, t_end?)` | CPU/RSS/threads 샘플 + cpu_max/avg, rss_min/max 요약 |
| `search_logs(session_id, query, limit?)` | 로그 메시지 전문 검색 |
| `get_frame_at(session_id, t_video_s)` | 단일 JPEG 프레임 (1MB 캡 자동 다운스케일) |
| `get_viewer_path(session_id)` | 로컬: 절대경로 · Hub: HTTP URL |

### 클라이언트 환경변수 (`Trailbox-mcp.exe`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `TRAILBOX_OUTPUT` | 빌드 형태에 따라 다름 | 로컬 모드 시 세션 폴더 위치. 미설정 시 frozen=`<exe_dir>/output`, 소스=`../output` |
| `TRAILBOX_HUB_URL` | (없음) | 설정 시 HubBackend 로 분기 |
| `TRAILBOX_HUB_TOKEN` | (없음) | Hub backend 의 API 토큰 |

---

## Frame extraction (MCP `get_frame_at`)

`core/frame_extractor.py` 가 local / hub 양쪽이 공유. ffmpeg 호출:

```
ffmpeg -ss <t> -i <video> -frames:v 1 -vf "scale='min(1280,iw)':-2" -q:v 5 -f image2pipe -vcodec mjpeg -
```

- **빠른 seek**: `-ss` 를 `-i` 앞에 둬서 keyframe seek. QA 리뷰엔 충분한 정확도
- **JPEG (PNG 아님)**: 4K 게임 스크린샷은 JPEG 이 PNG 보다 ~12배 작음. PNG 로 하면 Claude 의 1MB 이미지 입력 한도 초과
- **자동 다운스케일**: 1280px @ q=5 시도 → 1MB 초과시 960/720/480 으로 단계적 축소

서버사이드 ffmpeg (`/api/sessions/{id}/frame?t=`) — MCP 클라이언트가 multi-GB mp4 를 통째로 안 받아도 됨.

---

## viewer.html 생성

`core/viewer_generator.py` 가 세션 종료 시 호출됨. 한 번 생성한 .html 은 외부 의존성 0 으로 동작:

- `screen.mp4` / `logs.vtt` / `inputs.vtt` 는 **상대경로 `<track>`**
- 모든 JSONL 이벤트는 **inline `<script type="application/json">`** (브라우저는 file:// 에서 fetch() 가 막힘, JSON 인라인은 OK)
- 템플릿에서 `__SESSION_ID__` / `__EVENTS_JSON__` / `__META_JSON__` / `__METRICS_JSON__` / `__TRACKS_HTML__` 토큰 치환 (`.format()` 아님 — JS/CSS 안에 `{}` 많아서 충돌)

VTT 트랙은 브라우저 자막 토글로 켤 수 있게 남겨두고, JS 의 `forceHideOverlayTracks()` 가 페이지 로드 시 `track.mode = 'hidden'` 강제. 안 그러면 HTTP 서빙 (Hub) 환경에서 cue 가 영상 위에 오버레이로 떠 보임.

---

## Inno Setup 인스톨러

`installer/Trailbox-installer.iss` — Inno Setup 6 PascalScript.

핵심:
- **Components**: `gui` (required) + `mcp` (optional) + `hub` (optional)
- **Custom Hub config 페이지**: `wpSelectComponents` 뒤에 CreateCustomPage. URL/Token 필드 + Generate 버튼 (32자 URL-safe random) + 클립보드 복사 (clip.exe round-trip — PascalScript 에 native 클립보드 helper 없음)
- **Registry 자동 기록**: 입력값을 `HKCU\Software\Trailbox\Trailbox\hub\{url,token}` 에 쓰기 — QSettings 가 이걸 읽음
- **start-hub.bat 자동 생성**: Hub 컴포넌트 선택 시, 토큰을 baked-in 한 .bat 파일 생성
- **`hub-token.txt`**: admin 이 팀에 공유할 토큰 사본을 설치 폴더에 저장

빌드: `build.py` 가 ISCC.exe 자동 감지 (PATH 또는 `%LOCALAPPDATA%\Programs\Inno Setup 6\`). 미설치면 .exe 3개만 나옴, 인스톨러 skip.

---

## 빠진 부분 / 백로그

[ROADMAP.md](ROADMAP.md) 참조. 굵직한 것:

- **재시작 가능한 업로드 — 클라이언트 측 영속화**: 현재 청크 업로드는 *세션 안* 에서만 재개 가능. 크로스-프로세스 재개는 `output/{sid}/.hub_upload.json` 같은 작은 상태 파일 필요
- **공유 토큰 만료 / 1회용**: 현재는 영구
- **S3/object-store 백엔드**: `Storage` 인터페이스 분리 필요
- **`/mcp` HTTP transport 직접 노출**: 현재는 stdio 브리지 + `TRAILBOX_HUB_URL`. MCP Streamable HTTP 가 mainstream 되면 추가
- **거대 jsonl streaming**: 현재 `_iter_jsonl` 가 `read_text().splitlines()` — 100MB 로그면 메모리 폭주. 라인 단위 streaming 으로 전환

기여 환영 — PR 전 [DEVNOTES.md](DEVNOTES.md) 의 의사결정 기록 참고.
