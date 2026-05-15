"""Pick a target window by clicking it or pressing a global hotkey.

Both pickers use pynput listeners running on their own threads. Results are
delivered to the Qt UI via pyqtSignal, which is thread-safe across threads.
Win32 ``WindowFromPoint`` returns the deepest visible child window under the
cursor; we walk up to the top-level ancestor with ``GetAncestor(GA_ROOT)``.
"""
from __future__ import annotations

from typing import Iterable

import win32gui
from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard, mouse


GA_ROOT = 2


def top_level_hwnd_at(x: int, y: int) -> int:
    """Return the top-level HWND under screen coordinates (x, y), or 0."""
    hwnd = win32gui.WindowFromPoint((x, y))
    if not hwnd:
        return 0
    top = win32gui.GetAncestor(hwnd, GA_ROOT)
    return top or hwnd


class ClickPicker(QObject):
    """One-shot: capture the next left mouse click anywhere on screen."""

    picked = pyqtSignal(int)
    cancelled = pyqtSignal()

    def __init__(self, exclude_hwnds: Iterable[int] = ()) -> None:
        super().__init__()
        self._exclude = {int(h) for h in exclude_hwnds if h}
        self._mouse_listener: mouse.Listener | None = None
        self._key_listener: keyboard.Listener | None = None

    def start(self) -> None:
        def on_click(x: int, y: int, button: mouse.Button, pressed: bool) -> bool:
            if button != mouse.Button.left or not pressed:
                return True
            hwnd = top_level_hwnd_at(int(x), int(y))
            if not hwnd or hwnd in self._exclude:
                self.cancelled.emit()
            else:
                self.picked.emit(hwnd)
            self._stop_key_listener()
            return False  # stop mouse listener

        def on_key_press(key: keyboard.Key) -> bool:
            if key == keyboard.Key.esc:
                self.cancelled.emit()
                self._stop_mouse_listener()
                return False
            return True

        self._mouse_listener = mouse.Listener(on_click=on_click)
        self._key_listener = keyboard.Listener(on_press=on_key_press)
        self._mouse_listener.start()
        self._key_listener.start()

    def stop(self) -> None:
        self._stop_mouse_listener()
        self._stop_key_listener()

    def _stop_mouse_listener(self) -> None:
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._mouse_listener = None

    def _stop_key_listener(self) -> None:
        if self._key_listener is not None:
            try:
                self._key_listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._key_listener = None


class HotkeyPicker(QObject):
    """Always-on global hotkey: picks the window under the cursor when pressed."""

    picked = pyqtSignal(int)

    def __init__(
        self,
        exclude_hwnds: Iterable[int] = (),
        hotkey: str = "<ctrl>+<shift>+p",
    ) -> None:
        super().__init__()
        self._exclude = {int(h) for h in exclude_hwnds if h}
        self._hotkey = hotkey
        self._listener: keyboard.GlobalHotKeys | None = None
        self._mouse_controller = mouse.Controller()

    def set_exclude(self, hwnds: Iterable[int]) -> None:
        self._exclude = {int(h) for h in hwnds if h}

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.GlobalHotKeys({self._hotkey: self._on_hotkey})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._listener = None

    def _on_hotkey(self) -> None:
        try:
            x, y = self._mouse_controller.position
            hwnd = top_level_hwnd_at(int(x), int(y))
        except Exception:  # noqa: BLE001
            return
        if hwnd and hwnd not in self._exclude:
            self.picked.emit(hwnd)
