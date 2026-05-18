# Android Device Capture — 구현 계획

이 문서는 [ROADMAP.md](../ROADMAP.md)의 "모바일 확장 — Android" 섹션에 대한 **확정된 구현 계획**이다. 결정사항과 페이즈별 작업 내용을 담고 있으며, 실제 구현 시작 시 이 문서를 따라 진행한다.

---

## 결정사항 (확정)

| 항목 | 결정 |
|---|---|
| 캡처 백엔드 | **scrcpy 바이너리 래핑** (직접 프로토콜 구현 X) |
| v1 스코프 | **Windows 기능 풀 패리티** — video + audio + logs + inputs + metrics 동시 |
| 바이너리 배포 | **설치 프로그램에 adb + scrcpy 번들** (사용자 별도 설치 불필요) |
| 멀티 디바이스 | v1은 **1대** (확장은 추후) |
| 무선 ADB | v1은 **USB only** (Wi-Fi ADB는 사용자가 직접 페어링한 디바이스만 자동 인식) |
| 출시 버전 | 0.3.0 (minor bump) |

배경: Mac 포팅(=iOS 캡처 전제조건) 대비 Android는 Windows 코드베이스에 침습이 최소이고 사용자 가치가 크다. Apple Developer 계정 비용 부담 없이 진행 가능한 점도 의사결정에 반영됨.

---

## 설계 원칙

CLAUDE.md의 *single rule*을 그대로 유지: `t0_perf`를 한 곳에서 캡처하고 모든 레코더가 `t_video_s = perf_counter() - t0_perf`를 JSONL에 방출. 출력 디렉터리 레이아웃과 JSONL 스키마는 Windows 세션과 **100% 동일**. `viewer.html` 생성기와 MCP 서버는 분기 없이 동작.

새 `CaptureTarget` 변형 추가:
```python
@dataclass(frozen=True)
class AndroidDeviceTarget:
    serial: str
    package: str | None       # 포어그라운드 패키지 (best-effort)

CaptureTarget = MonitorTarget | WindowTarget | AndroidDeviceTarget
```

신호별로 Windows 구현과 Android 구현이 같은 출력 스키마를 산출하는 **자매 클래스**를 만들고, `main.py`의 `_on_start_requested`가 target 타입을 보고 어느 세트를 생성할지 결정한다.

---

## Phase 1 — 기반 (binary bundling + adb helper)

**새 파일**: `core/adb.py`
- `get_adb_path()` / `get_scrcpy_path()` — `sys.frozen` 분기로 `_MEIPASS/bin/`에서 찾고, dev 환경에선 PATH fallback
- `list_devices()` — `adb devices -l` 파싱 → `[(serial, model, state)]`
- `get_foreground_package(serial)` — `adb shell dumpsys window windows | grep mCurrentFocus`, best-effort (실패 시 None)
- `get_screen_size(serial)` — `adb shell wm size` → `(w, h)` (input recorder 좌표 정규화용)
- `get_cpu_count(serial)` — `adb shell nproc` (metrics에서 cpu_pct 정규화)
- 모든 호출은 명시적 timeout, stderr 캡처 후 로깅

**수정**: `build.py`
- `--add-binary` 두 줄 추가 (adb.exe, scrcpy.exe + scrcpy-server.jar)
- `tools/android/` 디렉터리에 platform-tools와 scrcpy 바이너리를 두고 build.py가 참조. `.gitignore`에 추가하고 README에 다운로드 가이드
- scrcpy **2.4+** 핀 (`--record=-` 안정성)

**수정**: `installer/Trailbox-installer.iss`
- `[Files]`에 `Source: "{#DistDir}\bin\adb.exe"; DestDir: "{app}\bin"` 등 추가
- 라이선스: scrcpy = Apache-2.0, adb (platform-tools) = Apache-2.0. `NOTICE.txt`에 attribution 명시 후 installer 포함

---

## Phase 2 — UI (디바이스 선택)

**수정**: `ui/launcher_panel.py`
- 기존 `monitor_radio` / `window_radio` 옆에 `android_radio` 추가
- `android_device_combo: QComboBox` — `_DetectAndroidDevicesWorker(QThread)` 결과로 populate
- `_DetectAndroidDevicesWorker`: `core/process_detector.py`의 `_DetectWindowWorker` 패턴 그대로 미러링. `run()`에서 `core.adb.list_devices()` 호출 → `pyqtSignal(list)` emit
- 주기적 갱신: `QTimer`로 3초마다 재실행 (USB 연결/해제 자동 반영). `refresh_window_list`와 똑같이 `blockSignals(True/False)`로 감싸기
- `capture_target()`에 분기 추가: `android_radio.isChecked()` → `AndroidDeviceTarget(serial=..., package=...)`
- `_update_target_controls()`에 Android 모드 토글 추가
- (선택) 패키지 텍스트 박스 — 비우면 시작 시 `get_foreground_package()` 자동 호출

---

## Phase 3 — 화면 + 오디오 (scrcpy → ffmpeg)

**수정**: `core/screen_recorder.py`

기존 dispatch (`isinstance(target, MonitorTarget)` vs `WindowTarget`) 옆에 세 번째 분기:

```python
elif isinstance(self.target, AndroidDeviceTarget):
    self._run_scrcpy()
```

**`_run_scrcpy()` 동작**:
1. scrcpy spawn:
   ```
   scrcpy --serial=<S> --no-window --record=- --record-format=mkv
          --audio-source=output --audio-codec=opus --max-fps=60
   ```
   (Android 11+ `--audio-source=output`; 그 이하면 자동으로 `--no-audio`로 폴백)
2. scrcpy stdout(MKV bytestream) → 새로 spawn한 ffmpeg subprocess stdin
3. ffmpeg 커맨드: `ffmpeg -i - -c copy -movflags +faststart screen.mp4` (재인코딩 없이 컨테이너 변환). 기존 `_spawn_ffmpeg`는 BGRA rawvideo 가정이라 재사용 불가 → **`_spawn_ffmpeg_passthrough()` 별도 메서드로 분리**
4. `frames.jsonl`: scrcpy stderr에 frame 로그가 안 나오므로, v1에선 비워두고 `frame_stats`는 ffmpeg 종료 로그의 `frame=` 카운터만 기록. 향후 ffprobe pass로 보완.
5. 에러 처리: scrcpy/ffmpeg 둘 다 모니터링, 한쪽이 죽으면 나머지도 종료 후 `_error`에 사유 저장

**post_mux 우회**: scrcpy가 이미 video+audio를 한 MKV로 합쳐서 주므로 `core/post_mux.py`의 `mux_av()` 호출 불필요. `main.py`의 finalize에서 target 타입 보고 skip.

---

## Phase 4 — 로그 (adb logcat)

**새 파일**: `core/android_log_collector.py` — `LogCollector`와 동일 시그니처:
```python
AndroidLogCollector(serial: str, output_dir: Path, t0_perf: float,
                    package_filter: str | None = None)
```

- `adb -s <serial> logcat -v threadtime -T <session_start_iso>` 서브프로세스 (–T로 세션 시작 시각 이후 라인만 수신, 버퍼 청소 X)
- `threadtime` 포맷: `MM-DD HH:MM:SS.mmm  PID  TID LEVEL TAG: message`
- 출력 스키마는 기존 `logs.jsonl`과 동일 (`@timestamp`, `t_video_s`, `message`, `ecs.version`). 추가로 `log.process.{pid,tid}`, `log.level`, `log.tag` — ECS 8.11 호환
- `logs.vtt`도 같이 생성 (LogCollector의 VTT 작성 로직 helper로 추출 권장)
- package_filter가 있으면 `--pid=$(adb shell pidof <pkg>)` 옵션으로 소음 감소
- threading: 기존과 동일 plain daemon thread

---

## Phase 5 — 입력 (adb getevent)

**새 파일**: `core/android_input_recorder.py` — `InputRecorder`와 동일 시그니처 (hwnd 대신 screen size):
```python
AndroidInputRecorder(serial: str, output_dir: Path, t0_perf: float,
                     screen_size: tuple[int, int])
```

- `adb -s <serial> shell getevent -lt` 서브프로세스
- 파싱 대상:
  - `EV_ABS ABS_MT_POSITION_X / _Y` → 터치 좌표 (raw 디바이스 값을 `screen_size` 기준으로 정규화)
  - `EV_KEY BTN_TOUCH 1/0` → tap press/release
  - `EV_SYN SYN_REPORT` → 이벤트 경계 (이때 누적된 좌표 flush)
  - `EV_KEY KEY_VOLUMEUP/DOWN/POWER` 등 → 키 이벤트
- 출력 스키마는 기존 `inputs.jsonl`과 동일
- **알려진 한계**: 일부 디바이스/제조사에서 getevent 권한 거부. 실패 시 recorder는 `_error`에 사유 기록하고 빈 jsonl로 종료 — 다른 레코더는 영향 없음 (best-effort)

---

## Phase 6 — 메트릭

**새 파일**: `core/android_metrics_recorder.py` — `MetricsRecorder`와 동일 시그니처:
```python
AndroidMetricsRecorder(serial: str, package: str, output_path: Path,
                       t0_perf: float, interval_s: float = 1.0)
```

- 1Hz 폴링 스레드. 매 tick:
  - `adb shell top -n 1 -p $(pidof <package>)` → CPU%, RSS
  - `adb shell dumpsys gfxinfo <package>` → jank count, 99th/95th percentile frame time
  - `adb shell dumpsys meminfo <package> -d` → graphics mem, native heap (선택)
- 출력 스키마는 기존 `process.jsonl`과 동일:
  - `process.cpu_pct` (nproc로 정규화)
  - `process.cpu_pct_per_core` (raw)
  - `process.rss_mb`
  - `process.gpu_pct` — Android는 직접 노출 X, `gpu_pct=null` 두고 `process.android.jank_count` / `frame_time_99p_ms` 같은 보조 필드 추가
- adb 호출 비용 (~50-200ms/call) 때문에 interval_s=1.0이 적정

---

## Phase 7 — 오케스트레이션 (main.py)

**수정**: `main.py`의 `_on_start_requested`

```python
target = self.launcher_panel.capture_target()
t0_perf = time.perf_counter()

if isinstance(target, AndroidDeviceTarget):
    package = target.package or core.adb.get_foreground_package(target.serial)
    screen_size = core.adb.get_screen_size(target.serial)
    session = Session(
        exe_path=None,
        app_name=f"android_{target.serial}_{package or 'unknown'}",
        log_dir=None,
        output_root=OUTPUT_ROOT,
        target_pid=None,
    )
    screen_recorder = ScreenRecorder(...)  # _run_scrcpy 경로
    log_collector = AndroidLogCollector(target.serial, ..., t0_perf, package_filter=package)
    input_recorder = AndroidInputRecorder(target.serial, ..., t0_perf, screen_size)
    metrics_recorder = AndroidMetricsRecorder(target.serial, package, ..., t0_perf)
    audio_recorder = None  # scrcpy가 이미 처리
else:
    # 기존 Windows 경로 그대로
    ...
```

- `Session`: `app_name` 파라미터로 안전화된 이름을 직접 받을 수 있게 (지금은 `exe_path` stem에서 뽑음 → 약간 조정 필요). session_id 형식: `android_<serial>_<pkg>_<YYYYMMDD_HHMMSS>`
- `session_meta.json`의 `system` 섹션: Android 모드는 호스트 OS가 아닌 **디바이스** 정보 (`adb shell getprop ro.build.version.release`, `ro.product.model`) 기록 — `core/system_info.py`에 `collect_android_info(serial)` 추가
- `finalize`에서 `post_mux.mux_av()` skip (scrcpy 경로)
- `viewer_generator.generate_viewer()`는 수정 불필요 — JSONL 스키마가 같으므로 자동 동작

---

## 변경 파일 매트릭스

| 파일 | 변경 |
|---|---|
| `core/screen_recorder.py` | AndroidDeviceTarget 추가, `_run_scrcpy`, `_spawn_ffmpeg_passthrough` 분리 |
| `core/adb.py` | 신규 |
| `core/android_log_collector.py` | 신규 |
| `core/android_input_recorder.py` | 신규 |
| `core/android_metrics_recorder.py` | 신규 |
| `core/system_info.py` | `collect_android_info(serial)` 추가 |
| `core/session.py` | `app_name` 파라미터 추가 (exe_path 우회 경로) |
| `ui/launcher_panel.py` | android_radio, device combo, `_DetectAndroidDevicesWorker` |
| `main.py` | `_on_start_requested`에 target dispatch |
| `build.py` | adb/scrcpy `--add-binary` |
| `installer/Trailbox-installer.iss` | adb/scrcpy `[Files]` + NOTICE.txt |
| `requirements.txt` | 변경 없음 (새 Python 의존성 없음) |
| `tools/android/` | 신규 디렉터리 (bundle용 바이너리, `.gitignore`) |
| `README.md` | Android 사용법 + 빌드 시 바이너리 준비 방법 |

---

## 재사용할 기존 패턴

- **CaptureTarget union dispatch**: `core/screen_recorder.py:32-43` — 그대로 확장
- **frames.jsonl 라이팅**: `core/screen_recorder.py:290-307`
- **QThread worker + blockSignals**: `ui/launcher_panel.py:262` + `core/process_detector.py`의 `_DetectWindowWorker`
- **`get_ffmpeg_exe()` (imageio-ffmpeg)**: 번들 바이너리 위치 결정 패턴 → `core/adb.py`에서 동일 구조로 작성
- **best-effort 에러 처리**: 각 레코더의 `_error` + `session.finalize(extra={...})`
- **JSONL ECS 스키마** (`ecs.version`, `@timestamp`, `t_video_s`)

---

## 검증

1. **단위 동작**: Pixel/Galaxy USB 연결 → `adb devices` 확인 → Trailbox 실행 → "Android device" 라디오 선택 → 디바이스 콤보에 serial 표시
2. **풀 세션**: 녹화 시작/종료 → `output/android_<serial>_<pkg>_<ts>/`에 다음 모두 생성:
   - `screen.mp4` (video + audio, ffprobe 확인)
   - `logs/logs.jsonl` + `logs.vtt`
   - `inputs/inputs.jsonl` + `inputs.vtt`
   - `metrics/process.jsonl` (1Hz, jank 카운트 포함)
   - `viewer.html`
   - `session_meta.json` — `system.android.model` / `system.android.android_version` 필드 존재
3. **viewer**: `viewer.html` 더블클릭(`file://`)으로 열어 video 재생 + 로그/입력 오버레이가 시간축에 정렬되는지
4. **MCP 통합**: `python -m mcp_server` → Claude Desktop에서 `list_sessions` / `query_events`로 새 Android 세션 조회
5. **번들 검증**: `build.py` → `dist/Trailbox-Setup.exe`로 클린 머신에 설치 → adb/scrcpy가 PATH에 없는 환경에서도 동작
6. **음성 폴백**: Android 10 이하 디바이스로 `--no-audio` 자동 폴백 작동 확인

---

## 알려진 리스크 / TBD

- **Android 10 이하**: `--audio-source=output` 미지원 → 자동 `--no-audio` 폴백
- **getevent 권한**: 일부 제조사 차단 → 해당 디바이스는 inputs.jsonl 비어있는 채로 세션 진행 (best-effort)
- **frame_stats 정밀도**: scrcpy 경로에선 per-frame timing 어려움 → v1은 거시 통계만, per-frame `frames.jsonl`은 비워둠. ffprobe pass로 추후 보완
- **post_mux 우회**: scrcpy 경로는 video+audio가 이미 한 컨테이너로 나옴 → `screen.video.mp4` + `screen.audio.wav` 중간 파일 없음. finalize 로직이 이를 인지해야 함
- **scrcpy 버전 2.4 미만**: `--record=-` 불안정 → build.py 버전 체크 + README 가이드
- **session_id 충돌**: 무선 adb 등으로 동일 디바이스가 다른 serial로 표시되면 디렉터리 두 개. v1 수용
- **버전 동기화 룰** (CLAUDE.md): `main.py.__version__` + `installer.iss.MyAppVersion`을 같은 커밋에서 0.3.0으로 올리고 그 위에 태그

---

## 작업 순서

Phase 1 → 2 → 3 → 7(부분: video만 종단 동작) → 4 → 5 → 6 → 7(완성) → 검증.

Phase 3까지 끝나면 "Android 화면+오디오만 잡히는 미니멀 세션"이 동작 → 그 시점에 사용자 검증 1회 후 나머지 신호 부착이 리스크 분산에 좋음.

---

## 사전 준비물

구현 시작 전 사용자가 준비해야 할 것:
- Android 테스트 디바이스 (개발자 옵션 + USB 디버깅 ON)
- [platform-tools](https://developer.android.com/tools/releases/platform-tools) 윈도우 빌드 → `tools/android/platform-tools/`에 압축 해제
- [scrcpy 2.4+ Windows 빌드](https://github.com/Genymobile/scrcpy/releases) → `tools/android/scrcpy/`에 압축 해제
