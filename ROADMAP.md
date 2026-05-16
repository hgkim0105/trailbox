# ROADMAP — 향후 작업

세션 안에서 결론 난 항목은 [DEVNOTES.md](DEVNOTES.md) 참조. 여기는 *아직 안 한 일* 의 설계 메모.

---

## Trailbox Hub — v0.1 (완료)

Phase 1~6 모두 구현. 코드는 `hub_server/` + `core/hub_*` + `ui/hub_dialogs.py` / `ui/remote_session_picker.py`,
배포 아티팩트는 `Dockerfile.hub` / `docker-compose.yml` / `Caddyfile` / `DEPLOYMENT.md`,
빌드는 `build.py` 가 `Trailbox-hub.exe` 까지 동시 생성. 자세한 결정 기록은 [DEVNOTES.md](DEVNOTES.md) 의 Hub 섹션 참조.

### Hub 다음 단계 (백로그)

- **재시작 가능한 업로드 — 클라이언트 측 영속화**: 현재 청크 업로드는 *세션 안* 에서만 재개. Trailbox 가 죽고 다시 켜져도 이어 받으려면 `output/{sid}/.hub_upload.json` 같은 작은 상태 파일이 필요. 청크당 round-trip 줄이려고 병렬 PUT 도 검토 가능
- **공유 토큰 만료 / 1회용**: 현재는 영구. 만료시각/사용횟수 필드 + revoke UI 만 추가하면 됨
- **백업 자동화**: hub_data 를 일 1회 tar.gz → S3/B2. `restic` 컨테이너 추가 권장
- **S3/object-store 백엔드**: 현재는 디스크 only. `Storage` 인터페이스를 `LocalStorage` / `S3Storage` 로 분리하면 됨
- **`/mcp` HTTP transport 직접 노출**: 현재는 stdio 브리지 + `TRAILBOX_HUB_URL`. MCP Streamable HTTP 가 mainstream 되면 추가
- **클라이언트의 SessionPicker 에 `허브 상태` 컬럼**: 로컬 vs 업로드됨 vs 둘다 표시
- **AC/Anvil 같은 거대 로그 대응**: `_iter_jsonl` 가 현재 `.read_text().splitlines()` — 100MB 로그면 메모리 폭주. 라인 단위 streaming 으로 전환

---

## (구) Trailbox Hub — 설계 메모 (구현 완료, 참고용)

### 목표

- Trailbox 가 녹화한 세션을 **서버에 업로드 / 서버에서 다운로드**
- 서버는 **단일 파일 실행 웹 서버** (의존성 셋업 최소)
- 녹화 데이터는 서버의 **하위 폴더** (`hub_data/{session_id}/...`) 로 저장
- 운영 코스트 최소화 (단일 VPS 또는 사내 LAN 에서 0원에 가깝게)
- **인간용 공유 URL** — Trailbox 설치 없는 사람도 브라우저로 viewer 페이지. QA 결과를 *링크로 던지는* 워크플로
- **AI용 MCP 접근** — 원격 세션을 AI 가 MCP 도구로 조회. 핵심 이유: **토큰 비용**. viewer.html 통째로 AI 에게 던지면 (수백 KB ~ 수 MB) 한 세션 분석에 수만~수십만 토큰 소비. MCP 로 *필요한 시간 구간 / 이벤트 종류만* 골라 받으면 1k~5k 토큰으로 끝남. 로컬에서 이미 검증된 패턴 (`Trailbox.exe`=인간 / `Trailbox-mcp.exe`=AI) 을 Hub 에 그대로 확장.

### 왜 단독 뷰가 거의 공짜인가

세션의 `viewer.html` 은 이미 **자체완결형** 으로 빌드되어 있다:
- `logs.jsonl` / `inputs.jsonl` / `metrics/*.jsonl` 모두 인라인 `<script type="application/json">`
- `screen.mp4` / `logs.vtt` / `inputs.vtt` 만 **상대경로 참조**
- 즉 서버가 그 폴더를 **정적 파일로 서빙만 하면** 됨. 별도 뷰어 백엔드 0

→ Hub 구현이 사실상 "세션 폴더 업로드 + 정적 호스팅 + 약간의 인덱스" 로 줄어듦.

### 엔드포인트 스케치

세 가지 소비자, 세 가지 인터페이스 — **같은 백엔드** 공유:

```
# (1) Trailbox 클라이언트 ↔ 서버  (인증: API 토큰)
POST   /api/sessions/{id}              # multipart 업로드 (재개 지원: chunked)
GET    /api/sessions                   # 목록 (페이지네이션 + 메타 요약)
GET    /api/sessions/{id}/zip          # zip 다운로드
DELETE /api/sessions/{id}              # 삭제
POST   /api/sessions/{id}/share        # 공유 토큰 발급

# (2) 인간 reviewers — 브라우저  (인증: 토큰이 URL 일부)
GET    /v/{token}/                     # viewer.html — full HTML, 변경 없음
GET    /v/{token}/screen.mp4           # 미디어 (HTTP Range, 시킹용)
GET    /v/{token}/{anything}           # 정적 서빙 (logs.vtt 등)

# (3) AI clients — MCP  (인증: API 토큰)
# Option A — HTTP transport 직접:
GET/POST  /mcp                         # MCP Streamable HTTP endpoint
# 7개 도구 (list_sessions, query_events, get_metrics, search_logs,
# get_frame_at, get_session, get_viewer_path) 모두 노출

# Option B — 로컬 stdio 브리지:
# 별도 Trailbox-hub-mcp.exe (혹은 기존 Trailbox-mcp.exe 가 환경변수로 분기)
# TRAILBOX_HUB_URL 환경변수 설정 시 같은 7개 도구가 Hub HTTP API 를 호출
# Claude Desktop 등록 시 stdio 트랜스포트만 지원하면 이 경로
```

**왜 같은 7개 도구를 재사용하나** — 토큰 비용 절감의 핵심은 *AI 가 데이터를 일부만 골라 받는 능력*. 로컬 MCP 서버가 이미 그 패턴을 구현해놨고 (시간 범위 / 종류 / 검색어 필터, 단일 프레임 추출 등), Hub 도 결국 같은 *질의 패턴* 으로 끝남. 백엔드만 "filesystem under output/" → "HTTP GET to hub" 로 바뀜.

### 저장 레이아웃

```
hub_data/
├── _index.json            # 가벼운 인덱스 (선택, 캐시 용도)
├── _tokens.json           # 공유 토큰 → session_id 매핑
└── {session_id}/...       # Trailbox output 구조 그대로 (viewer.html 포함)
```

- 데이터베이스 없음. **flat files + filesystem enumeration** 이 충분.
- 토큰 매핑은 작은 JSON 한 파일로 충분 (수천 세션까지). 더 커지면 SQLite.

### 단일 파일 웹 서버 — 후보 비교

| 구현 | 단일 바이너리 크기 | 메모리 | 개발 비용 | 메모 |
|---|---|---|---|---|
| **Go** (`net/http`) | ~10 MB | ~20 MB | 1~2일 | 가장 가벼움. Range request / 정적 서빙 표준 라이브러리. 다른 언어 추가 비용 |
| **Rust** (`axum`) | ~5 MB | ~10 MB | 1~2일 (러스트 익숙도 가정) | 더 작고 빠름. 학습/관리 비용 |
| **Python + FastAPI + PyInstaller** | ~30 MB | ~80 MB | 0.5~1일 | 본 프로젝트와 같은 스택. 빌드는 build.py 로 통합 가능. 런타임 무거움 |
| **Caddy + 정적 파일** | ~40 MB (Caddy) | 낮음 | 거의 0 (config 만) | API (upload/share-token) 가 없음 → 별도 작은 API 서버 병행 필요 |

**추천**: Go 가 "single-file + 가벼움 + 운영 코스트 최소" 의 정의에 가장 잘 맞음. 다만 본 프로젝트가 Python 단일 스택을 유지하려면 Python+FastAPI 도 합리적 (PyInstaller 로 묶어 단일 .exe / 단일 ELF 가능).

이 결정은 *구현 시점* 에 다시. Python 으로 가면 본 코드와 코드 공유 가능 (viewer 재생성 로직 등) 이라는 미세한 이점.

### Trailbox 클라이언트 측

UI 추가:
- 설정 패널 (현재 없음 — 새로 만들어야): `Hub URL`, `API Token`
- 레코더 패널에 토글: `녹화 종료 시 자동 업로드`
- 세션 선택 모달 (`SessionPickerDialog`) 에 추가 컬럼 `허브 상태` (uploaded / local-only)
- "허브에서 세션 가져오기" 다이얼로그 — 원격 목록 + 다운로드
- 세션 우클릭 컨텍스트 메뉴: `공유 링크 만들기` → 토큰 받아 클립보드에 URL 복사

작업량:
- 클라이언트 HTTP 코드 (`core/hub_client.py`, requests/httpx): ~150줄
- UI 통합 (설정 다이얼로그 + 메뉴 + 자동 업로드): ~200줄

### 운영 / 보안 / 비용 고려

**호스팅**
- 사내 LAN: 0원. 1U 박스 / 회사 서버 한 슬롯
- 인터넷 노출 필요 시: Hetzner CX11 ($4.5/월) / Oracle Cloud Free / Fly.io 무료 티어
- 디스크: 세션 하나당 mp4 100MB~수 GB. 100 세션이면 평균 200GB 라고 잡으면 됨
- 도메인 + Caddy 자동 TLS: 도메인 비용 (~$10/년) 만

**인증**
- API: API 토큰 (한 팀에 하나 공유 OK MVP). 헤더 `X-Trailbox-Token`
- 공유 뷰: 토큰이 URL 일부 (UUIDv4) → unguessable. 만료시각·1회용 옵션 추가 가능

**개인정보 / 프라이버시**
- 녹화는 화면+사운드+키입력 → 패스워드 입력 / 개인 메시지 같은 민감 데이터 포함 가능성
- 클라이언트 업로드 시 *선택 제외 옵션*: `inputs.jsonl` 빼기, raw 로그 빼기 등
- 서버 access log 보존 (감사용)
- HTTPS 필수 (사내 LAN 도 권장)

**저장 정책**
- 자동 만료: 30/60/90일 후 자동 삭제 옵션
- 디스크 쿼터 알람
- 백업: 일 1회 hub_data 전체 tar.gz → object storage (S3/B2) 옵션

### 구현 페이즈 제안

| 단계 | 내용 | 작업량 |
|---|---|---|
| **Phase 1** | 서버 골격 (업로드/목록/다운로드/삭제 + 정적 서빙) + Trailbox 클라이언트 수동 업로드 버튼 | 1~2일 |
| **Phase 2** | 공유 토큰 + `/v/{token}` 인간용 뷰 라우팅 + 토큰 발급 UI | 0.5일 |
| **Phase 3** | **AI MCP 통합** — 로컬 MCP 의 7개 도구를 Hub 백엔드와 연결. 환경변수 `TRAILBOX_HUB_URL` 로 분기하는 게 가장 단순 (`Trailbox-mcp.exe` 한 바이너리가 로컬/원격 둘 다 처리). 또는 별도 `Trailbox-hub-mcp.exe` | 1일 |
| **Phase 4** | 자동 업로드 토글 + 청크 업로드(재개) + 인증 + 만료 정책 | 1~2일 |
| **Phase 5** | 클라이언트의 "허브에서 가져오기" + 원격 SessionPicker | 0.5일 |
| **Phase 6** | TLS / Caddy 통합 가이드 / Docker compose 한 줄 배포 | 0.5일 |

총 ~6일. 단일 .exe / 단일 ELF / docker-compose.yml 셋 다 제공해서 *셋업 비용을 거의 0* 으로 만드는 게 목표.

### 핵심 디자인 결정 (구현 시작 시 점검)

- [ ] 서버 언어: Go vs Python (단일 스택 가치 vs 운영 가벼움)
- [ ] 인증: API key only vs OIDC vs none(LAN)
- [ ] 공유 토큰: 영구 vs 만료. 1회용 옵션
- [ ] mp4 압축: 업로드 전 추가 압축? 현재 H.264 충분히 작음 → skip
- [ ] 동시 업로드: 직렬 vs 청크 병렬
- [ ] 객체 스토리지(S3) 백엔드: Phase 1엔 disk-only, 후에 추상화
- [ ] **AI MCP 트랜스포트**: 서버 직접 노출 (`/mcp` HTTP) vs 로컬 stdio 브리지 vs 둘 다. Claude Desktop 현재 stdio 가 가장 보편적이라 우선은 브리지 권장. HTTP MCP 표준이 mainstream 되면 추가
- [ ] **MCP 백엔드 분기 방식**: 기존 `Trailbox-mcp.exe` 에 `TRAILBOX_HUB_URL` 환경변수 추가 vs 별도 `Trailbox-hub-mcp.exe`. 전자가 사용자 경험 단순 (바이너리 1개), 후자가 코드 격리 깔끔. 환경변수 분기 추천

### 인간 뷰 vs AI 뷰의 데이터 흐름 차이

**인간 (브라우저)** — viewer.html 통째 다운로드 OK:
- HTML 30~100 KB, 그 안에 모든 jsonl 인라인 → 브라우저는 한 번 받고 끝
- mp4 는 Range request 로 스트리밍

**AI (MCP 클라이언트)** — 통째 받기 거부:
- 토큰 비용 ≈ HTML 크기 × 4 (대략)
- 한 세션 분석 위해 통째 로드 → 5만~50만 토큰
- 그래서 MCP 가 *작은 도구 호출* 단위로 분리. `query_events(t_start=10, t_end=15)` 같은 식으로 필요한 슬라이스만
- 7개 도구로 충분히 커버됨 (`list_sessions`, `get_session`, `query_events`, `get_metrics`, `search_logs`, `get_frame_at`, `get_viewer_path`)

### viewer.html / mp4 / 인프라 조정 사항

거의 없음 — 현재 viewer.html 이 이미 file:// 호환 (`fetch()` 안 쓰고 인라인). HTTP 서빙 시 그대로 동작.

확인할 것:
- `<video>` 의 mp4 streaming: 서버가 **HTTP Range request** 지원해야 영상 시킹 가능. Go `http.ServeFile` / FastAPI `FileResponse` 둘 다 기본 지원.
- 큰 mp4 (수 GB) 의 초기 메타데이터 위치: ffmpeg 인코딩 시 `-movflags +faststart` 추가하면 mp4의 moov atom 이 파일 앞쪽으로 와서 스트리밍 시 빠른 시킹. **screen_recorder.py 의 ffmpeg 호출에 추가하면 좋음** — 본 작업과 독립적으로 가능.
- 큰 jsonl (수십만 라인) viewer 렌더링: 현재 통째 로드라 브라우저 메모리 압박. 본 작업 들어가기 전 viewer 에 가상 스크롤 도입하면 더 좋음 — 이미 백로그에 있음.

---

## 기타 백로그 (우선순위 낮음)

- **GitHub Actions 자동 빌드** — tag 푸시 시 GUI/MCP .exe 자동 빌드 + Release 자동 첨부
- **메모리 덤프** (옵션) — anti-cheat 제약 큼. 자체 개발 게임 QA 시나리오 한정으로 유용
- **viewer 차트 후처리 옵션** — fps moving average, GPU 엔진별 라인 분리, X축 줌
- **per-app audio (WASAPI Process Loopback)** — 게임 소리만 격리. ~260줄
- **로그 라인 자동 파싱** — `[INFO]`/`[ERROR]` 패턴 추출해 `log.level` 필드 자동 채우기
- **MCP 캡처 제어** — AI 가 녹화 시작/종료. 헤드리스 모드 또는 IPC 필요
- **viewer 의 1만+ 이벤트 대응** — 가상 스크롤 도입
