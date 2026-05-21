# Trailbox

Windows 멀티-시그널 세션 레코더. **화면 · 시스템 사운드 · 앱 로그 · 키마 입력 · CPU/GPU/RAM 텔레메트리** 를 *하나의 타임라인에 정렬해* 녹화하고, 브라우저에서 통합 뷰어로 보고, 팀과 링크로 공유합니다.

PC 데스크탑뿐 아니라 **USB 연결된 Android 디바이스** 도 캡처합니다 — 화면 + logcat + 터치 입력 + jank/CPU/RSS 메트릭을 동일한 타임라인으로.

게임 QA / 사용자 세션 리플레이 / 버그 리포트 / 튜토리얼 제작 / 디버깅 세션 기록 / 모바일 앱 QA — 여러 신호가 *동기화된 채로* 봐야 가치 있는 모든 워크플로.

---

## 받기

[**Releases 최신**](https://github.com/hgkim0105/trailbox/releases/latest) 에서 **`Trailbox-Setup.exe`** (~256 MB) 받아 더블클릭.

설치 마법사가 셋업 종류 (Full / Client / GUI-only / Custom) 와 Hub 연결 정보를 물어보고 알아서 잡아 줍니다. **Python · ffmpeg · adb · scrcpy · 그 외 의존성 모두 .exe 안에 포함** — 별도 설치 불필요.

> 분리된 `Trailbox.exe` / `Trailbox-mcp.exe` / `Trailbox-hub.exe` 도 같은 페이지에 있음. 인스톨러 안 쓰고 수동 배치할 때만.

요구사항:
- **PC**: Windows 10 1903+ (Windows 11 권장)
- **Android 캡처** (선택): USB 디버깅이 켜진 Android 4.4+ 디바이스. Samsung 갤럭시면 «자동 차단» 의 «USB 케이블로 명령 차단» 옵션 OFF 필요

---

## 무엇을 캡처하는가

### PC 캡처

| 신호 | 백엔드 | 출력 |
|---|---|---|
| 화면 (모니터 전체) | `dxcam` (DXGI Desktop Duplication) | `screen.mp4` |
| 화면 (특정 창) | `windows-capture` (WGC) — 가려진 창·HW 가속 앱 OK | `screen.mp4` |
| 시스템 오디오 | `soundcard` (WASAPI loopback) | `screen.mp4` 내 AAC |
| 앱 로그 (다중 폴더 · 재귀 · 확장자 설정 · 바이너리 자동 제외) | `watchdog` + tail-follow + 2초 rescan 안전망 | `logs/logs.jsonl`, `logs/logs.vtt`, `logs/raw/<root>/` |
| 키보드 + 마우스 | `pynput` 글로벌 리스너 | `inputs/inputs.jsonl`, `inputs/inputs.vtt` |
| 프로세스 텔레메트리 (CPU + GPU + RAM + VRAM + threads) | `psutil` + Windows PDH 1Hz 샘플 | `metrics/process.jsonl` |
| 프레임 타이밍 | 매 프레임 인스턴트 fps + Δ | `metrics/frames.jsonl` |
| PC 사양 스냅샷 | OS / CPU / RAM / GPU / 디스플레이 / Python / 버전 | `session_meta.json` 의 `system` |

### Android 디바이스 캡처 (v0.3.0+)

| 신호 | 백엔드 | 출력 |
|---|---|---|
| 화면 + 오디오 (scrcpy 가능 디바이스) | scrcpy 4.0 wrap (헤드리스, MKV→mp4 무재인코딩) | `screen.mp4` (H.264 + Opus/AAC) |
| 화면 (screenrecord 폴백) | `adb shell screenrecord` 청크 회전 → ffmpeg `-c copy` concat | `screen.mp4` (오디오 없음) |
| 시스템 로그 (logcat) | `adb logcat -v threadtime` (디바이스 시각 `-T` 필터 + 옵션 `--pid` 패키지 좁힘) | `logs/logcat.jsonl` + `logcat.vtt` |
| **PC 측 보조 로그 폴더** (선택) | 같은 다중 폴더 / 재귀 / 확장자 설정 — Android 세션에서도 그대로 동작 | `logs/logs.jsonl` (logcat 과 분리, 뷰어에서 소스별 토글) |
| 터치 + 키 입력 | `adb getevent -lt` (멀티터치 protocol B + ABS_MT 정규화) | `inputs/inputs.jsonl` + `inputs.vtt` |
| 텔레메트리 (CPU + RSS + jank + 프레임 시간 p95/p99) | `adb top + dumpsys gfxinfo` 1Hz, **포어그라운드 자동 추적 (4초 간격 재해상)** | `metrics/process.jsonl` |
| 디바이스 사양 스냅샷 | Android 버전 / SDK / model / manufacturer / 디스플레이 해상도 / abi | `session_meta.json` 의 `system` |

**캡처 백엔드 «auto»** (기본): 디바이스 SDK ≥ 36 (Android 16+) 이면 즉시 screenrecord. 그 외엔 scrcpy 시도 후 3초 안에 첫 프레임 못 받으면 자동으로 screenrecord 로 hot-swap. 사용자 결정 불필요.

### 공통

전부 동일한 `t_video_s` (영상 시작 기준 초) 로 동기화. AI/Elasticsearch에 그대로 던지거나 `viewer.html` 에서 사람이 보면서 검토 가능. 통합 뷰어는 자체 생성 HTML.

---

## 첫 사용

설치 후 시작 메뉴 **「Trailbox」** 더블클릭.

### PC 화면 캡처

1. **캡처 대상** — `전체 모니터` 또는 `특정 창 (WGC)`. 창은 콤보박스에서 고르거나, `🎯 창 클릭으로 선택` 또는 풀스크린 앱 안에서 `Ctrl+Shift+P` 단축키로 잡을 수 있음 (게임 풀스크린 안에서도 작동)
2. (선택) **실행 파일** + **로그 폴더** — 둘 중 하나만 입력해도 다른 쪽을 자동 추론. 대상 앱이 로그를 *쓰는 폴더만 알면* (UE/Unity의 `Saved/Logs`, Electron 앱의 `%APPDATA%`, 일반 데스크탑 앱의 `%LOCALAPPDATA%/.../logs` 등) 자동 tail. 디스크 로깅이 없는 앱이면 부모 프로세스 (런처/IDE/터미널) 로그가 잡힙니다
   - **추가 로그 폴더** (`+ 폴더 추가`): 서버 로그 공유 폴더 / 별도 컴포넌트 로그 등 보조 경로를 N개 더 추가. 뷰어에서 폴더별로 보기/감추기 토글
   - **하위 폴더까지 스캔** (기본 ON): 각 로그 폴더 안의 하위 폴더 내 파일까지 재귀로 따라잡음. 새로 만들어지는 하위 폴더도 자동 감지
   - **확장자** (기본 `log, txt`): 캡처할 파일 형식. `json, out, err` 등 자유롭게 추가 가능. 비우거나 `*` 입력 시 와일드카드 모드 — `.exe / .png / .zip` 등 잘 알려진 바이너리 + NUL 바이트로 시작하는 파일은 자동으로 제외
3. **시스템 사운드 녹음** / **입력 기록** / **프로세스 텔레메트리** 토글 (기본 모두 ON)
4. **최대 fps** 선택 (10/15/24/30/60). VFR이라 실제 fps는 소스 따라 변함
5. **녹화 시작** → 작업 진행 → **녹화 종료**
6. **📂 세션 뷰어 열기…** → 목록에서 골라 더블클릭 → 기본 브라우저로 통합 뷰어 열림

### Android 디바이스 캡처

1. 디바이스: 설정 → 휴대전화 정보 → 빌드번호 7회 탭 → 개발자 옵션 → **USB 디버깅 ON**. Samsung 갤럭시면 설정 → 보안 및 개인 정보 보호 → **자동 차단** → «USB 케이블로 명령 차단» OFF
2. **데이터 전송용 USB-C 케이블** 로 PC 연결 (충전 전용은 안 됨)
3. 첫 연결 시 디바이스 화면의 «USB 디버깅을 허용하시겠습니까?» 다이얼로그에 **«항상 허용»** 체크 + 확인
4. Trailbox 의 **캡처 대상** 그룹에서 **«Android 디바이스 (scrcpy)»** 선택 → 디바이스 콤보에 시리얼/모델 자동 표시 (3초마다 폴링)
5. **영상 백엔드** 는 «auto» 권장 — 디바이스에 맞게 알아서 분기됨. 강제하려면 «scrcpy» / «screenrecord» 직접 선택
6. **녹화 시작** → Tab 에서 작업 진행 → **녹화 종료**

Android 세션은 시스템 사운드 토글이 자동 비활성됨 (loopback 의미 없음). scrcpy 백엔드 + Android 11+ 디바이스면 시스템 오디오가 자동 캡처됨, screenrecord 경로면 영상만.

**Android 세션에서 PC 측 로그 폴더 같이 캡처**: 위 PC 화면 캡처의 step 2 와 동일하게 「로그 폴더」 / 「추가 로그 폴더」 를 입력하면 logcat 과 함께 PC 폴더 로그도 잡힘. 두 출처는 `logs/logcat.jsonl` / `logs/logs.jsonl` 로 분리 저장되고 뷰어 타임라인에서는 소스별로 토글 가능. 서버 로그 공유 폴더와 모바일 클라이언트를 동시 분석할 때 유용.

### 공통

녹화 결과는 `output/{session_id}/` 폴더에 저장. **다른 PC 로 폴더 통째 압축해 보내도 viewer.html 더블클릭으로 그대로 재생** 됩니다 (자체완결 HTML).

---

## 통합 뷰어 (`viewer.html`)

세션 종료 시 자동 생성되는 단일 HTML 파일. 폴더에서 더블클릭하면 기본 브라우저로 열림.

- **좌측**: HTML5 비디오 (mp4 + AAC 사운드)
- **우측 상단**: CPU / GPU / RSS / VRAM / fps 5라인 차트 + 영상 playhead 수직선 (Android 세션은 GPU/VRAM 미수집, jank/frame_time 은 별도 행)
- **우측 중간**: logs + inputs 통합 타임라인 — 종류/마우스/키 필터 + **로그 소스별 토글** (다중 폴더 캡처 또는 Android logcat + PC 로그 동시 캡처 시 자동 표시, 「전체 / 해제」 단축 링크 포함) + 검색 (메시지·파일경로·소스명까지 매칭) + 행 클릭 → 그 시점으로 점프
- **헤더**: 이벤트 카운트 / duration / frames / Δ avg/p99 / cores 등 한눈 요약
- **사양 ▶**: 캡처 대상에 맞춰 표시 — PC 세션은 OS / CPU(P/L) / RAM / GPU / Display + Python · Trailbox 버전. Android 세션은 **Device** (model + serial) / **OS** (Android N · SDK) / **CPU** (abi · N cores) / **Display** (해상도) / Trailbox 버전

---

## 쓸 만한 시나리오

게임 QA 가 가장 또렷한 use case 지만, *동기화된 멀티-시그널 녹화* 가 필요한 곳이면 어디든:

- **게임 QA / 성능 진단** — fps 드롭 / RAM leak / GPU 스파이크 구간을 영상·로그·입력이랑 같이. 클로즈드 엔진 (Anvil, Frostbite) 도 런처 로그 + 텔레메트리는 잡힘
- **재현 가능한 버그 리포트** — "여기 클릭했더니 멈춤" 을 영상 + 정확한 input 시퀀스 + 그 순간 메모리/CPU 로. 개발자가 받자마자 원인 추적 가능. Jira/Slack 첨부 대신 공유 링크 한 줄
- **사용자 세션 리플레이 (UX 리서치)** — 참가자가 앱 쓰는 모습 + 음성 (마이크는 시스템 오디오로 안 잡힘, OBS 보조 권장) + 클릭 히트맵
- **튜토리얼 / 데모 영상 만들기** — 화면 + 시스템 사운드 + 키 입력 자막 트랙. viewer 의 input 타임라인이 그대로 "이때 무슨 키 눌렀음" 설명 자료
- **개발자 디버깅 세션 기록** — 빌드 로그 tail + IDE 화면 + 컴파일 시간 동안 CPU/메모리. 회고/페어 리뷰용
- **AI 코딩 세션 분석** — Claude Code / Cursor 사용하는 동안 화면 + 도구 호출 로그 + 자기 입력. 어디서 막혔는지 사후 회고
- **장시간 백그라운드 작업** — ML 학습 / 빌드 / 데이터 처리 돌리는 동안 화면 + 콘솔 로그 + 리소스 사용량. 새벽에 멈춘 시점 찾기
- **모바일 앱 QA** — Android 디바이스에서 실제 사용자 시나리오 재현하면서 화면 + logcat + 터치 + 앱별 jank/메모리 추적. 사용자가 앱 전환해도 메트릭이 자동 따라감

공통 패턴: **"무슨 일이 일어났는지 *나중에* 정확히 보고 싶다"**. 단순 화면 녹화 (OBS / Loom) 와 차이는 *로그·입력·텔레메트리가 같은 시간축에 정렬* 되어 있다는 것.

---

## 팀 공유 — Trailbox Hub

Hub 는 옵션입니다. 안 깔아도 위 기능 다 동작. 다음 시나리오면 켜세요:

| 원하는 것 | Hub 없이 | Hub 로 |
|---|---|---|
| 다른 사람에게 세션 보여주기 | 폴더 압축해서 메신저로 전송 → 받은 사람이 풀고 viewer.html 열기 | 「공유 링크」 클릭 → URL 한 줄 보내기 |
| 자동 백업 | 수동 | 녹화 종료 시 자동 업로드 + N일 만료 정책 |
| AI 가 원격 세션 분석 | 불가 (로컬 파일만) | Claude Desktop 의 MCP 가 원격 세션 조회 |

### 셋업 (같은 PC, LAN-only)

인스톨러에서 **Full** 선택 + **Hub Configuration** 페이지의 **Generate** 버튼 → 자동으로 토큰 생성 + 레지스트리 + `start-hub.bat` 모두 채워짐.

설치 끝나면 시작 메뉴 **「Trailbox Hub」** 한 번 실행 (콘솔 창 유지). Trailbox 의 「허브 설정」 다이얼로그는 이미 자동 입력됨.

### 팀원 (다른 PC) 추가

1. Admin 이 자기 PC 의 `hub-token.txt` 또는 클립보드의 토큰을 메신저로 전달
2. 팀원은 인스톨러에서 **Client only** 선택 + Hub Configuration 페이지에 admin URL + 토큰 붙여넣기
3. 끝 — 첫 실행에 자동으로 Hub 연결됨

### 세션 공유 흐름 (Trailbox 의 「세션 뷰어 열기」 다이얼로그)

- **허브 업로드** — 선택한 로컬 세션을 Hub 로 올림 (64MB 이상이면 자동 청크 업로드 + 재개 지원)
- **공유 링크** — Hub 의 세션에 공유 토큰 발급 → URL 자동 클립보드 복사. 받는 사람은 Trailbox 미설치라도 브라우저로 viewer 그대로 봄
- **허브에서 가져오기…** — 다른 사람이 올린 Hub 세션을 로컬로 다운로드

원격 호스팅 / Docker / HTTPS 셋업은 → [DEPLOYMENT.md](DEPLOYMENT.md)

---

## AI 분석 (Claude Desktop)

Trailbox MCP 가 설치되어 있으면 Claude Desktop 에 등록할 수 있습니다.

`%APPDATA%\Claude\claude_desktop_config.json` 편집:

```json
{
  "mcpServers": {
    "trailbox": {
      "command": "C:\\Program Files\\Trailbox\\Trailbox-mcp.exe",
      "env": {
        "TRAILBOX_HUB_URL": "http://127.0.0.1:8765",
        "TRAILBOX_HUB_TOKEN": "<인스톨러에서-받은-토큰>"
      }
    }
  }
}
```

> `env` 블록을 빼면 로컬 `output/` 폴더만 봄 (Hub 미사용 모드).

Claude Desktop 재시작 후 채팅에서 활용:

- "최근 세션에서 CPU 50% 넘긴 구간 알려줘"
- "이 세션 12~15초 사이에 무슨 입력이 있었나"
- "logs 에서 'error' 들어간 라인만 영상 타임코드와 같이 보여줘"
- "5번째 마우스 클릭 시점에 화면이 어땠어?" (영상 프레임을 JPEG 로 추출해 보여줌)

7개 도구 (`list_sessions` / `get_session` / `query_events` / `get_metrics` / `search_logs` / `get_frame_at` / `get_viewer_path`) 가 자동 인식됩니다.

---

## 알려진 한계

### PC 캡처
- **DRM 보호 콘텐츠** (Netflix 등): 영상은 검은 박스로 캡처됨 (OS 강제 보호). 사운드는 정상
- **Anti-cheat 게임**: 메모리 덤프류 차단. **텔레메트리는 차단되지 않음** (perf counter는 별도 경로)
- **풀스크린 Exclusive 앱**: 일부 게임/미디어 플레이어는 백버퍼 접근 제한. Borderless 모드 권장
- **자체 로그를 안 남기는 앱**: tail 할 파일이 없으면 로그 트랙은 빔. 부모 프로세스 (런처/터미널/IDE) 로그가 *대체로* 잡히긴 함. UE / Unity / Electron / Java 앱은 보통 풍부
- **마이크 / 외부 입력 오디오**: WASAPI loopback 은 *시스템 출력* 만 잡음. 마이크는 OBS 보조 또는 추후 옵션
- **와일드카드 로그 캡처 + UTF-16 LE 텍스트 로그**: 와일드카드 모드의 바이너리 sniff 가 UTF-16 의 NUL 바이트를 바이너리 신호로 오인해 해당 파일을 제외함. 해당 형식을 캡처해야 하면 확장자 입력에 명시적으로 추가 (예: `log, txt, etl`) — 명시 모드에서는 sniff 안 함

### Android 캡처
- **scrcpy 백엔드 + 일부 OEM 펌웨어 비호환**: Galaxy + One UI 8 / Android 16 같은 최신 조합은 scrcpy 4.0 의 hidden-API 경로가 막힘. «auto» 백엔드가 자동으로 screenrecord 로 폴백
- **screenrecord 백엔드는 시스템 오디오 미지원**: Android API 한계. scrcpy 가 동작하는 디바이스라면 오디오도 같이 잡힘 (Android 11+)
- **screenrecord 청크 경계**: 180초마다 새 청크로 회전 → 경계 부근에서 수십 ms 끊김 가능. 종료 시 ffmpeg `-c copy` 로 자동 머지
- **`getevent` 권한 차단**: 일부 OEM (Samsung Knox, MIUI) 이 non-root getevent 거부. 해당 디바이스는 `inputs.jsonl` 비어둔 채 세션 진행 (다른 신호는 정상)
- **DRM-protected 모바일 콘텐츠** (Netflix 모바일, 일부 OTT): `FLAG_SECURE` 가 적용된 앱은 디바이스 측 인코더가 검은 프레임 송출 — 회피 불가
- **무선 ADB**: v1 은 USB 우선. Wi-Fi 페어링 된 디바이스도 인식은 되지만 안정성 보장 없음

---

## 더 알아보기

- **[DEPLOYMENT.md](DEPLOYMENT.md)** — Hub 서버 배포 (단일 .exe / Docker / Caddy + Let's Encrypt)
- **[DEVELOPING.md](DEVELOPING.md)** — 소스 빌드 / 아키텍처 / JSONL 스키마 / REST API 전체 / 환경변수 / MCP 백엔드
- **[DEVNOTES.md](DEVNOTES.md)** — 개발 의사결정 기록
- **[ROADMAP.md](ROADMAP.md)** — 백로그

## 라이선스

MIT
