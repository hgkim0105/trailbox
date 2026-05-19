"""Screen recording with three backends, all converging on a single mp4:

- MonitorTarget: dxcam (DXGI Desktop Duplication) — captures an entire monitor.
  Pulls BGRA frames into ffmpeg only on present; VFR-paced.
- WindowTarget:  windows-capture (Windows Graphics Capture) — captures one
  HWND even if covered by other windows; works with HW-accelerated games.
  Push model; same BGRA-into-ffmpeg pipeline.
- AndroidDeviceTarget: scrcpy wraps the device's encoder and emits a complete
  MKV bytestream on stdout; we pipe that into ffmpeg ``-c copy`` to remux to
  mp4 without re-encoding. Audio is handled by scrcpy itself, so the post-mux
  step in main.py is skipped for this path.

The ``max_fps`` argument is an upper rate cap. For dxcam/WGC it's enforced on
the writer side (drops frames arriving faster than 1/max_fps since the last
write). For scrcpy it's passed through as ``--max-fps``.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class AndroidDeviceTarget:
    serial: str
    package: str | None = None     # foreground package (best-effort)
    capture_audio: bool = True     # Android 11+ output capture; else falls back
    # Video backend. "scrcpy" wraps Genymobile/scrcpy (high quality, audio
    # support, but blocked on Android 16 / One UI 8 because scrcpy 4.0 still
    # relies on the legacy DisplayManager hidden API). "screenrecord" shells
    # out to the OS-builtin tool which uses public APIs only — wider
    # compatibility, no audio, capped at 3 min per chunk.
    backend: str = "scrcpy"


CaptureTarget = MonitorTarget | WindowTarget | AndroidDeviceTarget


class ScreenRecorder:
    def __init__(
        self,
        output_path: Path,
        target: CaptureTarget,
        max_fps: int = 60,
        frames_log_path: Path | None = None,
    ) -> None:
        self.output_path = Path(output_path)
        self.target = target
        self.max_fps = max(1, int(max_fps))
        self.frames_log_path = Path(frames_log_path) if frames_log_path else None

        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._stderr_log = None
        self._frames_fh = None
        self._frame_intervals_ms: list[float] = []
        self._error: BaseException | None = None
        self._frames_written = 0
        self._first_write_t: float | None = None
        self._last_write_t: float = 0.0

        # WGC: latest frame produced by callback + new-frame signaling.
        self._latest_lock = threading.Lock()
        self._latest_frame_bytes: bytes | None = None
        self._frame_shape: tuple[int, int] | None = None  # (h, w)
        self._new_frame_event = threading.Event()

        # Android (scrcpy): two cooperating subprocesses we need to tear down
        # in a specific order on stop (scrcpy first → ffmpeg sees EOF → MP4
        # is finalized cleanly).
        self._scrcpy_proc: subprocess.Popen | None = None
        self._scrcpy_stderr_log = None

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
            self._open_frame_log()
            if isinstance(self.target, AndroidDeviceTarget):
                if self.target.backend == "screenrecord":
                    self._run_screenrecord(self.target)
                else:
                    self._run_scrcpy(self.target)
            elif isinstance(self.target, WindowTarget):
                self._run_window(self.target)
            else:
                self._run_monitor(self.target)
        except BaseException as e:  # noqa: BLE001
            self._error = e
            self._started.set()
        finally:
            self._close_frame_log()
            # scrcpy must close BEFORE ffmpeg: closing scrcpy lets ffmpeg see
            # EOF on stdin and finalize the mp4 footer cleanly.
            self._close_scrcpy()
            self._close_ffmpeg()

    def _open_frame_log(self) -> None:
        if self.frames_log_path is None:
            return
        try:
            self.frames_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._frames_fh = open(
                self.frames_log_path, "w", encoding="utf-8", newline="\n"
            )
        except OSError:
            self._frames_fh = None

    def _close_frame_log(self) -> None:
        if self._frames_fh is not None:
            try:
                self._frames_fh.close()
            except OSError:
                pass
            self._frames_fh = None

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
        t = now if now is not None else time.perf_counter()
        delta_ms: float | None = None
        if self._first_write_t is None:
            self._first_write_t = t
            t_video = 0.0
        else:
            t_video = t - self._first_write_t
            delta_ms = (t - self._last_write_t) * 1000.0
            self._frame_intervals_ms.append(delta_ms)
        self._last_write_t = t
        self._frame_log(t_video, delta_ms)
        self._frames_written += 1

    def _frame_log(self, t_video: float, delta_ms: float | None) -> None:
        """Append one JSONL line per frame written to ffmpeg (optional)."""
        if self._frames_fh is None:
            return
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rec = {
            "@timestamp": ts_utc,
            "t_video_s": round(t_video, 4),
            "frame": {
                "index": self._frames_written,
                "delta_ms": round(delta_ms, 3) if delta_ms is not None else None,
            },
            "ecs": {"version": "8.11"},
        }
        try:
            self._frames_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def frame_stats(self) -> dict[str, float]:
        """Aggregate frame interval statistics in milliseconds.

        ``count`` is the number of *intervals* observed (= frames - 1). Useful
        as a session-level jitter readout in session_meta.json.
        """
        intervals = self._frame_intervals_ms
        if not intervals:
            return {}
        sorted_iv = sorted(intervals)
        n = len(sorted_iv)
        # Simple percentile via nearest-rank, sufficient for QA visualization.
        p99 = sorted_iv[min(n - 1, int(n * 0.99))]
        p95 = sorted_iv[min(n - 1, int(n * 0.95))]
        return {
            "intervals": n,
            "min_ms": round(min(intervals), 3),
            "avg_ms": round(sum(intervals) / n, 3),
            "max_ms": round(max(intervals), 3),
            "p95_ms": round(p95, 3),
            "p99_ms": round(p99, 3),
        }

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
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
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

    # ---- scrcpy (Android) -------------------------------------------------

    def _run_scrcpy(self, target: AndroidDeviceTarget) -> None:
        """Pipe scrcpy's MKV output into ffmpeg ``-c copy`` to produce mp4.

        scrcpy.exe ──stdout(mkv)──> ffmpeg.exe ──> screen.mp4

        Lifecycle: we spawn both, signal ``_started`` once both are running,
        block until ``_stop`` is set, then signal scrcpy to terminate. scrcpy
        closes its stdout, ffmpeg drains and writes a finalized mp4.
        """
        # Local import keeps the module free of the adb dep until needed.
        from core import adb

        scrcpy_cmd = [
            str(adb.get_scrcpy_path()),
            f"--serial={target.serial}",
            "--no-window",                  # headless: don't pop a mirror window
            "--no-control",                 # we're recording, not interacting
            "--record=-",                   # stream container to stdout
            "--record-format=mkv",
            f"--max-fps={self.max_fps}",
        ]
        if target.capture_audio:
            # output capture is Android 11+; main.py is responsible for the
            # version check and passing capture_audio=False when unsupported.
            scrcpy_cmd += ["--audio-source=output", "--audio-codec=opus"]
        else:
            scrcpy_cmd += ["--no-audio"]

        # scrcpy looks up adb via ADB env var when set; pin it to our bundled
        # binary so it doesn't pick up some other adb from PATH.
        env = os.environ.copy()
        env["ADB"] = str(adb.get_adb_path())

        # Process group + dedicated stderr log. CREATE_NEW_PROCESS_GROUP is
        # required to deliver CTRL_BREAK_EVENT on stop without also killing
        # this Python process.
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._scrcpy_stderr_log = open(
            str(self.output_path) + ".scrcpy.log", "wb"
        )
        scrcpy_creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            scrcpy_creationflags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            scrcpy_creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP

        scrcpy_proc = subprocess.Popen(
            scrcpy_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=self._scrcpy_stderr_log,
            bufsize=0,
            env=env,
            creationflags=scrcpy_creationflags,
        )
        self._scrcpy_proc = scrcpy_proc
        assert scrcpy_proc.stdout is not None

        try:
            self._proc = self._spawn_ffmpeg_passthrough(scrcpy_proc.stdout)
        except BaseException:
            # ffmpeg failed to start: kill scrcpy before re-raising so we don't
            # leak a recording process.
            self._terminate_scrcpy()
            raise

        # Close our copy of scrcpy's stdout — ffmpeg now owns the read end. If
        # we kept it open, ffmpeg wouldn't see EOF when scrcpy exits and would
        # wait forever for more data.
        try:
            scrcpy_proc.stdout.close()
        except OSError:
            pass

        self._started.set()

        # Block until stop. Also bail early if either child dies on its own
        # (device disconnected, scrcpy auth dialog dismissed, etc.).
        while not self._stop.is_set():
            if scrcpy_proc.poll() is not None:
                # Promote unclean exit to a session-level error so the user
                # sees it. Code 0 = graceful, anything else = device/auth fail.
                if scrcpy_proc.returncode != 0:
                    raise RuntimeError(
                        f"scrcpy exited with code {scrcpy_proc.returncode}; "
                        f"see {self._scrcpy_stderr_log.name}"
                    )
                break
            if self._proc is not None and self._proc.poll() is not None:
                # Same logic, ffmpeg side.
                if self._proc.returncode != 0:
                    raise RuntimeError(
                        f"ffmpeg exited with code {self._proc.returncode}"
                    )
                break
            if self._stop.wait(timeout=0.25):
                break

    # ---- Android via OS-builtin screenrecord ------------------------------

    def _run_screenrecord(self, target: AndroidDeviceTarget) -> None:
        """Capture by shelling out to the Android-builtin ``screenrecord``.

        Used when scrcpy fails on the device (Android 16 / One UI 8 currently
        block scrcpy 4.0's hidden-API path), or when the user explicitly
        chose this backend in the UI.

        Trade-offs:
        - No system audio (the OS tool doesn't surface it).
        - 180s per chunk (toolchain hard cap); we loop and concat at stop.
        - No per-frame timing; ``frames.jsonl`` is left empty.

        Chunk lifecycle:
        1. Spawn ``adb shell screenrecord --time-limit=180 <device path>``.
        2. Wait for stop signal OR for the 180s cap to elapse naturally.
        3. Terminating the adb client sends SIGHUP through the shell to
           ``screenrecord``, which finalizes the MP4 cleanly.
        4. After stop: ``adb pull`` each chunk, ffmpeg concat to
           ``output_path``, then delete device-side + local intermediates.
        """
        from core import adb

        adb_path = adb.get_adb_path()
        chunks_dir = self.output_path.parent / "_screenrecord_chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr_log = open(str(self.output_path) + ".screenrecord.log", "wb")

        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP

        # Timestamp-prefix the chunk so concurrent/aborted sessions don't
        # collide on the device's /sdcard.
        device_prefix = f"/sdcard/trailbox_sr_{int(time.time())}_chunk"
        chunk_count = 0

        # Bitrate keeps file size reasonable for QA review while still
        # capturing fine detail. 8 Mbps ≈ ~60 MB / minute at 1080p.
        bitrate_arg = "--bit-rate=8000000"

        self._started.set()

        try:
            while not self._stop.is_set():
                chunk_count += 1
                device_path = f"{device_prefix}_{chunk_count:03d}.mp4"
                cmd = [
                    str(adb_path), "-s", target.serial, "shell",
                    "screenrecord",
                    "--time-limit=180",
                    bitrate_arg,
                    device_path,
                ]
                current = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=self._stderr_log,
                    creationflags=creationflags,
                )
                self._scrcpy_proc = current  # reuse slot for shared teardown

                # Poll for stop OR natural 180s exit. Short sleep — we want to
                # spawn the next chunk promptly when 180s elapses.
                while current.poll() is None and not self._stop.is_set():
                    if self._stop.wait(timeout=0.5):
                        break

                if self._stop.is_set() and current.poll() is None:
                    # SIGINT to the device-side process is the only reliable
                    # way to get a finalized MP4 — TerminateProcess on the
                    # adb client is too abrupt and the shell's SIGHUP often
                    # doesn't reach screenrecord in time. Once screenrecord
                    # exits, the adb client follows naturally.
                    try:
                        subprocess.run(
                            [str(adb_path), "-s", target.serial, "shell",
                             "killall", "-SIGINT", "screenrecord"],
                            capture_output=True,
                            timeout=5,
                            creationflags=(
                                subprocess.CREATE_NO_WINDOW
                                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                            ),
                        )
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                    try:
                        current.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try:
                            current.kill()
                        except OSError:
                            pass
                    break  # no further chunks once user stopped

            # Pull + concat after loop ends (stop OR final-180s rollover).
            self._screenrecord_concat(
                adb_path=adb_path,
                serial=target.serial,
                device_prefix=device_prefix,
                chunk_count=chunk_count,
                chunks_dir=chunks_dir,
            )
        finally:
            # Clean up device-side chunks even if we crashed mid-concat.
            for i in range(1, chunk_count + 1):
                try:
                    subprocess.run(
                        [str(adb_path), "-s", target.serial, "shell",
                         "rm", "-f", f"{device_prefix}_{i:03d}.mp4"],
                        capture_output=True,
                        timeout=5,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW
                            if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                        ),
                    )
                except (subprocess.TimeoutExpired, OSError):
                    pass
            # Local chunks too (we wrote final mp4 elsewhere).
            try:
                for p in chunks_dir.glob("*.mp4"):
                    p.unlink(missing_ok=True)
                chunks_dir.rmdir()
            except OSError:
                pass

    def _screenrecord_concat(
        self,
        adb_path: Path,
        serial: str,
        device_prefix: str,
        chunk_count: int,
        chunks_dir: Path,
    ) -> None:
        """Pull each chunk and concat into ``self.output_path``.

        Single-chunk sessions skip ffmpeg entirely (just adb pull straight
        to the final path). Multi-chunk uses ffmpeg's concat demuxer with
        ``-c copy`` — no re-encoding, ~instant for QA-length sessions.
        """
        if chunk_count == 0:
            raise RuntimeError("screenrecord produced no chunks")

        # Pull each chunk locally first.
        local_chunks: list[Path] = []
        for i in range(1, chunk_count + 1):
            local = chunks_dir / f"chunk_{i:03d}.mp4"
            device_path = f"{device_prefix}_{i:03d}.mp4"
            pull = subprocess.run(
                [str(adb_path), "-s", serial, "pull", device_path, str(local)],
                capture_output=True,
                timeout=120,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                ),
            )
            if pull.returncode == 0 and local.exists() and local.stat().st_size > 0:
                local_chunks.append(local)

        if not local_chunks:
            raise RuntimeError(
                "screenrecord chunks could not be pulled — "
                "device may have run out of /sdcard space"
            )

        # Single chunk: skip concat, just move.
        if len(local_chunks) == 1:
            local_chunks[0].replace(self.output_path)
            self._frames_written = 1  # placeholder so the meta isn't 0
            return

        # Multi-chunk: ffmpeg concat demuxer needs a temp filelist.
        filelist = chunks_dir / "concat.txt"
        # ffmpeg concat demuxer wants forward slashes + 'file' prefix per line.
        filelist.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in local_chunks),
            encoding="utf-8",
        )
        cmd = [
            get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(filelist),
            "-c", "copy",
            "-movflags", "+faststart",
            str(self.output_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            ),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed: {result.stderr.decode('utf-8', errors='replace')[:500]}"
            )
        # Same placeholder reasoning as single-chunk path.
        self._frames_written = len(local_chunks)

    def _spawn_ffmpeg_passthrough(self, stdin_pipe) -> subprocess.Popen:
        """ffmpeg that copies an already-encoded container (no re-encoding).

        Reads MKV from ``stdin_pipe`` (scrcpy's stdout), remuxes to mp4 with
        ``-c copy`` + ``+faststart`` so the result plays straight from a
        ``file://`` link in the viewer.
        """
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        # Note: we share the GUI/WGC stderr log handle name pattern so users
        # can find both ffmpeg logs the same way.
        self._stderr_log = open(str(self.output_path) + ".ffmpeg.log", "wb")
        cmd = [
            get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-f", "matroska",
            "-i", "-",
            "-c", "copy",
            "-movflags", "+faststart",
            str(self.output_path),
        ]
        return subprocess.Popen(
            cmd,
            stdin=stdin_pipe,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_log,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )

    def _terminate_scrcpy(self) -> None:
        """Politely stop scrcpy so the MKV stream closes with a proper footer.

        On Windows ``subprocess.terminate`` is a hard TerminateProcess, which
        truncates the recording. We send CTRL_BREAK_EVENT instead — that's
        equivalent to the user hitting Ctrl+C in a scrcpy console, and scrcpy
        cleanly writes the EBML close + flushes its output buffer.
        """
        proc = self._scrcpy_proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if hasattr(signal, "CTRL_BREAK_EVENT"):
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        except (OSError, ValueError):
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except OSError:
                pass

    def _close_scrcpy(self) -> None:
        self._terminate_scrcpy()
        self._scrcpy_proc = None
        if self._scrcpy_stderr_log is not None:
            try:
                self._scrcpy_stderr_log.close()
            except OSError:
                pass
            self._scrcpy_stderr_log = None
