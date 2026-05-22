"""Hub settings + upload-progress dialogs.

Kept out of session_picker.py so the picker stays generic. Both dialogs are
modal and self-contained — the picker just calls ``open_hub_settings`` /
``upload_session_to_hub`` and gets a boolean result.
"""
from __future__ import annotations

from pathlib import Path

import socket

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import hub_config
from core.hub_client import HubClient, HubError


# ---- Settings dialog -------------------------------------------------------


def _default_token_label() -> str:
    name = ""
    try:
        name = socket.gethostname() or ""
    except OSError:
        pass
    return f"trailbox-{name}" if name else "trailbox-client"


class _PasswordChangeDialog(QDialog):
    """Modal shown when login returns ``must_change_password=True``.

    The user types the current (temp) password again plus a new one. On
    success we call ``POST /api/auth/password`` and the parent flow
    continues (token issue, save, close).

    We deliberately re-prompt for the current password rather than
    reusing the value typed at login. It both confirms intent and protects
    against the case where the parent widget cleared the field between
    calls.
    """

    def __init__(
        self,
        client: HubClient,
        cookies,
        username: str,
        prefilled_current: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("비밀번호 변경 필요")
        self.setModal(True)
        self.resize(420, 0)
        self._client = client
        self._cookies = cookies
        self._username = username

        intro = QLabel(
            "관리자가 비밀번호를 재설정했습니다.\n"
            "계속 사용하려면 새 비밀번호를 설정해야 합니다.",
            self,
        )
        intro.setWordWrap(True)

        form = QFormLayout()
        self.current_edit = QLineEdit(prefilled_current, self)
        self.current_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_edit = QLineEdit(self)
        self.new_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new2_edit = QLineEdit(self)
        self.new2_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("현재 (임시) 비밀번호", self.current_edit)
        form.addRow("새 비밀번호 (최소 8자)", self.new_edit)
        form.addRow("새 비밀번호 (확인)", self.new2_edit)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(intro)
        root.addLayout(form)
        root.addWidget(self.status_label)
        root.addWidget(buttons)

    def _on_accept(self) -> None:
        cur = self.current_edit.text()
        new = self.new_edit.text()
        new2 = self.new2_edit.text()
        if not cur or not new:
            self.status_label.setText("모든 항목을 입력하세요")
            return
        if new != new2:
            self.status_label.setText("새 비밀번호 확인이 일치하지 않습니다")
            return
        self.status_label.setText("변경 중…")
        try:
            # The /api/auth/password endpoint takes cookies (we logged in
            # but never issued a token).
            with self._client._client() as c:
                # Inject cookies into the per-call client. HubClient
                # exposes a private _client() factory; we mirror what
                # issue_token() / me() do.
                for k, v in (self._cookies or {}).items():
                    c.cookies.set(k, v)
                r = c.post(
                    "/api/auth/password",
                    json={"current_password": cur, "new_password": new},
                )
                if r.status_code != 200:
                    try:
                        detail = r.json().get("detail", r.text)
                    except Exception:  # noqa: BLE001
                        detail = r.text
                    self.status_label.setText(f"실패: {detail}")
                    return
        except Exception as e:  # noqa: BLE001
            self.status_label.setText(f"오류: {e}")
            return
        self.accept()


class HubSettingsDialog(QDialog):
    """Three-tab dialog: Login / Register / Advanced (manual token).

    Login and Register both end the same way: the client receives a per-user
    API token (via /api/auth/tokens) and persists it. Advanced exists for
    operators using the legacy service-token compatibility path.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trailbox Hub — 설정")
        self.resize(480, 0)
        current = hub_config.load()

        # URL is shared across all tabs.
        self.url_edit = QLineEdit(current.url, self)
        self.url_edit.setPlaceholderText("http://hub.local:8765")
        top = QFormLayout()
        top.addRow("Hub URL", self.url_edit)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_login_tab(current), "로그인")
        self.tabs.addTab(self._build_register_tab(), "회원가입")
        self.tabs.addTab(self._build_advanced_tab(current), "고급 (수동 토큰)")

        # Open on whichever tab makes sense based on current state.
        if current.token:
            self.tabs.setCurrentIndex(0)  # already logged in — show Login (with username pre-filled)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.tabs)
        root.addWidget(self.status_label)
        root.addWidget(close_btn)

        # Poll timer used by the post-register "waiting for approval" flow.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._poll_pending)
        self._pending_creds: tuple[str, str] | None = None

    # ---- helpers ----------------------------------------------------------

    def _current_url(self) -> str:
        return self.url_edit.text().strip()

    def _client(self, token: str = "") -> HubClient | None:
        url = self._current_url()
        if not url:
            return None
        return HubClient(base_url=url, token=token, timeout=10.0)

    def _set_status(self, text: str, ok: bool | None = None) -> None:
        color = ""
        if ok is True:
            color = "color: #1b7a1b;"
        elif ok is False:
            color = "color: #b00020;"
        self.status_label.setStyleSheet(color)
        self.status_label.setText(text)

    def _save_and_close(self, token: str, username: str) -> None:
        hub_config.save(
            hub_config.HubSettings(
                url=self._current_url(),
                token=token,
                username=username,
            )
        )
        self._poll_timer.stop()
        self.accept()

    # ---- Login tab --------------------------------------------------------

    def _build_login_tab(self, current: hub_config.HubSettings) -> QWidget:
        page = QWidget(self)
        form = QFormLayout()
        self.login_user = QLineEdit(current.username, page)
        self.login_pass = QLineEdit(page)
        self.login_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", self.login_user)
        form.addRow("Password", self.login_pass)

        self.login_btn = QPushButton("로그인 + 토큰 발급", page)
        self.login_btn.clicked.connect(self._on_login)

        root = QVBoxLayout(page)
        root.addLayout(form)
        root.addWidget(self.login_btn)
        root.addStretch(1)
        return page

    def _on_login(self) -> None:
        client = self._client()
        if client is None:
            self._set_status("Hub URL 을 먼저 입력하세요", ok=False)
            return
        username = self.login_user.text().strip()
        password = self.login_pass.text()
        if not username or not password:
            self._set_status("Username/Password 모두 입력하세요", ok=False)
            return
        self.login_btn.setEnabled(False)
        self._set_status("로그인 중…")
        try:
            info, cookies = client.login(username, password)
        except HubError as e:
            self._set_status(f"로그인 실패: {e}", ok=False)
            self.login_btn.setEnabled(True)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"오류: {e}", ok=False)
            self.login_btn.setEnabled(True)
            return

        # If admin reset this account, the server flags must_change_password
        # and blocks /api/auth/tokens until the user picks a new one. Pop
        # the change dialog inline before continuing — otherwise issue_token
        # would 403 with no feedback the user can act on.
        user_info = info.get("user", {}) if isinstance(info, dict) else {}
        if user_info.get("must_change_password"):
            self._set_status("비밀번호 변경 필요 — 다이얼로그를 따라 진행하세요")
            dlg = _PasswordChangeDialog(
                client, cookies, username, prefilled_current=password, parent=self
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._set_status("비밀번호 변경 취소됨", ok=False)
                self.login_btn.setEnabled(True)
                return

        try:
            tok = client.issue_token(label=_default_token_label(), cookies=cookies)
        except HubError as e:
            self._set_status(f"토큰 발급 실패: {e}", ok=False)
            self.login_btn.setEnabled(True)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"오류: {e}", ok=False)
            self.login_btn.setEnabled(True)
            return
        self.login_btn.setEnabled(True)
        self._set_status("토큰 발급 완료 — 저장 후 닫는 중…", ok=True)
        self._save_and_close(tok["token"], username)

    # ---- Register tab -----------------------------------------------------

    def _build_register_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout()
        self.reg_user = QLineEdit(page)
        self.reg_email = QLineEdit(page)
        self.reg_email.setPlaceholderText("(선택) 운영자에게 전달용")
        self.reg_pass = QLineEdit(page)
        self.reg_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.reg_pass.setPlaceholderText("최소 12자")
        form.addRow("Username", self.reg_user)
        form.addRow("Email", self.reg_email)
        form.addRow("Password", self.reg_pass)

        self.reg_btn = QPushButton("회원가입 신청", page)
        self.reg_btn.clicked.connect(self._on_register)

        self.reg_status = QLabel("", page)
        self.reg_status.setWordWrap(True)

        root = QVBoxLayout(page)
        root.addLayout(form)
        root.addWidget(self.reg_btn)
        root.addWidget(self.reg_status)
        root.addStretch(1)
        return page

    def _on_register(self) -> None:
        client = self._client()
        if client is None:
            self._set_status("Hub URL 을 먼저 입력하세요", ok=False)
            return
        username = self.reg_user.text().strip()
        password = self.reg_pass.text()
        email = self.reg_email.text().strip() or None
        if not username or not password:
            self._set_status("Username/Password 모두 입력하세요", ok=False)
            return
        self.reg_btn.setEnabled(False)
        self._set_status("가입 신청 중…")
        try:
            result = client.register(username, password, email=email)
        except HubError as e:
            self._set_status(f"가입 실패: {e}", ok=False)
            self.reg_btn.setEnabled(True)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"오류: {e}", ok=False)
            self.reg_btn.setEnabled(True)
            return

        if result.get("auto_approved") or result.get("status") == "active":
            # Auto-approve: log in immediately and finish.
            try:
                _info, cookies = client.login(username, password)
                tok = client.issue_token(label=_default_token_label(), cookies=cookies)
            except HubError as e:
                self._set_status(f"가입은 됐지만 로그인 실패: {e}", ok=False)
                self.reg_btn.setEnabled(True)
                return
            self._save_and_close(tok["token"], username)
            return

        # Pending: park here and poll until admin approves.
        self.reg_status.setText("관리자 승인 대기 중… (자동으로 새로고침)")
        self.reg_btn.setEnabled(False)
        self._pending_creds = (username, password)
        self._poll_timer.start()

    def _poll_pending(self) -> None:
        if self._pending_creds is None:
            self._poll_timer.stop()
            return
        username, password = self._pending_creds
        client = self._client()
        if client is None:
            return
        try:
            info, cookies = client.login(username, password)
        except HubError as e:
            if e.status_code == 403:
                # Still pending — keep polling.
                return
            self.reg_status.setText(f"확인 실패: {e}")
            self._poll_timer.stop()
            self.reg_btn.setEnabled(True)
            return
        except Exception as e:  # noqa: BLE001
            self.reg_status.setText(f"오류: {e}")
            return

        # Unlikely on first-time registration (admin can't reset before
        # the user even exists), but handle defensively.
        user_info = info.get("user", {}) if isinstance(info, dict) else {}
        if user_info.get("must_change_password"):
            self._poll_timer.stop()
            dlg = _PasswordChangeDialog(
                client, cookies, username, prefilled_current=password, parent=self
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self.reg_status.setText("비밀번호 변경이 취소되어 가입을 완료하지 못했습니다.")
                self.reg_btn.setEnabled(True)
                return

        try:
            tok = client.issue_token(label=_default_token_label(), cookies=cookies)
        except HubError as e:
            self.reg_status.setText(f"토큰 발급 실패: {e}")
            self._poll_timer.stop()
            self.reg_btn.setEnabled(True)
            return
        self._save_and_close(tok["token"], username)

    # ---- Advanced tab -----------------------------------------------------

    def _build_advanced_tab(self, current: hub_config.HubSettings) -> QWidget:
        page = QWidget(self)
        form = QFormLayout()
        self.adv_token = QLineEdit(current.token, page)
        self.adv_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.adv_token.setPlaceholderText("기존 토큰 또는 운영자 service-token")
        form.addRow("API Token", self.adv_token)

        self.adv_test_btn = QPushButton("연결 테스트", page)
        self.adv_test_btn.clicked.connect(self._on_adv_test)
        self.adv_save_btn = QPushButton("저장", page)
        self.adv_save_btn.clicked.connect(self._on_adv_save)
        self.adv_status = QLabel("", page)
        self.adv_status.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(self.adv_test_btn)
        row.addWidget(self.adv_save_btn)
        row.addStretch(1)

        root = QVBoxLayout(page)
        root.addLayout(form)
        root.addLayout(row)
        root.addWidget(self.adv_status)
        root.addStretch(1)
        return page

    def _on_adv_test(self) -> None:
        client = self._client(token=self.adv_token.text().strip())
        if client is None:
            self.adv_status.setText("Hub URL 을 먼저 입력하세요")
            return
        self.adv_status.setText("연결 중…")
        try:
            info = client.healthz()
            self.adv_status.setText(
                f"OK · data_root={info.get('data_root')} · admins={info.get('admin_count')}"
            )
        except HubError as e:
            self.adv_status.setText(f"실패: {e}")
        except Exception as e:  # noqa: BLE001
            self.adv_status.setText(f"실패: {e}")

    def _on_adv_save(self) -> None:
        token = self.adv_token.text().strip()
        if not self._current_url():
            self.adv_status.setText("Hub URL 을 먼저 입력하세요")
            return
        # Keep the existing username (advanced mode doesn't change identity).
        prev = hub_config.load()
        self._save_and_close(token, prev.username)


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
    return _run_upload_with_progress(client, session_dir, parent)


def auto_upload_session(session_dir: Path, parent: QWidget | None = None) -> bool:
    """Same as upload_session_to_hub but silently skips when Hub isn't configured.

    Used by the recorder's "auto-upload on stop" toggle — never want to nag
    the user mid-flow if they just haven't set up the Hub.
    """
    settings = hub_config.load()
    if not settings.configured:
        return False
    client = HubClient(base_url=settings.url, token=settings.token, timeout=30.0)
    return _run_upload_with_progress(client, session_dir, parent)


def _run_upload_with_progress(
    client: HubClient, session_dir: Path, parent: QWidget | None
) -> bool:
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
