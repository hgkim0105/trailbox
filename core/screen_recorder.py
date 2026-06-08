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

import glob
import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

# dxcam / numpy / windows_capture are *deliberately* not imported at module
# scope. dxcam triggers comtypes' COM init + type-library compilation (~0.5s),
# windows_capture loads a Rust pyd (~0.2s), and numpy is ~0.1s — together they
# dominated app startup. Each one is now imported lazily inside the specific
# backend method that uses it (`_run_monitor`, `_run_window`), so an idle
# Trailbox.exe sitting on the launcher screen never pays for them.
#
# The COM-ordering rule from CLAUDE.md ("screen_recorder must import before
# audio_recorder") was about main-thread import order. Now both libraries are
# imported inside their respective recorder threads, so per-thread COM
# apartments stay independent and the ordering becomes moot.


class _ScrcpyNoFramesError(RuntimeError):
    """Raised by the auto-backend probe when scrcpy stays silent.

    Distinct from a generic ``RuntimeError`` so the dispatcher only catches
    the "scrcpy is bricked, try screenrecord" case and lets every other
    scrcpy failure propagate normally.
    """


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


@dataclass(frozen=True)
class IOSDeviceTarget:
    """An iPhone/iPad tethered over USB, captured on a macOS host.

    Screen+audio come through AVFoundation/CoreMediaIO (the QuickTime "movie
    recording → iPhone" mechanism, macOS-only). ``udid`` identifies the device
    to pymobiledevice3 (logs/metrics); ``device_name`` is the AVFoundation
    capture-device name used to find the matching ``AVCaptureDevice``.
    """

    udid: str
    device_name: str
    bundle_id: str | None = None   # foreground app bundle id (best-effort)
    capture_audio: bool = True


CaptureTarget = MonitorTarget | WindowTarget | AndroidDeviceTarget | IOSDeviceTarget


class ScreenRecorder:
    # Lookback ring segment length. Short enough that a captured clip is
    # keyframe-trimmable to within a couple seconds of the requested window;
    # long enough that segment churn (and the per-segment mp4/ts overhead)
    # stays negligible.
    _SEG_SECONDS = 2.0

    def __init__(
        self,
        output_path: Path,
        target: CaptureTarget,
        max_fps: int = 60,
        frames_log_path: Path | None = None,
        *,
        lookback: bool = False,
        buffer_seconds: float = 30.0,
    ) -> None:
        self.output_path = Path(output_path)
        self.target = target
        self.max_fps = max(1, int(max_fps))
        self.frames_log_path = Path(frames_log_path) if frames_log_path else None

        # Lookback mode: ffmpeg writes a rolling ring of mpegts segments into
        # ``output_path`` (treated as a directory) instead of one mp4. A janitor
        # prunes old segments and records each segment's creation perf-time so
        # save_window() can map a wall-window onto the right files. Per-frame
        # timing also goes to an in-memory ring instead of frames.jsonl.
        self.lookback = bool(lookback)
        self.buffer_seconds = float(buffer_seconds)
        self._seg_dir = Path(output_path) if self.lookback else None
        self._janitor_thread: threading.Thread | None = None
        # perf_counter()/time.time() pair captured at start, so a segment file's
        # wall-clock creation time can be converted into the buffering timeline.
        self._perf0 = 0.0
        self._wall0 = 0.0
        # segment index -> creation perf-time, in ascending index order.
        self._seg_marks: "dict[int, float]" = {}
        self._seg_lock = threading.Lock()
        # Per-frame timing ring: (perf_time, delta_ms). Bounded by janitor.
        self._frame_ring: deque[tuple[float, float | None]] = deque()

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

        # iOS: the throwaway built-in-camera session that makes the iPhone
        # screen device enumerate. It MUST be created on the main thread (the
        # CoreMediaIO device-arrival notification is only processed on the main
        # run loop), so start() does it before spawning the recorder thread.
        self._ios_trigger_session = None

    # ---- Public API -------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("ScreenRecorder already started")
        # iOS prep happens on the *calling* thread (main thread in the GUI and
        # in smoke tests) because the screen-device trigger + camera-permission
        # prompt only work off the main run loop. Do it before the recorder
        # thread spawns so the muxed device is already visible when it runs.
        if isinstance(self.target, IOSDeviceTarget):
            self._ios_main_thread_prep()
        self._thread = threading.Thread(
            target=self._run, name="ScreenRecorder", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        if self._error is not None:
            raise self._error

    def _ios_main_thread_prep(self) -> None:
        """Main-thread iOS setup: camera authorization + screen-device trigger.

        Both rely on the main run loop (the camera-permission prompt and the
        CoreMediaIO device-arrival notification are delivered there), so this
        cannot run in the recorder thread. Best-effort: any failure is left for
        ``_run_ios`` to surface as a clear "device not found" error.
        """
        import sys as _sys
        if _sys.platform != "darwin":
            return
        try:
            from Foundation import NSRunLoop, NSDate
            from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
            from core import ios_device

            self._ensure_camera_authorized(AVCaptureDevice, AVMediaTypeVideo,
                                           NSRunLoop, NSDate)
            self._ios_trigger_session = ios_device.trigger_screen_capture_devices()
        except BaseException:  # noqa: BLE001 - surfaced later as device-not-found
            pass

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        # Wake up any wait-for-frame loop blocked on the event.
        self._new_frame_event.set()
        if self._thread is not None:
            # The iOS backend finalizes a .mov and then remuxes it to screen.mp4
            # inside this thread on stop; that runs well past the default budget,
            # and cutting the join short leaves a .ios.mov with no screen.mp4.
            join_timeout = timeout
            if isinstance(self.target, IOSDeviceTarget):
                join_timeout = max(timeout, 60.0)
            self._thread.join(timeout=join_timeout)
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
            if self.lookback:
                # Anchor the wall↔perf conversion used to date segment files.
                self._perf0 = time.perf_counter()
                self._wall0 = time.time()
                self._start_janitor()
            if isinstance(self.target, IOSDeviceTarget):
                self._run_ios(self.target)
            elif isinstance(self.target, AndroidDeviceTarget):
                self._run_android_dispatch(self.target)
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
            if self._janitor_thread is not None:
                self._janitor_thread.join(timeout=2.0)
                self._janitor_thread = None

    # ---- iOS (AVFoundation / CoreMediaIO, macOS-only) ---------------------

    @staticmethod
    def _ensure_camera_authorized(AVCaptureDevice, media_type, NSRunLoop, NSDate):
        """Block until the Camera TCC permission is `authorized`, else raise.

        AVFoundation authorization status codes: 0 notDetermined, 1 restricted,
        2 denied, 3 authorized. Only 3 yields real frames; 0/1/2 all silently
        produce a black recording. On `notDetermined` we fire
        ``requestAccessForMediaType:completionHandler:`` (the only call that
        shows the system prompt) and pump the run loop until the user answers.

        Requesting access requires an ``NSCameraUsageDescription`` in the host's
        Info.plist: the bundled Trailbox.app injects it, and a raw-python run
        inherits Terminal.app's. Without it the prompt can't appear and the
        status stays notDetermined — which is exactly the case we error on.
        """
        status = AVCaptureDevice.authorizationStatusForMediaType_(media_type)
        if status == 3:
            return
        if status == 0:  # notDetermined → request + wait for the user's answer
            done = threading.Event()

            def _handler(_granted):
                done.set()

            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                media_type, _handler
            )
            # The completion handler is delivered on an internal dispatch queue,
            # but the system prompt needs a live run loop — pump it until the
            # user responds (cap at 120s so a walked-away user still unwinds).
            rl = NSRunLoop.currentRunLoop()
            deadline = time.perf_counter() + 120.0
            while not done.is_set() and time.perf_counter() < deadline:
                rl.runMode_beforeDate_(
                    "kCFRunLoopDefaultMode",
                    NSDate.dateWithTimeIntervalSinceNow_(0.1),
                )
            status = AVCaptureDevice.authorizationStatusForMediaType_(media_type)
            if status == 3:
                return

        raise RuntimeError(
            "Camera permission required to capture the iPhone screen "
            f"(authorization status={status}, expected 3=authorized). "
            "Grant it in System Settings > Privacy & Security > Camera "
            "for Trailbox (or your terminal), then record again. Without it "
            "AVFoundation records only black frames."
        )

    def _run_ios(self, target: IOSDeviceTarget) -> None:
        """Capture a tethered iOS device via AVFoundation (macOS-only).

        Uses ``AVCaptureMovieFileOutput`` to write a single self-contained .mov
        (video + audio), then remuxes to ``output_path`` with ffmpeg
        ``-c copy -movflags +faststart``. Mirrors the scrcpy path's "device
        already produced a muxed container → skip post_mux" contract: caller
        points ``output_path`` straight at the final mp4 and skips ``mux_av``.

        pyobjc / AVFoundation / CoreMediaIO are imported lazily here (inside the
        recorder thread) — the same rule dxcam / windows-capture follow: keep
        heavy, platform-only deps out of module scope so the module imports on
        every platform.

        NOTE: requires on-device validation on real macOS + iPhone hardware;
        the AVCaptureSession wiring and CMIO device-reveal cannot be exercised
        in CI / non-mac environments.
        """
        from Foundation import NSURL, NSObject, NSRunLoop, NSDate
        from AVFoundation import (
            AVCaptureSession,
            AVCaptureDevice,
            AVCaptureDeviceInput,
            AVCaptureMovieFileOutput,
            AVMediaTypeMuxed,
            AVMediaTypeVideo,
        )

        from core import ios_device

        # Camera authorization + the screen-device trigger already ran on the
        # main thread in start()/_ios_main_thread_prep (both need the main run
        # loop). The muxed "iOS Device" is therefore already visible here, and
        # the throwaway built-in-camera trigger session is held in
        # self._ios_trigger_session — we keep it running until our real session
        # has claimed the iPhone device, then stop it. (Re-checking auth here is
        # cheap and returns immediately when already authorized.)
        self._ensure_camera_authorized(AVCaptureDevice, AVMediaTypeVideo,
                                       NSRunLoop, NSDate)
        trigger_session = self._ios_trigger_session
        self._ios_trigger_session = None

        def _find_screen_device():
            """The tethered iPhone's *screen* — a MUXED device (video+audio).

            Prefer a name match against the target; else the sole muxed device
            whose modelID is "iOS Device". We never fall back to a *video*
            device: the iPhone's only video device is its Continuity Camera,
            and recording that yields the camera feed, not the screen (the
            black-screen bug)."""
            muxed = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed) or [])
            for dev in muxed:
                try:
                    if ios_device.names_match(target.device_name,
                                              str(dev.localizedName())):
                        return dev
                except Exception:  # noqa: BLE001
                    continue
            for dev in muxed:  # name didn't match — take the lone iOS screen dev
                try:
                    if str(dev.modelID()) == "iOS Device":
                        return dev
                except Exception:  # noqa: BLE001
                    continue
            return muxed[0] if muxed else None

        try:
            video_dev = _find_screen_device()

            if video_dev is None:
                raise RuntimeError(
                    f"iPhone screen-capture device not found: {target.device_name!r}. "
                    "Unlock the device + tap 'Trust', keep the screen on, and "
                    "confirm a built-in/USB camera exists (used to trigger the "
                    "screen device). The Continuity Camera alone is not the screen."
                )

            session = AVCaptureSession.alloc().init()

            # The muxed iOS screen device carries video + audio together, so a
            # single input covers both — no separate mic input needed.
            dev_input, err_ptr = AVCaptureDeviceInput.deviceInputWithDevice_error_(
                video_dev, None
            )
            if dev_input is None:
                raise RuntimeError(f"AVCaptureDeviceInput failed: {err_ptr}")
            if session.canAddInput_(dev_input):
                session.addInput_(dev_input)
            else:
                raise RuntimeError("AVCaptureSession refused the iOS device input")
        except BaseException:
            if trigger_session is not None:
                try:
                    trigger_session.stopRunning()
                except Exception:  # noqa: BLE001
                    pass
            raise

        movie_out = AVCaptureMovieFileOutput.alloc().init()
        if session.canAddOutput_(movie_out):
            session.addOutput_(movie_out)
        else:
            raise RuntimeError("AVCaptureSession refused the movie file output")

        # Recording-finished delegate (AVCaptureFileOutputRecordingDelegate).
        # We capture the error from didFinish: an interrupted/failed capture
        # reports it here, and swallowing it leaves only the generic "empty
        # .mov" — surface it so the real cause (e.g. session interrupted, no
        # connection) is visible.
        finished = threading.Event()
        delegate_err: dict[str, str] = {}

        class _RecDelegate(NSObject):
            def captureOutput_didStartRecordingToOutputFileAtURL_fromConnections_(  # noqa: N802,E501
                self, _out, _url, _conns
            ):
                pass

            def captureOutput_didFinishRecordingToOutputFileAtURL_fromConnections_error_(  # noqa: N802,E501
                self, _out, _url, _conns, error
            ):
                if error is not None:
                    try:
                        delegate_err["msg"] = str(error.localizedDescription())
                    except Exception:  # noqa: BLE001
                        delegate_err["msg"] = str(error)
                finished.set()

        delegate = _RecDelegate.alloc().init()

        # Single .mov next to the final mp4; remuxed + deleted after stop. The
        # finally block's _close_scrcpy/_close_ffmpeg stay no-ops on this path.
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        mov_path = self.output_path.with_suffix(".ios.mov")
        if mov_path.exists():
            try:
                mov_path.unlink()
            except OSError:
                pass
        mov_url = NSURL.fileURLWithPath_(str(mov_path))

        # AVCaptureMovieFileOutput gives no per-frame callback, so the live
        # frame count is derived from its recordedDuration (a CMTime) × the
        # device's active max frame rate. Without this the status gauge and the
        # final screen_frames/effective_fps sit at 0 on the iOS backend.
        fps_nominal = 30.0
        try:
            ranges = video_dev.activeFormat().videoSupportedFrameRateRanges()
            if ranges:
                fps_nominal = float(ranges[0].maxFrameRate()) or 30.0
        except Exception:  # noqa: BLE001
            pass

        def _recorded_seconds() -> float:
            # CMTime → seconds without importing CoreMedia: value / timescale.
            try:
                t = movie_out.recordedDuration()
                ts = getattr(t, "timescale", 0)
                return (t.value / ts) if ts else 0.0
            except Exception:  # noqa: BLE001
                return 0.0

        def _refresh_frames() -> None:
            secs = _recorded_seconds()
            if secs <= 0:
                return
            if self._first_write_t is None:
                self._first_write_t = time.perf_counter() - secs
            self._frames_written = int(round(secs * fps_nominal))
            self._last_write_t = time.perf_counter()

        session.startRunning()
        # Our session now holds the iPhone screen device, so the throwaway
        # trigger session (built-in camera) has done its job — stop it to free
        # the Mac camera (turn its indicator light off).
        if trigger_session is not None:
            try:
                trigger_session.stopRunning()
            except Exception:  # noqa: BLE001
                pass
            trigger_session = None
        movie_out.startRecordingToOutputFileURL_recordingDelegate_(mov_url, delegate)
        self._started.set()

        # Cocoa needs a live run loop for the capture/delegate callbacks. Spin
        # it in short slices so we stay responsive to the stop event.
        rl = NSRunLoop.currentRunLoop()
        while not self._stop.is_set():
            rl.runMode_beforeDate_(
                "kCFRunLoopDefaultMode", NSDate.dateWithTimeIntervalSinceNow_(0.2)
            )
            _refresh_frames()

        movie_out.stopRecording()
        # stopRecording() finalizes the file asynchronously; isRecording stays
        # True until it's fully closed. Poll that (with the delegate as a
        # backstop) while spinning the run loop — the delegate callback arrives
        # on a dispatch queue, not this NSRunLoop, so waiting on it alone was
        # unreliable and always burned the full timeout.
        deadline = time.perf_counter() + 15.0
        while (
            movie_out.isRecording()
            and not finished.is_set()
            and time.perf_counter() < deadline
        ):
            rl.runMode_beforeDate_(
                "kCFRunLoopDefaultMode", NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )
        _refresh_frames()

        if not mov_path.exists() or mov_path.stat().st_size < 1024:
            # Tear the (possibly half-dead) session down best-effort and bail.
            try:
                session.stopRunning()
            except Exception:  # noqa: BLE001
                pass
            extra = f" (delegate error: {delegate_err['msg']})" if delegate_err.get("msg") else ""
            raise RuntimeError("iOS capture produced no video (empty .mov)" + extra)

        # Remux the finalized .mov BEFORE tearing the session down: on a degraded
        # USB link session.stopRunning() can block for tens of seconds and must
        # not gate the deliverable. Once screen.video.mp4 exists the
        # orchestrator's post-mux finds it even if this thread is later cut off
        # by the stop() join.
        self._remux_mov(mov_path)
        try:
            mov_path.unlink()
        except OSError:
            pass

        # session.stopRunning() can block for tens of seconds on a degraded USB
        # link. The deliverable (screen.mp4) is already written, so tear the
        # session down in the background and let this thread return promptly —
        # otherwise every iOS stop looks like a ~60s hang in the UI.
        def _teardown():
            try:
                session.stopRunning()
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_teardown, name="iOSSessionTeardown",
                         daemon=True).start()

    def _remux_mov(self, mov_path: Path) -> None:
        """ffmpeg ``-c copy -movflags +faststart`` from a finished .mov."""
        self._stderr_log = open(str(self.output_path) + ".ffmpeg.log", "wb")
        cmd = [
            get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-i", str(mov_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(self.output_path),
        ]
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=self._stderr_log,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
        if proc.returncode != 0 or not self.output_path.exists():
            raise RuntimeError("ffmpeg remux of iOS .mov failed (see .ffmpeg.log)")

    # ---- Android backend dispatch with auto-fallback ----------------------

    # Minimum file size that proves ffmpeg has written actual video frames
    # (not just the mp4 container box header). Empirically a few seconds of
    # 1080p h264 lands well above this; an MP4 with header-only is ~40 B.
    _ANDROID_FIRST_FRAME_MIN_BYTES = 4096
    _ANDROID_FIRST_FRAME_TIMEOUT_S = 3.0

    def _run_android_dispatch(self, target: AndroidDeviceTarget) -> None:
        """Pick scrcpy vs screenrecord per ``backend``, with optional auto.

        ``backend == "auto"`` resolves at runtime in two layers:

        1. **SDK gate** — probe the device's API level. Android 16+ (SDK 36+)
           is known-broken for scrcpy 4.0's hidden-API path; skip straight
           to screenrecord so we don't burn 3 s on a guaranteed failure.
        2. **First-frame fallback** — for any other SDK, spawn scrcpy and
           watch the output file. If it stays empty for
           ``_ANDROID_FIRST_FRAME_TIMEOUT_S`` seconds, tear scrcpy down and
           retry the session with screenrecord.

        Explicit ``backend == "scrcpy"`` / ``"screenrecord"`` bypass auto.
        """
        backend = target.backend
        if backend == "screenrecord":
            self._run_screenrecord(target)
            return
        if backend == "scrcpy":
            # User opted out of fallback — fail loud if scrcpy can't deliver.
            self._run_scrcpy(target)
            return

        # backend == "auto"
        from core import adb

        sdk: int | None = None
        try:
            sdk = adb.get_android_sdk(target.serial)
        except Exception:  # noqa: BLE001 - probe is best-effort
            sdk = None

        if sdk is not None and sdk >= 36:
            self._run_screenrecord(target)
            return

        # Try scrcpy first. _run_scrcpy raises if it dies hard; we also
        # check for the silent-no-frames case via the file-size probe.
        try:
            self._run_scrcpy(target, first_frame_check=True)
        except _ScrcpyNoFramesError:
            # Reset everything scrcpy touched so screenrecord starts clean.
            self._close_scrcpy()
            self._close_ffmpeg()
            self._proc = None
            self._scrcpy_proc = None
            self._stderr_log = None
            # Wipe the dead-header mp4 if it exists, so screenrecord's
            # eventual replace() doesn't fight an open handle on Windows.
            try:
                if self.output_path.exists():
                    self.output_path.unlink()
            except OSError:
                pass
            self._run_screenrecord(target)

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
        import dxcam  # lazy: comtypes type-library load is ~0.5s

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
        # Lazy: windows_capture loads a Rust pyd and numpy adds another ~0.1s.
        import numpy as np
        from windows_capture import Frame, InternalCaptureControl, WindowsCapture

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
        self._last_write_t = t
        if self.lookback:
            # Per-frame timing goes to a bounded ring; save_window() slices it.
            # We keep the absolute perf-time so frames map onto the same window
            # the video/audio/event streams use.
            cutoff = t - self.buffer_seconds
            self._frame_ring.append((t, delta_ms))
            while self._frame_ring and self._frame_ring[0][0] < cutoff:
                self._frame_ring.popleft()
        else:
            if delta_ms is not None:
                self._frame_intervals_ms.append(delta_ms)
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
        if self.lookback:
            return self._spawn_ffmpeg_segments(width, height)
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

    # ---- Lookback: segment ring + window extraction -----------------------

    def _spawn_ffmpeg_segments(self, width: int, height: int) -> subprocess.Popen:
        """ffmpeg that encodes into a rolling ring of mpegts segments.

        Same BGRA-stdin → libx264 pipeline as the normal path, but the output
        is the segment muxer: one ``seg_%05d.ts`` every ``_SEG_SECONDS``, each
        starting on a forced keyframe so the trailing segments concat cleanly
        with ``-c copy`` at capture time. mpegts is used (not fragmented mp4)
        because it tolerates reading the still-being-written active segment.
        """
        assert self._seg_dir is not None
        self._seg_dir.mkdir(parents=True, exist_ok=True)
        self._stderr_log = open(str(self._seg_dir / "ffmpeg.log"), "wb")
        seg_pattern = str(self._seg_dir / "seg_%05d.ts")
        gop = max(1, int(self._SEG_SECONDS * self.max_fps))
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
            "-g", str(gop),
            "-force_key_frames", f"expr:gte(t,n_forced*{self._SEG_SECONDS})",
            "-f", "segment",
            "-segment_time", str(self._SEG_SECONDS),
            "-segment_format", "mpegts",
            "-reset_timestamps", "1",
            seg_pattern,
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

    def _start_janitor(self) -> None:
        self._janitor_thread = threading.Thread(
            target=self._janitor_loop, name="ScreenSegJanitor", daemon=True
        )
        self._janitor_thread.start()

    def _seg_index(self, path: str) -> int:
        stem = Path(path).stem  # "seg_00042"
        try:
            return int(stem.split("_")[-1])
        except ValueError:
            return -1

    def _perf_of_file(self, path: str) -> float:
        """Convert a segment file's wall-clock creation time to the perf timeline."""
        try:
            wall = os.path.getctime(path)
        except OSError:
            wall = time.time()
        return wall - self._wall0 + self._perf0

    def _janitor_loop(self) -> None:
        """Record new segments' start times; prune ones older than the window.

        Polls the segment dir a few times a second. Each newly-seen segment
        index gets its creation perf-time stamped (the content-start of that
        segment). Segments whose successor is already older than the buffer
        window get deleted, keeping disk usage bounded to ~buffer_seconds of
        video regardless of how long buffering runs.
        """
        # Keep a little margin beyond the requested window so save_window()
        # can always cover the full buffer even mid-segment.
        keep_seconds = self.buffer_seconds + 3 * self._SEG_SECONDS
        assert self._seg_dir is not None
        pattern = str(self._seg_dir / "seg_*.ts")
        while not self._stop.is_set():
            try:
                files = sorted(glob.glob(pattern), key=self._seg_index)
                now = time.perf_counter()
                with self._seg_lock:
                    for f in files:
                        idx = self._seg_index(f)
                        if idx >= 0 and idx not in self._seg_marks:
                            self._seg_marks[idx] = self._perf_of_file(f)
                    cutoff = now - keep_seconds
                    # Drop segments older than the keep window. Never touch the
                    # two newest (one is the active write target).
                    for f in files[:-2]:
                        idx = self._seg_index(f)
                        mark = self._seg_marks.get(idx)
                        if mark is not None and mark < cutoff:
                            try:
                                os.remove(f)
                            except OSError:
                                pass
                            self._seg_marks.pop(idx, None)
            except Exception:  # noqa: BLE001 - janitor is best-effort
                pass
            self._stop.wait(timeout=0.25)

    def save_window(
        self, t_end_perf: float, buffer_seconds: float, out_path: Path
    ) -> tuple[float, float]:
        """Concat the trailing segments overlapping the window into ``out_path``.

        Returns ``(t0_new_perf, duration_s)`` where ``t0_new_perf`` is the
        content-start of the earliest concatenated segment — the shared zero the
        caller rebases audio + events to. Buffering is undisturbed: we only read
        finalized + active segment files.
        """
        assert self._seg_dir is not None
        cutoff = t_end_perf - float(buffer_seconds)
        pattern = str(self._seg_dir / "seg_*.ts")
        files = sorted(glob.glob(pattern), key=self._seg_index)
        if not files:
            raise RuntimeError("no video segments buffered yet")

        with self._seg_lock:
            marks = dict(self._seg_marks)
            for f in files:
                idx = self._seg_index(f)
                if idx not in marks:
                    marks[idx] = self._perf_of_file(f)

        # A segment overlaps the window if its successor starts after the
        # cutoff (or it is the last segment). Walk newest→oldest, keep going
        # until a segment starts before the cutoff.
        included: list[str] = []
        for i in range(len(files) - 1, -1, -1):
            included.append(files[i])
            start = marks.get(self._seg_index(files[i]), t_end_perf)
            if start <= cutoff:
                break
        included.reverse()
        if not included:
            included = [files[-1]]

        t0_new = marks.get(self._seg_index(included[0]), cutoff)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        list_path = out_path.with_suffix(".segments.txt")
        list_path.write_text(
            "\n".join(f"file '{Path(p).as_posix()}'" for p in included),
            encoding="utf-8",
        )
        log_path = open(str(out_path) + ".concat.log", "wb")
        try:
            cmd = [
                get_ffmpeg_exe(),
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(out_path),
            ]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_path,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
        finally:
            log_path.close()
        if proc.returncode != 0 or not out_path.exists():
            raise RuntimeError("ffmpeg segment concat failed (see .concat.log)")
        try:
            list_path.unlink(missing_ok=True)
        except OSError:
            pass

        return t0_new, max(0.0, t_end_perf - t0_new)

    def frame_window(
        self, t0_new_perf: float, t_end_perf: float, frames_log_path: Path
    ) -> tuple[int, float, dict]:
        """Write frames.jsonl for the captured window and return its stats.

        Mirrors the per-frame log + frame_stats of a normal session but only
        for frames whose write-time falls inside ``[t0_new_perf, t_end_perf]``,
        rebased so the clip starts at ``t_video_s == 0``.
        """
        frames = [
            (t, d) for (t, d) in list(self._frame_ring)
            if t0_new_perf <= t <= t_end_perf
        ]
        frames_log_path.parent.mkdir(parents=True, exist_ok=True)
        intervals: list[float] = []
        with open(frames_log_path, "w", encoding="utf-8", newline="\n") as fh:
            for index, (t, delta_ms) in enumerate(frames):
                t_video = round(t - t0_new_perf, 4)
                # Drop the carried-over delta on the first kept frame — it spans
                # the gap before the window and would skew jitter stats.
                d = None if index == 0 else delta_ms
                if d is not None:
                    intervals.append(d)
                rec = {
                    "@timestamp": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "t_video_s": t_video,
                    "frame": {
                        "index": index,
                        "delta_ms": round(d, 3) if d is not None else None,
                    },
                    "ecs": {"version": "8.11"},
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        count = len(frames)
        effective_fps = 0.0
        if count >= 2:
            span = frames[-1][0] - frames[0][0]
            if span > 0:
                effective_fps = (count - 1) / span
        stats = self._intervals_stats(intervals)
        return count, effective_fps, stats

    @staticmethod
    def _intervals_stats(intervals: list[float]) -> dict:
        if not intervals:
            return {}
        sorted_iv = sorted(intervals)
        n = len(sorted_iv)
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

    # ---- scrcpy (Android) -------------------------------------------------

    def _run_scrcpy(
        self,
        target: AndroidDeviceTarget,
        *,
        first_frame_check: bool = False,
    ) -> None:
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

        # Optional first-frame probe used by the "auto" backend: if ffmpeg's
        # output file doesn't grow past the MP4 container header within the
        # timeout, scrcpy is silently failing (Android 16 / One UI 8 case)
        # and the caller should hot-swap to screenrecord.
        if first_frame_check:
            deadline = time.perf_counter() + self._ANDROID_FIRST_FRAME_TIMEOUT_S
            while time.perf_counter() < deadline:
                if self._stop.is_set():
                    break
                if scrcpy_proc.poll() is not None:
                    # scrcpy died during the probe — not the "no frames" case,
                    # fall through to the main loop which will surface it.
                    break
                try:
                    if (
                        self.output_path.exists()
                        and self.output_path.stat().st_size
                        >= self._ANDROID_FIRST_FRAME_MIN_BYTES
                    ):
                        first_frame_check = False  # we're good
                        break
                except OSError:
                    pass
                time.sleep(0.2)
            if first_frame_check:
                # Timeout fired without any real frames. Tear scrcpy down and
                # let the dispatcher catch this so it can retry with the
                # screenrecord backend.
                self._terminate_scrcpy()
                raise _ScrcpyNoFramesError(
                    "scrcpy did not emit frames within "
                    f"{self._ANDROID_FIRST_FRAME_TIMEOUT_S:.1f}s "
                    "(Android 16 / OEM-blocked hidden API?)"
                )

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
