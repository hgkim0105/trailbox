"""Modal dialog that lists all sessions in ``output/`` and lets the user pick one."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class _NumericItem(QTableWidgetItem):
    """Cell that sorts by a numeric key but displays a formatted string."""

    def __init__(self, sort_value: float, display: str) -> None:
        super().__init__(display)
        self._sort_value = float(sort_value)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        if isinstance(other, _NumericItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


class SessionPickerDialog(QDialog):
    """Pick a session by reading meta from each ``output/<sid>/session_meta.json``."""

    def __init__(self, output_root: Path, parent=None) -> None:
        super().__init__(parent)
        self.output_root = Path(output_root)
        self.setWindowTitle("Trailbox — 세션 선택")
        self.resize(860, 520)
        self._build_ui()
        self.refresh()

    # ---- Public API -------------------------------------------------------

    def selected_session(self) -> Path | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        path = item.data(Qt.ItemDataRole.UserRole)
        return Path(path) if path else None

    def refresh(self) -> None:
        sessions: list[Path] = []
        if self.output_root.is_dir():
            sessions = [p for p in self.output_root.iterdir() if p.is_dir()]

        # Disable sorting while we populate; re-enable after.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            meta = self._load_meta(session)
            duration = meta.get("duration_seconds")
            duration_disp = f"{duration:.1f}s" if isinstance(duration, (int, float)) else "?"
            started = (meta.get("started_at") or "")[:19].replace("T", " ")
            screen_frames = int(meta.get("screen_frames") or 0)
            log_lines = int(meta.get("log_lines") or 0)
            input_events = int(meta.get("input_events") or 0)

            sid_item = QTableWidgetItem(session.name)
            sid_item.setData(Qt.ItemDataRole.UserRole, str(session))
            started_item = QTableWidgetItem(started)
            duration_item = _NumericItem(duration or 0.0, duration_disp)
            frames_item = _NumericItem(screen_frames, str(screen_frames))
            logs_item = _NumericItem(log_lines, str(log_lines))
            inputs_item = _NumericItem(input_events, str(input_events))

            for col, item in enumerate(
                [sid_item, started_item, duration_item, frames_item, logs_item, inputs_item]
            ):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)

        self.table.setSortingEnabled(True)
        # Default sort: newest first by 시작 시각 (column 1, descending).
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        self._apply_filter()
        self.empty_label.setVisible(self.table.rowCount() == 0)

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("session_id 검색…")
        self.search.textChanged.connect(self._apply_filter)
        top.addWidget(self.search, 1)
        refresh_btn = QPushButton("새로고침", self)
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)
        hub_settings_btn = QPushButton("허브 설정", self)
        hub_settings_btn.clicked.connect(self._on_hub_settings)
        top.addWidget(hub_settings_btn)
        root.addLayout(top)

        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["세션 ID", "시작", "길이", "프레임", "로그", "입력"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.accept())
        root.addWidget(self.table, 1)

        self.empty_label = QPushButton("저장된 세션이 없습니다", self)
        self.empty_label.setEnabled(False)
        self.empty_label.setFlat(True)
        root.addWidget(self.empty_label)

        btn_row = QHBoxLayout()
        self.upload_btn = QPushButton("허브 업로드", self)
        self.upload_btn.setEnabled(False)
        self.upload_btn.clicked.connect(self._on_upload_to_hub)
        btn_row.addWidget(self.upload_btn)
        btn_row.addStretch(1)
        self.open_btn = QPushButton("뷰어 열기", self)
        self.open_btn.setEnabled(False)
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.open_btn)
        cancel_btn = QPushButton("취소", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _load_meta(self, session_dir: Path) -> dict:
        meta_path = session_dir / "session_meta.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

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
        has_row = self.table.currentRow() >= 0
        self.open_btn.setEnabled(has_row)
        self.upload_btn.setEnabled(has_row)

    def _on_hub_settings(self) -> None:
        from ui.hub_dialogs import open_hub_settings
        open_hub_settings(self)

    def _on_upload_to_hub(self) -> None:
        session = self.selected_session()
        if session is None:
            return
        from ui.hub_dialogs import upload_session_to_hub
        upload_session_to_hub(session, self)
