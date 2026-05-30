# iOS 캡처 — Mac 세션 핸드오프

> 이 문서는 **macOS + iPhone 실기에서 작업을 이어받는 세션**(사람 또는 Claude Code)을 위한 것이다.
> 전체 설계·페이즈는 [mac-ios-capture-plan.md](mac-ios-capture-plan.md), 이 문서는 *지금 당장 무엇을 하면 되는지*만 담는다.

브랜치: **`claude/mac-version-plan-AvqB5`** — 이미 원격에 푸시됨.

---

## 30초 요약

Windows 전용 Trailbox를 **macOS에서 기동 + 테더된 iPhone을 캡처**하도록 확장하는 작업. 코어 로직은 전부 작성·커밋됐고 **Linux CI에서 import/컴파일/순수 파서까지 검증**했다. 남은 건 **실기에서만 가능한 것**: ① AVFoundation/CoreMediaIO/DVT 실동작 튜닝, ② macOS 빌드(`build.py`), ③ 디바이스 선택 UI.

⚠️ **핵심**: `_run_ios`(AVCaptureSession), `ios_device`(CMIO 노출), `ios_metrics_recorder`(DVT 행 shape)는 **하드웨어 없이 검증 불가**였다. 실기에서 깨지면 그게 정상 — 아래 "튜닝 예상 지점" 먼저 보라.

---

## 셋업 (Mac)

```bash
git fetch origin claude/mac-version-plan-AvqB5
git checkout claude/mac-version-plan-AvqB5

python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # win 스택은 마커로 자동 skip
```

iPhone 준비물: USB 연결 → 잠금 해제 → **"이 컴퓨터를 신뢰"** → 설정 > 개인정보 보호 및 보안 > **개발자 모드 ON** (메트릭용, 재부팅 필요).

---

## 검증 순서 (이 순서대로)

각 단계가 통과해야 다음으로. 실패 지점이 곧 튜닝 지점.

**1. import 기동 (가장 먼저)**
```bash
.venv/bin/python -c "import core.ios_device, core.ios_log_collector, core.ios_metrics_recorder, core.screen_recorder; print('ok')"
```
실패하면 pyobjc/pymobiledevice3 설치 문제. Linux에선 이미 통과 확인됨.

**2. 디바이스 열거** — `core/ios_device.py:list_devices()`
```bash
.venv/bin/python -c "from core.ios_device import list_devices; print(list_devices())"
```
- 빈 리스트 → usbmux가 디바이스를 못 봄(신뢰 안 됨 / 케이블).
- `capturable=False` → usbmux는 보는데 AVFoundation이 못 봄. → `enable_screen_capture_devices()`의 **CMIO 프로퍼티 set이 안 먹은 것** (튜닝 지점 #1).

**3. 화면 캡처 단독** — `core/screen_recorder.py:192 _run_ios()`
```bash
.venv/bin/python - <<'PY'
import time
from pathlib import Path
from core.ios_device import list_devices
from core.screen_recorder import ScreenRecorder, IOSDeviceTarget
d = list_devices()[0]
t = IOSDeviceTarget(udid=d.udid, device_name=d.name)
r = ScreenRecorder(output_path=Path("output/_ios_smoke/screen.mp4"), target=t, max_fps=60)
r.start(); time.sleep(5); r.stop()
print("frames:", r.frames_written())
PY
ffprobe output/_ios_smoke/screen.mp4   # video+audio 트랙 확인
```
여기가 가장 손이 많이 갈 지점 (튜닝 지점 #2 — AVCaptureSession / 런루프 / delegate).

**4. 풀 세션** — GUI(`.venv/bin/python main.py`) 또는 Tauri bridge로 iOS 타깃 선택 후 녹화. 출력 `output/ios_<udid8>_<bundle>_<ts>/`에 `screen.mp4` / `logs/syslog.jsonl` / `metrics/process.jsonl` / `viewer.html` 생성 확인.

**5. viewer** — `viewer.html` 더블클릭 → 영상 + 로그/메트릭 오버레이가 `t_video_s` 축에 정렬되는지.

---

## 튜닝 예상 지점 (실기에서 깨질 가능성 높은 순)

| # | 위치 | 증상 / 할 일 |
|---|---|---|
| 1 | `core/ios_device.py:enable_screen_capture_devices()` | CMIO 프로퍼티 set이 pyobjc 바인딩에서 인자 형태가 안 맞을 수 있음. `capturable=False`면 여기부터. QuickTime을 한 번 열면 OS가 대신 켜주므로 그걸로 우회 검증 가능 |
| 2 | `core/screen_recorder.py:_run_ios()` (192~) | `AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed)` 결과/디바이스 매칭, `AVCaptureMovieFileOutput` delegate 시그니처, `NSRunLoop` 슬라이스. delegate 메서드명은 Objective-C 셀렉터 그대로(`captureOutput:didFinishRecordingToOutputFileAtURL:...`) — pyobjc 변환명 확인 |
| 3 | `core/ios_metrics_recorder.py:_extract_proc()` / `_iter_proc_rows()` | DVT **Sysmontap 행 shape가 pymobiledevice3 버전마다 다름**. 실제 한 틱을 `print`해서 키 이름(`cpuUsage`/`physFootprint`/...) 맞추기. `_extract_gfx()`의 Graphics 키도 동일 |
| 4 | `core/ios_log_collector.py:_fields()` | `OsTraceService.syslog()` 엔트리의 속성명(`message`/`label`/`level`/`pid`) 버전 확인. 안 되면 `SyslogService.watch()` 문자열 폴백으로 자동 강등됨 |
| 5 | `core/ios_device.py:get_foreground_app()` | iOS 16+ DVT는 Developer Mode + DDI 마운트 필요. 안 되면 `bundle_id="unknown"` → 메트릭 skip(정상 degrade) |

**팁**: 2/3/4는 "실제 객체 한 개를 `print`/`dir()`로 찍어 키 확인 → 파서 보정"이 패턴. 파서는 이미 방어적(getattr+폴백)이라 키만 맞추면 됨.

---

## 코드 지도 (이미 작성된 것)

| 파일 | 역할 | 핵심 심볼:라인 |
|---|---|---|
| `core/screen_recorder.py` | iOS 화면 캡처 | `IOSDeviceTarget`, `_run_ios():192`, `_remux_mov():313` |
| `core/ios_device.py` | 디바이스 열거 + CMIO 노출 | `list_devices`, `enable_screen_capture_devices`, `get_foreground_app` |
| `core/ios_log_collector.py` | syslog → `logs/syslog.jsonl` | `IOSLogCollector`, `_iter_syslog`, `_fields` |
| `core/ios_metrics_recorder.py` | DVT → `metrics/process.jsonl` | `IOSMetricsRecorder`, `_extract_proc`, `_extract_gfx` |
| `core/system_info.py` | 디바이스 스냅샷 | `collect_ios_info` |
| `main.py` | PyQt 오케스트레이션 | iOS 브랜치 `:157` |
| `desktop-tauri/bridge_record.py` | Tauri 녹화 daemon | `kind=="ios":107` |
| `desktop-tauri/bridge.py` | Tauri one-shot | `list-ios-devices:235` |

**설계 불변식 (깨지 말 것)**: 모든 레코더는 `t0_perf` 하나로 `t_video_s` 방출, JSONL 스키마는 Windows/Android와 100% 동일 → viewer/MCP 무수정. 무거운 dep(pyobjc 등)는 **워커 스레드 내부 lazy import** (모듈 스코프 금지 — COM/startup 규칙과 동일).

---

## 아직 안 한 것 (실기 검증 후 착수)

1. **A3 — macOS 빌드**: `build.py`에 `sys.platform=="darwin"` 분기. Tauri는 `bundle.targets="all"`이라 `npm run tauri:build`로 `.app` 생성; PyInstaller로 `trailbox-bridge`(Mach-O) 사이드카. 코드사이닝은 v1 ad-hoc, 배포 시 Apple Developer($99/년) + notarytool. `Info.plist`에 `NSCameraUsageDescription` 필요.
2. **Phase 2 — UI 디바이스 선택**: bridge `list-ios-devices`는 준비됨. (a) Tauri React: 캡처 소스에 "iOS Device" + 드롭다운 + 3초 폴링, start payload `{"kind":"ios","udid":...,"device_name":...,"bundle_id":...}`. (b) PyQt `ui/launcher_panel.py`: `android_radio` 옆에 `ios_radio` + `_DetectIOSDevicesWorker` (Android worker 미러링, `blockSignals` 패턴).
3. **버전 동기화** (CLAUDE.md 규칙): 출시 시 `main.py.__version__` + `tauri.conf.json` version 같은 커밋에서 bump + 태그.

---

## 커밋 로그 (이 브랜치)

```
docs: record iOS capture implementation status in the plan
feat(ios): bridge list-ios-devices command + cross-platform requirements
feat(ios): wire iOS capture into main.py + Tauri bridge orchestration
feat(ios): add IOSDeviceTarget + iOS capture core modules
feat(macos): guard Windows-only imports so core/ loads on macOS
docs: add macOS build + iOS capture implementation plan
```
