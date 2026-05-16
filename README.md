# Trailbox

Windows 멀티-시그널 세션 레코더. **화면 · 시스템 사운드 · 앱 로그 · 키마 입력 · CPU/GPU/RAM 텔레메트리** 를 *하나의 타임라인에 정렬해* 녹화하고, 브라우저에서 통합 뷰어로 보고, 팀과 링크로 공유합니다.

게임 QA / 사용자 세션 리플레이 / 버그 리포트 / 튜토리얼 제작 / 디버깅 세션 기록 — 여러 신호가 *동기화된 채로* 봐야 가치 있는 모든 워크플로.

---

## 받기

[**Releases 최신**](https://github.com/hgkim0105/trailbox/releases/latest) 에서 **`Trailbox-Setup.exe`** (~212 MB) 받아 더블클릭.

설치 마법사가 셋업 종류 (Full / Client / GUI-only / Custom) 와 Hub 연결 정보를 물어보고 알아서 잡아 줍니다. **Python · ffmpeg · 그 외 의존성 모두 .exe 안에 포함** — 별도 설치 불필요.

> 분리된 `Trailbox.exe` / `Trailbox-mcp.exe` / `Trailbox-hub.exe` 도 같은 페이지에 있음. 인스톨러 안 쓰고 수동 배치할 때만.

요구사항: **Windows 10 1903+** (Windows 11 권장)

---

## 무엇을 캡처하는가

| 신호 | 백엔드 | 출력 |
|---|---|---|
| 화면 (모니터 전체) | `dxcam` (DXGI Desktop Duplication) | `screen.mp4` |
| 화면 (특정 창) | `windows-capture` (WGC) — 가려진 창·HW 가속 앱 OK | `screen.mp4` |
| 시스템 오디오 | `soundcard` (WASAPI loopback) | `screen.mp4` 내 AAC |
| 앱 로그 (어느 폴더든) | `watchdog` + tail-follow | `logs/logs.jsonl`, `logs/logs.vtt`, `logs/raw/` |
| 키보드 + 마우스 | `pynput` 글로벌 리스너 | `inputs/inputs.jsonl`, `inputs/inputs.vtt` |
| 프로세스 텔레메트리 (CPU + GPU + RAM + VRAM + threads) | `psutil` + Windows PDH 1Hz 샘플 | `metrics/process.jsonl` |
| 프레임 타이밍 | 매 프레임 인스턴트 fps + Δ | `metrics/frames.jsonl` |
| PC 사양 스냅샷 | OS / CPU / RAM / GPU / 디스플레이 / Python / 버전 | `session_meta.json` 의 `system` |
| 통합 뷰어 | 자체 생성 HTML | `viewer.html` |

전부 동일한 `t_video_s` (영상 시작 기준 초) 로 동기화. AI/Elasticsearch에 그대로 던지거나 viewer.html에서 사람이 보면서 검토 가능.

---

## 첫 사용

설치 후 시작 메뉴 **「Trailbox」** 더블클릭.

1. **캡처 대상** — `전체 모니터` 또는 `특정 창 (WGC)`. 창은 콤보박스에서 고르거나, `🎯 창 클릭으로 선택` 또는 풀스크린 앱 안에서 `Ctrl+Shift+P` 단축키로 잡을 수 있음 (게임 풀스크린 안에서도 작동)
2. (선택) **실행 파일** + **로그 폴더** — 둘 중 하나만 입력해도 다른 쪽을 자동 추론. 대상 앱이 로그를 *쓰는 폴더만 알면* (UE/Unity의 `Saved/Logs`, Electron 앱의 `%APPDATA%`, 일반 데스크탑 앱의 `%LOCALAPPDATA%/.../logs` 등) 자동 tail. 디스크 로깅이 없는 앱이면 부모 프로세스 (런처/IDE/터미널) 로그가 잡힙니다
3. **시스템 사운드 녹음** / **키보드/마우스 입력 기록** / **프로세스 텔레메트리** 토글 (기본 모두 ON)
4. **최대 fps** 선택 (10/15/24/30/60). VFR이라 실제 fps는 소스 따라 변함
5. **녹화 시작** → 작업 진행 → **녹화 종료**
6. **📂 세션 뷰어 열기…** → 목록에서 골라 더블클릭 → 기본 브라우저로 통합 뷰어 열림

녹화 결과는 `output/{session_id}/` 폴더에 저장. **다른 PC 로 폴더 통째 압축해 보내도 viewer.html 더블클릭으로 그대로 재생** 됩니다 (자체완결 HTML).

---

## 통합 뷰어 (`viewer.html`)

세션 종료 시 자동 생성되는 단일 HTML 파일. 폴더에서 더블클릭하면 기본 브라우저로 열림.

- **좌측**: HTML5 비디오 (mp4 + AAC 사운드)
- **우측 상단**: CPU / GPU / RSS / VRAM / fps 5라인 차트 + 영상 playhead 수직선
- **우측 중간**: logs + inputs 통합 타임라인 — 필터 / 검색 / 행 클릭 → 그 시점으로 점프
- **헤더**: 이벤트 카운트 / duration / frames / Δ avg/p99 / cores 등 한눈 요약
- **PC 사양 ▶**: OS / CPU / RAM / GPU / Display(해상도+scaling) / Python / Trailbox 버전

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

- **DRM 보호 콘텐츠** (Netflix 등): 영상은 검은 박스로 캡처됨 (OS 강제 보호). 사운드는 정상
- **Anti-cheat 게임**: 메모리 덤프류 차단. **텔레메트리는 차단되지 않음** (perf counter는 별도 경로)
- **풀스크린 Exclusive 앱**: 일부 게임/미디어 플레이어는 백버퍼 접근 제한. Borderless 모드 권장
- **자체 로그를 안 남기는 앱**: tail 할 파일이 없으면 로그 트랙은 빔. 부모 프로세스 (런처/터미널/IDE) 로그가 *대체로* 잡히긴 함. UE / Unity / Electron / Java 앱은 보통 풍부
- **마이크 / 외부 입력 오디오**: WASAPI loopback 은 *시스템 출력* 만 잡음. 마이크는 OBS 보조 또는 추후 옵션

---

## 더 알아보기

- **[DEPLOYMENT.md](DEPLOYMENT.md)** — Hub 서버 배포 (단일 .exe / Docker / Caddy + Let's Encrypt)
- **[DEVELOPING.md](DEVELOPING.md)** — 소스 빌드 / 아키텍처 / JSONL 스키마 / REST API 전체 / 환경변수 / MCP 백엔드
- **[DEVNOTES.md](DEVNOTES.md)** — 개발 의사결정 기록
- **[ROADMAP.md](ROADMAP.md)** — 백로그

## 라이선스

MIT
