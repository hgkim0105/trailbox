"""Recorder panel: start/stop recording and show current session status."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.lookback import (
    DEFAULT_BUFFER_SECONDS,
    MAX_BUFFER_SECONDS,
    MIN_BUFFER_SECONDS,
)

_SETTINGS_ORG = "Trailbox"
_SETTINGS_APP = "Trailbox"
_AUTO_UPLOAD_KEY = "recorder/auto_upload_on_stop"
_LOOKBACK_KEY = "recorder/lookback_enabled"
_LOOKBACK_SECONDS_KEY = "recorder/lookback_seconds"


class RecorderPanel(QWidget):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    view_requested = pyqtSignal()
    capture_requested = pyqtSignal()  # lookback: save the trailing N seconds

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(400)
        self._anim_timer.timeout.connect(self._tick_transition_anim)
        self._anim_base = ""
        self._anim_color = "#2c3e50"
        self._anim_step = 0
        self._recording = False
        self._build_ui()
        self.set_recording(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        group = QGroupBox("세션 녹화", self)
        layout = QVBoxLayout(group)

        # Lookback ("instant replay") toggle + buffer length. When enabled, the
        # start button begins *buffering* instead of recording, and a capture
        # button materializes the last N seconds on demand.
        lookback_row = QHBoxLayout()
        self.lookback_check = QCheckBox("되감기(즉시 리플레이) 모드", self)
        self.lookback_check.setToolTip(
            "켜면 «녹화 시작»이 대기/버퍼링으로 바뀝니다. 그동안 직전 N초가 항상\n"
            "메모리/디스크에 보관되고, «직전 N초 저장»(또는 단축키)을 누르는 순간\n"
            "그 구간이 하나의 세션으로 저장됩니다. 저장 후에도 버퍼링은 계속됩니다.\n"
            "데스크톱(모니터/창) 캡처에서만 동작합니다."
        )
        self.lookback_check.setChecked(self._load_lookback())
        self.lookback_check.toggled.connect(self._on_lookback_toggled)
        lookback_row.addWidget(self.lookback_check)
        lookback_row.addSpacing(8)
        lookback_row.addWidget(QLabel("버퍼:", self))
        self.lookback_spin = QSpinBox(self)
        self.lookback_spin.setRange(MIN_BUFFER_SECONDS, MAX_BUFFER_SECONDS)
        self.lookback_spin.setSingleStep(5)
        self.lookback_spin.setSuffix(" 초")
        self.lookback_spin.setValue(self._load_lookback_seconds())
        self.lookback_spin.valueChanged.connect(self._save_lookback_seconds)
        lookback_row.addWidget(self.lookback_spin)
        lookback_row.addStretch(1)
        layout.addLayout(lookback_row)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("녹화 시작", self)
        self.start_btn.clicked.connect(self.start_requested.emit)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("녹화 종료", self)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        # Capture button: only meaningful while buffering in lookback mode.
        self.capture_btn = QPushButton("💾 직전 구간 저장", self)
        self.capture_btn.clicked.connect(self.capture_requested.emit)
        self.capture_btn.setVisible(False)
        layout.addWidget(self.capture_btn)

        self.status_label = QLabel("대기 중", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("QLabel { padding: 8px; font-weight: bold; }")
        layout.addWidget(self.status_label)

        self.session_label = QLabel("", self)
        self.session_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.session_label.setStyleSheet("QLabel { color: #666; }")
        layout.addWidget(self.session_label)

        view_row = QHBoxLayout()
        view_row.addStretch(1)
        self.view_btn = QPushButton("📂 세션 뷰어 열기…", self)
        self.view_btn.setToolTip("저장된 세션 목록에서 골라 viewer.html 을 엽니다")
        self.view_btn.clicked.connect(self.view_requested.emit)
        view_row.addWidget(self.view_btn)
        view_row.addStretch(1)
        layout.addLayout(view_row)

        self.auto_upload_cb = QCheckBox("녹화 종료 시 허브 자동 업로드", self)
        self.auto_upload_cb.setToolTip(
            "켜져 있으면 세션 종료 후 곧바로 Hub 로 업로드합니다.\n"
            "Hub URL 이 미설정이면 조용히 건너뜁니다 (세션은 로컬에 정상 저장됩니다)."
        )
        self.auto_upload_cb.setChecked(self._load_auto_upload())
        self.auto_upload_cb.toggled.connect(self._save_auto_upload)
        layout.addWidget(self.auto_upload_cb)

        root.addWidget(group)
        root.addStretch(1)

    @staticmethod
    def _load_auto_upload() -> bool:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        # QSettings returns str on Windows; coerce explicitly.
        return str(s.value(_AUTO_UPLOAD_KEY, "false")).lower() in ("1", "true", "yes")

    @staticmethod
    def _save_auto_upload(checked: bool) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue(_AUTO_UPLOAD_KEY, "true" if checked else "false")
        s.sync()

    def auto_upload_enabled(self) -> bool:
        return self.auto_upload_cb.isChecked()

    # ---- Lookback settings + state ---------------------------------------

    @staticmethod
    def _load_lookback() -> bool:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        return str(s.value(_LOOKBACK_KEY, "false")).lower() in ("1", "true", "yes")

    @staticmethod
    def _load_lookback_seconds() -> int:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        try:
            val = int(s.value(_LOOKBACK_SECONDS_KEY, DEFAULT_BUFFER_SECONDS))
        except (TypeError, ValueError):
            val = DEFAULT_BUFFER_SECONDS
        return max(MIN_BUFFER_SECONDS, min(MAX_BUFFER_SECONDS, val))

    def _on_lookback_toggled(self, checked: bool) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue(_LOOKBACK_KEY, "true" if checked else "false")
        s.sync()
        self._apply_lookback_ui()

    @staticmethod
    def _save_lookback_seconds(value: int) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue(_LOOKBACK_SECONDS_KEY, int(value))
        s.sync()

    def lookback_enabled(self) -> bool:
        return self.lookback_check.isChecked()

    def lookback_buffer_seconds(self) -> int:
        return int(self.lookback_spin.value())

    def _apply_lookback_ui(self) -> None:
        """Sync button labels / capture-button visibility to the current mode."""
        lookback = self.lookback_check.isChecked()
        if lookback:
            self.start_btn.setText("⏺ 버퍼링 시작" if not self._recording else "버퍼링 중")
        else:
            self.start_btn.setText("녹화 시작")
        self.capture_btn.setVisible(lookback and self._recording)
        self.capture_btn.setEnabled(lookback and self._recording)
        # The mode + buffer length are locked while a buffering run is active.
        self.lookback_check.setEnabled(not self._recording)
        self.lookback_spin.setEnabled(not self._recording)

    def set_recording(self, recording: bool) -> None:
        self._stop_transition_anim()
        self._recording = recording
        self.start_btn.setEnabled(not recording)
        self.stop_btn.setEnabled(recording)
        lookback = self.lookback_check.isChecked()
        if recording:
            self.status_label.setText("● 버퍼링 중" if lookback else "● 녹화 중")
            self.status_label.setStyleSheet(
                "QLabel { padding: 8px; font-weight: bold; color: #c0392b; }"
            )
        else:
            self.status_label.setText("대기 중")
            self.status_label.setStyleSheet(
                "QLabel { padding: 8px; font-weight: bold; color: #2c3e50; }"
            )
        self._apply_lookback_ui()

    def set_transitioning(self, kind: str) -> None:
        # "starting" / "stopping": disable both buttons, show an animated
        # in-progress label so the user knows the click registered even
        # though the actual start/stop (esp. post-mux on stop) is slow.
        # The dot animation also keeps ticking while QTimer fires, giving
        # a heartbeat unless the event loop is fully blocked (e.g. mid-mux).
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        if kind == "starting":
            self._anim_base = "🟡 준비 중"
            self._anim_color = "#d68910"
        else:
            self._anim_base = "⏳ 마무리 중 (영상 인코딩)"
            self._anim_color = "#d68910"
        self._anim_step = 0
        self._render_transition_frame()
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _tick_transition_anim(self) -> None:
        self._anim_step = (self._anim_step + 1) % 4
        self._render_transition_frame()

    def _render_transition_frame(self) -> None:
        dots = "·" * self._anim_step
        # Pad to a fixed width so the label doesn't jitter as dots grow.
        self.status_label.setText(f"{self._anim_base}{dots:<3}")
        self.status_label.setStyleSheet(
            f"QLabel {{ padding: 8px; font-weight: bold; color: {self._anim_color}; }}"
        )

    def _stop_transition_anim(self) -> None:
        if self._anim_timer.isActive():
            self._anim_timer.stop()

    def set_session_id(self, session_id: str | None) -> None:
        self.session_label.setText(f"세션 ID: {session_id}" if session_id else "")
