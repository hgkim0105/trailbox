"""Enumerate visible top-level windows for the capture-target picker."""
from __future__ import annotations

from dataclasses import dataclass

import psutil
import win32con
import win32gui
import win32process


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process_name: str
    exe_path: str = ""

    @property
    def label(self) -> str:
        """Human-readable label used in the UI dropdown."""
        return f"{self.title}  —  {self.process_name}  [hwnd 0x{self.hwnd:X}]"


def enumerate_windows() -> list[WindowInfo]:
    """Return visible top-level windows in z-order (front-most first)."""
    results: list[WindowInfo] = []

    def cb(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.GetParent(hwnd) != 0:
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        # Filter out invisible tool windows (taskbar tray helpers, etc.)
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if ex_style & win32con.WS_EX_TOOLWINDOW:
            return True
        # Skip zero-area windows.
        rect = win32gui.GetWindowRect(hwnd)
        if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
            return True

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        pname = "?"
        exe = ""
        try:
            proc = psutil.Process(pid)
            pname = proc.name()
            try:
                exe = proc.exe() or ""
            except (psutil.AccessDenied, OSError):
                exe = ""
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        results.append(
            WindowInfo(
                hwnd=hwnd, title=title, pid=pid, process_name=pname, exe_path=exe
            )
        )
        return True

    win32gui.EnumWindows(cb, None)
    return results
