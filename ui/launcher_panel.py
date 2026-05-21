"""Launcher panel: pick target app, log folder, capture target, and launch."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from core import adb
from core.adb import AdbDevice
from core.process_detector import find_log_dir_for_pid, find_pids_for_log_dir
from core.screen_recorder import (
    AndroidDeviceTarget,
    CaptureTarget,
    MonitorTarget,
    WindowTarget,
)
from core.window_clicker import ClickPicker, HotkeyPicker
from core.window_picker import WindowInfo, enumerate_windows


class _DetectWindowWorker(QThread):
    """Scan running processes for ones writing to ``log_dir`` (async)."""

    found = pyqtSignal(list)

    def __init__(self, log_dir: Path) -> None:
        super().__init__()
        self._log_dir = Path(log_dir)

    def run(self) -> None:
        try:
            pids = find_pids_for_log_dir(self._log_dir)
        except Exception:  # noqa: BLE001 - best-effort, never crash the UI
            pids = []
        self.found.emit(pids)


class _DetectLogDirWorker(QThread):
    """Find the likely log directory for a given PID (async)."""

    found = pyqtSignal(int, str)  # (pid, log_dir or "")

    def __init__(self, pid: int) -> None:
        super().__init__()
        self._pid = int(pid)

    def run(self) -> None:
        try:
            result = find_log_dir_for_pid(self._pid)
        except Exception:  # noqa: BLE001
            result = None
        self.found.emit(self._pid, str(result) if result else "")


class _DetectAndroidDevicesWorker(QThread):
    """Run ``adb devices -l`` off the GUI thread.

    Mirrors the ``_DetectWindowWorker`` pattern: a single shot scan that emits
    the result on completion. A QTimer in the panel re-fires it every few
    seconds so plug/unplug events show up without user action.
    """

    found = pyqtSignal(list)  # list[AdbDevice]

    def run(self) -> None:
        try:
            devices = adb.list_devices()
        except Exception:  # noqa: BLE001 - never crash the UI
            devices = []
        self.found.emit(devices)


HOTKEY_LABEL = "Ctrl+Shift+P"
FPS_OPTIONS = [10, 15, 24, 30, 60]
DEFAULT_FPS = 15

# How often the Android device list refreshes itself. Long enough that adb
# isn't constantly being invoked while the user fiddles with the UI; short
# enough that plug-in is noticed within a couple seconds.
_ANDROID_REFRESH_MS = 3000


class LauncherPanel(QWidget):
    app_launched = pyqtSignal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._launched_process: subprocess.Popen | None = None
        self._click_picker: ClickPicker | None = None
        self._hotkey_picker: HotkeyPicker | None = None
        self._detect_thread: _DetectWindowWorker | None = None
        self._logdir_thread: _DetectLogDirWorker | None = None
        self._android_thread: _DetectAndroidDevicesWorker | None = None
        self._android_timer: QTimer | None = None
        self._build_ui()
        self.refresh_window_list()
        self._start_hotkey_picker()
        # Initial Android scan + recurring poll. Fires regardless of the
        # current radio selection so switching to Android is instant.
        self._kick_android_refresh()
        self._android_timer = QTimer(self)
        self._android_timer.setInterval(_ANDROID_REFRESH_MS)
        self._android_timer.timeout.connect(self._kick_android_refresh)
        self._android_timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # --- Target app group ----------------------------------------------
        app_group = QGroupBox("대상 애플리케이션", self)
        app_layout = QVBoxLayout(app_group)

        exe_row = QHBoxLayout()
        exe_row.addWidget(QLabel("실행 파일:"))
        self.exe_edit = QLineEdit(self)
        self.exe_edit.setPlaceholderText("예: C:\\Games\\MyGame\\MyGame.exe")
        exe_row.addWidget(self.exe_edit, 1)
        self.exe_browse_btn = QPushButton("찾아보기…", self)
        self.exe_browse_btn.clicked.connect(self._browse_exe)
        exe_row.addWidget(self.exe_browse_btn)
        app_layout.addLayout(exe_row)

        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("로그 폴더:"))
        self.log_edit = QLineEdit(self)
        self.log_edit.setPlaceholderText("예: C:\\Games\\MyGame\\Logs")
        self.log_edit.editingFinished.connect(self._on_log_dir_changed)
        log_row.addWidget(self.log_edit, 1)
        self.log_browse_btn = QPushButton("찾아보기…", self)
        self.log_browse_btn.clicked.connect(self._browse_log_dir)
        log_row.addWidget(self.log_browse_btn)
        self.detect_btn = QPushButton("🔍 창 찾기", self)
        self.detect_btn.setToolTip("이 폴더에 로그를 쓰는 프로세스의 창을 자동 선택")
        self.detect_btn.clicked.connect(self._on_log_dir_changed)
        log_row.addWidget(self.detect_btn)
        app_layout.addLayout(log_row)

        # Extra log folders: a list + +/- buttons so users can mirror e.g. a
        # server log share alongside the client's local log dir. Kept compact
        # — height-limited so it doesn't dominate the panel until needed.
        extra_row = QHBoxLayout()
        extra_row.addWidget(QLabel("추가 로그 폴더:"))
        extra_row.addStretch(1)
        self.extra_log_add_btn = QPushButton("+ 폴더 추가", self)
        self.extra_log_add_btn.clicked.connect(self._add_extra_log_dir)
        extra_row.addWidget(self.extra_log_add_btn)
        self.extra_log_remove_btn = QPushButton("− 제거", self)
        self.extra_log_remove_btn.clicked.connect(self._remove_extra_log_dir)
        extra_row.addWidget(self.extra_log_remove_btn)
        app_layout.addLayout(extra_row)

        self.extra_log_list = QListWidget(self)
        self.extra_log_list.setMaximumHeight(72)
        self.extra_log_list.setToolTip(
            "기본 로그 폴더 외에 추가로 감시할 폴더 (예: 서버 로그 공유 폴더).\n"
            "녹화 시작 시점 EOF부터 새 라인만 기록됩니다."
        )
        app_layout.addWidget(self.extra_log_list)

        recursive_row = QHBoxLayout()
        self.log_recursive_check = QCheckBox("하위 폴더까지 스캔", self)
        self.log_recursive_check.setChecked(True)
        self.log_recursive_check.setToolTip(
            "켜져 있으면 각 로그 폴더의 하위 폴더 내 파일도 자동으로 따라잡습니다."
        )
        recursive_row.addWidget(self.log_recursive_check)
        recursive_row.addSpacing(12)
        recursive_row.addWidget(QLabel("확장자:"))
        self.log_extensions_edit = QLineEdit(self)
        self.log_extensions_edit.setText("log, txt")
        self.log_extensions_edit.setPlaceholderText("log, txt")
        self.log_extensions_edit.setToolTip(
            "캡처할 파일 확장자 (쉼표 또는 공백 구분).\n"
            "예: log, txt, json, out, err\n"
            "비우거나 *를 입력하면 모든 파일을 캡처합니다.\n"
            "(와일드카드 모드에서도 .exe / .png / .zip 등 잘 알려진 바이너리,\n"
            " 그리고 NUL 바이트로 시작하는 파일은 자동으로 제외됩니다.)"
        )
        self.log_extensions_edit.setMaximumWidth(220)
        recursive_row.addWidget(self.log_extensions_edit)
        recursive_row.addStretch(1)
        app_layout.addLayout(recursive_row)

        launch_row = QHBoxLayout()
        launch_row.addStretch(1)
        self.launch_btn = QPushButton("앱 실행", self)
        self.launch_btn.clicked.connect(self._launch_app)
        launch_row.addWidget(self.launch_btn)
        app_layout.addLayout(launch_row)

        root.addWidget(app_group)

        # --- Capture target group ------------------------------------------
        cap_group = QGroupBox("캡처 대상", self)
        cap_layout = QVBoxLayout(cap_group)

        radio_row = QHBoxLayout()
        self.monitor_radio = QRadioButton("전체 모니터", self)
        self.window_radio = QRadioButton("특정 창 (WGC)", self)
        self.android_radio = QRadioButton("Android 디바이스 (scrcpy)", self)
        self.monitor_radio.setChecked(True)
        self.monitor_radio.toggled.connect(self._update_target_controls)
        self.android_radio.toggled.connect(self._update_target_controls)
        radio_row.addWidget(self.monitor_radio)
        radio_row.addWidget(self.window_radio)
        radio_row.addWidget(self.android_radio)
        radio_row.addStretch(1)
        cap_layout.addLayout(radio_row)

        win_row = QHBoxLayout()
        win_row.addWidget(QLabel("창:"))
        self.window_combo = QComboBox(self)
        self.window_combo.setMinimumWidth(380)
        self.window_combo.currentIndexChanged.connect(self._on_window_changed)
        win_row.addWidget(self.window_combo, 1)
        self.refresh_btn = QPushButton("새로고침", self)
        self.refresh_btn.clicked.connect(self.refresh_window_list)
        win_row.addWidget(self.refresh_btn)
        cap_layout.addLayout(win_row)

        android_row = QHBoxLayout()
        android_row.addWidget(QLabel("디바이스:"))
        self.android_combo = QComboBox(self)
        self.android_combo.setMinimumWidth(320)
        android_row.addWidget(self.android_combo, 1)
        self.android_refresh_btn = QPushButton("새로고침", self)
        self.android_refresh_btn.clicked.connect(self._kick_android_refresh)
        android_row.addWidget(self.android_refresh_btn)
        cap_layout.addLayout(android_row)

        # Status hint populated by the device-detect worker.
        self.android_status = QLabel("Android: 디바이스 검색 중…", self)
        self.android_status.setStyleSheet("QLabel { color: #666; }")
        cap_layout.addWidget(self.android_status)

        backend_row = QHBoxLayout()
        backend_row.addWidget(QLabel("영상 백엔드:"))
        self.android_backend_combo = QComboBox(self)
        self.android_backend_combo.addItem(
            "auto (SDK 감지 + 첫 프레임 폴백)", userData="auto",
        )
        self.android_backend_combo.addItem("scrcpy (고화질 + 오디오)", userData="scrcpy")
        self.android_backend_combo.addItem(
            "screenrecord (Android 16+ 호환, 오디오 X, 3분/청크)",
            userData="screenrecord",
        )
        self.android_backend_combo.setToolTip(
            "auto: SDK 36+ (Android 16+) 면 즉시 screenrecord. 그 외엔 scrcpy 시도 후 3초 안에 첫 프레임 없으면 screenrecord 로 자동 전환.\n"
            "scrcpy: 활발히 업데이트되는 Genymobile 도구. 영상+오디오. 단 OEM 정책에 막힐 수 있음 (Galaxy + One UI 8 등).\n"
            "screenrecord: Android 4.4+ 에 기본 내장된 Google 도구. 시스템 API 만 사용 → 막히는 케이스 적음. 오디오 미지원."
        )
        backend_row.addWidget(self.android_backend_combo, 1)
        cap_layout.addLayout(backend_row)

        pick_row = QHBoxLayout()
        self.click_pick_btn = QPushButton("🎯 창 클릭으로 선택", self)
        self.click_pick_btn.clicked.connect(self._begin_click_pick)
        pick_row.addWidget(self.click_pick_btn)
        self.pick_status = QLabel(f"(또는 단축키 {HOTKEY_LABEL})", self)
        self.pick_status.setStyleSheet("QLabel { color: #666; }")
        pick_row.addWidget(self.pick_status, 1, Qt.AlignmentFlag.AlignLeft)
        cap_layout.addLayout(pick_row)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("최대 fps:"))
        self.fps_combo = QComboBox(self)
        for v in FPS_OPTIONS:
            self.fps_combo.addItem(f"{v} fps", userData=v)
        self.fps_combo.setCurrentIndex(FPS_OPTIONS.index(DEFAULT_FPS))
        fps_row.addWidget(self.fps_combo)
        fps_row.addStretch(1)
        cap_layout.addLayout(fps_row)

        audio_row = QHBoxLayout()
        self.audio_check = QCheckBox("시스템 사운드 녹음 (loopback)", self)
        self.audio_check.setChecked(True)
        audio_row.addWidget(self.audio_check)
        audio_row.addStretch(1)
        cap_layout.addLayout(audio_row)

        input_row = QHBoxLayout()
        self.input_check = QCheckBox("입력 기록", self)
        self.input_check.setToolTip(
            "PC: 키보드/마우스 (pynput)\n"
            "Android: 터치 + 볼륨/전원 키 (adb getevent)"
        )
        self.input_check.setChecked(True)
        input_row.addWidget(self.input_check)
        input_row.addStretch(1)
        cap_layout.addLayout(input_row)

        metrics_row = QHBoxLayout()
        self.metrics_check = QCheckBox("프로세스 텔레메트리", self)
        self.metrics_check.setToolTip(
            "PC: CPU/메모리/스레드/GPU (psutil + PDH)\n"
            "Android: CPU/RSS + jank 카운트 + 프레임 타임 95/99p (adb top + dumpsys gfxinfo)"
        )
        self.metrics_check.setChecked(True)
        metrics_row.addWidget(self.metrics_check)
        metrics_row.addStretch(1)
        cap_layout.addLayout(metrics_row)

        root.addWidget(cap_group)
        root.addStretch(1)
        self._update_target_controls()

    # --- Public API --------------------------------------------------------

    def exe_path(self) -> str:
        return self.exe_edit.text().strip()

    def log_dir(self) -> str:
        return self.log_edit.text().strip()

    def extra_log_dirs(self) -> list[str]:
        """Additional log directories the user added via the list widget."""
        result: list[str] = []
        for i in range(self.extra_log_list.count()):
            text = self.extra_log_list.item(i).text().strip()
            if text:
                result.append(text)
        return result

    def log_dirs(self) -> list[str]:
        """Primary log dir + extras, deduped (case-insensitive on Windows),
        skipping empty entries. Order: primary first, then extras as added.
        """
        result: list[str] = []
        seen: set[str] = set()
        for path in [self.log_dir(), *self.extra_log_dirs()]:
            if not path:
                continue
            key = path.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(path)
        return result

    def log_recursive(self) -> bool:
        return self.log_recursive_check.isChecked()

    def log_extensions(self) -> frozenset[str]:
        """Parse the user's extension input into a normalized frozenset.

        Empty input or ``*`` means "all files" (LogCollector treats an empty
        set that way). Accepts ``log``, ``.log``, or ``*.log``; case-insensitive.
        """
        text = self.log_extensions_edit.text().strip()
        if not text or text == "*":
            return frozenset()
        out: set[str] = set()
        # Allow either commas or whitespace as separators so users can type
        # "log, txt" or "log txt json" — both feel natural.
        for raw in text.replace(",", " ").split():
            piece = raw.strip().lower().lstrip("*").lstrip(".")
            if piece:
                out.add("." + piece)
        # All-garbage input ("***", ",,,") falls back to "all files" rather
        # than capturing nothing — failing silent capture would be worse than
        # capturing too much.
        return frozenset(out) if out else frozenset()

    def launched_pid(self) -> int | None:
        if self._launched_process and self._launched_process.poll() is None:
            return self._launched_process.pid
        return None

    def capture_fps(self) -> int:
        data = self.fps_combo.currentData()
        return int(data) if data is not None else DEFAULT_FPS

    def audio_enabled(self) -> bool:
        return self.audio_check.isChecked()

    def input_enabled(self) -> bool:
        return self.input_check.isChecked()

    def metrics_enabled(self) -> bool:
        return self.metrics_check.isChecked()

    def capture_target(self) -> CaptureTarget | None:
        """Return the selected capture target, or None if the picker is invalid."""
        if self.monitor_radio.isChecked():
            return MonitorTarget(index=0)
        if self.android_radio.isChecked():
            device = self._selected_android_device()
            if device is None or not device.online:
                return None
            backend = self.android_backend_combo.currentData() or "auto"
            # Audio capture is decided by the backend (not the PC-side audio
            # checkbox — that's loopback, which doesn't apply here).
            # screenrecord never carries audio; scrcpy on Android <11 also
            # can't (main.py downgrades after the SDK probe). "auto" may
            # resolve to either at runtime, so we leave it on and the
            # screen recorder no-ops audio if it ends up using screenrecord.
            capture_audio = backend in ("scrcpy", "auto")
            return AndroidDeviceTarget(
                serial=device.serial,
                capture_audio=capture_audio,
                backend=backend,
            )
        info = self._selected_window()
        if info is None:
            return None
        return WindowTarget(hwnd=info.hwnd, title=info.title)

    def selected_android_device(self) -> AdbDevice | None:
        """For main.py: read the picked device (model/serial for session meta)."""
        return self._selected_android_device()

    def selected_window_info(self) -> WindowInfo | None:
        return self._selected_window()

    def select_hwnd(self, hwnd: int) -> bool:
        """Switch capture mode to 'window' and select the given HWND in the combo.

        Refreshes the list if the HWND is not currently in the combo. Returns
        False if the HWND can't be found even after a refresh.
        """
        self.window_radio.setChecked(True)
        if self._set_combo_to_hwnd(hwnd):
            return True
        self.refresh_window_list()
        return self._set_combo_to_hwnd(hwnd)

    def _set_combo_to_hwnd(self, hwnd: int) -> bool:
        for i in range(self.window_combo.count()):
            info: WindowInfo = self.window_combo.itemData(i)
            if info.hwnd == hwnd:
                self.window_combo.setCurrentIndex(i)
                # setCurrentIndex doesn't emit currentIndexChanged when the
                # target equals the current index; trigger the side-effect
                # (exe auto-fill) explicitly.
                self._on_window_changed(i)
                return True
        return False

    def refresh_window_list(self) -> None:
        previous_hwnd = None
        info = self._selected_window()
        if info is not None:
            previous_hwnd = info.hwnd

        # Block signals so transient intermediate indices during clear/repopulate
        # don't trigger _on_window_changed with the wrong window.
        self.window_combo.blockSignals(True)
        try:
            self.window_combo.clear()
            for w in enumerate_windows():
                self.window_combo.addItem(w.label, userData=w)
            if previous_hwnd is not None:
                for i in range(self.window_combo.count()):
                    w_info: WindowInfo = self.window_combo.itemData(i)
                    if w_info.hwnd == previous_hwnd:
                        self.window_combo.setCurrentIndex(i)
                        break
        finally:
            self.window_combo.blockSignals(False)

    # --- Internals ---------------------------------------------------------

    def _selected_window(self) -> WindowInfo | None:
        data = self.window_combo.currentData()
        return data if isinstance(data, WindowInfo) else None

    def _update_target_controls(self) -> None:
        is_window = self.window_radio.isChecked()
        is_android = self.android_radio.isChecked()
        self.window_combo.setEnabled(is_window)
        self.refresh_btn.setEnabled(is_window)
        self.click_pick_btn.setEnabled(is_window)
        self.android_combo.setEnabled(is_android)
        self.android_refresh_btn.setEnabled(is_android)
        self.android_status.setVisible(is_android)
        self.android_backend_combo.setEnabled(is_android)
        # PC-side WASAPI loopback doesn't apply to Android sessions. Grey
        # the box out but leave its check state alone so flipping back to
        # PC mode restores the user's prior preference automatically.
        self.audio_check.setEnabled(not is_android)
        if is_android:
            self.audio_check.setToolTip(
                "Android 캡처는 별도 토글 없음:\n"
                "• scrcpy + Android 11+ → 시스템 오디오 자동 캡처\n"
                "• scrcpy + Android 10 이하 → 영상만\n"
                "• screenrecord 백엔드 → 영상만 (API 한계)"
            )
        else:
            self.audio_check.setToolTip("")

    # ---- Android device picker -------------------------------------------

    def _selected_android_device(self) -> AdbDevice | None:
        data = self.android_combo.currentData()
        return data if isinstance(data, AdbDevice) else None

    def _kick_android_refresh(self) -> None:
        """Spawn a worker to refresh the device combo; no-op if one is running."""
        if self._android_thread is not None and self._android_thread.isRunning():
            return
        worker = _DetectAndroidDevicesWorker()
        worker.found.connect(self._on_android_devices_found)
        worker.finished.connect(worker.deleteLater)
        self._android_thread = worker
        worker.start()

    def _on_android_devices_found(self, devices: list) -> None:
        self._android_thread = None

        previous_serial: str | None = None
        prev = self._selected_android_device()
        if prev is not None:
            previous_serial = prev.serial

        # Same pattern as refresh_window_list: clear+repopulate under
        # blockSignals so we don't emit currentIndexChanged for transients.
        self.android_combo.blockSignals(True)
        try:
            self.android_combo.clear()
            for d in devices:
                self.android_combo.addItem(d.label, userData=d)
            if previous_serial is not None:
                for i in range(self.android_combo.count()):
                    item = self.android_combo.itemData(i)
                    if isinstance(item, AdbDevice) and item.serial == previous_serial:
                        self.android_combo.setCurrentIndex(i)
                        break
        finally:
            self.android_combo.blockSignals(False)

        if not devices:
            self.android_status.setText(
                "연결된 Android 디바이스가 없습니다. USB 디버깅을 켜고 케이블을 연결하세요."
            )
            self.android_status.setStyleSheet("QLabel { color: #c0392b; }")
        else:
            offline = [d for d in devices if not d.online]
            if offline:
                self.android_status.setText(
                    f"{len(devices)}대 발견 · {len(offline)}대 권한/오프라인 — "
                    "디바이스 화면의 USB 디버깅 허용 프롬프트를 확인하세요."
                )
                self.android_status.setStyleSheet("QLabel { color: #c0392b; }")
            else:
                self.android_status.setText(
                    f"Android 디바이스 {len(devices)}대 연결됨."
                )
                self.android_status.setStyleSheet("QLabel { color: #2c7a2c; }")

    def _own_top_level_hwnds(self) -> list[int]:
        """HWNDs to exclude from picking (this app's own windows)."""
        top = self.window()
        result = []
        if top is not None:
            try:
                result.append(int(top.winId()))
            except Exception:  # noqa: BLE001
                pass
        return result

    def _start_hotkey_picker(self) -> None:
        self._hotkey_picker = HotkeyPicker(exclude_hwnds=self._own_top_level_hwnds())
        self._hotkey_picker.picked.connect(self._on_hotkey_picked)
        self._hotkey_picker.start()

    def stop_pickers(self) -> None:
        """Called from main window on close to release pynput listeners."""
        if self._click_picker is not None:
            self._click_picker.stop()
            self._click_picker = None
        if self._hotkey_picker is not None:
            self._hotkey_picker.stop()
            self._hotkey_picker = None
        if self._android_timer is not None:
            self._android_timer.stop()
            self._android_timer = None

    def _begin_click_pick(self) -> None:
        if self._click_picker is not None:
            return
        top = self.window()
        excludes = self._own_top_level_hwnds()
        if self._hotkey_picker is not None:
            self._hotkey_picker.set_exclude(excludes)

        self._click_picker = ClickPicker(exclude_hwnds=excludes)
        self._click_picker.picked.connect(self._on_click_picked)
        self._click_picker.cancelled.connect(self._on_click_cancelled)

        self.pick_status.setText("원하는 창을 클릭하세요 · ESC로 취소")
        self.pick_status.setStyleSheet("QLabel { color: #c0392b; font-weight: bold; }")
        self.click_pick_btn.setEnabled(False)
        if top is not None:
            top.showMinimized()
        self._click_picker.start()

    def _on_click_picked(self, hwnd: int) -> None:
        self._restore_after_pick()
        if not self.select_hwnd(hwnd):
            self._warn_on_top(
                "선택한 창을 캡처 대상으로 등록할 수 없습니다.\n\n"
                "다음 중 하나일 수 있어요:\n"
                "• 관리자 권한으로 실행된 창 (Trailbox 도 관리자 권한으로 재실행 필요)\n"
                "• 보호 모드 / DRM 콘텐츠 창 (Netflix, 일부 보안 SW)\n"
                "• 자식 창이거나 타이틀이 없는 창 (목록 필터에서 제외됨)\n\n"
                "다시 시도하거나 «모니터 캡처» 모드를 사용하세요."
            )

    def _on_click_cancelled(self) -> None:
        self._restore_after_pick()

    def _on_hotkey_picked(self, hwnd: int) -> None:
        # Called from pynput thread; Qt routes the signal to the main thread.
        if not self.select_hwnd(hwnd):
            return
        top = self.window()
        if top is not None and top.isMinimized():
            top.showNormal()

    def _restore_after_pick(self) -> None:
        if self._click_picker is not None:
            self._click_picker.stop()
            self._click_picker = None
        top = self.window()
        if top is not None:
            # After the picker click went to a foreign window, that window
            # owns the foreground. Windows' no-steal-focus rule means a
            # bare showNormal()+activateWindow() can leave Trailbox behind
            # the picked app — including any QMessageBox we open next.
            # setWindowState clears the Minimized bit + asserts Active in
            # one shot; QApplication.alert flashes the taskbar as a fallback
            # when Windows still refuses focus transfer.
            top.setWindowState(
                (top.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            top.show()
            top.raise_()
            top.activateWindow()
            QApplication.alert(top)
        self.pick_status.setText(f"(또는 단축키 {HOTKEY_LABEL})")
        self.pick_status.setStyleSheet("QLabel { color: #666; }")
        self.click_pick_btn.setEnabled(self.window_radio.isChecked())

    def _warn_on_top(self, text: str) -> None:
        """Show a warning that surfaces above other windows.

        Used after the click-picker path because Trailbox often can't take
        foreground from the freshly-clicked target app, and a normal
        QMessageBox would open behind that app (or behind a still-minimized
        Trailbox) — the user would perceive the click as a no-op.
        """
        top = self.window() or self
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            "Trailbox",
            text,
            QMessageBox.StandardButton.Ok,
            top,
        )
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "대상 실행 파일 선택", "", "실행 파일 (*.exe);;모든 파일 (*.*)"
        )
        if path:
            self.exe_edit.setText(path)

    def _browse_log_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "로그 폴더 선택", "")
        if path:
            self.log_edit.setText(path)
            # editingFinished only fires on focus loss; trigger detection now.
            self._on_log_dir_changed()

    def _add_extra_log_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "추가 로그 폴더 선택", "")
        if not path:
            return
        # Dedupe against the primary field + already-added entries (case
        # insensitive on Windows). Silent no-op if duplicate — the user
        # wouldn't see a difference between "added" and "already there".
        existing = {self.log_dir().lower()} | {p.lower() for p in self.extra_log_dirs()}
        if path.lower() in existing:
            return
        self.extra_log_list.addItem(path)

    def _remove_extra_log_dir(self) -> None:
        for item in self.extra_log_list.selectedItems():
            self.extra_log_list.takeItem(self.extra_log_list.row(item))

    def _on_window_changed(self, _index: int = -1) -> None:
        """Auto-fill exe and (asynchronously) log_dir from the selected window."""
        info = self._selected_window()
        if info is None:
            return
        if info.exe_path and not self.exe_edit.text().strip():
            self.exe_edit.setText(info.exe_path)
        # If the user already typed a log folder, don't override.
        if self.log_edit.text().strip():
            return
        # Skip if another log-dir scan is already running.
        if self._logdir_thread is not None and self._logdir_thread.isRunning():
            return
        worker = _DetectLogDirWorker(info.pid)
        worker.found.connect(self._on_log_dir_for_pid_found)
        worker.finished.connect(worker.deleteLater)
        self._logdir_thread = worker
        worker.start()

    def _on_log_dir_for_pid_found(self, pid: int, log_dir: str) -> None:
        self._logdir_thread = None
        if not log_dir:
            return
        # Stale-result guard: if the user has since selected a different
        # window or typed a log path, ignore.
        current = self._selected_window()
        if current is None or current.pid != pid:
            return
        if self.log_edit.text().strip():
            return
        self.log_edit.setText(log_dir)
        self.statusBar_message(f"로그 폴더 자동 감지: {log_dir}")

    def _on_log_dir_changed(self) -> None:
        """Kick off async scan to find a window whose process writes here."""
        log_dir = self.log_dir()
        if not log_dir or not Path(log_dir).is_dir():
            return
        if self._detect_thread is not None and self._detect_thread.isRunning():
            return
        self.detect_btn.setEnabled(False)
        self.detect_btn.setText("🔍 검색 중…")
        worker = _DetectWindowWorker(Path(log_dir))
        worker.found.connect(self._on_detect_found)
        worker.finished.connect(worker.deleteLater)
        self._detect_thread = worker
        worker.start()

    def _on_detect_found(self, pids: list[int]) -> None:
        self._detect_thread = None
        self.detect_btn.setEnabled(True)
        self.detect_btn.setText("🔍 창 찾기")
        if not pids:
            self.statusBar_message("이 폴더에 쓰는 창을 찾지 못했습니다.")
            return
        # Refresh first so newly-launched apps are included.
        self.refresh_window_list()
        target_info: WindowInfo | None = None
        for pid in pids:
            for i in range(self.window_combo.count()):
                info: WindowInfo = self.window_combo.itemData(i)
                if info.pid == pid:
                    target_info = info
                    break
            if target_info is not None:
                break
        if target_info is None:
            self.statusBar_message(
                "매칭 프로세스는 찾았으나 화면에 보이는 창이 없습니다."
            )
            return
        self.window_radio.setChecked(True)
        self.select_hwnd(target_info.hwnd)
        self.statusBar_message(
            f"자동 선택: {target_info.process_name} ({target_info.title})"
        )

    def statusBar_message(self, msg: str, timeout: int = 5000) -> None:
        top = self.window()
        if top is not None and hasattr(top, "statusBar"):
            top.statusBar().showMessage(msg, timeout)

    def _launch_app(self) -> None:
        exe = self.exe_path()
        if not exe:
            QMessageBox.warning(self, "Trailbox", "실행 파일 경로를 입력하세요.")
            return
        exe_path = Path(exe)
        if not exe_path.is_file():
            QMessageBox.warning(self, "Trailbox", f"실행 파일을 찾을 수 없습니다:\n{exe}")
            return

        try:
            proc = subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))
        except OSError as e:
            QMessageBox.critical(self, "Trailbox", f"앱 실행 실패:\n{e}")
            return

        self._launched_process = proc
        self.app_launched.emit(proc.pid, str(exe_path))
        # Refresh window list so the just-launched app appears in the picker.
        self.refresh_window_list()
