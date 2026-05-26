# macOS 포팅 계획 — Trailbox 데스크톱 앱

> 대상: **데스크톱 앱 (Tauri 셸 + Python 캡처 스택)**.
> 비대상: MCP 서버 (build target 추가만), Hub 서버 (이미 cross-platform).
> 후속: 본 포팅이 끝난 뒤 **iOS 캡처** 기능을 추가한다 — 그 작업의 *전제조건* 이 이 문서.

배경: `docs/android-capture-plan.md` 의 의도("Mac 포팅 = iOS 캡처 전제조건. Android 는 우회로로 먼저 처리") 를 이어받아, 이번에는 Mac 자체의 데스크톱 캡처를 1급 시민으로 올린다.

---

## 0. 범위 합의

| 신호 | Windows (기존) | macOS 목표 | 동등성 |
|---|---|---|---|
| 화면 (모니터/창) | dxcam + windows-capture | **ScreenCaptureKit** (macOS 12.3+) | full |
| 시스템 오디오 | soundcard (WASAPI loopback) | **SCStream audio** (macOS 13+) | full on 13+, *graceful degrade* on 12.x |
| 키보드/마우스 | pynput + win32gui 좌표 | pynput + Quartz `CGWindowList…` 좌표 | full (단 Accessibility 권한 필수) |
| 앱 로그 (watchdog) | 동일 | 동일 | full (watchdog cross-platform) |
| 프로세스 텔레메트리 (CPU/RSS/threads) | psutil | psutil | full |
| GPU% / VRAM | win32pdh | **v1: None**, v2: `powermetrics` / IOReport | partial (뷰어가 누락 필드 graceful) |
| 글로벌 핫키 | pynput.GlobalHotKeys | 동일 | full (Accessibility) |
| 윈도우 열거 / 클릭-피커 | win32gui | Quartz `CGWindowListCopyWindowInfo` | full |
| 시스템 스냅샷 (sysinfo) | wmic + win32_ver | `sw_vers` + `system_profiler -json` + `sysctl` | full |
| 앱 자동 실행 | subprocess + cwd | `open -a` / `subprocess` | full |
| Android 캡처 | adb/scrcpy 번들 | adb/scrcpy mac 바이너리 번들 | full (재컴파일 무용) |

**v1 Definition of Done**: 위 표의 "full" 항목 9개가 mac에서 동작 + GPU 는 빈 값으로 나가도 viewer/MCP/Hub 가 깨지지 않음 + 새 mac 빌드로 PC + Android 캡처 둘 다 1회 통과.

---

## 1. 불변식 — *절대 깨지 않는다*

CLAUDE.md 의 single rule 그대로:

1. **`t0_perf` 캡처는 한 군데** (`bridge_record.py` 또는 `main.py._on_start_requested`).
2. 모든 레코더는 `t_video_s = perf_counter() - t0_perf` 를 JSONL 라인에 방출.
3. **출력 디렉터리 레이아웃, 파일명, JSONL 스키마는 OS 무관 동일.**
4. viewer/MCP/Hub 는 OS 분기 없음.

mac 백엔드도 *반드시* 이 계약을 따른다. ScreenCaptureKit 의 native 콜백 시각이 별도 시계라도 입력 시점에 `time.perf_counter()` 로 변환해 통일한다.

---

## 2. 모듈별 포팅 매트릭스

리팩토링 원칙: 각 모듈에 *얇은 dispatcher* + `core/_backends/` 하위에 `win_*.py` / `mac_*.py` / `common_*.py` 분리. 외부 호출 인터페이스(public API)는 그대로.

### 2.1 `core/screen_recorder.py` — 가장 큰 작업

현재: `CaptureTarget` discriminated union (`MonitorTarget` / `WindowTarget` / `AndroidDeviceTarget`) + 백엔드 dispatch (`core/screen_recorder.py:256-307`).

추가: OS 축에서 분기. `MonitorTarget` / `WindowTarget` 둘 다 mac 에서는 **ScreenCaptureKit (SCK)** 단일 백엔드로 합쳐진다 (SCK 가 `SCContentFilter` 로 display/window 양쪽을 커버).

```
core/_backends/
├── screen_win_monitor.py     # dxcam (이관)
├── screen_win_window.py      # windows-capture (이관)
├── screen_mac_sck.py         # 신규: pyobjc-framework-ScreenCaptureKit
└── screen_android_scrcpy.py  # scrcpy (이관, OS-agnostic)
```

`ScreenRecorder.__init__` 가 `sys.platform` × `target.kind` 로 백엔드 클래스를 선택. ffmpeg 파이프라인(`-use_wallclock_as_timestamps 1 -fps_mode passthrough` + BGRA stdin) 은 mac 에서도 그대로 재사용.

SCK 구현 노트:
- `SCStreamConfiguration.pixelFormat = kCVPixelFormatType_32BGRA` 로 맞춰 ffmpeg 픽셀 포맷 변경 불필요.
- `CMSampleBuffer` 의 PTS 를 무시하고 콜백 도착 시점에 `time.perf_counter()` 찍는다 — VFR 정책 유지.
- macOS 14.4+ 는 "녹화 중" 시스템 인디케이터(빨간 점)가 메뉴바에 강제 표시됨 — 우회 불가, README 에 명시.
- DRM 콘텐츠는 OS 차원 블랭킹 (Windows 와 동일).

mac 12.x 미만 fallback: 없음. v1 의 최소 지원 OS 를 **macOS 12.3** 으로 고정 (SCK 도입 시점).

### 2.2 `core/audio_recorder.py`

- mac 13+ : SCK 의 audio output (`SCStreamConfiguration.capturesAudio = True`). 화면과 같은 stream 에서 받아도 되고 audio-only stream 으로 별도 구성해도 됨. WAV 출력 형식은 동일하게 유지 (s16le 48kHz stereo).
- mac 12.x : **OS 기본 loopback 없음**. UI 에서 "오디오 캡처 비활성" 또는 "BlackHole / Loopback 가상 디바이스 사용" 안내. 사용자가 가상 디바이스 설치하면 그 입력을 `sounddevice` 로 받음 — `soundcard` 는 mac 에서도 동작은 하지만 loopback 매칭이 약해서 `sounddevice` 권장.

리팩토링: `AudioRecorder` 가 backend 객체를 위임. `_backends/audio_mac_sck.py`, `_backends/audio_mac_device.py`, `_backends/audio_win_soundcard.py`.

### 2.3 `core/input_recorder.py`

- pynput 자체는 mac 지원. **단 Accessibility 권한** (System Settings → Privacy & Security → Accessibility) 필요. 첫 실행 시 권한 미허용이면 `pynput.keyboard.Listener.start()` 가 조용히 실패 → 명시적 사전 점검 추가.
- 윈도우 좌표 보정 (`core/input_recorder.py:137` 의 `win32gui.GetWindowRect`) → mac 에서는 `Quartz.CGWindowListCopyWindowInfo` 로 동일 정보 추출. backend dispatch.

### 2.4 `core/window_picker.py`, `core/window_clicker.py`

- `win32gui.EnumWindows` → `Quartz.CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)`.
- `WindowFromPoint` → 같은 API 로 좌표 hit-test.
- `WindowInfo` 데이터클래스 스키마 유지. `hwnd` 필드는 mac 에서 `CGWindowID` (정수) 로 재사용.
- pyobjc-framework-Quartz 의존성 추가.

### 2.5 `core/gpu_monitor.py`

v1: **stub** 반환 (`gpu_pct=None, gpu_engines=[], vram_mb=None`). 뷰어/MCP 가 이미 누락 필드 graceful 하게 처리 (`get_metrics` summary 의 `gpu_max` 가 None 이어도 렌더). viewer 의 `gpuMax = Math.max(100, …)` 로직은 mac 세션에서 GPU 위젯을 숨기는 분기 추가.

v2 (선택): `powermetrics --samplers gpu_power -i 1000 -n 1` 파싱. sudo 필요 — 사용자에게 admin 도움 없이 동작시키려면 helper tool + Launch Agent. **v1 범위 외.**

### 2.6 `core/system_info.py`

- `_windows_release` 옆에 `_macos_release()` 추가: `platform.mac_ver()` + `sw_vers -productName/-productVersion -buildVersion` + `sysctl -n hw.optional.arm64` (Apple Silicon 감지).
- `_gpu_names` 는 `system_profiler SPDisplaysDataType -json` 파싱.
- CPU 이름: `sysctl -n machdep.cpu.brand_string`.
- 디스플레이: `system_profiler SPDisplaysDataType -json` 의 `_items[].spdisplays_ndrvs`.

`gather()` 의 최상위 키 (`os`, `cpu`, `ram`, `gpus`, `displays`, `python`, `trailbox_version`) 는 유지 — viewer/MCP 가 그대로 읽음.

### 2.7 `core/global_hotkey.py`

pynput.GlobalHotKeys 는 mac 지원. Accessibility 권한 의존. 코드 변경 사실상 없음 — Qt 시그널 emit 만 유지.

### 2.8 `core/process_detector.py`

- `_SYSTEM_DIRS_LOWER` (`core/process_detector.py:159`) 는 Windows 경로. mac 에서는 `/system/`, `/usr/`, `/library/`, `/applications/utilities/` 추가.
- `psutil.Process.open_files()` 는 mac 에서 *제대로* 동작 (Windows 보다 오히려 잘 됨). install-dir 휴리스틱은 보조로 남김.
- 부모 프로세스 walk (`_PARENT_WALK_DEPTH=2`) 는 그대로 — Steam launcher 등 mac 에서도 동일 패턴.

### 2.9 `core/post_mux.py`

ffmpeg subprocess. 변경 없음. imageio-ffmpeg 가 mac universal2 휠 제공.

### 2.10 `core/adb.py`, `core/android_*_recorder.py`

코드 변경 거의 없음. 한 줄: `core/adb.py:78, 103` 의 에러 메시지 `"adb.exe not found"` → `f"{_exe_name('adb')} not found"`.

번들링: `tools/android/platform-tools/` 에 mac 바이너리 (`adb`, `*.dylib`), `tools/android/scrcpy/` 에 mac 빌드 (`scrcpy`, `scrcpy-server.jar`). build.py 의 `--add-binary` 평탄화 로직 그대로 동작.

### 2.11 `ui/` (PyQt6)

PyQt6 자체는 cross-platform. **단 mac 에서는 Tauri 셸을 1차 GUI 로 가져가고 PyQt6 GUI 는 Windows 전용 레거시로 유지** — 이미 진행되던 Tauri 마이그레이션의 자연스러운 종착점. `main.py` 진입점은 mac 에서 PyQt6 import 를 시도하되 실패 시 친절한 오류 후 종료 (또는 `--no-gui` 가 기본).

대안: PyQt6 도 mac 빌드 — 작업량 대비 가치 낮음 (Tauri 가 모든 윈도우 UX 를 이미 커버). 본 계획은 **Tauri-only on mac**.

---

## 3. Tauri 셸 (`desktop-tauri/`) 변경

Rust 측은 `cargo build --target aarch64-apple-darwin` / `x86_64-apple-darwin` 으로 cross-compile 가능. 거의 모든 코드가 `#[cfg(target_os = "windows")]` 가드되어 있어 mac 빌드가 통과.

손볼 곳:

- `desktop-tauri/src-tauri/src/commands.rs:315` `python_exe()` — mac venv 는 `.venv/bin/python`. 분기 추가.
- 같은 파일 `:322, 340` `bridge_command` / `bridge_record_command` — 하드코딩된 `"trailbox-bridge.exe"` 를 `cfg!(target_os = "windows")` 분기로 `"trailbox-bridge"` 와 양분.
- `desktop-tauri/bridge.py` `cmd_pick_window_click` 함수의 `win32api`/`win32con` 직접 import — backend dispatcher 로 빼고 mac 경로는 Quartz 사용.
- `tauri.conf.json` 의 `bundle.targets` 는 `"all"` 이라 mac `.app` / `.dmg` 자동 생성. **단 codesigning identity 환경변수 (`APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`)** 필요.
- 오버레이 윈도우 (`tauri.conf.json` 의 `overlay` 라벨) 의 `alwaysOnTop + transparent + decorations:false` 조합은 mac 도 지원, 동작 확인만.

---

## 4. 빌드/배포 파이프라인

### 4.1 `build.py`

darwin 분기 추가:

```python
if sys.platform == "darwin":
    # PyInstaller 로 Trailbox-mcp, Trailbox-hub, trailbox-bridge 빌드 (확장자 없음)
    # GUI 는 Tauri 가 .app 생성 — PyInstaller 로는 만들지 않음
    # codesign + notarytool 호출은 별도 스크립트 (CI 권장)
elif sys.platform == "win32":
    # 기존 로직
```

`requirements.txt` 도 platform marker 정비:

```
PyQt6>=6.6 ; sys_platform == "win32"
dxcam>=0.3 ; sys_platform == "win32"
windows-capture>=2.0 ; sys_platform == "win32"
soundcard>=0.4 ; sys_platform == "win32"
pywin32>=306 ; sys_platform == "win32"
pyobjc-framework-ScreenCaptureKit>=10.0 ; sys_platform == "darwin"
pyobjc-framework-Quartz>=10.0 ; sys_platform == "darwin"
pyobjc-framework-AVFoundation>=10.0 ; sys_platform == "darwin"
# 공통: psutil, pynput, watchdog, mcp, fastapi, …
```

### 4.2 산출물

| OS | GUI | MCP | Hub | Bridge |
|---|---|---|---|---|
| Windows | `Trailbox-Setup.exe` (Inno) + `Trailbox.exe` (Tauri) | `Trailbox-mcp.exe` | `Trailbox-hub.exe` | `trailbox-bridge.exe` |
| macOS | `Trailbox.app` (+`.dmg`) | `trailbox-mcp` (CLI) | `trailbox-hub` (CLI) | `trailbox-bridge` |

mac 인스톨러: **`.dmg` 가 사실상의 인스톨러**. `.pkg` 는 LaunchDaemon 이 필요한 시점에 재고. v1 은 `.dmg` 만.

### 4.3 코드 서명 + 공증

- **Developer ID Application** 인증서 필수. Apple Developer 계정 ($99/년) 필요.
- `codesign --sign "Developer ID Application: …" --options runtime --entitlements …` 로 Tauri `.app` + 내부 사이드카 (`trailbox-bridge`) + `adb` / `scrcpy` 까지 *전부* 서명. 미서명 사이드카 1개라도 있으면 Gatekeeper 차단.
- `notarytool submit … --wait` 으로 공증. 통과 후 `xcrun stapler staple` 로 ticket 부착.
- entitlements 필요 항목:
  - `com.apple.security.device.camera` — ScreenCaptureKit
  - `com.apple.security.device.audio-input` — 오디오 캡처
  - `com.apple.security.app-sandbox` — **false** (sandbox 켜면 adb/scrcpy 사이드카가 막힘. Developer ID 배포는 sandbox 불요)
  - hardened runtime: 켬

### 4.4 권한 onboarding

첫 실행 시 4가지 권한 요청 — 사용자가 한 번에 통과하도록 onboarding 화면을 Tauri 측에 추가:

1. **Screen Recording** (시스템 설정 → Privacy → Screen Recording) — SCK
2. **Accessibility** (시스템 설정 → Privacy → Accessibility) — pynput 글로벌 입력 후킹
3. **Input Monitoring** (시스템 설정 → Privacy → Input Monitoring) — pynput 키보드
4. **(선택) Microphone** — SCK audio 가 마이크 권한도 요구하는 케이스

상태 점검 API: `CGPreflightScreenCaptureAccess()`, `AXIsProcessTrusted()`. 모자라면 `tccutil` 안내 + 시스템 설정 딥링크 (`x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture`).

---

## 5. 진행 순서 (체크포인트 8개)

각 단계가 끝나면 *작은 데모* 가 가능하도록 슬라이스. 단계 간 의존성 최소.

1. **빌드 인프라 베이스라인** — `requirements.txt` platform markers, `build.py` darwin 분기, `desktop-tauri` Rust cross-compile 통과. 산출물은 안 돌아도 OK, *빌드만 성공*.
2. **system_info + window_picker + process_detector mac 백엔드** — 표면 적고 안전. Tauri bridge 의 `enumerate-windows`, `system-info` 명령이 mac 에서 정상 응답.
3. **input_recorder + global_hotkey** — Accessibility 권한 onboarding 1차. 입력 JSONL 이 mac 에서 생성됨.
4. **ScreenCaptureKit screen_recorder (Monitor)** — 가장 큰 위험. 1차 영상 캡처 성공. ffmpeg 파이프 + VFR 검증.
5. **ScreenCaptureKit screen_recorder (Window)** — `SCContentFilter` 로 window 캡처.
6. **Audio (SCK + fallback)** — mac 13+ 본선, 12.x 는 disable.
7. **gpu_monitor stub + viewer/MCP graceful degrade 검증** — 한 세션이 mac 에서 끝까지 녹화되고 viewer.html 이 정상 렌더.
8. **Codesign + notarize + DMG** — 클린 mac 에서 다운로드 → 더블클릭 → 권한 4개 통과 → 녹화 → 뷰어 오픈 까지 *처음부터 끝까지*.

총 예상 작업량: **2~3 주** (1인 풀타임 가정, 코드 서명/공증 셋업이 의외로 길게 늘어짐).

---

## 6. 위험과 미해결 사안

- **macOS 12.x 사용자 처리**: SCK 가 12.3+. 12.0~12.2 사용자에게 어떤 메시지? — *결정 필요*. 권고: 12.3 미만 미지원, 인스톨러가 OS 버전 점검.
- **Apple Silicon vs Intel 분배**: `universal2` 단일 바이너리 vs ARM/x64 각각. Tauri 는 universal 빌드 옵션 있음. 의존 휠 중 universal2 미배포가 있으면 ARM 우선 + Rosetta 안내.
- **사이드카 codesign 자동화**: `trailbox-bridge` + `adb` + `scrcpy` + `ffmpeg` (imageio-ffmpeg 캐시) 까지 모두 서명. PyInstaller 의 `--codesign-identity` 만으론 부족 — 별도 sweep 스크립트 필요.
- **SCK 영상 인디케이터**: 메뉴바 빨간 점은 macOS 14.4+ 부터 강제. 기능적으론 문제 없으나 *몰래 녹화* 가 불가능. README/뷰어에 알림.
- **소프트웨어 키보드 인디케이터** (글로벌 입력 후킹 시 메뉴바 표시) — macOS 가 강제, 동일하게 README 명시.
- **오버레이 alwaysOnTop**: mac Mission Control 의 spaces 간 표시 동작 차이. v1 에서 다른 데스크톱으로 이동 시 오버레이 사라져도 허용.
- **viewer.html 자체 동작**: mac Safari/Chrome 모두 file:// 에서 `<video>` + `<track>` 정상. 별도 작업 없음.

---

## 7. MCP 와의 분리

본 계획은 **데스크톱 앱 전용**. MCP 서버는 다음으로 충분:

1. `build.py` darwin 분기에 `Trailbox-mcp` (CLI 바이너리) 추가.
2. `mcp_server/backends/local.py:19` 의 `_output_root()` 가 frozen + darwin 환경에서 `~/Library/Application Support/Trailbox/output` 을 fallback 으로 검사하도록 보강 (없으면 기존 동작).
3. Claude Desktop 설정 예시를 README 의 macOS 섹션에 추가 (`~/Library/Application Support/Claude/claude_desktop_config.json`).

→ MCP 는 본 계획의 **체크포인트 1** 안에서 부수적으로 끝낸다 (코드 변경 ~10 줄).

---

## 8. iOS 캡처 — 본 포팅 이후

iOS 화면 캡처는 **macOS 호스트가 필수** (Apple 의 Developer Disk + AVFoundation 의 `AVCaptureScreenInput` mirroring 또는 QuickTime 의 같은 메커니즘). 즉 본 mac 포팅이 iOS 의 **물리적 전제조건**.

다음 계획서에서 다룰 항목 (현 문서에는 상세 안 함):

- USB-Lightning/USB-C 연결된 iOS 디바이스의 mirroring stream 캡처 (`AVCaptureDeviceInput` + `AVCaptureSession`)
- iOS 측 입력 후킹은 OS 차원에서 **불가능** — touch event 는 캡처 불가, 대안은 mirrored 화면의 OCR 또는 idevice 도구의 syslog
- 로그: `idevicesyslog` (libimobiledevice) 사용
- 메트릭: `instruments -t Activity Monitor` CLI 또는 `idevice_id` + `pymobiledevice3`
- 이 모든 게 mac-only — 본 포팅이 끝나야 시작 가능

→ 본 계획의 모듈 분리 패턴 (`core/_backends/*_mac_*.py`) 이 그대로 iOS 백엔드의 자리를 마련해 둔다.

---

## 9. CLAUDE.md 갱신 요점 (별도 작업)

이 계획이 머지되면 `CLAUDE.md` 1행의 *"Windows-only PyQt6 desktop app"* 표현을 *"Windows + macOS desktop app — capture stack splits per-OS under `core/_backends/`"* 으로 갱신하고, COM 스레딩 / dxcam 관련 단락은 `### Windows 전용 메모` 하위로 옮긴다. macOS 전용 메모 (권한 4종, SCK 인디케이터, codesign 사이드카 sweep) 는 같은 위치에 새 섹션으로 추가.
