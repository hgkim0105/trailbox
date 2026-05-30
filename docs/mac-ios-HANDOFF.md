# iOS 캡처 — Mac 세션 핸드오프

> 이 문서는 **macOS + iPhone 실기에서 작업을 이어받는 세션**(사람 또는 Claude Code)을 위한 것이다.
> 전체 설계·페이즈는 [mac-ios-capture-plan.md](mac-ios-capture-plan.md), 이 문서는 *지금 당장 무엇을 하면 되는지*만 담는다.

브랜치: **`claude/mac-version-plan-AvqB5`** — 이미 원격에 푸시됨.

---

## 30초 요약

Windows 전용 Trailbox를 **macOS에서 기동 + 테더된 iPhone을 캡처**하도록 확장하는 작업. 코어 로직은 전부 작성·커밋됐고 **macOS에서 import/컴파일까지 검증**했다. 남은 건 **실기에서만 가능한 것**: ① AVFoundation/CoreMediaIO/DVT 실동작 튜닝, ② macOS 빌드(`build.py`), ③ 디바이스 선택 UI.

⚠️ **핵심**: `_run_ios`(AVCaptureSession), `ios_device`(CMIO 노출), `ios_metrics_recorder`(Sysmontap/Graphics 행 shape)는 **하드웨어 없이 검증 불가**다. 실기에서 깨지면 그게 정상 — 아래 "튜닝 예상 지점" 먼저 보라.

### pymobiledevice3 v9 async 리라이트 — 완료 (2026-05-30)

초기 코드는 sync 시절(v4) 기준이었으나 설치되는 라이브러리가 v9.x로 메이저 점프하면서 API가 전면 async로 바뀜:

- `usbmux.list_devices` / `create_using_usbmux` / `lockdown.get_value` / `lockdown.close` 전부 `async`
- `DvtSecureSocketProxyService` 클래스 자체가 사라지고 `DvtProvider` (`async with`)로 대체
- `Sysmontap` 생성은 `await Sysmontap.create(dvt)`, 결과는 `async for entries in sysmon.iter_processes()` — `entries`는 `list[dict]`
- `DeviceInfo.foreground_running_process()` 제거 → `get_foreground_app`은 None stub (UI에서 사용자가 bundle 명시)
- **iOS 17+ DVT는 RemoteXPC(RSD) 강제** → `pymobiledevice3.tunneld.api.get_tunneld_devices(TUNNELD_DEFAULT_ADDRESS)`로 받은 RSD를 `DvtProvider(rsd)`에 넘김

`SyslogService.watch()` / `OsTraceService.syslog()`는 v9에서도 sync 그대로라 syslog 경로는 lockdown 핸드셰이크만 async 브리지하면 됨.

iOS 26은 모두 RSD 경로 강제 — 즉 **메트릭을 잡으려면 별도 터미널에서 `sudo pymobiledevice3 remote tunneld` 데몬이 떠 있어야 한다**. 화면(AVF)과 syslog는 tunneld 불필요.

---

## 셋업 (Mac)

```bash
git fetch origin claude/mac-version-plan-AvqB5
git checkout claude/mac-version-plan-AvqB5

python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # win 스택은 마커로 자동 skip
```

iPhone 준비물:
1. USB 연결 → 잠금 해제 → **"이 컴퓨터를 신뢰"**
2. 설정 > 개인정보 보호 및 보안 > **개발자 모드 ON** (메트릭용, 재부팅 필요)
3. **메트릭을 쓸 거면** — 별도 터미널에서:
   ```bash
   sudo pymobiledevice3 remote tunneld
   ```
   띄워둔 채로 Trailbox 사용. iOS 17+ DVT는 이 데몬 없이는 접근 불가. 화면 캡처와 syslog는 영향 없음.

타깃 iOS 버전: **iOS 26.5 이상** (그 아래는 의도적으로 테스트하지 않음 — v9 RSD 경로가 메인).

---

## 검증 순서 (이 순서대로)

각 단계가 통과해야 다음으로. 실패 지점이 곧 튜닝 지점.

**1. import 기동 (가장 먼저)**
```bash
.venv/bin/python -c "import core.ios_device, core.ios_log_collector, core.ios_metrics_recorder, core.screen_recorder, core.system_info; print('ok')"
```
macOS에서 이미 통과 확인됨 (2026-05-30, pymobiledevice3 9.15.1 + pyobjc 12.2).

**2. 디바이스 열거** — `core/ios_device.py:list_devices()`
```bash
.venv/bin/python -c "from core.ios_device import list_devices; print(list_devices())"
```
- 빈 리스트 → usbmux가 디바이스를 못 봄(신뢰 안 됨 / 케이블).
- `capturable=False` → usbmux는 보는데 AVFoundation이 못 봄. → `enable_screen_capture_devices()`의 **CMIO 프로퍼티 set이 안 먹은 것** (튜닝 지점 #2).
- ⚠️ 디바이스 없이도 `RuntimeWarning: coroutine was never awaited`가 뜨면 v9 async 리라이트가 회귀한 것 — 보정 필요.

**2.5. tunneld 살아있는지 확인** (메트릭 검증 전제)
```bash
sudo pymobiledevice3 remote tunneld &      # 다른 터미널에 두는 게 편함
pymobiledevice3 tunneld devices            # iPhone udid가 나오면 성공
```
나오지 않으면 페어링 다시 (잠금해제 + 신뢰), Developer Mode 확인, 케이블 교체 순.

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
| 1 | tunneld 데몬 자체 | `sudo pymobiledevice3 remote tunneld`가 떠 있지 않으면 `IOSMetricsRecorder._error`에 "tunneld not reachable" 메시지가 들어감. **메트릭만 영향** — 화면/로그는 진행. 떠 있는데도 device가 안 잡히면 페어링/Developer Mode 의심 |
| 2 | `core/ios_device.py:enable_screen_capture_devices()` | CMIO 프로퍼티 set이 pyobjc 바인딩에서 인자 형태가 안 맞을 수 있음. `capturable=False`면 여기부터. QuickTime을 한 번 열면 OS가 대신 켜주므로 그걸로 우회 검증 가능 |
| 3 | `core/screen_recorder.py:_run_ios()` (192~) | `AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed)` 결과/디바이스 매칭, `AVCaptureMovieFileOutput` delegate 시그니처, `NSRunLoop` 슬라이스. delegate 메서드명은 Objective-C 셀렉터 그대로(`captureOutput:didFinishRecordingToOutputFileAtURL:...`) — pyobjc 변환명 확인 |
| 4 | `core/ios_metrics_recorder.py:_extract_proc()` | Sysmontap이 yield하는 `list[dict]` 안의 키 이름(`cpuUsage`/`physFootprint`/`name`/`pid`...) 실기 확인. 한 틱 `print(entries[0])` → 후보키 보정. cpu가 0-1 fraction인지 0-100인지도 여기서 결정 (코드는 둘 다 처리하나 한쪽으로 굳히면 정확도 향상) |
| 5 | `core/ios_metrics_recorder.py:_extract_gfx()` | Graphics 이벤트가 `(selector, [args])` tuple로 오는지 dict notification으로 오는지 실기 확인. `print(sample)` 한 번이면 끝. fps/gpu 키 이름(`CoreAnimationFramesPerSecond`/`Device Utilization %`)도 같은 자리 |
| 6 | `core/ios_log_collector.py:_fields()` | `OsTraceService.syslog()` 엔트리의 속성명(`message`/`label`/`level`/`pid`) 버전 확인. 안 되면 `SyslogService.watch()` 문자열 폴백으로 자동 강등됨 |

**팁**: 3/4/5/6는 "실제 객체 한 개를 `print`/`dir()`로 찍어 키 확인 → 파서 보정"이 패턴. 파서는 이미 방어적(getattr+폴백+다중 후보키)이라 키만 맞추면 됨.

**제거된 항목**: 이전 핸드오프의 "`get_foreground_app` Developer Mode" 튜닝은 v9에서 해당 API(`DeviceInfo.foreground_running_process`)가 사라져 의도적으로 None stub. Phase 2 UI에서 사용자가 `ApplicationListing.applist`(async) 결과로부터 bundle을 선택하게 하는 게 v9 정석.

---

## 코드 지도 (이미 작성된 것)

| 파일 | 역할 | 핵심 심볼 |
|---|---|---|
| `core/screen_recorder.py` | iOS 화면 캡처 | `IOSDeviceTarget`, `_run_ios()`, `_remux_mov()` |
| `core/ios_device.py` | 디바이스 열거 + CMIO 노출 | `list_devices` (sync facade over async usbmux), `enable_screen_capture_devices`, `get_foreground_app` (v9에서 None stub) |
| `core/ios_log_collector.py` | syslog → `logs/syslog.jsonl` | `IOSLogCollector`, `_open_lockdown` (async), `_open_syslog_gen` (sync) |
| `core/ios_metrics_recorder.py` | DVT → `metrics/process.jsonl` | `IOSMetricsRecorder`, `_run_async` (asyncio.wait + gather), `_open_dvt_service_provider` (tunneld RSD) |
| `core/system_info.py` | 디바이스 스냅샷 | `collect_ios_info` (async lockdown bridge) |
| `main.py` | PyQt 오케스트레이션 | iOS 브랜치 |
| `desktop-tauri/bridge_record.py` | Tauri 녹화 daemon | `kind=="ios"` |
| `desktop-tauri/bridge.py` | Tauri one-shot | `list-ios-devices` |

**설계 불변식 (깨지 말 것)**: 모든 레코더는 `t0_perf` 하나로 `t_video_s` 방출, JSONL 스키마는 Windows/Android와 100% 동일 → viewer/MCP 무수정. 무거운 dep(pyobjc 등)는 **워커 스레드 내부 lazy import** (모듈 스코프 금지 — COM/startup 규칙과 동일). pymobiledevice3 호출은 워커 스레드가 자체 `asyncio.run`을 도는 패턴(이벤트 루프 1개/스레드 1개) — 외부에는 모두 sync facade.

---

## 아직 안 한 것 (실기 검증 후 착수)

1. **A3 — macOS 빌드**: `build.py`에 `sys.platform=="darwin"` 분기. Tauri는 `bundle.targets="all"`이라 `npm run tauri:build`로 `.app` 생성; PyInstaller로 `trailbox-bridge`(Mach-O) 사이드카. 코드사이닝은 v1 ad-hoc, 배포 시 Apple Developer($99/년) + notarytool. `Info.plist`에 `NSCameraUsageDescription` 필요.
2. **Phase 2 — UI 디바이스 선택**: bridge `list-ios-devices`는 준비됨. (a) Tauri React: 캡처 소스에 "iOS Device" + 드롭다운 + 3초 폴링, start payload `{"kind":"ios","udid":...,"device_name":...,"bundle_id":...}`. (b) PyQt `ui/launcher_panel.py`: `android_radio` 옆에 `ios_radio` + `_DetectIOSDevicesWorker` (Android worker 미러링, `blockSignals` 패턴).
3. **버전 동기화** (CLAUDE.md 규칙): 출시 시 `main.py.__version__` + `tauri.conf.json` version 같은 커밋에서 bump + 태그.

---

## 커밋 로그 (이 브랜치)

```
feat(ios): rewrite for pymobiledevice3 v9 async API + tunneld RSD     # 2026-05-30
docs: add Mac-session handoff + CLAUDE.md pointer for iOS capture
docs: record iOS capture implementation status in the plan
feat(ios): bridge list-ios-devices command + cross-platform requirements
feat(ios): wire iOS capture into main.py + Tauri bridge orchestration
feat(ios): add IOSDeviceTarget + iOS capture core modules
feat(macos): guard Windows-only imports so core/ loads on macOS
docs: add macOS build + iOS capture implementation plan
```
