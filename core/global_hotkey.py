"""Tiny reusable wrapper around ``pynput.keyboard.GlobalHotKeys``.

Emits a Qt signal when the hotkey fires, so handlers run on the main UI
thread automatically (PyQt's queued connection across threads). pynput
swallows the keystroke when the listener is active, so the hotkey doesn't
bleed into focused games / apps.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard


class GlobalHotkey(QObject):
    """Listen for a single global hotkey; emit ``triggered`` when fired."""

    triggered = pyqtSignal()

    def __init__(self, hotkey: str = "<ctrl>+<alt>+r") -> None:
        super().__init__()
        self.hotkey = hotkey
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.GlobalHotKeys({self.hotkey: self._fire})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._listener = None

    def _fire(self) -> None:
        # Called on pynput's listener thread. Qt routes signals back to the
        # connected slot's thread (the main UI thread for our callers).
        self.triggered.emit()
