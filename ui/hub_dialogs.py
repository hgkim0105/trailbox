"""Hub settings + upload-progress dialogs.

Kept out of session_picker.py so the picker stays generic. Both dialogs are
modal and self-contained — the picker just calls ``open_hub_settings`` /
``upload_session_to_hub`` and gets a boolean result.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication
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


def _ensure_client(parent: QWidget | None) -> HubClient | None:
    """Return a configured HubClient, walking the user through settings if needed."""
    settings = hub_config.load()
    if not settings.configured:
        QMessageBox.information(
            parent, "Hub 설정 필요", "Hub URL 이 설정되어 있지 않습니다. 먼저 설정하세요."
        )
        if not open_hub_settings(parent):
            return None
        settings = hub_config.load()
        if not settings.configured:
            return None
    return HubClient(base_url=settings.url, token=settings.token, timeout=30.0)


def upload_session_to_hub(session_dir: Path, parent: QWidget | None = None) -> bool:
    """Upload a session dir to the configured Hub. Blocks on a modal progress.

    Returns True on success. If the Hub isn't configured, prompts the settings
    dialog first; if the user cancels that, returns False.
    """
    client = _ensure_client(parent)
    if client is None:
        return False

    session_id = Path(session_dir).name
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


# ---- Share-link creation ---------------------------------------------------


def _show_share_url(url: str, parent: QWidget | None) -> None:
    """Modal showing the URL with a one-click 'copy to clipboard' button."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("공유 링크 생성됨")
    dlg.resize(520, 0)

    label = QLabel("아래 URL 을 공유하세요 (브라우저에서 바로 열림):", dlg)
    edit = QLineEdit(url, dlg)
    edit.setReadOnly(True)
    edit.selectAll()

    copy_btn = QPushButton("클립보드에 복사", dlg)
    def _copy() -> None:
        QGuiApplication.clipboard().setText(url)
        copy_btn.setText("복사됨!")
    copy_btn.clicked.connect(_copy)

    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.rejected.connect(dlg.reject)
    close.accepted.connect(dlg.accept)

    root = QVBoxLayout(dlg)
    root.addWidget(label)
    root.addWidget(edit)
    row = QHBoxLayout()
    row.addWidget(copy_btn)
    row.addStretch(1)
    root.addLayout(row)
    root.addWidget(close)

    # Pre-copy to clipboard so the user can paste immediately even without clicking.
    QGuiApplication.clipboard().setText(url)
    copy_btn.setText("복사됨!  (다시 복사)")
    dlg.exec()


def create_share_for_session(session_dir: Path, parent: QWidget | None = None) -> bool:
    """Create a share link for the given session.

    If the session isn't on the Hub yet, prompts to upload first.
    Returns True if a link was generated and shown.
    """
    client = _ensure_client(parent)
    if client is None:
        return False

    session_id = Path(session_dir).name

    def _try_share() -> dict | None:
        try:
            return client.create_share(session_id)
        except HubError as e:
            if e.status_code == 404:
                return None
            QMessageBox.critical(parent, "공유 링크 실패", str(e))
            raise

    try:
        info = _try_share()
    except HubError:
        return False

    if info is None:
        ans = QMessageBox.question(
            parent,
            "허브에 없음",
            "이 세션은 아직 허브에 업로드되어 있지 않습니다.\n지금 업로드한 뒤 공유 링크를 만들까요?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return False
        if not upload_session_to_hub(session_dir, parent):
            return False
        try:
            info = client.create_share(session_id)
        except HubError as e:
            QMessageBox.critical(parent, "공유 링크 실패", str(e))
            return False

    _show_share_url(info["url"], parent)
    return True
