# macOS 빌드 + iOS Device Capture — 구현 계획

이 문서는 [ROADMAP.md](../ROADMAP.md)의 "모바일 확장 — iOS (Mac + Instruments / AVFoundation)" 섹션에 대한 **구현 계획**이다. [docs/android-capture-plan.md](android-capture-plan.md)의 자매 문서이며, 동일한 설계 원칙(`t0_perf` single rule, 출력 스키마 100% 동일, viewer/Hub/MCP 무변경)을 따른다.

핵심 한 줄: **iPhone/iPad를 USB로 Mac에 물려 화면·로그·메트릭을 캡처하는 Trailbox의 Mac 실행 버전.** iOS는 샌드박싱 때문에 디바이스 단독 캡처가 불가능하고, USB 화면 캡처에 필요한 `CoreMediaIO` DAL 프로토콜이 **macOS-only**이기 때문에 Mac 빌드가 전제 조건이다 (QuickTime "새로운 동영상 녹화 → iPhone"이 쓰는 그 메커니즘).

이 작업은 **두 개의 독립적 산출물**로 나뉜다:

1. **Trailbox.app (macOS 빌드)** — Windows 전용 코드를 플랫폼 가드로 감싸 앱이 macOS에서 *기동*되게 만드는 포팅 작업. iOS 캡처의 전제 조건이지만 그 자체로 독립.
2. **iOS device capture** — `IOSDeviceTarget` + 자매 레코더들. Mac 빌드 위에서만 동작.

---

## 결정사항 (제안 — 구현 시작 시 확정)

| 항목 | 제안 |
|---|---|
| Mac 프론트엔드 | **Tauri 앱 재사용** (`desktop-tauri/`). 이미 `bundle.targets="all"` + `com.trailbox.desktop`로 macOS 빌드 전제. PyQt6 `main.py` + py2app은 보조 경로로만 |
| 화면 캡처 | **pyobjc + AVFoundation** (CoreMediaIO DAL 디바이스로 잡히는 연결된 iPhone). QuickTime 메커니즘, frame-accurate, Apple Developer 계정 불필요 |
| 로그 | **pymobiledevice3 `syslog`** (pure-python, pip 설치 가능 — 단일 Python 스택 유지). `idevicesyslog` 바이너리 번들 대안은 보조 |
| 메트릭 | **pymobiledevice3 DVT instruments 서비스** (`sysmontap` = per-process CPU/mem, `graphics` = FPS/GPU util). xctrace 결과 파싱보다 깔끔하고 Android와 동일하게 1Hz 폴링 |
| 입력 | **v1 미지원** — iOS는 터치 이벤트를 호스트에 노출하지 않음 (탈옥 없이 불가). `inputs.jsonl`은 빈 채로, viewer는 그대로 동작 |
| 오디오 | **AVFoundation 오디오 입력** — CoreMediaIO 디바이스가 video와 함께 audio 트랙도 노출. ffmpeg로 video와 함께 mux |
| 코드사이닝 | **v1은 ad-hoc / 미서명** (로컬 빌드, Gatekeeper 우회는 사용자가 우클릭→열기). 배포 서명은 추후 (Apple Developer $99/년) |
| 출시 버전 | TBD (현재 v0.11.x 기준 minor bump, 예: `0.12.0`) — CLAUDE.md 버전 동기화 룰 준수 |

배경: ROADMAP에서 iOS를 Android 뒤에 둔 이유가 "Mac 빌드 환경 셋업이 절반"이기 때문이다. Android가 이미 구현되어 `IOSDeviceTarget`가 끼어들 dispatch 골격(`main.py`, `bridge_record.py`, `ScreenRecorder`)이 전부 자리잡았다 — 이 계획은 그 골격을 그대로 재사용한다.

---

## 설계 원칙

CLAUDE.md의 *single rule* 유지: `t0_perf`를 한 곳(`_on_start_requested` / `bridge_record.py`)에서 캡처하고 모든 레코더가 `t_video_s = perf_counter() - t0_perf`를 JSONL에 방출. 출력 디렉터리 레이아웃과 JSONL 스키마는 Windows/Android 세션과 **100% 동일**. `viewer.html` 생성기와 MCP 서버는 분기 없이 동작.

새 `CaptureTarget` 변형 추가 (`core/screen_recorder.py`, Android와 동형):
```python
@dataclass(frozen=True)
class IOSDeviceTarget:
    udid: str                 # libimobiledevice/pymobiledevice3 디바이스 식별자
    bundle_id: str | None     # 포어그라운드 앱 번들 ID (best-effort)
    device_name: str          # AVFoundation 디바이스 이름 (UI 표시용)
    capture_audio: bool = True

CaptureTarget = MonitorTarget | WindowTarget | AndroidDeviceTarget | IOSDeviceTarget
```

Android에서 검증된 **자매 클래스 패턴**을 그대로 따른다: 신호별로 `IOSLogCollector` / `IOSMetricsRecorder`를 만들고, `ScreenRecorder`에 `_run_ios()` 분기를 추가. `main.py`(PyQt)와 `bridge_record.py`(Tauri)의 dispatch가 target 타입을 보고 어느 세트를 생성할지 결정한다.

---

## Part A — macOS 빌드 (전제 조건)

iOS 캡처 코드를 짜기 전에 앱이 macOS에서 *기동*되어야 한다. 현재 코드베이스는 Windows 전용 의존성(dxcam, windows-capture, win32pdh, soundcard, comtypes, pywin32, pynput Windows 백엔드)이 곳곳에 박혀 있다. 다행히 화면 레코더의 무거운 dep는 이미 **스레드 내부 lazy import**로 격리되어 있어(CLAUDE.md의 COM 섹션 참조) 모듈 import 시점엔 터지지 않는다. 남은 작업은 *Windows-only 진입점*을 플랫폼 가드로 감싸는 것.

### A1 — 플랫폼 가드 감사

import 시점/기동 시점에 Windows API를 건드리는 지점을 전수 조사해 `if sys.platform == "win32":` 또는 lazy-import 가드로 감싼다:

| 모듈 | Windows 의존 | macOS 처리 |
|---|---|---|
| `core/gpu_monitor.py` | `win32pdh` (PDH 카운터) | iOS 세션은 호스트 GPU 안 씀 → import 가드, macOS에선 `None` 반환 stub |
| `core/window_picker.py` / `window_clicker.py` | `win32gui` 등 | Windows 캡처 타깃 전용 → macOS 빌드에서 UI에 노출 안 함, import 가드 |
| `core/process_detector.py` | `psutil.open_files()` + 윈도우 휴리스틱 | Windows-only 기능, lazy import |
| `core/global_hotkey.py` | Windows 메시지 훅 | macOS는 pynput/Cocoa 전역 핫키로 대체 또는 v1 비활성 |
| `core/system_info.py` | WMI/PDH로 host 스냅샷 | iOS 세션은 `collect_ios_info(udid)`로 대체(아래). 호스트 Mac 정보는 `psutil` + `platform` 모듈로 |
| `core/audio_recorder.py` | `soundcard` (WASAPI) | iOS 경로는 AVFoundation이 처리 → 미사용. Mac *데스크톱* 캡처는 v1 스코프 밖 |
| `core/metrics_recorder.py` | psutil (cross-platform) + `gpu_monitor` | psutil은 OK, gpu_monitor만 가드 |

원칙: **iOS 세션에서 실제로 호출되는 경로만** macOS에서 동작하면 된다. Windows 캡처 타깃(Monitor/Window)은 macOS 빌드에서 UI에 아예 노출하지 않으므로 그쪽 코드는 import만 안 터지면 충분.

### A2 — Mac 데스크톱 자체 캡처는 스코프 밖

"Mac 화면 자체를 캡처"하는 것(ScreenCaptureKit / AVFoundation desktop)은 매력적이지만 **이 작업의 목표가 아니다**. iOS 캡처에 집중. 단, `IOSDeviceTarget`용으로 작성하는 AVFoundation 코드 상당수가 Mac 데스크톱 캡처로 재활용 가능하므로, 그건 후속 작업으로 자연스럽게 떨어진다(별도 백로그).

### A3 — 빌드 인프라

**권장: Tauri 경로** (`desktop-tauri/`)
- `tauri.conf.json`이 이미 `bundle.targets: "all"` → `npm run tauri:build`가 macOS에서 `.app` / `.dmg` 생성
- Python 사이드카: 현재 `trailbox-bridge.exe`(PyInstaller)에 대응하는 **`trailbox-bridge`(macOS Mach-O)** 를 PyInstaller로 빌드. `build.py`에 macOS 분기 추가 (`sys.platform == "darwin"`)
- Rust 프론트엔드는 그대로 크로스 빌드됨 (~9 MB)
- 산출물: `Trailbox.app` (내부에 trailbox-desktop + trailbox-bridge 사이드카)

**보조: PyQt6 + py2app** (ROADMAP 원안)
- `main.py`를 직접 `.app`으로. `py2app` 또는 PyInstaller `--windowed`. Tauri 경로가 막힐 때의 백업.

**코드사이닝 / 공증(notarization)**
- v1: ad-hoc 서명(`codesign -s -`) 또는 미서명. 사용자는 첫 실행 시 우클릭→열기로 Gatekeeper 우회. README에 명시.
- 배포 단계: Apple Developer Program($99/년) + `notarytool` 공증 → 후속 작업, 비용 결정 필요(체크리스트에 둠).

**권한(TCC)**
- 화면/카메라 접근: `.app`의 `Info.plist`에 `NSCameraUsageDescription`(CoreMediaIO 디바이스는 카메라 권한 모델 사용) 추가
- 첫 실행 시 macOS가 카메라/화면 권한 프롬프트 → 사용자 승인 필요. README 안내.

---

## Part B — iOS Device Capture

### Phase 1 — 기반 (의존성 + device helper)

**requirements 추가** (macOS 한정 — `requirements.txt`에 환경 마커):
```
pyobjc-framework-AVFoundation ; sys_platform == "darwin"
pyobjc-framework-CoreMediaIO ; sys_platform == "darwin"
pymobiledevice3 ; sys_platform == "darwin"
```
- `pymobiledevice3`는 pure-python libimobiledevice 대체 — syslog + DVT instruments 서비스 모두 제공. 별도 네이티브 바이너리 번들 불필요(단일 Python 스택 유지, Android의 adb/scrcpy 번들과 대비되는 장점).

**새 파일**: `core/ios_device.py` (Android의 `core/adb.py` 대응)
- `list_devices()` — 연결된 iOS 디바이스 열거. **두 소스를 교차**:
  - `pymobiledevice3`의 usbmux로 USB 디바이스 목록(udid, name, ios_version)
  - AVFoundation `CoreMediaIO`에서 캡처 가능한 비디오 디바이스 목록(QuickTime이 보는 그 목록)
  - 두 목록을 디바이스 이름으로 매칭 → `[(udid, device_name, ios_version, capturable: bool)]`
  - **중요**: CoreMediaIO DAL 디바이스는 `kCMIOHardwarePropertyAllowScreenCaptureDevices = 1`을 한 번 set 해야 iPhone이 캡처 디바이스로 나타난다. helper 초기화 시 호출.
- `get_foreground_app(udid)` — pymobiledevice3 DVT `device_info` / `application_listing`로 best-effort (실패 시 None)
- `get_ios_version(udid)` — `lockdown.get_value(key="ProductVersion")`
- 모든 호출 명시적 timeout + 예외 로깅, best-effort

**수정**: `build.py`
- macOS 분기: pyobjc/pymobiledevice3가 PyInstaller hidden-import에 잡히도록 hook 추가. CoreMediaIO/AVFoundation 프레임워크 번들 확인.

---

### Phase 2 — UI (디바이스 선택)

Android의 `android_radio` + device combo + `_DetectAndroidDevicesWorker` 패턴을 그대로 미러링.

**Tauri 경로** (`desktop-tauri/`, 권장):
- `bridge.py`에 `{"cmd":"list_ios_devices"}` 핸들러 추가 → `core.ios_device.list_devices()` JSON 반환 (창 열거와 동일 one-shot 패턴)
- React UI: 캡처 소스 선택에 "iOS Device" 옵션 + 디바이스 드롭다운. 3초 폴링으로 USB 연결/해제 반영
- `bridge_record.py`의 start payload에 `{"kind":"ios","udid":...,"bundle_id":...}` 추가

**PyQt 경로** (`ui/launcher_panel.py`, 보조):
- `ios_radio` + `ios_device_combo: QComboBox`
- `_DetectIOSDevicesWorker(QThread)` — `core/process_detector.py`의 `_DetectWindowWorker` 패턴. `run()`에서 `core.ios_device.list_devices()` → `pyqtSignal(list)`
- `QTimer` 3초 폴링, `blockSignals(True/False)`로 감싸기 (CLAUDE.md의 combo refresh 함정 회피)
- `capture_target()`에 `IOSDeviceTarget` 분기, `_update_target_controls()`에 iOS 모드 토글

---

### Phase 3 — 화면 + 오디오 (AVFoundation → ffmpeg)

**수정**: `core/screen_recorder.py`

기존 dispatch 옆에 네 번째 분기 (Android의 `_run_scrcpy` 대응):
```python
elif isinstance(self.target, IOSDeviceTarget):
    self._run_ios()
```

**`_run_ios()` 동작** (스레드 내부 lazy import로 pyobjc 로드 — COM 가드와 동일 철학):
1. CoreMediaIO 화면 캡처 허용 플래그 set (`kCMIOHardwarePropertyAllowScreenCaptureDevices`)
2. AVFoundation `AVCaptureSession` 구성:
   - `AVCaptureDevice`(매칭된 udid의 iPhone) → `AVCaptureDeviceInput`
   - 비디오 `AVCaptureVideoDataOutput` + (가능 시) 오디오 `AVCaptureAudioDataOutput`
   - delegate 콜백으로 `CMSampleBuffer` 프레임 수신 (windows-capture의 push 모델과 동형)
3. 프레임 → ffmpeg subprocess stdin. **인코딩 경로 선택**:
   - iPhone 디바이스는 보통 디코딩된 BGRA/420 프레임을 줌 → 기존 `_spawn_ffmpeg`의 rawvideo 경로 재사용 가능
   - 단, iOS 디바이스 출력 포맷/해상도가 가변 → `_run_window`의 latest-frame-under-lock + `new_frame_event` 패턴 재사용. VFR 유지(`-use_wallclock_as_timestamps 1 -fps_mode passthrough`), 고정 cadence 금지 (CLAUDE.md)
   - 오디오 샘플버퍼는 별도 ffmpeg 입력 또는 WAV로 받아 post_mux. **단순화 권장**: 비디오/오디오를 AVFoundation `AVCaptureMovieFileOutput`으로 한 .mov로 받은 뒤 ffmpeg `-c copy -movflags +faststart`로 screen.mp4 변환 → Android scrcpy 경로처럼 post_mux 우회
4. `frames.jsonl`: delegate 콜백마다 presentation timestamp 기록 가능 → Android보다 유리. per-frame timing 채울 수 있음(`frames_log_path` 전달)
5. 에러 처리: AVCaptureSession runtime error 노티 구독, 실패 시 `_error` 저장

**post_mux 처리**: `AVCaptureMovieFileOutput`으로 단일 .mov를 받으면 video+audio가 이미 합쳐져 나옴 → Android와 동일하게 `screen.video.mp4`/`screen.audio.wav` 중간 파일 없이 `FINAL_NAME`으로 직행, finalize의 `post_mux.mux_av()` 자연 skip.

---

### Phase 4 — 로그 (pymobiledevice3 syslog)

**새 파일**: `core/ios_log_collector.py` — `AndroidLogCollector`와 동일 시그니처:
```python
IOSLogCollector(udid: str, output_dir: Path, t0_perf: float,
                bundle_filter: str | None = None)
```

- `pymobiledevice3.services.syslog.SyslogService(lockdown).watch()` 제너레이터를 daemon 스레드에서 소비
- os_log 라인 파싱: timestamp, process(pid), level, subsystem/category, message
- 출력 스키마는 기존 `logs.jsonl`과 동일 (`@timestamp`, `t_video_s`, `message`, `ecs.version`). 추가로 `log.process.{name,pid}`, `log.level`, `log.tag`(subsystem) — Android와 같은 ECS 8.11 호환 매핑
- `logs.vtt`도 같이 생성 (LogCollector/AndroidLogCollector의 VTT helper 재사용)
- `bundle_filter`가 있으면 process name으로 필터링해 소음 감소
- **한계**: syslog는 OS 전역 로그 — 게임이 os_log를 안 쓰고 자체 파일에만 쓰면 거기까진 안 잡힘 (sandbox로 호스트가 앱 컨테이너 파일 접근 제한). best-effort.

---

### Phase 5 — 입력 (v1 미지원)

iOS는 터치 이벤트를 호스트에 노출하지 않는다 (탈옥 없이 불가). `AndroidInputRecorder`의 getevent 대응물이 없음.

- v1: `inputs/inputs.jsonl`을 빈 파일로 생성(또는 미생성), `session_meta.json`에 `inputs_unavailable: "ios_no_touch_export"` 기록
- viewer는 inputs 트랙이 비어도 정상 동작 (Android getevent 권한 거부 케이스와 동일하게 best-effort 취급)
- **후속(옵션)**: syslog의 `UIEvent`/`BKHIDEvent` 디버그 라인에서 일부 탭 좌표가 새어나오는 경우가 있으나 iOS 버전/빌드 의존적이라 v1 비포함

---

### Phase 6 — 메트릭 (pymobiledevice3 DVT instruments)

**새 파일**: `core/ios_metrics_recorder.py` — `AndroidMetricsRecorder`와 동일 시그니처:
```python
IOSMetricsRecorder(udid: str, bundle_id: str, output_path: Path,
                   t0_perf: float, interval_s: float = 1.0)
```

- pymobiledevice3 DVT(DeveloperTools) 채널을 통해 Instruments가 쓰는 동일 서비스에 접속:
  - `Sysmontap` 서비스 → 프로세스별 CPU%, 메모리(RSS), thread 수
  - `Graphics`(coreanimation) 서비스 → device FPS, GPU utilization, CoreAnimation frame stats
- 1Hz 폴링 스레드. 출력 스키마는 기존 `process.jsonl`과 동일:
  - `process.cpu_pct` (디바이스 코어 수로 정규화) + `process.cpu_pct_per_core` (raw)
  - `process.rss_mb`
  - `process.gpu_pct` — iOS는 Graphics 서비스가 device-wide GPU util 제공 → 채울 수 있음 (Android의 `null`보다 유리)
  - 보조 필드: `process.ios.fps`, `process.ios.gpu_util`, `process.ios.coreanimation_fps`
- **주의**: iOS 17+는 DVT 접근에 Developer Disk Image 마운트 또는 `tunneld`(RemoteXPC) 필요. pymobiledevice3가 자동 처리하나, 첫 사용 시 디바이스에서 "개발자 모드" 활성화 필요 — README 안내. DDI 마운트 실패 시 메트릭만 비고 다른 신호는 진행(best-effort).

---

### Phase 7 — 오케스트레이션

**수정**: `main.py`의 `_on_start_requested` (Android 분기 바로 옆, L150 패턴 그대로):

```python
if isinstance(target, IOSDeviceTarget):
    from core import ios_device

    bundle_id = target.bundle_id or ios_device.get_foreground_app(target.udid)
    stem = f"ios_{target.udid[:8]}_{bundle_id or 'unknown'}"
    session = Session(exe_path=None, log_dir=None, output_root=OUTPUT_ROOT,
                      target_pid=None, app_name=stem)
    session_id = session.start()

    self._system_info = collect_ios_info(target.udid)   # 디바이스 스냅샷
    t0_perf = time.perf_counter()

    screen_recorder = ScreenRecorder(
        output_path=session.dir / FINAL_NAME,    # 단일 .mov 변환 → post_mux skip
        target=target, max_fps=max_fps,
        frames_log_path=session.dir / "metrics" / "frames.jsonl",  # AVF는 per-frame ts 가능
    )
    log_collector = IOSLogCollector(target.udid, session.dir / "logs", t0_perf,
                                    bundle_filter=bundle_id)
    metrics_recorder = IOSMetricsRecorder(target.udid, bundle_id,
                                          session.dir / "metrics" / "process.jsonl", t0_perf)
    audio_recorder = None        # AVFoundation이 오디오 트랙 처리
    input_recorder = None        # iOS 터치 미노출
    ...
```

- `session_meta.json`의 `system` 섹션: 호스트 Mac이 아닌 **iOS 디바이스** 정보 (`collect_ios_info(udid)` → 모델, iOS 버전, 디바이스명). `core/system_info.py`에 `collect_android_info` 옆에 추가
- `finalize`에서 `post_mux.mux_av()` skip (AVF 단일 컨테이너 경로 — Android와 동일 조건 분기)
- `viewer_generator.generate_viewer()` 수정 불필요 — JSONL 스키마 동일

**수정**: `desktop-tauri/bridge_record.py`의 `main()` — L93~98의 target dispatch에 `elif kind == "ios": target = IOSDeviceTarget(...)` 추가, 위와 동일한 레코더 세트 구성. 1Hz status 이벤트에 iOS fps/gpu 포함.

---

## 변경 파일 매트릭스

| 파일 | 변경 |
|---|---|
| `core/screen_recorder.py` | `IOSDeviceTarget` 추가, `_run_ios()` (AVFoundation), 단일 .mov→mp4 변환 |
| `core/ios_device.py` | 신규 — device 열거 + CoreMediaIO 활성화 + lockdown 헬퍼 |
| `core/ios_log_collector.py` | 신규 — pymobiledevice3 syslog |
| `core/ios_metrics_recorder.py` | 신규 — DVT sysmontap + graphics |
| `core/system_info.py` | `collect_ios_info(udid)` 추가 |
| `core/gpu_monitor.py` | `sys.platform` import 가드 (macOS stub) |
| `core/global_hotkey.py` / `window_picker.py` / `window_clicker.py` / `process_detector.py` | import 가드 (Windows-only) |
| `main.py` | `_on_start_requested`에 `IOSDeviceTarget` dispatch |
| `desktop-tauri/bridge.py` | `list_ios_devices` one-shot 핸들러 |
| `desktop-tauri/bridge_record.py` | iOS target dispatch + status에 fps/gpu |
| `desktop-tauri/src/` (React) | iOS 디바이스 선택 UI |
| `ui/launcher_panel.py` | (PyQt 보조) `ios_radio` + combo + `_DetectIOSDevicesWorker` |
| `build.py` | macOS 분기 (PyInstaller darwin), pyobjc/pymobiledevice3 hidden-import |
| `requirements.txt` | pyobjc-AVFoundation/CoreMediaIO + pymobiledevice3 (`sys_platform=="darwin"` 마커) |
| `installer/` | macOS는 Inno Setup 미적용 → `.dmg`/`.app` 번들 (Tauri/py2app), 별도 README 섹션 |
| `README.md` | macOS 빌드법 + iOS 사용법 (개발자 모드, 권한 프롬프트, 첫 실행 Gatekeeper) |

---

## 재사용할 기존 패턴

- **CaptureTarget union dispatch**: `core/screen_recorder.py` — Android 3분기 → iOS 4분기로 확장
- **push-model 프레임 캐시 + `new_frame_event`**: `_run_window`(WGC) → `_run_ios`(AVFoundation delegate) 동형
- **스레드 내부 lazy import**(COM/startup-perf 룰): pyobjc도 `_run_ios` 내부에서 import
- **자매 레코더 + best-effort `_error`**: Android의 `AndroidLogCollector`/`AndroidMetricsRecorder` 구조 그대로
- **post_mux 우회**(단일 컨테이너 경로): Android scrcpy 분기와 동일 조건
- **QThread worker + blockSignals**: Android device 폴링 worker 미러링
- **`collect_android_info` → `collect_ios_info`**: `system` 메타 디바이스 스냅샷
- **JSONL ECS 스키마** (`ecs.version`, `@timestamp`, `t_video_s`) — 무변경

---

## 검증

1. **앱 기동 (Part A)**: macOS에서 `Trailbox.app` 실행 → 크래시 없이 UI 표시 (Windows-only import 가드 동작 확인)
2. **디바이스 인식**: iPhone USB 연결 → 개발자 모드 ON → 캡처 소스에 "iOS Device" + 디바이스명 표시
3. **풀 세션**: 녹화 시작/종료 → `output/ios_<udid8>_<bundle>_<ts>/`에 생성:
   - `screen.mp4` (video + audio, ffprobe 확인)
   - `logs/logs.jsonl` + `logs.vtt` (os_log)
   - `metrics/process.jsonl` (1Hz, cpu/rss/gpu/fps)
   - `metrics/frames.jsonl` (AVF presentation timestamp)
   - `inputs/inputs.jsonl` (빈 파일 + meta에 unavailable 사유)
   - `viewer.html` / `session_meta.json` (`system.ios.model` / `ios_version`)
4. **viewer**: `viewer.html`을 `file://`로 열어 video 재생 + 로그/메트릭 오버레이가 `t_video_s` 시간축 정렬 확인
5. **MCP 통합**: `python -m mcp_server` → `list_sessions`/`query_events`/`get_metrics`로 새 iOS 세션 조회 (gpu_pct가 null 아닌지 확인)
6. **권한 플로우**: 클린 Mac에서 첫 실행 시 카메라 권한 프롬프트 + 디바이스 "이 컴퓨터를 신뢰" 프롬프트 처리

---

## 알려진 리스크 / TBD

- **iOS major 버전 변동성**: CoreMediaIO DAL / DVT 프로토콜이 iOS 17의 RemoteXPC 전환처럼 메이저마다 깨질 수 있음. pymobiledevice3 버전 핀 + capability 체크 + 사용자 안내로 흡수 (ROADMAP의 "OS 변동성은 abstraction 한 겹 위에서" 원칙)
- **개발자 모드 / DDI**: iOS 16+는 메트릭(DVT)에 개발자 모드 + Developer Disk Image 필요. 미충족 시 화면/로그는 잡되 메트릭만 비움 (best-effort)
- **입력 미지원**: iOS 터치 호스트 미노출 → v1 `inputs.jsonl` 빈 채. 차별화 매트릭스에서 "입력"은 iOS에서 빠짐 (문서화)
- **코드사이닝/공증 비용**: 미서명 v1은 Gatekeeper 우회 필요. 배포하려면 Apple Developer $99/년 — 결정 보류 항목
- **Mac 빌드 CI**: 현재 빌드는 Windows(PyInstaller + Inno Setup) 전제. macOS 빌드는 별도 러너 필요 (GitHub Actions `macos-latest`) — 백로그의 "GitHub Actions 자동 빌드"와 연계
- **Fullscreen/HDR iOS 콘텐츠**: 일부 DRM 보호 콘텐츠는 캡처 시 블랭크 (Windows의 Netflix 케이스와 동일 OS 제약)
- **버전 동기화 룰** (CLAUDE.md): `main.py.__version__` + Tauri `tauri.conf.json` version + (있으면) installer 버전을 같은 커밋에서 올리고 그 위에 태그

---

## 작업 순서

```
Part A (macOS 기동)
  A1 플랫폼 가드 → A3 Tauri/PyInstaller macOS 빌드 → 앱 기동 검증
        ↓
Part B (iOS 캡처)
  Phase 1 (deps + ios_device.py)
        ↓
  Phase 2 (UI 디바이스 선택)
        ↓
  Phase 3 (화면+오디오) ── 여기까지로 "iOS 화면만 잡히는 미니멀 세션" 동작 → 사용자 검증 1회
        ↓
  Phase 4 (로그) → Phase 6 (메트릭) → Phase 7 (오케스트레이션 완성)
        ↓
  Phase 5 (입력)은 v1 스킵 (meta 플래그만)
        ↓
  검증 1~6
```

Android와 마찬가지로 Phase 3까지 끝나면 화면+오디오 미니멀 세션이 동작 → 그 시점에 사용자 검증 1회 후 나머지 신호 부착이 리스크 분산에 유리.

---

## 사전 준비물

구현 시작 전 사용자가 준비해야 할 것:
- **Mac** (Apple Silicon 또는 Intel, macOS 12.3+ 권장 — ScreenCaptureKit/최신 AVF API 기준)
- iOS 테스트 디바이스 (iPhone/iPad) + USB 케이블 + Lightning/USB-C
- 디바이스에서 **개발자 모드 ON** (설정 → 개인정보 보호 및 보안 → 개발자 모드; 메트릭용)
- 첫 연결 시 "이 컴퓨터를 신뢰" 승인
- (배포 시) Apple Developer Program 계정 — 코드사이닝/공증용, v1 로컬 빌드엔 불필요
