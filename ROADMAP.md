# ROADMAP — 향후 작업

세션 안에서 결론 난 항목은 [DEVNOTES.md](DEVNOTES.md) 참조. 여기는 *아직 안 한 일* 의 설계 메모.

---

## Trailbox Hub — 세션 공유 웹 서비스

### 목표

- Trailbox 가 녹화한 세션을 **서버에 업로드 / 서버에서 다운로드**
- 서버는 **단일 파일 실행 웹 서버** (의존성 셋업 최소)
- 녹화 데이터는 서버의 **하위 폴더** (`hub_data/{session_id}/...`) 로 저장
- 운영 코스트 최소화 (단일 VPS 또는 사내 LAN 에서 0원에 가깝게)
- **공유 URL 단독 뷰** — Trailbox 설치 없는 사람도 브라우저로 viewer 페이지 열 수 있어야 함. QA 결과를 *링크로 던지는* 워크플로 지원

### 왜 단독 뷰가 거의 공짜인가

세션의 `viewer.html` 은 이미 **자체완결형** 으로 빌드되어 있다:
- `logs.jsonl` / `inputs.jsonl` / `metrics/*.jsonl` 모두 인라인 `<script type="application/json">`
- `screen.mp4` / `logs.vtt` / `inputs.vtt` 만 **상대경로 참조**
- 즉 서버가 그 폴더를 **정적 파일로 서빙만 하면** 됨. 별도 뷰어 백엔드 0

→ Hub 구현이 사실상 "세션 폴더 업로드 + 정적 호스팅 + 약간의 인덱스" 로 줄어듦.

### 엔드포인트 스케치

```
# Trailbox 클라이언트 ↔ 서버 (인증 필요)
POST   /api/sessions/{id}              # multipart 업로드 (재개 지원: chunked)
GET    /api/sessions                   # 목록 (페이지네이션 + 메타 요약)
GET    /api/sessions/{id}/zip          # zip 다운로드 (Trailbox 가 가져올 때)
DELETE /api/sessions/{id}              # 삭제

# 공유 뷰 (인증 분리: 단축 토큰)
POST   /api/sessions/{id}/share        # 공유 토큰 발급 (만료시각 옵션)
GET    /v/{token}/                     # 토큰 매핑된 세션의 viewer.html
GET    /v/{token}/screen.mp4           # 미디어 (HTTP Range 필수, 시킹용)
GET    /v/{token}/logs/logs.vtt        # 자막
GET    /v/{token}/{anything}           # 그 외 세션 폴더 정적 파일 (read-only)
```

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
| **Phase 2** | 공유 토큰 + `/v/{token}` 단독 뷰 라우팅 + 토큰 발급 UI | 0.5일 |
| **Phase 3** | 자동 업로드 토글 + 청크 업로드(재개) + 인증 + 만료 정책 | 1~2일 |
| **Phase 4** | 클라이언트의 "허브에서 가져오기" + 원격 SessionPicker | 0.5일 |
| **Phase 5** | TLS / Caddy 통합 가이드 / Docker compose 한 줄 배포 | 0.5일 |

총 ~5일 정도. 단일 .exe / 단일 ELF / docker-compose.yml 셋 다 제공해서 *셋업 비용을 거의 0* 으로 만드는 게 목표.

### 핵심 디자인 결정 (구현 시작 시 점검)

- [ ] 서버 언어: Go vs Python (단일 스택 가치 vs 운영 가벼움)
- [ ] 인증: API key only vs OIDC vs none(LAN)
- [ ] 공유 토큰: 영구 vs 만료. 1회용 옵션
- [ ] mp4 압축: 업로드 전 추가 압축? 현재 H.264 충분히 작음 → skip
- [ ] 동시 업로드: 직렬 vs 청크 병렬
- [ ] 객체 스토리지(S3) 백엔드: Phase 1엔 disk-only, 후에 추상화

### 단독 뷰가 의도대로 동작하기 위한 viewer.html 조정 사항

거의 없음 — 현재 viewer.html 이 이미 file:// 호환 (`fetch()` 안 쓰고 인라인). HTTP 서빙 시 그대로 동작.

확인할 것:
- `<video>` 의 mp4 streaming: 서버가 **HTTP Range request** 지원해야 영상 시킹 가능. Go `http.ServeFile` / FastAPI `FileResponse` 둘 다 기본 지원.
- 큰 mp4 (수 GB) 의 초기 메타데이터 위치: ffmpeg 인코딩 시 `-movflags +faststart` 추가하면 mp4의 moov atom 이 파일 앞쪽으로 와서 스트리밍 시 빠른 시킹. **screen_recorder.py 의 ffmpeg 호출에 추가하면 좋음** — 본 작업과 독립적으로 가능.

---

## 기타 백로그 (우선순위 낮음)

- **GitHub Actions 자동 빌드** — tag 푸시 시 GUI/MCP .exe 자동 빌드 + Release 자동 첨부
- **메모리 덤프** (옵션) — anti-cheat 제약 큼. 자체 개발 게임 QA 시나리오 한정으로 유용
- **viewer 차트 후처리 옵션** — fps moving average, GPU 엔진별 라인 분리, X축 줌
- **per-app audio (WASAPI Process Loopback)** — 게임 소리만 격리. ~260줄
- **로그 라인 자동 파싱** — `[INFO]`/`[ERROR]` 패턴 추출해 `log.level` 필드 자동 채우기
- **MCP 캡처 제어** — AI 가 녹화 시작/종료. 헤드리스 모드 또는 IPC 필요
- **viewer 의 1만+ 이벤트 대응** — 가상 스크롤 도입
