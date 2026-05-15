"""Launcher panel: pick target app, log folder, capture target, and launch."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from core.process_detector import find_log_dir_for_pid, find_pids_for_log_dir
from core.screen_recorder import CaptureTarget, MonitorTarget, WindowTarget
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


HOTKEY_LABEL = "Ctrl+Shift+P"
FPS_OPTIONS = [10, 15, 24, 30, 60]
DEFAULT_FPS = 15


class LauncherPanel(QWidget):
    app_launched = pyqtSignal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._launched_process: subprocess.Popen | None = None
        self._click_picker: ClickPicker | None = None
        self._hotkey_picker: HotkeyPicker | None = None
        self._detect_thread: _DetectWindowWorker | None = None
        self._logdir_thread: _DetectLogDirWorker | None = None
        self._build_ui()
        self.refresh_window_list()
        self._start_hotkey_picker()

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
        self.monitor_radio.setChecked(True)
        self.monitor_radio.toggled.connect(self._update_target_controls)
        radio_row.addWidget(self.monitor_radio)
        radio_row.addWidget(self.window_radio)
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
        self.input_check = QCheckBox("키보드/마우스 입력 기록", self)
        self.input_check.setChecked(True)
        input_row.addWidget(self.input_check)
        input_row.addStretch(1)
        cap_layout.addLayout(input_row)

        metrics_row = QHBoxLayout()
        self.metrics_check = QCheckBox("프로세스 텔레메트리 (CPU/메모리/스레드)", self)
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
        info = self._selected_window()
        if info is None:
            return None
        return WindowTarget(hwnd=info.hwnd, title=info.title)

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
        self.window_combo.setEnabled(is_window)
        self.refresh_btn.setEnabled(is_window)
        self.click_pick_btn.setEnabled(is_window)

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
            QMessageBox.warning(self, "Trailbox", "선택한 창을 캡처 대상으로 등록할 수 없습니다.")

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
            top.showNormal()
            top.activateWindow()
            top.raise_()
        self.pick_status.setText(f"(또는 단축키 {HOTKEY_LABEL})")
        self.pick_status.setStyleSheet("QLabel { color: #666; }")
        self.click_pick_btn.setEnabled(self.window_radio.isChecked())

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
