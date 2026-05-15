# DEVNOTES — Trailbox v0.1.1

한 세션 안에서 0에서부터 v0.1.1까지 만들면서 내린 의사결정·삽질·트레이드오프를 시간순/주제별로 정리한 기록. "왜 이렇게 짰지?"가 궁금할 때 코드 주석이 아닌 *맥락*을 찾는 용도.

## 시작 시점에 정해져 있던 것 vs 비어 있던 것

스펙으로 주어진 것:
- 플랫폼: Windows 전용, Python 3.11+, PyQt6 UI
- 캡처 신호의 *목록*: 화면·로그·메모리 덤프·입력
- 출력 컨벤션: `output/{앱명_타임스탬프}/...`
- 5단계 MVP 로드맵 (Qt 뼈대 → 세션 → 화면 → 로그 → 메모리 덤프)
- "외부 의존성 최소화, pip 만으로 셋업"

스펙에 *없던* 것 (세션 진행 중 추가 결정):
- 시스템 사운드 (요청에서 나옴 — DRM 영상이 검정으로 찍히는 걸 본 뒤)
- 영상·로그 *동기화 모델* (그냥 "로그 복사"가 스펙이었음)
- 통합 뷰어 HTML
- 프로세스 텔레메트리 (메모리 덤프 대체로 등장)
- MCP 서버
- 양방향 자동 감지 (창↔로그폴더)
- PyInstaller 릴리즈

스펙이 *손바뀜*된 것:
- "메모리 덤프" → "프로세스 텔레메트리" (Anti-cheat ROI 분석 후 사용자가 변경)
- "로그 폴더 통째 복사" → "tail-follow + 영상 동기화" (영상 싱크 중요성 인지 후)

## 단계별 진화 (이벤트 로그가 아니라 *왜* 그렇게 갔는지)

### 1. 화면 캡처: mss → dxcam → +WGC

처음엔 스펙대로 `mss` (GDI BitBlt 기반)로 시작. Netflix 녹화 검증에서 영상이 검정으로 잡혀 사용자가 의문 제기. 그 자리에서 두 가지를 구분:
- DRM (Widevine L1) — *어떤 API로도 못 뚫음*, OS/GPU 강제. 정상 동작
- HW 가속 게임 — GDI는 못 잡지만 DXGI/WGC는 잡음

→ `mss` 떼고 `dxcam` (DXGI Desktop Duplication)으로 교체. 다음 질문은 "특정 창만 캡처?" — 두 가지 경로 검토:
- dxcam region: 화면 좌표 잘라내기. occlusion 못 막음 (다른 창이 위에 오면 그게 찍힘)
- WGC (`windows-capture`): 창의 백버퍼 직접 접근. 가려져도 OK, HW 가속도 OK

WGC 단독 결정. **occlusion 안전성**이 QA 도구에 결정적 — 테스터가 잠시 Trailbox 자체를 들여다본다고 게임 녹화에 잡음이 끼면 안 됨. 검증: clowder 창을 Chrome 위로 올린 채 녹화 → Chrome 백버퍼가 그대로 찍힘 (통계 mean 15.2 → 15.6, 거의 동일).

`screen_recorder.py`는 `MonitorTarget`/`WindowTarget` 디스크리미네이티드 union으로 두 백엔드를 같은 ffmpeg 파이프로 합류시키는 구조 — 상위 코드는 백엔드 모름.

### 2. fps 부드러움 — VFR 리팩토링의 동기

사용자가 "60fps도 게임 화면처럼 부드럽진 않다"고 보고. 원인 분석:

기존 구현: 별도 스레드가 `time.sleep` 으로 fps 틱, 매 틱마다 *최신 캐시 프레임*을 ffmpeg에 push. 문제:
1. 새 프레임 안 왔으면 → **같은 프레임 두 번 씀** (duplicate frame judder)
2. 두 프레임 왔으면 → **하나 버림** (drop)
3. Windows `time.sleep` 의 ~15ms 해상도 → 매 틱 jitter

이건 *temporal aliasing*. 시계 두 개(소스 클럭 vs Python 타이머)가 비동기라서 발생.

해결책 세 가지 비교:
| | 비용 | 효과 |
|---|---|---|
| `timeBeginPeriod(1)` | 5줄 | 미미 |
| 캡처 fps를 모니터 refresh 위로 | 0줄 | 미미 |
| **VFR 인코딩** | ~30줄 | 큼 |

VFR로 갔다. 핵심 변경:
- ffmpeg 입력: `-use_wallclock_as_timestamps 1`, 고정 `-r` 제거
- 출력: `-fps_mode passthrough` — PTS 그대로 유지
- Python: ticker 제거, **새 프레임 도착 시에만** stdin write

부수효과: 출력 mp4가 가변 프레임률이 됨. 호환성 우려가 있었지만 VLC/Chrome/Windows Media 모두 정상 재생 확인. 메타에 `effective_fps` 필드 추가해 사용자가 실제 캡처율 확인 가능.

CLAUDE.md에 "고정 ticker로 돌아가지 말 것"을 명시 — 이게 가장 큰 함정이라서.

### 3. 동기화 모델 — `t_video_s` 가 출현한 이유

원래 스펙은 "로그 폴더를 세션 종료 시 복사"였다. 사용자가 "영상화 싱크가 중요해 보여"라고 말하면서 방향이 바뀜.

복사 모델의 문제: 로그 파일 내부 timestamp 와 영상 시계가 일치한다는 보장이 없음. 시계 drift, NTP 조정, 파일 쓰기 latency 등으로 어긋남.

해결: 세션 시작 시점에 `t0_perf = time.perf_counter()` 한 번 잡고, 모든 레코더가 **그 t0 기준 상대 시각** (`t_video_s = perf_counter() - t0_perf`)을 자기 출력의 모든 라인에 박는다. 

이게 시스템의 결정적인 디자인 선언이 됨. 모든 레코더 — screen, audio, log, input, metrics — 가 같은 t0를 공유. CLAUDE.md 의 "single rule that holds everything together" 표현이 거기서 나옴. 이후 viewer.html, MCP 서버, AI 질의("12.3초에 뭐 있었나?") 가 전부 이 한 필드를 지렛대로 동작.

### 4. JSONL + WebVTT 동시 출력 — AI친화 vs 사람친화

로그 포맷 결정 시 후보: JSONL, WebVTT, OpenTelemetry, CSV. 트레이드오프:

| 포맷 | ES 적합도 | AI 적합도 | 영상 오버레이 |
|---|---|---|---|
| JSONL (ECS) | ◎ `_bulk` 그대로 | ◎ 구조화 | 필드 |
| WebVTT | △ 변환 필요 | ○ | ◎ 자막 |

**둘 다 떨어뜨리는** 선택. 같은 소스에서 파생해 비용 거의 동일. `logs.jsonl` 은 ES/AI, `logs.vtt` 는 비디오 플레이어 자막. 후에 viewer.html이 둘 다 활용하는 구조의 토대가 됨.

`raw/` 아카이브 추가도 같은 결정 — "원본을 따로 보존" 요구는 늦지 않게 들어왔고, 비용이 거의 0(파일 복사)이라 옵션이 아니라 디폴트로.

### 5. 양방향 자동 감지 — UX 가 만든 비대칭

처음엔 한 방향만 — 로그 폴더 → 창 자동 매칭. 사용자가 "역방향도?" 라고 물어 양방향으로 확장. 

각 방향이 *다른 휴리스틱* 을 요구한다는 게 흥미로운 발견:

- **로그폴더 → 창**: 그 폴더에 *쓰는* 프로세스를 찾고 싶음. `psutil.open_files()` 가 1순위 신호. Windows에선 비신뢰적이라 install-dir heuristic (exe_dir이 log_dir 의 가까운 조상인 프로세스) 으로 폴백.

- **창 → 로그폴더**: 그 프로세스가 *쓸 만한 로그 폴더*를 찾고 싶음. open_files 도 시도하지만 더 풍부한 컨벤션 목록(`Saved/Logs`, `%LOCALAPPDATA%/<app>/Logs`, `Documents/My Games/<app>/...`)으로 폴백.

추가로 **부모 프로세스 트리 walk** 도입 (depth=2, System32 제외):
- AC Odyssey 같은 게임은 로그를 자기가 안 씀 → 부모인 Ubisoft Connect 가 씀
- 게임 PID 에서 시작해 부모 → 조부모로 올라가며 각각 로그 폴더 컨벤션을 시도
- AC Odyssey 케이스에서 실제로 `C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\logs` 정확히 잡음

휴리스틱 튜닝 포인트 — 처음엔 `_HEURISTIC_MAX_DEPTH=4` 양쪽 독립 (총 8) → AC Odyssey 가 *드라이브 루트만 공유*해서 매칭되는 false positive. 그래서 `_HEURISTIC_MAX_COMBINED=4` + 드라이브 루트 제외로 좁힘. 휴리스틱은 *덜 매칭하는 게 더 매칭하는 것보다 나쁘지 않다* — 잘못된 결과로 사용자를 misleading 하는 것보다 "못 찾았음" 이 낫다.

### 5b. PC 사양 + 프레임 로그 + GPU 부하 (v0.1.2)

v0.1.1 출시 후 추가된 세 줄기 — 모두 "세션을 *해석 가능하게* 만드는" 메타데이터.

**PC 사양 스냅샷** (`session_meta.json`의 `system` 필드)
- 의도: 며칠 뒤 같은 세션을 다시 볼 때 "어느 PC에서?" 가 명확해야 함. 게임 QA는 머신 사양이 결정적.
- 수집: `platform.win32_ver()` + `psutil` + `wmic path win32_videocontroller` + Qt `screen()`.
- 트랩 한 건: Qt `geometry()` 는 DIP (device-independent pixels). 사용자 환경이 125% 스케일이라 `3072×1728` 로 보고됨 → 실제 native 는 `3840×2160`. `device_pixel_ratio` 와 `native_width/height` 모두 노출해서 *둘 다 의미 있게* 사용 가능하게 함.

**프레임 로그** (`metrics/frames.jsonl`)
- 매 프레임 한 라인: `{frame.index, t_video_s, delta_ms}`. 첫 프레임은 `delta_ms: null` (선행 없음).
- 집계 통계는 메타 `frame_stats`: min/avg/max/p95/p99 ms.
- 60fps × 5분 ≈ 18k 라인 ≈ 1.5 MB — 부담 없음.
- 의도: viewer 차트와 jitter 분석. CPU spike 직후 fps 떨어지는 구간 같은 *상관관계* 가 한 눈에 보임.

**GPU 부하** (`metrics/process.jsonl` 안에 합쳐서)
- 게임 QA에 GPU는 CPU보다 중요할 때가 많아 늦게 추가하긴 했지만 핵심.
- 첫 후보: NVML (NVIDIA 전용) — clean API, vendor lock. **거부**.
- 채택: **Windows PDH** (`win32pdh`) — `\GPU Engine(*)\Utilization Percentage` 와 `\GPU Process Memory(*)\Dedicated Usage`. NVIDIA / AMD / Intel 통일. pywin32 이미 의존성이라 추가 dep 0.
- PDH 특유의 트랩 두 건:
  1. **Delta counter first-sample = 0** — `AddCounter` 후 첫 `CollectQueryData` 는 항상 0 반환 (선행 표본 없음). `start()` 끝에 primed call 한 번 추가 후 실제 샘플은 그 다음부터.
  2. **`PDH_CALC_NEGATIVE_DENOMINATOR`** — 활동 없는 엔진은 예외 발생. `try/except` 로 잡고 "absent" 처리. 그래서 `gpu_engines` 가 비어 있는 게 "값이 0" 이 아니라 "샘플 없음"을 뜻함.
- `gpu_pct` 는 `max(engines)` — Task Manager 의 "GPU" 컬럼 컨벤션. `sum(engines)` 으로 가면 100% 자주 초과 (병렬 엔진), `max` 가 *병목 엔진을 가리키는* 더 의미 있는 단일 숫자.

**Viewer 차트 5-라인 통합**
- 빨강 CPU% · 초록 GPU% · 파랑 RSS · 보라 VRAM · 노랑 fps
- 각 라인 *독립 Y 스케일* — 단위 다른데 한 캔버스에 그리는 트릭. CPU/GPU 는 0–100% / RSS/VRAM 은 MB / fps 는 0–max_fps. 시각적으로 *상대적 추이* 만 봐도 충분히 정보가 됨.
- fps 는 데이터 포인트 가장 많으므로 *제일 먼저* 그려서 (opacity 낮은 라인이 뒤로) CPU/GPU 가 그 위에 얹히게 했음.

### 6. 메모리 덤프 → 프로세스 텔레메트리

스펙엔 5단계로 메모리 덤프가 있었지만, 실제 도입 직전에 ROI 분석을 하니:
- Anti-cheat 게임 (BattlEye/EAC/Vanguard) 대부분 `OpenProcess(VM_READ)` 차단
- 풀 덤프 크기 4~8GB
- 유스케이스 좁음 (크래시 디버그 한정)
- *반대로* 메모리 누수·CPU 스파이크는 1Hz 텔레메트리로 시각적으로 한 방에 잡힘

→ 사용자에게 대안 제시, 텔레메트리로 전환. psutil로 CPU%/RSS/threads/handles 1초마다 샘플 → `metrics/process.jsonl`. 같은 `t_video_s` 컨벤션 유지.

여기서 작은 함정 한 건 — `psutil.Process.cpu_percent()` 는 *코어당 %* 반환 (Unix `top` 관습). 20코어 머신에서 1139% 표시되어 사용자가 "CPU 퍼센트가 이상해" 라고 제보. 시스템 전체 대비 정규화(`/ cpu_count()`)로 0–100 범위로 바꾸고, raw 값은 `cpu_pct_per_core` 로 보존. 메타에 `cpu_cores` 추가 — 후에 데이터 해석할 때 컨텍스트 필요해서. 기존 세션 데이터도 보정 스크립트로 retroactive 업데이트.

### 7. viewer.html — 자체 완결 단일 파일이라는 제약

세션 검토용 UI를 만들면서 옵션 비교:
- PyQt 별도 윈도우: 외부 의존성 깔끔하지만 공유 안 됨
- VLC + .vtt: 구현 0이지만 통합 타임라인 없음
- HTML 페이지: 모든 브라우저, 공유 쉬움

HTML 선택. 단, **file:// 제약** 이 결정적 영향:
- Chrome 등 모던 브라우저는 file:// 페이지에서 `fetch()` 로 로컬 파일 못 읽음
- `<video src="./screen.mp4">`, `<track src="./logs.vtt">` 는 OK (HTML media element 는 예외)
- JSONL은 fetch 불가 → **HTML 내부에 인라인** (`<script type="application/json">`)

이 제약이 viewer 코드의 모양을 거의 다 결정함. 파이썬에서 jsonl 읽고 → JSON 직렬화 → HTML 토큰 치환(`__EVENTS_JSON__`). `.format()` 안 씀 — embedded CSS/JS의 `{}` 충돌 때문.

세션 폴더 압축해서 다른 PC로 보내도 viewer.html 더블클릭으로 그대로 동작 — 이 *전송성*이 QA 도구의 큰 가치.

차트는 Canvas + 직접 그리기 (Chart.js 같은 외부 의존 없음). 작은 단점: 인터랙티브 줌·다른 메트릭 추가 시 직접 코드. 큰 장점: 의존성 0, 페이지 로드 빠름.

### 8. MCP 서버 — 캡처 제어를 의도적으로 *안* 한 이유

MCP 서버를 처음 논의할 때 두 카테고리:
1. 읽기 도구 (세션 조회·검색)
2. 캡처 제어 (AI 가 녹화 시작/종료)

2번은 매력적이지만 비용 큼:
- Trailbox GUI는 현재 단일 프로세스. AI가 외부에서 제어하려면 IPC 채널 필요 (named pipe? HTTP? Qt remote?)
- 또는 headless 모드 별도 구현
- 첫 v0.1에 이걸 욱여넣으면 다른 부분이 부실해짐

1번만 우선 — 6개 도구(`list_sessions`, `get_session`, `query_events`, `get_metrics`, `search_logs`, `get_viewer_path`)로 충분히 가치 있음. 핵심: **모든 도구가 `t_video_s` 를 노출** → AI가 "12.3초에 뭐 있었나?" 같이 단일 시간축으로 다중 소스 횡단 가능.

### 9. PyInstaller — 단일 .exe 의 함정과 두 바이너리 답

v0.1.0 은 `Trailbox.exe` 하나 (124 MB)로 출시. 사용자가 "MCP도 .exe로 안 됨?" 질문 — Python 모르는 사람이 git clone+venv 하는 게 비현실적.

PyInstaller `--windowed` 의 결정적 제약 발견: **stdout/stdin 이 닫힘**. MCP stdio transport 는 stdin/stdout 으로 JSON-RPC 주고받으므로 windowed exe 에선 동작 불가.

해결책 비교:
- 단일 console 모드 .exe + 시작 시 콘솔 숨김 → 100ms 콘솔 플리커 (UX 어색)
- 콘솔 attach/free 동적 처리 → 복잡, 신뢰성 ↓
- **두 바이너리 분리** ← 선택

두 바이너리 빌드:
- `Trailbox.exe` (124 MB) — `--windowed`, main.py 진입점, GUI
- `Trailbox-mcp.exe` (13 MB) — `--console`, mcp_entry.py 진입점, MCP 서버

핵심: **별도 진입점 스크립트**(`mcp_entry.py`)로 분리해서 PyInstaller 의존성 분석이 따로 돌아가게 함. mcp_entry.py 는 Qt/dxcam/soundcard 임포트 안 함 → 13 MB로 끝남 (GUI 의 1/10).

빌드 중 두 가지 함정:
1. `--collect-submodules mcp` 가 `mcp.cli` 분석하다가 optional dep `typer` 없어서 실패 → `mcp.server`, `mcp.shared`, `mcp.types` 만 명시적으로
2. `mcp_server._output_root()` 의 `Path(__file__).parent.parent` 이 PyInstaller 번들 안에선 `_MEIxxx` 임시 폴더가 됨 → `getattr(sys, 'frozen', False)` 체크해서 `sys.executable.parent / "output"` 로 폴백

검증: 직접 MCP 클라이언트로 `Trailbox-mcp.exe` 띄워 initialize → list_tools → call_tool 전 과정 통과.

## 일관된 패턴 (의식적이지 않았지만 반복됨)

코드를 다시 보면 거의 모든 레코더가 같은 모양:

```python
class XxxRecorder:
    def __init__(self, output_path, t0_perf, ...): ...
    def start(self) -> None:              # 백그라운드 스레드 시작
    def stop(self, timeout=...) -> None:  # 종료 신호 + join + 에러 전파
    def _run(self) -> None:               # 워커 스레드 본체
```

- 항상 `daemon=True` 스레드 (인터프리터 종료 시 정리)
- `threading.Event` 로 stop 신호
- 에러는 `self._error` 에 저장하고 `stop()` 에서 재발생 → 호출자(main.py)가 메타에 기록
- `start()` 가 빠르게 리턴 (워커가 init 끝나면 `_started.set()` 으로 알림, 호출자가 wait)

이 패턴이 *세션 라이프사이클의 직렬화*를 가능하게 함. main.py 의 `_on_start_requested` 가 레코더들을 순서대로 시작하고, `_on_stop_requested` 가 역순으로 stop. 각 stop은 독립적 best-effort — 하나가 실패해도 다른 것들은 계속.

세션 종료 → mux → finalize → viewer 생성 의 직렬 파이프라인도 같은 철학: 각 단계 try/except, 실패는 메타의 `*_error` 필드로 surfacing.

## 의도적으로 안 한 것들

- **테스트 스위트**: 시간 대비 가치. 대신 `_smoketest_*.py` 스크립트들로 통합 시점에 검증 후 폐기. 향후 QA 빌드 연결 시 회귀 테스트 필요할 수 있음.
- **GitHub Actions**: 로컬 빌드 + 수동 업로드로 충분. v0.2 후보.
- **MCP 캡처 제어**: 위 참조. IPC/headless 둘 다 nontrivial.
- **메모리 덤프**: anti-cheat ROI 낮음. 필요해지면 작업량 200줄로 추가 가능.
- **모니터 다중 선택**: 단일 모니터로 충분, 멀티는 UI 복잡도 ↑.
- **자동 업데이터**: 사용자 수가 적어서 ROI 낮음.

## 회고

### 잘 된 결정
- **t_video_s 한 필드를 모든 출력의 공통 컨벤션으로 만든 것**. 이게 없었으면 viewer/MCP 가 완전히 다른 구조가 됐을 것.
- **사용자 질문에 대해 즉답이 아니라 "근거 + 옵션 + 추천"으로 응답**. "60fps가 안 부드러워" → "원인은 X, 해결책 A/B/C, 추천 A" 패턴이 좋은 결정을 빠르게 내리게 했음.
- **VFR 리팩토링을 미루지 않은 것**. 작은 변경이 아니었지만 즉시 손대서 viewer 빌드 시점엔 정확한 영상이 있었음.
- **메모리 덤프를 텔레메트리로 바꾼 것**. 스펙 고수보다 ROI 분석이 이긴 케이스.

### 만약 다시 한다면
- **로깅 인프라**: 이 세션 동안엔 print + `_smoketest_*.py` 로 디버그했음. 실제 사용자가 늘면 `logging` 모듈로 통일된 진단 로그 필요. v0.2 후보.
- **타입 힌트 일관성**: 일부 모듈은 `from __future__ import annotations`, 일부는 `Optional[X]` vs `X | None` 혼재. 일괄 정리할 수 있었음.
- **휴리스틱 매개변수의 노출**: `_HEURISTIC_MAX_COMBINED=4` 같은 magic number는 모듈 상수로 빼긴 했지만, 환경별 튜닝이 필요해지면 메타 파일이나 사용자 설정으로 옮기는 게 맞음.
- **windows-capture 의 `--collect-data`**: 처음 PyInstaller 빌드에서 cffi/comtypes 관련 함정으로 시간 소비. PyInstaller 빌드를 *처음부터* 염두에 두고 의존성 골랐다면 windows-capture 대신 다른 WGC 바인딩을 고려했을 수도 있음.

### 메타: AI 페어 프로그래밍 관찰
- **사용자가 "X 가능?" 물을 때**: 항상 *가능 여부 + 비용 + 트레이드오프 + 추천* 으로 답하는 게 의사결정 가속화. "그냥 됩니다" 보다 "30분 들지만 ROI 작음 — 다음으로 미루는 게 어떨까요" 가 나음.
- **삽질 공개**: open_files()가 Windows에서 자주 빈다는 사실, PyInstaller --windowed 가 stdio 막는다는 사실 — 발견 즉시 명시했음. 숨기면 나중에 같은 곳에서 다시 막힘.
- **CLAUDE.md 의 가치**: 세션 막바지에 작성. 다음 인스턴스가 같은 함정 (COM threading import 순서, VFR ticker 재도입, blockSignals 패턴)을 피할 수 있게 *결정의 근거*를 박아둠. 코드 주석이 *뭐를 하는지*면, CLAUDE.md 는 *왜 그렇게 안 하는지*.

## 한 줄 요약

스펙의 5단계 MVP가 한 세션 안에서 *영상 + 오디오 + 로그 + 입력 + 텔레메트리 + 자체완결 뷰어 + AI MCP + 0-Python 릴리즈 + 깃허브 공개* 까지 갔다. 결정의 80%는 "사용자 질문 → 옵션 분석 → 트레이드오프 선택" 패턴. 핵심 디자인은 한 줄: **모든 출력이 같은 `t_video_s` 축을 공유한다.**
