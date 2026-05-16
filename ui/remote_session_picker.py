"""Browse + download sessions from a Trailbox Hub.

Async list fetch + async download, both via QThread workers so the dialog
never blocks the UI loop. Downloads land in the caller-provided ``out_dir``
(typically the local ``output/`` root) so they show up in the regular
SessionPicker afterwards.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import hub_config
from core.hub_client import HubClient, HubError


# ---- Workers ---------------------------------------------------------------


class _ListWorker(QThread):
    ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, client: HubClient) -> None:
        super().__init__()
        self._client = client

    def run(self) -> None:
        try:
            sessions = self._client.list_sessions()
            self.ok.emit(sessions)
        except HubError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class _DownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    ok = pyqtSignal(str)        # absolute path to downloaded session dir
    failed = pyqtSignal(str)

    def __init__(self, client: HubClient, session_id: str, out_dir: Path) -> None:
        super().__init__()
        self._client = client
        self._sid = session_id
        self._out = out_dir

    def run(self) -> None:
        try:
            path = self._client.download_session(
                self._sid,
                self._out,
                progress=lambda d, t: self.progress.emit(d, t),
            )
            self.ok.emit(str(path))
        except HubError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


# ---- Download progress modal ----------------------------------------------


class _DownloadProgressDialog(QDialog):
    def __init__(self, session_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trailbox Hub — 다운로드")
        self.setModal(True)
        self.resize(420, 110)
        self._path: str | None = None
        self.label = QLabel(f"다운로드 중…\n{session_id}", self)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)  # indeterminate until first tick

        root = QVBoxLayout(self)
        root.addWidget(self.label)
        root.addWidget(self.bar)

    def on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.label.setText(
                f"다운로드 중… {done / (1024*1024):.1f} / {total / (1024*1024):.1f} MB"
            )

    def on_done(self, path: str) -> None:
        self._path = path
        self.accept()

    def on_failed(self, msg: str) -> None:
        QMessageBox.critical(self, "다운로드 실패", msg)
        self.reject()

    @property
    def downloaded_path(self) -> str | None:
        return self._path


# ---- Picker dialog --------------------------------------------------------


class _SizeItem(QTableWidgetItem):
    def __init__(self, size_bytes: int) -> None:
        mb = size_bytes / (1024 * 1024)
        super().__init__(f"{mb:.1f} MB")
        self._sort = size_bytes
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        if isinstance(other, _SizeItem):
            return self._sort < other._sort
        return super().__lt__(other)


class RemoteSessionPickerDialog(QDialog):
    """List Hub sessions; downloads land in ``out_dir``.

    Result: ``downloaded_path`` carries the absolute path of the most recently
    downloaded session (or None if the dialog was cancelled / nothing pulled).
    """

    def __init__(self, out_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trailbox Hub — 원격 세션")
        self.resize(900, 540)
        self._out_dir = Path(out_dir)
        self._downloaded_path: str | None = None
        self._client: HubClient | None = None
        self._list_worker: _ListWorker | None = None
        self._build_ui()
        self._reload()

    # ---- Public ----------------------------------------------------------

    @property
    def downloaded_path(self) -> str | None:
        return self._downloaded_path

    # ---- UI --------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("session_id 검색…")
        self.search.textChanged.connect(self._apply_filter)
        top.addWidget(self.search, 1)
        refresh = QPushButton("새로고침", self)
        refresh.clicked.connect(self._reload)
        top.addWidget(refresh)
        root.addLayout(top)

        self.status = QLabel("", self)
        self.status.setStyleSheet("QLabel { color: #666; }")
        root.addWidget(self.status)

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["세션 ID", "시작", "길이", "크기", "뷰어"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(lambda _it: self._on_download_and_open())
        root.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.download_btn = QPushButton("다운로드", self)
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download)
        btns.addWidget(self.download_btn)
        self.open_btn = QPushButton("다운로드 + 뷰어 열기", self)
        self.open_btn.setEnabled(False)
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self._on_download_and_open)
        btns.addWidget(self.open_btn)
        close_btn = QPushButton("닫기", self)
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        root.addLayout(btns)

    # ---- Network ---------------------------------------------------------

    def _ensure_client(self) -> HubClient | None:
        if self._client is not None:
            return self._client
        settings = hub_config.load()
        if not settings.configured:
            QMessageBox.information(
                self, "Hub 설정 필요", "Hub URL 이 설정되어 있지 않습니다."
            )
            return None
        self._client = HubClient(
            base_url=settings.url, token=settings.token, timeout=30.0
        )
        return self._client

    def _reload(self) -> None:
        client = self._ensure_client()
        if client is None:
            self.reject()
            return
        self.status.setText("목록 가져오는 중…")
        self.table.setRowCount(0)
        self._list_worker = _ListWorker(client)
        self._list_worker.ok.connect(self._on_list_ok)
        self._list_worker.failed.connect(self._on_list_failed)
        self._list_worker.start()

    def _on_list_ok(self, sessions: list[dict[str, Any]]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(sessions))
        for row, s in enumerate(sessions):
            sid = s.get("session_id", "")
            started = (s.get("started_at") or "")[:19].replace("T", " ")
            dur = s.get("duration_seconds")
            dur_disp = f"{dur:.1f}s" if isinstance(dur, (int, float)) else "?"
            size = int(s.get("size_bytes") or 0)
            viewer = "✓" if s.get("has_viewer") else ""

            sid_item = QTableWidgetItem(sid)
            sid_item.setData(Qt.ItemDataRole.UserRole, sid)
            started_item = QTableWidgetItem(started)
            dur_item = QTableWidgetItem(dur_disp)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            size_item = _SizeItem(size)
            viewer_item = QTableWidgetItem(viewer)
            viewer_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            for col, it in enumerate(
                [sid_item, started_item, dur_item, size_item, viewer_item]
            ):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, it)

        self.table.setSortingEnabled(True)
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        self._apply_filter()
        self.status.setText(f"{len(sessions)}개 세션")

    def _on_list_failed(self, msg: str) -> None:
        self.status.setText("")
        QMessageBox.critical(self, "목록 실패", msg)

    # ---- Actions ---------------------------------------------------------

    def _selected_session_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def _on_download(self) -> bool:
        sid = self._selected_session_id()
        if sid is None:
            return False
        client = self._ensure_client()
        if client is None:
            return False

        dlg = _DownloadProgressDialog(sid, self)
        worker = _DownloadWorker(client, sid, self._out_dir)
        worker.progress.connect(dlg.on_progress)
        worker.ok.connect(dlg.on_done)
        worker.failed.connect(dlg.on_failed)
        worker.start()
        try:
            dlg.exec()
        finally:
            worker.wait(2000)
        if dlg.downloaded_path:
            self._downloaded_path = dlg.downloaded_path
            return True
        return False

    def _on_download_and_open(self) -> None:
        if self._on_download():
            self.accept()

    def _apply_filter(self) -> None:
        q = self.search.text().strip().lower()
        for row in range(self.table.rowCount()):
            if not q:
                self.table.setRowHidden(row, False)
                continue
            sid_item = self.table.item(row, 0)
            visible = bool(sid_item) and q in sid_item.text().lower()
            self.table.setRowHidden(row, not visible)

    def _on_selection_changed(self) -> None:
        has = self.table.currentRow() >= 0
        self.download_btn.setEnabled(has)
        self.open_btn.setEnabled(has)
