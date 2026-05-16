"""Hub settings + upload-progress dialogs.

Kept out of session_picker.py so the picker stays generic. Both dialogs are
modal and self-contained — the picker just calls ``open_hub_settings`` /
``upload_session_to_hub`` and gets a boolean result.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import hub_config
from core.hub_client import HubClient, HubError


# ---- Settings dialog -------------------------------------------------------


class HubSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trailbox Hub — 설정")
        self.resize(440, 0)
        current = hub_config.load()

        form = QFormLayout()
        self.url_edit = QLineEdit(current.url, self)
        self.url_edit.setPlaceholderText("http://hub.local:8765")
        self.token_edit = QLineEdit(current.token, self)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("X-Trailbox-Token (서버와 동일)")
        form.addRow("Hub URL", self.url_edit)
        form.addRow("API Token", self.token_edit)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("연결 테스트", self)
        self.test_btn.clicked.connect(self._on_test)
        self.test_label = QLabel("", self)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_label, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(test_row)
        root.addWidget(buttons)

    def _current_client(self) -> HubClient | None:
        url = self.url_edit.text().strip()
        if not url:
            return None
        return HubClient(base_url=url, token=self.token_edit.text().strip(), timeout=5.0)

    def _on_test(self) -> None:
        client = self._current_client()
        if client is None:
            self.test_label.setText("Hub URL 을 먼저 입력하세요")
            return
        self.test_label.setText("연결 중…")
        self.test_btn.setEnabled(False)
        try:
            info = client.healthz()
            auth = "on" if info.get("auth_enabled") else "OFF"
            self.test_label.setText(f"OK · data_root={info.get('data_root')} · auth={auth}")
        except HubError as e:
            self.test_label.setText(f"실패: {e}")
        except Exception as e:  # noqa: BLE001 - surface any error to UI
            self.test_label.setText(f"실패: {e}")
        finally:
            self.test_btn.setEnabled(True)

    def _on_accept(self) -> None:
        hub_config.save(
            hub_config.HubSettings(
                url=self.url_edit.text().strip(),
                token=self.token_edit.text().strip(),
            )
        )
        self.accept()


def open_hub_settings(parent: QWidget | None = None) -> bool:
    dlg = HubSettingsDialog(parent)
    return dlg.exec() == QDialog.DialogCode.Accepted


# ---- Upload worker + progress dialog --------------------------------------


class _UploadWorker(QThread):
    progress = pyqtSignal(int, int)  # (sent_bytes, total_bytes)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, client: HubClient, session_id: str, session_dir: Path) -> None:
        super().__init__()
        self._client = client
        self._session_id = session_id
        self._session_dir = session_dir

    def run(self) -> None:
        try:
            summary = self._client.upload_session(
                self._session_id,
                self._session_dir,
                progress=lambda done, total: self.progress.emit(done, total),
            )
            self.finished_ok.emit(summary)
        except HubError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class _UploadProgressDialog(QDialog):
    def __init__(self, session_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trailbox Hub — 업로드")
        self.setModal(True)
        self.resize(420, 110)
        self._success = False

        self.label = QLabel(f"세션 압축 및 업로드 중…\n{session_id}", self)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)  # indeterminate until first progress tick
        self.bar.setValue(0)

        root = QVBoxLayout(self)
        root.addWidget(self.label)
        root.addWidget(self.bar)

    def on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            mb_done = done / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.label.setText(f"업로드 중… {mb_done:.1f} / {mb_total:.1f} MB")

    def on_done(self, _summary: dict) -> None:
        self._success = True
        self.accept()

    def on_failed(self, msg: str) -> None:
        self._success = False
        QMessageBox.critical(self, "업로드 실패", msg)
        self.reject()

    @property
    def success(self) -> bool:
        return self._success


def upload_session_to_hub(session_dir: Path, parent: QWidget | None = None) -> bool:
    """Upload a session dir to the configured Hub. Blocks on a modal progress.

    Returns True on success. If the Hub isn't configured, prompts the settings
    dialog first; if the user cancels that, returns False.
    """
    settings = hub_config.load()
    if not settings.configured:
        QMessageBox.information(
            parent, "Hub 설정 필요", "Hub URL 이 설정되어 있지 않습니다. 먼저 설정하세요."
        )
        if not open_hub_settings(parent):
            return False
        settings = hub_config.load()
        if not settings.configured:
            return False

    session_id = Path(session_dir).name
    client = HubClient(base_url=settings.url, token=settings.token, timeout=30.0)

    dlg = _UploadProgressDialog(session_id, parent)
    worker = _UploadWorker(client, session_id, Path(session_dir))
    worker.progress.connect(dlg.on_progress)
    worker.finished_ok.connect(dlg.on_done)
    worker.failed.connect(dlg.on_failed)
    worker.start()
    try:
        dlg.exec()
    finally:
        worker.wait(2000)
    return dlg.success
