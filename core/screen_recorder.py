"""Screen recording with two backends, VFR-driven by frame arrivals:

- MonitorTarget: dxcam (DXGI Desktop Duplication) — captures an entire monitor.
- WindowTarget:  windows-capture (Windows Graphics Capture) — captures one
  HWND even if covered by other windows; works with HW-accelerated games.

Both pipe BGRA frames into ffmpeg ONLY when a new frame is available; ffmpeg
stamps each frame with wallclock and writes a passthrough-paced mp4. This
avoids the duplicate-frame judder you get from a fixed Python ticker that's
out of phase with the source's present clock.

The ``max_fps`` argument is an upper rate cap (drops frames arriving faster
than 1/max_fps since the last write) — useful for shrinking files when the
source presents at very high rates. Set high (e.g. 120) to keep everything.
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import dxcam
import numpy as np
from imageio_ffmpeg import get_ffmpeg_exe
from windows_capture import Frame, InternalCaptureControl, WindowsCapture


@dataclass(frozen=True)
class MonitorTarget:
    index: int = 0


@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    title: str = ""


CaptureTarget = MonitorTarget | WindowTarget


class ScreenRecorder:
    def __init__(
        self,
        output_path: Path,
        target: CaptureTarget,
        max_fps: int = 60,
    ) -> None:
        self.output_path = Path(output_path)
        self.target = target
        self.max_fps = max(1, int(max_fps))

        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._stderr_log = None
        self._error: BaseException | None = None
        self._frames_written = 0
        self._first_write_t: float | None = None
        self._last_write_t: float = 0.0

        # WGC: latest frame produced by callback + new-frame signaling.
        self._latest_lock = threading.Lock()
        self._latest_frame_bytes: bytes | None = None
        self._frame_shape: tuple[int, int] | None = None  # (h, w)
        self._new_frame_event = threading.Event()

    # ---- Public API -------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("ScreenRecorder already started")
        self._thread = threading.Thread(
            target=self._run, name="ScreenRecorder", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        if self._error is not None:
            raise self._error

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        # Wake up any wait-for-frame loop blocked on the event.
        self._new_frame_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._error is not None:
            raise self._error

    def frames_written(self) -> int:
        return self._frames_written

    def effective_fps(self) -> float:
        """Average fps measured between first and last frame writes."""
        if self._first_write_t is None or self._frames_written < 2:
            return 0.0
        elapsed = self._last_write_t - self._first_write_t
        if elapsed <= 0:
            return 0.0
        return (self._frames_written - 1) / elapsed

    # ---- Dispatch ---------------------------------------------------------

    def _run(self) -> None:
        try:
            if isinstance(self.target, WindowTarget):
                self._run_window(self.target)
            else:
                self._run_monitor(self.target)
        except BaseException as e:  # noqa: BLE001
            self._error = e
            self._started.set()
        finally:
            self._close_ffmpeg()

    # ---- Monitor (dxcam) --------------------------------------------------

    def _run_monitor(self, target: MonitorTarget) -> None:
        camera = dxcam.create(output_idx=target.index, output_color="BGRA")
        if camera is None:
            raise RuntimeError(
                f"dxcam.create returned None for output_idx={target.index}"
            )
        try:
            width, height = camera.width, camera.height

            # Prime an initial frame.
            first = None
            deadline = time.perf_counter() + 2.0
            while first is None and time.perf_counter() < deadline:
                first = camera.grab()
                if first is None:
                    time.sleep(0.005)
            if first is None:
                raise RuntimeError("dxcam did not produce an initial frame")

            self._proc = self._spawn_ffmpeg(width, height)
            stdin = self._proc.stdin
            assert stdin is not None
            self._started.set()

            self._write(stdin, first.tobytes())

            min_interval = 1.0 / self.max_fps
            while not self._stop.is_set():
                frame = camera.grab()
                if frame is None:
                    time.sleep(0.001)
                    continue
                now = time.perf_counter()
                if now - self._last_write_t < min_interval:
                    continue  # rate cap
                try:
                    self._write(stdin, frame.tobytes(), now=now)
                except (BrokenPipeError, OSError):
                    break
        finally:
            try:
                camera.release()
            except Exception:  # noqa: BLE001
                pass

    # ---- Window (WGC) -----------------------------------------------------

    def _run_window(self, target: WindowTarget) -> None:
        capture = WindowsCapture(
            cursor_capture=True,
            draw_border=False,
            window_hwnd=target.hwnd,
        )

        first_frame_event = threading.Event()
        closed_event = threading.Event()

        @capture.event
        def on_frame_arrived(frame: Frame, _: InternalCaptureControl) -> None:
            buf: np.ndarray = frame.frame_buffer  # (H, W, 4) BGRA uint8
            h, w = buf.shape[0], buf.shape[1]
            with self._latest_lock:
                if self._frame_shape is None:
                    self._frame_shape = (h, w)
                    self._latest_frame_bytes = buf.tobytes()
                    first_frame_event.set()
                else:
                    fh, fw = self._frame_shape
                    if (h, w) == (fh, fw):
                        self._latest_frame_bytes = buf.tobytes()
                    else:
                        canvas = np.zeros((fh, fw, 4), dtype=np.uint8)
                        ch = min(fh, h)
                        cw = min(fw, w)
                        canvas[:ch, :cw] = buf[:ch, :cw]
                        self._latest_frame_bytes = canvas.tobytes()
            self._new_frame_event.set()

        @capture.event
        def on_closed() -> None:
            closed_event.set()
            self._new_frame_event.set()

        control = capture.start_free_threaded()
        try:
            if not first_frame_event.wait(timeout=5.0):
                raise RuntimeError(
                    "WGC did not deliver an initial frame (window may be invisible)"
                )
            with self._latest_lock:
                assert self._frame_shape is not None
                h, w = self._frame_shape

            self._proc = self._spawn_ffmpeg(w, h)
            stdin = self._proc.stdin
            assert stdin is not None
            self._started.set()

            min_interval = 1.0 / self.max_fps
            while not self._stop.is_set():
                if not self._new_frame_event.wait(timeout=0.5):
                    if closed_event.is_set():
                        break
                    continue
                self._new_frame_event.clear()
                if closed_event.is_set():
                    break

                now = time.perf_counter()
                if now - self._last_write_t < min_interval:
                    continue
                with self._latest_lock:
                    buf = self._latest_frame_bytes
                if buf is None:
                    continue
                try:
                    self._write(stdin, buf, now=now)
                except (BrokenPipeError, OSError):
                    break
        finally:
            try:
                control.stop()
            except Exception:  # noqa: BLE001
                pass

    # ---- ffmpeg plumbing --------------------------------------------------

    def _write(self, stdin, data: bytes, now: float | None = None) -> None:
        stdin.write(data)
        self._frames_written += 1
        t = now if now is not None else time.perf_counter()
        if self._first_write_t is None:
            self._first_write_t = t
        self._last_write_t = t

    def _spawn_ffmpeg(self, width: int, height: int) -> subprocess.Popen:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr_log = open(str(self.output_path) + ".ffmpeg.log", "wb")
        # -use_wallclock_as_timestamps stamps each input frame with its arrival
        # time, and -fps_mode passthrough preserves those PTSs on output. The
        # nominal -framerate is just to satisfy the rawvideo demuxer; the cap
        # is enforced on the writer side, not by ffmpeg.
        cmd = [
            get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-use_wallclock_as_timestamps", "1",
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{width}x{height}",
            "-framerate", str(self.max_fps),
            "-i", "-",
            "-an",
            "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "23",
            "-fps_mode", "passthrough",
            str(self.output_path),
        ]
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_log,
            bufsize=0,
        )

    def _close_ffmpeg(self) -> None:
        proc = self._proc
        if proc is not None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if self._stderr_log is not None:
            try:
                self._stderr_log.close()
            except OSError:
                pass
