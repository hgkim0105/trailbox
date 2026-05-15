"""Always-on-top, click-through "● REC" overlay shown during recording.

Visible over Windowed and Borderless games (most modern titles); Fullscreen
Exclusive games bypass the DWM compositor via DirectX swap chain present
and will hide it — that's documented as a known limitation, with Borderless
mode as the workaround.

The widget uses Qt's ``WindowTransparentForInput`` so mouse/keyboard events
fall through to whatever is underneath; combined with the ``Tool`` window
type it stays out of the taskbar and alt-tab list.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


class RecordingOverlay(QWidget):
    def __init__(self, stop_hotkey_label: str = "Ctrl+Alt+R") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._start_perf = time.perf_counter()
        self._timer: QTimer | None = None

        self._build_ui(stop_hotkey_label)
        self._position_top_right()

    # ---- Public API -------------------------------------------------------

    def begin(self) -> None:
        """Reset the elapsed counter and start updating the label."""
        self._start_perf = time.perf_counter()
        self._update_elapsed()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._update_elapsed)
        self._timer.start()
        self.show()

    def end(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.hide()

    # ---- Layout -----------------------------------------------------------

    def _build_ui(self, stop_hotkey_label: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self._dot = QLabel("●", self)
        self._dot.setStyleSheet(
            "color: #ff4d4d; font-size: 16px; font-weight: bold;"
        )
        layout.addWidget(self._dot)

        self._time = QLabel("00:00", self)
        self._time.setStyleSheet(
            "color: #ffffff; font-family: 'Consolas', 'Courier New', monospace; "
            "font-size: 14px; font-weight: bold;"
        )
        layout.addWidget(self._time)

        self._hint = QLabel(f"·  {stop_hotkey_label} 정지", self)
        self._hint.setStyleSheet(
            "color: #cccccc; font-size: 11px;"
        )
        layout.addWidget(self._hint)

        # Container background — drawn via a styled container widget would be
        # cleanest, but a stylesheet on self with WA_TranslucentBackground
        # composites the rgba background onto whatever is underneath.
        self.setStyleSheet(
            "RecordingOverlay { background: rgba(0, 0, 0, 200);"
            " border-radius: 6px; }"
        )
        self.adjustSize()

    def _position_top_right(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        margin = 16
        # Use sizeHint so the position is right even before show().
        size = self.sizeHint()
        x = geom.right() - size.width() - margin
        y = geom.top() + margin
        self.move(x, y)

    # ---- Timer ------------------------------------------------------------

    def _update_elapsed(self) -> None:
        elapsed = int(time.perf_counter() - self._start_perf)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        text = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self._time.setText(text)
