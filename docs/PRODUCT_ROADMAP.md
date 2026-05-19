# Trailbox — Product & Technical Roadmap

> **Status**: Strategy document (v1, 2026-05-19)
> **Scope**: 제품 비전부터 OSS / SaaS / B2B / Agent-시대 확장까지 단일 문서에서 통합 관리.
> **이 문서의 위치**: 단기 백로그/구현 결정 기록은 [ROADMAP.md](../ROADMAP.md), [DEVNOTES.md](../DEVNOTES.md) 가 담당. 본 문서는 **장기 전략 / 아키텍처 / 사업 방향** 만 다룬다.

---

## 0. TL;DR

Trailbox 는 “screen recorder” 가 아니라 **session-level execution trace platform** 이다.
한 문장으로:

> *어떤 실행(session)이 발생했는지를 video / audio / log / telemetry / input / network / AI-trace 까지 단일 monotonic timeline 위에 기록해, 이후 재현(replay) · 분석(observability) · 협업(collaboration)을 가능하게 만드는 cross-platform 플랫폼.*

진화 축:

```
Recording   →   Replayability   →   Observability   →   Session Intelligence
 (v0.x)         (v1.x)              (v2.x)             (v3.x, AI/Agent 시대)
```

핵심 차별점은 **(1) 단일 timeline 보장**, **(2) capture provider 추상화**, **(3) OSS-first core**.

---

## 1. 제품 비전 (Product Vision)

### 1.1 한 줄 비전
> **“실행을 다시 볼 수 있게 만든다.” (Make every execution replayable.)**

### 1.2 비전을 더 풀어쓰면
- 사람이든 AI agent 든 어떤 시스템이 “실행” 을 했을 때, 그 실행은 휘발되어선 안 된다.
- 그 실행은 **재현 가능**해야 하고, **시간 정렬된 멀티소스 데이터**로 분석 가능해야 하며, **공유 가능**해야 한다.
- 화면 녹화는 그 중 가장 직관적인 한 차원일 뿐, 본질은 **execution trace**.

### 1.3 Why now
| 트렌드 | Trailbox 와의 연관 |
| --- | --- |
| AI agent / autonomous workflows 의 확산 | agent 실행을 사람이 audit 하려면 replay infra 필요 |
| LLM observability 시장의 대두 (Langfuse, Helicone 등) | 텍스트-only trace 의 한계 → multimodal trace 가 다음 단계 |
| 게임 QA · 디바이스 팜 · 원격 QA 의 표준화 압력 | OEM-중립 cross-platform capture 의 시장 갭 |
| Remote work, distributed teams | bug 재현 비용 ↓ → 동기화된 session package 의 가치 ↑ |
| Local-first / privacy-first 회귀 | clip 을 서버로 보내지 않고도 분석 가능한 self-contained viewer 의 가치 |

### 1.4 비전이 아닌 것 (Non-Goals)
- **단순 화면 녹화기 (OBS / ShareX 대체) 가 아니다.** UX는 비슷해 보일 수 있지만 핵심은 “trace” 다.
- **클립 공유 SNS (Medal.tv) 가 아니다.** Trailbox 의 default 출력은 viewer + data, 30초 하이라이트가 아니다.
- **클라우드 SaaS-only 가 아니다.** Core 는 항상 local-first / file-based.

---

## 2. 핵심 철학 (Core Philosophy)

이 7개 원칙은 모든 설계/PR 의 평가 기준이다. 충돌 시 **위에 적힌 원칙이 우선**.

1. **Reproducibility > Fidelity**
   - “예쁜 비디오” 보다 “재현 가능한 trace” 가 우선. 비트레이트보다 timestamp 정확도가 중요.
2. **Single Monotonic Timeline**
   - 모든 데이터 소스는 동일한 `t_video_s = perf_counter() - t0_perf` 축에 정렬된다. 이 규칙은 [CLAUDE.md](../CLAUDE.md) 에 박혀 있고, 본 문서의 모든 기능은 이 규칙을 깨지 않는다.
3. **Capture Provider Abstraction**
   - OS, 디바이스, 캡처 방식은 plugin. Core 는 어떤 provider 가 frame 을 주든 동일 timeline 으로 받아들인다.
4. **No-install First**
   - 가능한 한 사용자 디바이스에 agent 설치를 강요하지 않는다. agent 는 **opt-in / premium** 경로.
5. **OSS-first Core, Commercial Edges**
   - Capture 코어 / viewer / session 포맷은 MIT. 클라우드, 어드밴스드 모바일 agent, 디바이스 팜 같은 “네트워크 효과 & 인프라” 부분은 상업 영역.
6. **Local-first, Cloud-optional**
   - 세션은 항상 로컬 파일로 존재해야 한다. 클라우드는 sync 레이어이지 소스가 아니다.
7. **No Vendor Lock-in (특히 OEM 정책)**
   - Samsung OneUI 의 마이크 정책 변경 한 번에 제품이 죽지 않도록, 대안 provider 가 항상 존재해야 한다.

---

## 3. 아키텍처 (Architecture)

### 3.1 Layered View

```
                    ┌──────────────────────────────────────────────┐
                    │           Session Intelligence Layer         │
                    │  (AI diagnostics, anomaly detect, summarize) │
                    └──────────────────────────────────────────────┘
                                          ▲
                    ┌──────────────────────────────────────────────┐
                    │              Observability Layer             │
                    │   (timeline viewer, query, overlays, search) │
                    └──────────────────────────────────────────────┘
                                          ▲
                    ┌──────────────────────────────────────────────┐
                    │              Session Package Layer           │
                    │   (manifest, indices, container, signing)    │
                    └──────────────────────────────────────────────┘
                                          ▲
                    ┌──────────────────────────────────────────────┐
                    │            Synchronization / Timeline        │
                    │       (t0_perf, monotonic clock, drift fix)  │
                    └──────────────────────────────────────────────┘
                                          ▲
   ┌────────────────────┬─────────────────┴─────────────────┬─────────────────────┐
   ▼                    ▼                                   ▼                     ▼
Capture Providers   Telemetry Providers              Input Providers       Network Providers
(video/audio)       (cpu/gpu/fps/perfetto)           (kbd/mouse/touch)     (pcap/proxy)
```

### 3.2 Capture Provider Abstraction

핵심 인터페이스 (의사 코드):

```python
class CaptureProvider(Protocol):
    name: str                       # "dxcam", "wgc", "scrcpy", "agent-android", ...
    target_kind: Literal["monitor","window","device","stream"]
    capabilities: ProviderCapabilities  # has_audio, has_input, max_fps, supports_drm, ...

    def start(self, t0_perf: float, sink: FrameSink) -> None: ...
    def stop(self) -> StopReport: ...                # frames written, gaps, errors
    def healthcheck(self) -> ProviderHealth: ...
```

Provider 카탈로그 (현재 + 계획):

| Provider | Platform | Type | Status | 비고 |
| --- | --- | --- | --- | --- |
| `dxcam` | Win | desktop monitor | **shipped** | DXGI Desktop Duplication |
| `wgc` (windows-capture) | Win | desktop window | **shipped** | WGC, push-model |
| `screenrecord` (adb) | Android | device | **shipped (fallback)** | no-install, USB |
| `scrcpy` | Android | device | **shipped** | low-latency, video+control |
| `agent-android` | Android | device | planned (v2) | premium, precise sync |
| `replaykit` | iOS | device | planned (v2) | broadcast extension |
| `quicktime-tether` | iOS | device | planned (v2) | macOS-host only |
| `hdmi-capture` | any | external | planned (v3) | capture card 기반 |
| `avfoundation` | macOS | desktop | planned (v1) | screencaptureket fallback |
| `pipewire` | Linux | desktop | planned (v1) | Wayland 호환 |
| `xcb-shm` | Linux | desktop | planned (v1) | X11 fallback |
| `agent-pc` | Win/mac/Linux | desktop | planned (v3) | for headless / remote |
| `webrtc-stream` | any | remote | planned (v3) | cloud replay / 디바이스 팜 |

### 3.3 Timeline 동기화 — 가장 중요한 invariant

> *The single rule that holds Trailbox together.*

- `TrailboxWindow._on_start_requested` 가 **하나의** `t0_perf = time.perf_counter()` 를 잡는다.
- 이후 spawn 되는 모든 recorder 는 이 값을 인자로 받고, 모든 emit line 에 `t_video_s = perf_counter() - t0_perf` 를 기록한다.
- Cross-host (PC ↔ Android) 의 경우엔 **clock translation table** 을 메타에 남긴다:
  - `host_perf_t0`, `device_monotonic_t0`, `device_realtime_t0`, `offset_estimator: {ntp|manual|adb-shell-clock}`
  - viewer/MCP 가 device 쪽 timestamp 를 host timeline 으로 mapping 할 수 있도록.

이 invariant 를 깨는 변경은 PR 단위에서 reject 한다.

### 3.4 Recorder / Pipeline Graph (현재 PC 기준)

```
                   ┌─────────────────────┐
                   │ Capture Provider    │  (dxcam / wgc / scrcpy / ...)
                   └─────────┬───────────┘
                             │ frames
                             ▼
        ┌──────────────────────────────────────────┐
        │ ffmpeg subprocess                        │
        │ -use_wallclock_as_timestamps 1           │
        │ -fps_mode passthrough                    │
        └────────┬─────────────────────────────────┘
                 │
                 ▼
          screen.video.mp4 (intermediate)
                                        ┌──── AudioRecorder ─── screen.audio.wav
                                        ├──── LogCollector  ─── logs/logs.jsonl + .vtt
                                        ├──── InputRecorder ─── inputs/inputs.jsonl + .vtt
                                        └──── MetricsRecorder ─ metrics/process.jsonl

                 │ on stop
                 ▼
         post_mux.mux_av() → screen.mp4
                 │
                 ▼
         session.finalize() → session_meta.json
                 │
                 ▼
         viewer_generator.generate_viewer() → viewer.html
```

### 3.5 Hub / Cloud 확장 슬롯

```
        Trailbox client                Trailbox Hub (self-hosted / SaaS)
        ───────────────                 ─────────────────────────────────
         output/{sid}/  ──── chunk upload (resumable) ──▶  /sessions/
                                                              │
                                                              ▼
                                                   /v/{token}/  ← share link
                                                   /admin       ← admin web UI
                                                   /mcp         ← MCP HTTP (future)
```

---

## 4. 단계별 로드맵 (Phased Roadmap)

각 phase 는 **6–9 개월** 단위로 잡되, “지금 어디쯤이냐” 의 좌표축으로 사용한다.
현재 Trailbox 는 **Phase 1 후반 / Phase 2 진입** 위치다.

### Phase 1 — Foundation: “Trustworthy Recorder” *(현재 ~ +3개월)*

| 항목 | 내용 |
| --- | --- |
| **목표** | PC + Android USB 캡처를 **production-grade quality** 로. 단일 timeline invariant 확립. |
| **핵심 기술** | dxcam, WGC, ffmpeg VFR, scrcpy/adb screenrecord, pynput, psutil, PDH (GPU) |
| **deliverables** | (✅ 대부분 완료) Windows desktop full capture, Android USB no-install capture, self-contained viewer.html, session_meta.json, MCP read-only tools |
| **남은 작업** | macOS / Linux desktop provider, Android scrcpy ↔ screenrecord 자동 fallback 안정화, audio sync drift 측정 자동화 |
| **리스크** | DRM 화면 blanking, anti-cheat process 보호, USB 끊김 복구 |
| **성공 기준** | (1) 30분 연속 세션 audio drift < 100ms, (2) `t_video_s` 정확도 ±16ms p95, (3) viewer.html file:// 환경에서 zero-dep 동작 |
| **OSS / BM** | 전부 MIT, BM 없음 — adoption 우선 |

### Phase 2 — Replayability: “Session as a Package” *(+3 ~ +9개월)*

| 항목 | 내용 |
| --- | --- |
| **목표** | 세션을 **단일 portable artifact** 로. timeline viewer 가 1급 시민. cross-machine 재현. |
| **핵심 기술** | session container 포맷 (`.tbx`), indexed timeline (sqlite), Perfetto 통합, VTT/Captions 다중 트랙, Hub v1 (이미 v0.1 출하), web viewer (browser-only) |
| **deliverables** | `.tbx` 포맷 spec v1, browser-based timeline viewer (CDN-load 가능), Hub admin web UI, share-link with expiration, S3 backend option |
| **리스크** | 포맷 lock-in (한 번 정하면 못 바꿈) → spec 을 protobuf + versioning 으로 안정화 |
| **성공 기준** | (1) `.tbx` 파일 1개로 모든 정보가 self-contained, (2) browser viewer 가 1GB 세션을 streaming 으로 재생, (3) Hub 가 100 동시 업로더 안정 운영 |
| **OSS / BM** | Core MIT 유지. **Hub Self-Hosted 는 무료 / Hub Cloud (managed) 는 유료** 분기 시작 |

### Phase 3 — Observability: “Query the Session” *(+9 ~ +18개월)*

| 항목 | 내용 |
| --- | --- |
| **목표** | 세션을 “재생” 하는 게 아니라 **질의**한다. metric overlay, log search, multi-session diff. |
| **핵심 기술** | OpenTelemetry traces 호환 import, ECS log schema 정착, FlatBuffers/Parquet 인덱싱, network capture (pcap / mitmproxy), Perfetto trace 직접 import |
| **deliverables** | “세션 검색 엔진” (across many sessions), multi-session compare view, alerting rules (e.g. “fps < 30 for 2s” → marker), team collaboration (comments, bookmarks) |
| **리스크** | scope creep — observability 시장은 이미 거대 (Datadog, Grafana). 우리는 **session-bounded** 라는 좁고 명확한 포지셔닝을 지킨다 |
| **성공 기준** | (1) 1000개 세션 query p95 < 500ms, (2) Perfetto / OTLP 양방향 import/export, (3) team 5인이 동일 세션에 주석 달고 협업 가능 |
| **OSS / BM** | Team collaboration / cloud query = paid. Local query / single-user = OSS. |

### Phase 4 — Session Intelligence: “Agent-era Replay” *(+18개월 ~)*

| 항목 | 내용 |
| --- | --- |
| **목표** | AI agent 실행을 audit / replay / 자동 진단. 디바이스 팜과 결합한 fleet-scale QA. |
| **핵심 기술** | Agent trace 표준 호환 (OpenAI / Anthropic / MCP), deterministic replay (input replay → bug 재현), distributed device farm (WebRTC streaming), AI diagnostic agent (이미 캡처된 세션을 보고 “여기서 뭔가 잘못됐다” 라고 말해줌) |
| **deliverables** | MCP server v2 (capture control 포함, headless mode), device farm scheduler, replayable input track, “diagnose this session” AI endpoint |
| **리스크** | deterministic replay 는 OS-level 난제 (rr, Hermit 사례 참고). 우선 **input replay + visual diff** 정도로 “practical replay” 만 노린다 |
| **성공 기준** | (1) Trailbox 세션 위에서 외부 AI agent 가 자동 trace 가능, (2) headless capture → CI 통합, (3) device farm 50대 동시 운영 |
| **OSS / BM** | 본격 SaaS 영역. Core 는 여전히 MIT. Cloud / 디바이스 팜 / AI diagnostics 가 매출 축. |

### 단계별 한눈에 보기

| Phase | 한 줄 정의 | 끝났을 때의 시그널 |
| --- | --- | --- |
| 1. Foundation | “녹화가 믿을 만하다.” | 사용자가 audio sync / drift 로 더 이상 issue 안 연다 |
| 2. Replayability | “세션이 portable artifact 다.” | `.tbx` 파일 하나로 동료가 재현 가능 |
| 3. Observability | “세션을 질의할 수 있다.” | 1000세션 중 “fps drop > 50% 인 것만” 추려낸다 |
| 4. Intelligence | “Agent 실행을 audit 한다.” | LLM agent 가 세션을 읽고 진단을 쓴다 |

---

## 5. 기술 스택 (Tech Stack)

현재 스택은 PyQt6 + Python 으로 **빠른 검증**에 최적화되어 있다. Phase 2 이후엔 두 가지 트랙으로 갈라진다:

| Layer | 현재 (v0.x) | 권장 진화 방향 | 비고 |
| --- | --- | --- | --- |
| Desktop GUI | PyQt6 | **Electron + React + TS** (Web viewer 와 코드 공유) 또는 **Tauri + React** (메모리/번들 크기 우위) | PyQt6 유지도 가능하나, web viewer 와 UI 코드 공유가 큰 이득 |
| Native hot path | Python | **Rust** (capture loop, mux, index) — 점진 마이그레이션, PyO3 bridge | ffmpeg pipe 관리, ring buffer, lock 처리에서 Python GIL 한계 시 |
| Capture (Win) | dxcam, windows-capture | 동일 + WGC 직접 바인딩 (Rust) | |
| Capture (mac) | — | AVFoundation, ScreenCaptureKit (macOS 12.3+) | |
| Capture (Linux) | — | PipeWire (Wayland), XCB-SHM (X11) | |
| Capture (Android) | adb, scrcpy | + optional native agent (Foreground Service + MediaProjection) | |
| Capture (iOS) | — | ReplayKit Broadcast Extension, QuickTime tether (mac host) | |
| Mux / encode | ffmpeg (subprocess) | ffmpeg 유지 + Rust wrapper for predictable I/O | imageio-ffmpeg 번들 유지 |
| Telemetry | psutil, PDH, GPU counters | + Perfetto (Android/Linux), ETW (Win), os_signpost (mac) | |
| Network | — | pcap (npcap/libpcap), mitmproxy (optional opt-in) | privacy 주의 |
| Storage (session) | JSONL + mp4 + html | `.tbx` (zip-based, manifest+protobuf+parquet+sqlite-index) | |
| Server (Hub) | FastAPI + sqlite | FastAPI + Postgres + S3 (managed cloud) | self-hosted 는 sqlite 유지 |
| IPC | — | gRPC (host ↔ agent), MCP (host ↔ AI client) | |
| Streaming | — | WebRTC (device farm / cloud replay) | |
| Viewer | self-contained HTML | + React/TS browser app (대용량 세션용) | file:// path 도 계속 지원 |

원칙:
- **Heavy lift 만 Rust**, glue 는 계속 Python/TS. 전면 재작성 금지.
- **번들 가능한 의존성**만 default 로. 외부 PATH 의존 금지 (ffmpeg 가 좋은 사례).
- **Wayland / macOS Sequoia 같은 OS 변동성이 큰 영역**은 abstraction 한 겹 위에서 다룬다.

---

## 6. 저장 포맷 (Storage Format)

### 6.1 현재 (v0)
[CLAUDE.md](../CLAUDE.md) 의 “Output convention” 그대로:

```
output/{session_id}/
├── screen.mp4
├── logs/{logs.jsonl, logs.vtt, raw/*}
├── inputs/{inputs.jsonl, inputs.vtt}
├── metrics/{process.jsonl, frames.jsonl}
├── viewer.html
└── session_meta.json
```

장점: 디렉터리 = 세션, 사람이 직접 까볼 수 있다.
단점: 100MB+ 로그에서 viewer.html inline 이 무거움, 인덱스 없음, share 시 zip 으로 묶어야 함.

### 6.2 `.tbx` v1 (Phase 2 도입)

`.tbx` = `.zip` (deflate / store) 컨테이너. 내부 구조:

```
session.tbx
├── manifest.json                # spec_version, capabilities, providers used
├── meta.pb                      # session_meta in protobuf (canonical)
├── video/
│   └── screen.mp4
├── audio/
│   └── screen.opus              # optional, separate from video
├── tracks/
│   ├── logs.parquet             # columnar, fast scan
│   ├── inputs.parquet
│   ├── metrics.parquet
│   └── network.parquet          # optional
├── traces/
│   └── perfetto.pb              # optional
├── index/
│   └── timeline.sqlite          # indexed by t_video_s
├── viewer/
│   └── viewer.html              # self-contained fallback
└── signatures/
    └── manifest.sig             # optional, for tamper-evidence
```

설계 원칙:
- **Manifest first**: `manifest.json` 에 `spec_version` 과 “이 세션은 어떤 트랙을 가지나” 가 적힘. 누락 트랙은 옵셔널.
- **Forward compat**: unknown 트랙은 viewer 가 무시. 새 트랙 추가가 깨는 변화 아님.
- **Streamable**: viewer 가 zip을 다 풀지 않고 entry 단위로 lazy load 가능 (브라우저 fetch + range).
- **Indexed**: `timeline.sqlite` 에 `(t_video_s, source, offset_in_parquet)` 인덱스. 1GB 세션도 “12:03:22.x 근방 이벤트” 조회 < 10ms.
- **Signable (optional)**: enterprise 사용 시 manifest 해시 서명으로 tamper-evidence.

### 6.3 마이그레이션 정책
- v0 디렉터리 → `.tbx` 변환기 / 역변환기 OSS 로 제공. 둘 다 1급.
- viewer 는 두 형식 모두 읽음.
- Hub 는 양쪽 다 accept, 내부적으론 `.tbx` 로 보관.

---

## 7. 비즈니스 모델 (Business Model)

### 7.1 4-Layer 가격 모델

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4 — Enterprise / Device Farm                         │  $$$$
│  on-prem fleet, SSO, RBAC, audit, SLA                       │
├─────────────────────────────────────────────────────────────┤
│  Layer 3 — Cloud / Collaboration                            │  $$
│  managed Hub, team workspaces, AI diagnostics, share-links  │
├─────────────────────────────────────────────────────────────┤
│  Layer 2 — Premium Providers / Add-ons                      │  $
│  Android Agent, iOS Agent, HDMI driver bundle, network cap  │
├─────────────────────────────────────────────────────────────┤
│  Layer 1 — Core (OSS, MIT)                                  │  free
│  desktop capture, USB android, viewer, MCP, .tbx, self-Hub  │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 매출 가설별 우선순위

| 시나리오 | TAM 가설 | 진입 난이도 | 우선순위 |
| --- | --- | --- | --- |
| **Mobile game QA studios** (Android Agent + Hub) | 중 | 낮음 (현존 고객층) | **1순위** |
| **AI agent observability** (Trace import + diag) | 큼, 빠르게 성장 | 중 (시장 형성 중) | **2순위** |
| **Enterprise dev tool** (on-prem) | 큼, 슬로우 | 높음 (sales-heavy) | 3순위 |
| **Indie dev / consumer** (Pro plan) | 작음, churn 큼 | 낮음 | 4순위 (실험) |
| **Device farm (CI 통합)** | 중 | 높음 (인프라) | 5순위 (Phase 4) |

### 7.3 비-BM (의도적으로 안 하는 것)
- 영상 호스팅으로 vimeo 식 단순 hosting 매출 — 차별점 없음.
- 광고 — 신뢰 깨짐, observability 와 충돌.
- 사용자 영상 학습데이터화 — 명시적으로 NO. 가격 페이지에 명기.

---

## 8. OSS 전략

### 8.1 라이선스
- **Core / capture / viewer / `.tbx` spec**: MIT.
- **Hub self-hosted**: Apache-2.0 (patent grant + 기업 채택 용이).
- **Cloud / Agent (Android/iOS) / Device Farm**: source-available or proprietary (BSL / commercial).

### 8.2 거버넌스
- 초기 BDFL 모델. Phase 2 이후 RFC 프로세스 도입 (`docs/rfcs/NNNN-*.md`).
- 주요 포맷/프로토콜(`.tbx`, MCP tool spec, clock translation table) 변경은 RFC 필수.

### 8.3 커뮤니티 빌딩
- **Discoverability**: GitHub topics, awesome-observability 류 리스트 등록, Hacker News “Show HN” (Phase 2 도입 시점).
- **Example sessions**: 공개 가능한 데모 세션 (`.tbx`) 들을 repo 에 둠 — 누구나 viewer 로 열어볼 수 있게.
- **MCP integration**: Claude Desktop, Cursor, Continue 등 에 default tool 로 들어가는 것을 목표. (이미 MCP server 구현됨)

### 8.4 OSS / 상업 라인 명확화 — “Open Core” 함정 피하기
- Capture, format, viewer, MCP read-only 는 **영원히 OSS**. 절대 EE 로 옮기지 않는다.
- 상업화 대상은 **(a) 운영/협업 인프라**, **(b) 디바이스 별 premium agent**, **(c) AI 진단**. 즉 “시간/돈/네트워크 효과” 가 드는 부분만.

---

## 9. 확장 전략 (Expansion Strategy)

### 9.1 Platform 확장 순서 (왜 이 순서인가)

```
Windows (done)
  → Android USB (done, MVP) 
      → macOS desktop (Phase 1 잔여)
          → Linux desktop (Phase 1 잔여)
              → Android Agent (Phase 2 premium)
                  → iOS via ReplayKit (Phase 2 premium)
                      → HDMI capture (Phase 3, console QA)
                          → Cloud / WebRTC device (Phase 4)
```

근거:
- **Windows + Android** 은 게임 QA 시장에서 가장 큰 페어. 매출 후보 1순위와 직결.
- **macOS / Linux desktop** 은 OSS adoption 에 결정적 (개발자 사용자).
- **iOS / HDMI** 는 비싸지만 시장 작음 → premium 으로만.

### 9.2 Vertical 확장

| Vertical | 진입 시기 | Hook |
| --- | --- | --- |
| Mobile game QA | Phase 2 | USB capture + perfetto + logcat |
| LLM agent observability | Phase 3 | trace import + replay UI |
| 보안/포렌식 (incident replay) | Phase 4 | signed `.tbx`, chain-of-custody |
| 학술 / HCI 연구 (user study) | Phase 2 | self-hosted Hub + privacy mode |
| Hardware QA / robotics | Phase 4 | external sensor ingest via plugin |

### 9.3 Ecosystem / Integration

- **Editor / IDE**: VS Code extension — open `.tbx` in side panel, jump to timestamps from stack trace.
- **CI**: GitHub Actions / Buildkite — headless capture during e2e tests, upload to Hub on failure.
- **AI Clients**: Claude / Cursor / Continue 등에서 MCP 로 직접 세션 query.
- **Bug trackers**: Linear / Jira / GitHub Issues attachment 로 `.tbx` 첨부 + auto-summary.

---

## 10. 리스크 (Risks)

### 10.1 기술 리스크

| Risk | 영향 | 완화 |
| --- | --- | --- |
| **Audio / video sync drift** (long sessions) | 사용자 신뢰 파괴 | wallclock + monotonic 이중 기록, post-mux 시 drift 보정, 자동 drift 측정 테스트 |
| **Timestamp drift across hosts** (PC↔Android) | cross-source 분석 불가 | NTP 보정 + adb shell clock 동기화 + offset estimator manifest |
| **Android OEM 정책 변동** (Samsung OneUI, MIUI 마이크 권한) | provider 하나가 죽을 수 있음 | 항상 fallback provider (예: scrcpy ↔ screenrecord ↔ agent) |
| **DRM-blanking** (Netflix, Widevine) | 일부 콘텐츠 캡처 불가 | 정책상 우회하지 않음. 명시적 documentation. |
| **Anti-cheat 가 process telemetry 차단** | 일부 게임에서 metric 없음 | psutil perf-counter 경로 (handle enumeration 보다 permissive), 안되면 graceful degrade |
| **Fullscreen Exclusive** | WGC 실패 | Borderless 권장 documentation, dxcam fallback |
| **USB 끊김 / Android device reset** | session corruption | resumable session writer, partial finalize, recovery on next start |
| **High-bitrate long session storage** | 디스크 폭주 | chunked writer, optional re-encode pass, retention policy |
| **Wayland / macOS 23+ API 변경** | 캡처 깨짐 | provider 별 capability matrix CI 매주 실행 |
| **`.tbx` v1 format mistake** | forward-compat 깨짐 | spec RFC + `spec_version` + 변환기 항상 OSS 동봉 |

### 10.2 사업/조직 리스크

| Risk | 완화 |
| --- | --- |
| Open core 함정 (community 와 commercial 의 갈등) | OSS 영역의 “절대 옮기지 않는다” 약속을 [README.md](../README.md) 와 가격 페이지에 명기 |
| 거대 클라우드 벤더(MS, Apple)가 same feature 내장 | 우리는 cross-platform + agent 협업 영역. OS 벤더는 자사 OS 내부만 다룸 — 차별성 유지 |
| 매출 발생 전 인프라 비용 (디바이스 팜) | Phase 4 까지 미루기. self-hosted Hub 로 운영비 0 base case 유지 |
| 작은 팀의 sustained 출시 부담 | release flow 자동화 ([CLAUDE.md](../CLAUDE.md) Releasing 섹션 그대로) + LTS 정책 |

### 10.3 법/프라이버시

- 사용자가 캡처한 화면에 제3자 정보 포함 가능 → **EULA / 공유 시 redaction 옵션** Phase 3 에 필수.
- Network capture 는 **opt-in only**, 기본 OFF, UI 상 명시적 경고.
- AI diagnostics 의 cloud 전송 옵션은 **per-session toggle**, default OFF.

---

## 11. 기술 난이도 (Difficulty Map)

| 작업 | 난이도 | 비고 |
| --- | --- | --- |
| Windows desktop capture | ★★☆☆☆ | 이미 해결, dxcam + WGC |
| macOS ScreenCaptureKit | ★★★☆☆ | 권한 모델 복잡 |
| Linux PipeWire/X11 | ★★★★☆ | Wayland 표준 fragment |
| Android USB no-install | ★★★☆☆ | 부분 완료, OEM 호환성 검증 부담 |
| iOS ReplayKit extension | ★★★★☆ | 앱 분리 / 코드사인 |
| Audio sync (long sessions) | ★★★★☆ | 가장 자주 사용자가 느끼는 issue |
| `.tbx` 포맷 spec & 양방향 호환 | ★★★☆☆ | 어렵진 않지만 한 번 잘못 정하면 영원히 짊어짐 |
| Indexed timeline (sqlite + parquet) | ★★☆☆☆ | 표준 도구로 가능 |
| Hub resumable upload + share | ★★★☆☆ | v0.1 완료 |
| Browser-based viewer (1GB 세션) | ★★★★☆ | streaming + WASM video |
| WebRTC device farm | ★★★★★ | 인프라 + latency + NAT |
| Deterministic replay | ★★★★★ | OS-level. **현재 단계에선 안 함.** input-replay + visual-diff 로 대체. |
| AI diagnostic agent | ★★★☆☆ | LLM 호출 + structured prompt. 데이터가 이미 정렬돼있어 상대적으로 쉬움 |

---

## 12. 미래 확장성 (Future Extensibility, “AI/Agent 시대”)

### 12.1 AI Agent 시대의 Trailbox 포지셔닝

LLM observability 가 지금 “텍스트 trace” 단계라면, agent 가 실제 OS / 브라우저 / 디바이스를 조작하는 시대엔 **multimodal trace** 가 표준이 된다. Trailbox 는 그 표준의 1차 후보가 될 수 있다:

- 사람이든 agent 든 trigger 한 “실행” 을 동일 포맷으로 기록.
- LLM 이 직접 `.tbx` 를 읽고 (이미 MCP server 가 그 인터페이스), “여기서 멈춰라 / 여기서부터 다시 해봐라” 의 결정을 내릴 수 있음.
- agent loop 의 step 마다 mini-session 을 spawn → 전체 task = `.tbx` 의 tree.

### 12.2 구체적 확장 시나리오

1. **Replayable agent runs**
   - Computer-use / browser-use agent 의 매 step 을 trailbox session 으로 기록.
   - 실패 시 사람이 video + log + input 으로 재현, agent prompt 디버그.

2. **Deterministic-ish replay (실용 버전)**
   - Phase 4: input track (mouse / keyboard / adb input) 만 정확히 기록되어 있으면, 동일 환경에서 “재생” 가능.
   - 100% deterministic 은 포기. **“시각적으로 동일한 결과” 가 나오는 빈도 70%+** 가 현실 목표.

3. **Multiplayer collaborative debugging**
   - 같은 `.tbx` 에 여러 사람이 timestamp 단위 주석 / 토론.
   - Phase 3 collaboration 의 자연스러운 확장.

4. **Remote execution tracing**
   - QA 엔지니어가 원격 디바이스에서 실행 → 매니저가 cloud 에서 실시간 (WebRTC) 으로 follow + 기록.

5. **Distributed observability**
   - 서버 + 클라이언트 + 모바일 의 세션을 **단일 분산 timeline** 으로 묶기 (예: PC 클라이언트 세션 ↔ 서버 OpenTelemetry trace ↔ 모바일 세션 동시 캡처).

6. **Autonomous QA agents**
   - “이 빌드를 가지고 30분 동안 자유롭게 플레이해. 이상한 거 발견하면 알려줘.” — agent 가 실행하고, Trailbox 가 모든 trace 를 받고, 다시 agent 가 self-review.

7. **Device farm**
   - 50대 Android + 10대 iOS 가 Hub 에 attach. CI 가 매 PR 마다 random subset 에 빌드를 push → `.tbx` 자동 수집.

### 12.3 표준화 시도
- **Clock translation table** 과 **`.tbx` manifest** 는 가능한 한 빠르게 spec 문서화.
- OpenTelemetry / Perfetto / W3C Media Source 같은 기존 표준과 **호환**을 우선. 새 표준을 만들기보다 기존 위에 layered.

---

## 13. 부록 — 의사결정 기록 / Open Questions

### 13.1 이미 결정된 것
- monotonic timeline 단일 invariant ([CLAUDE.md](../CLAUDE.md))
- ffmpeg 번들 (`imageio-ffmpeg`), PATH 의존 금지
- viewer.html 은 token replacement (`__SESSION_ID__` 등), `.format()` 금지
- COM threading import order (`screen_recorder` → `audio_recorder`)
- CPU%: `cpu_pct` + `cpu_pct_per_core` 둘 다 기록
- GPU%: MAX engine (Task Manager 컨벤션)
- Hub v0.1 완료, admin web UI 가 다음

### 13.2 열려 있는 질문 (RFC 후보)

| # | 질문 | 영향도 |
| --- | --- | --- |
| Q1 | `.tbx` v1 의 protobuf vs flatbuffers? | 큼 — 영구 |
| Q2 | Rust 도입 시기와 범위? capture loop 부터? mux 부터? | 큼 |
| Q3 | Electron vs Tauri 선택 (Phase 2 web viewer 와 데스크탑 GUI 코드 공유 시) | 큼 |
| Q4 | Android Agent 의 라이선스 — source-available BSL vs proprietary? | 중 |
| Q5 | Network capture 는 default-on 인가 opt-in 인가? | 중 (privacy) |
| Q6 | AI diagnostics 호출 시 cloud LLM vs 로컬 모델 우선순위? | 중 |
| Q7 | Replay 의 “determinism 수준” 을 어디까지 공식적으로 약속할 것인가? | 큼 (기대치 관리) |

각 질문은 결정 전까지 본 문서를 단일 출처로 사용. 결정되면 `docs/rfcs/` 로 옮긴다.

---

## 14. 본 문서 사용법

- **PR 리뷰 시**: 이 문서의 § 2(철학) / § 6(포맷) 와 충돌하는 변경이면 reject 또는 RFC 요구.
- **새 provider 추가 시**: § 3.2 의 인터페이스 따르기 + § 3.3 의 timeline invariant 깨지 않기.
- **새 BM 아이디어 검토 시**: § 7.3 “안 하는 것” 와 § 8.4 “OSS / 상업 라인” 에 안 부딪히는지 먼저 본다.
- **분기마다**: § 4 phase 위치를 갱신, § 13.2 의 open question 줄여나가기.

---

*Document owner: Trailbox core team. Last reviewed: 2026-05-19.*
