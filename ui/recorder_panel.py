"""Recorder panel: start/stop recording and show current session status."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_SETTINGS_ORG = "Trailbox"
_SETTINGS_APP = "Trailbox"
_AUTO_UPLOAD_KEY = "recorder/auto_upload_on_stop"


class RecorderPanel(QWidget):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    view_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.set_recording(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        group = QGroupBox("세션 녹화", self)
        layout = QVBoxLayout(group)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("녹화 시작", self)
        self.start_btn.clicked.connect(self.start_requested.emit)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("녹화 종료", self)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

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

    def set_recording(self, recording: bool) -> None:
        self.start_btn.setEnabled(not recording)
        self.stop_btn.setEnabled(recording)
        if recording:
            self.status_label.setText("● 녹화 중")
            self.status_label.setStyleSheet(
                "QLabel { padding: 8px; font-weight: bold; color: #c0392b; }"
            )
        else:
            self.status_label.setText("대기 중")
            self.status_label.setStyleSheet(
                "QLabel { padding: 8px; font-weight: bold; color: #2c3e50; }"
            )

    def set_session_id(self, session_id: str | None) -> None:
        self.session_label.setText(f"세션 ID: {session_id}" if session_id else "")
