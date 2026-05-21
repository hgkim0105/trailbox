"""Trailbox entry point: PyQt6 main window wiring launcher and recorder panels.

When invoked with ``--mcp-server`` (or via the Trailbox-mcp.exe build), the
entry point dispatches to the MCP stdio server BEFORE any Qt/dxcam imports,
so the same codebase ships as both a GUI binary and an MCP-server binary
without one path dragging the other path's deps into memory or touching
stdio at import time.
"""
from __future__ import annotations

__version__ = "0.4.0"

import sys

# Early dispatch: keep the MCP path free of Qt / dxcam / soundcard imports.
if __name__ == "__main__" and "--mcp-server" in sys.argv[1:]:
    from mcp_server.__main__ import mcp
    mcp.run()
    sys.exit(0)

import json
import os
import time
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

# IMPORTANT: screen_recorder (dxcam/comtypes) must import before audio_recorder
# (soundcard). soundcard initializes COM with a different threading mode, which
# makes the later comtypes init fail with "thread mode already set".
from core.screen_recorder import AndroidDeviceTarget, ScreenRecorder, WindowTarget
from core.system_info import collect_android_info, gather as gather_system_info
from core.android_input_recorder import AndroidInputRecorder
from core.android_log_collector import AndroidLogCollector
from core.android_metrics_recorder import AndroidMetricsRecorder
from core.audio_recorder import AudioRecorder
from core.global_hotkey import GlobalHotkey
from core.input_recorder import InputRecorder
from core.log_collector import LogCollector
from core.metrics_recorder import MetricsRecorder
from core.post_mux import mux_av
from core.session import Session
from core.viewer_generator import generate_viewer
from ui.launcher_panel import LauncherPanel
from ui.recorder_panel import RecorderPanel
from ui.recording_overlay import RecordingOverlay
from ui.session_picker import SessionPickerDialog

def _output_root() -> Path:
    """Where sessions are written.

    For PyInstaller-frozen builds, ``__file__`` is inside ``sys._MEIPASS``
    (the temp extract dir that's wiped on exit) — so output must resolve
    from ``sys.executable`` instead, giving ``<exe_dir>/output``. Matches
    how ``mcp_server`` finds the same folder when frozen.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "output"
    return Path(__file__).resolve().parent / "output"


OUTPUT_ROOT = _output_root()

VIDEO_TMP = "screen.video.mp4"
AUDIO_TMP = "screen.audio.wav"
FINAL_NAME = "screen.mp4"

STOP_HOTKEY = "<ctrl>+<alt>+r"
STOP_HOTKEY_LABEL = "Ctrl+Alt+R"


class TrailboxWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trailbox — 세션 레코더")
        self.resize(640, 420)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.launcher = LauncherPanel(central)
        self.recorder = RecorderPanel(central)
        layout.addWidget(self.launcher)
        layout.addWidget(self.recorder)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        self._session: Session | None = None
        self._system_info: dict = {}
        self._screen_recorder: ScreenRecorder | None = None
        self._audio_recorder: AudioRecorder | None = None
        # A session may carry several log collectors at once: an Android
        # logcat tail PLUS one or more PC LogCollectors watching server/log
        # folders. Each writes to its own *.jsonl under logs/, and the
        # viewer/MCP merge them by globbing.
        self._log_collectors: list = []
        self._input_recorder: InputRecorder | None = None
        self._metrics_recorder: MetricsRecorder | None = None
        self._overlay: RecordingOverlay | None = None
        self._stop_hotkey: GlobalHotkey | None = None
        # The PID/name MetricsRecorder is sampling — separate from
        # session.target_pid which only records app-launcher-spawned processes.
        self._metrics_target_pid: int | None = None
        self._metrics_target_name: str = ""

        self.launcher.app_launched.connect(self._on_app_launched)
        self.recorder.start_requested.connect(self._on_start_requested)
        self.recorder.stop_requested.connect(self._on_stop_requested)
        self.recorder.view_requested.connect(self._on_view_requested)

    def _on_app_launched(self, pid: int, exe_path: str) -> None:
        self.statusBar().showMessage(f"앱 실행됨 (PID {pid}): {exe_path}", 5000)

    def _resolve_target_pid(self, target) -> int | None:
        """Pick the most-likely target PID for telemetry.

        Priority: launcher-launched app > selected window's PID. Returns None
        when only monitor capture is configured and no app was launched.
        """
        pid = self.launcher.launched_pid()
        if pid:
            return pid
        if isinstance(target, WindowTarget):
            info = self.launcher.selected_window_info()
            if info is not None:
                return int(info.pid)
        return None

    def _on_start_requested(self) -> None:
        target = self.launcher.capture_target()
        if target is None:
            QMessageBox.warning(self, "Trailbox", "캡처할 창을 선택하세요.")
            return

        # ---- Android branch ----
        # Resolve foreground package + audio capability up-front so the
        # session_id reflects the actual app, and so we don't hand scrcpy a
        # capture_audio=True target on Android <11 (which would just fail).
        if isinstance(target, AndroidDeviceTarget):
            from core import adb as _adb

            try:
                package = target.package or _adb.get_foreground_package(target.serial)
            except Exception:  # noqa: BLE001 - probe is best-effort
                package = None
            package = package or "unknown"

            try:
                sdk = _adb.get_android_sdk(target.serial)
            except Exception:  # noqa: BLE001
                sdk = None
            backend = target.backend
            # Audio: scrcpy backend on Android 11+ (API 30) captures system
            # output; screenrecord backend has no audio support at all.
            # "auto" might resolve to either at runtime — set the flag as if
            # scrcpy will run; the screenrecord path ignores it anyway.
            if backend == "screenrecord":
                capture_audio = False
            else:  # scrcpy or auto
                capture_audio = target.capture_audio and (sdk is None or sdk >= 30)
            target = AndroidDeviceTarget(
                serial=target.serial,
                package=package,
                capture_audio=capture_audio,
                backend=backend,
            )

            # Friendly session-id stem: "android_<serial>_<pkg>"; the safe-name
            # regex in Session strips anything not [A-Za-z0-9_.-].
            stem = f"android_{target.serial}_{package}"

            session = Session(
                exe_path=None,
                log_dir=None,
                output_root=OUTPUT_ROOT,
                target_pid=None,
                app_name=stem,
            )
            try:
                session_id = session.start()
            except OSError as e:
                QMessageBox.critical(self, "Trailbox", f"세션 폴더 생성 실패:\n{e}")
                return

            self._session = session
            max_fps = self.launcher.capture_fps()

            # Same transitional UI as the PC branch — scrcpy spin-up is
            # also a 1-2s sync blocker, so without this the button click
            # looks like a no-op.
            self.recorder.set_transitioning("starting")
            QApplication.processEvents()

            # Device-side snapshot replaces the host PC profile for Android
            # sessions; same JSON shape so the viewer stays branch-free.
            try:
                self._system_info = collect_android_info(target.serial)
            except Exception:  # noqa: BLE001
                self._system_info = {"capture": "android"}

            t0_perf = time.perf_counter()

            # Direct-to-FINAL_NAME because scrcpy already remuxes a single
            # video+audio container; the post_mux step in stop is skipped
            # naturally when VIDEO_TMP doesn't exist on disk.
            screen_recorder = ScreenRecorder(
                output_path=session.dir / FINAL_NAME,
                target=target,
                max_fps=max_fps,
                frames_log_path=None,  # scrcpy path doesn't expose per-frame timing
            )
            try:
                screen_recorder.start()
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Trailbox", f"화면 녹화 시작 실패:\n{e}")
                session.finalize(
                    extra={"aborted": True, "error": str(e), "max_fps": max_fps}
                )
                self._session = None
                self.recorder.set_recording(False)
                return
            self._screen_recorder = screen_recorder

            # scrcpy already muxes audio into the same MP4, so no separate
            # AudioRecorder on this branch.
            self._audio_recorder = None
            self._log_collectors = []
            self._input_recorder = None
            self._metrics_recorder = None
            self._metrics_target_pid = None
            self._metrics_target_name = ""

            # Logcat → logcat.jsonl + logcat.vtt. Pid-filter to package_filter
            # to keep noise down; falls back to whole-device capture if pidof
            # can't resolve (e.g. app not foregrounded yet). Always on for
            # Android — there's no per-app log-folder setting to honor.
            try:
                logcat_collector = AndroidLogCollector(
                    serial=target.serial,
                    output_dir=session.dir / "logs",
                    t0_perf=t0_perf,
                    package_filter=package if package != "unknown" else None,
                )
                logcat_collector.start()
                self._log_collectors.append(logcat_collector)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Trailbox", f"Android logcat 시작 실패 (계속 진행):\n{e}"
                )

            # Additionally watch any PC-side log folders the user added (e.g.
            # a server log share). Writes to logs.jsonl alongside logcat.jsonl
            # — the viewer source filter keeps them togglable separately.
            android_log_dirs = [Path(p) for p in self.launcher.log_dirs()]
            if android_log_dirs:
                pc_log_collector = LogCollector(
                    log_dirs=android_log_dirs,
                    output_dir=session.dir / "logs",
                    t0_perf=t0_perf,
                    recursive=self.launcher.log_recursive(),
                    extensions=self.launcher.log_extensions(),
                )
                try:
                    pc_log_collector.start()
                    self._log_collectors.append(pc_log_collector)
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(
                        self, "Trailbox",
                        f"PC 로그 폴더 수집 시작 실패 (계속 진행):\n{e}",
                    )

            if self.launcher.input_enabled():
                try:
                    from core import adb as _adb_size
                    screen_size = _adb_size.get_screen_size(target.serial)
                except Exception:  # noqa: BLE001
                    screen_size = None
                try:
                    input_recorder = AndroidInputRecorder(
                        serial=target.serial,
                        output_dir=session.dir / "inputs",
                        t0_perf=t0_perf,
                        screen_size=screen_size,
                    )
                    input_recorder.start()
                    self._input_recorder = input_recorder
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(
                        self, "Trailbox",
                        f"Android getevent 시작 실패 (계속 진행):\n{e}",
                    )

            if self.launcher.metrics_enabled():
                try:
                    metrics_recorder = AndroidMetricsRecorder(
                        serial=target.serial,
                        package=package,  # initial guess; follow_foreground updates
                        output_path=session.dir / "metrics" / "process.jsonl",
                        t0_perf=t0_perf,
                        interval_s=1.0,
                        # Always follow on Android: the user typically starts
                        # recording from the launcher and then opens an app.
                        # Locking to whatever was foreground at start would
                        # miss the real target every time.
                        follow_foreground=True,
                    )
                    metrics_recorder.start()
                    self._metrics_recorder = metrics_recorder
                    self._metrics_target_name = package
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(
                        self, "Trailbox",
                        f"Android 텔레메트리 시작 실패 (계속 진행):\n{e}",
                    )

            self.recorder.set_recording(True)
            self.recorder.set_session_id(session_id)
            if backend == "auto":
                audio_status = "오디오 = backend 결과에 따라 (auto)"
            elif capture_audio:
                audio_status = "오디오 ON (scrcpy output)"
            elif backend == "screenrecord":
                audio_status = "오디오 OFF (screenrecord 한계)"
            elif sdk is not None and sdk < 30:
                audio_status = "오디오 OFF (Android 10 이하)"
            else:
                audio_status = "오디오 OFF"
            log_status = f"로그 {len(self._log_collectors)}개" if self._log_collectors else "로그 OFF"
            input_status = "입력 ON" if self._input_recorder else "입력 OFF"
            metrics_status = "메트릭 ON" if self._metrics_recorder else "메트릭 OFF"
            self.statusBar().showMessage(
                f"녹화 시작: {session.dir} (Android {target.serial} / {package} / {backend}, "
                f"max {max_fps}fps, {audio_status}, {log_status}, {input_status}, {metrics_status})",
                5000,
            )

            self._overlay = RecordingOverlay(stop_hotkey_label=STOP_HOTKEY_LABEL)
            self._overlay.begin()
            self._stop_hotkey = GlobalHotkey(STOP_HOTKEY)
            self._stop_hotkey.triggered.connect(self._on_stop_requested)
            self._stop_hotkey.start()
            return

        # ---- Desktop (monitor / window) branch ----
        exe_path = self.launcher.exe_path()
        if not exe_path:
            info = self.launcher.selected_window_info()
            if info is not None:
                exe_path = info.process_name or info.title
            else:
                QMessageBox.warning(
                    self, "Trailbox", "대상 실행 파일을 지정하거나 캡처할 창을 선택하세요."
                )
                return

        session = Session(
            exe_path=exe_path,
            log_dir=self.launcher.log_dir() or None,
            output_root=OUTPUT_ROOT,
            target_pid=self.launcher.launched_pid(),
        )
        try:
            session_id = session.start()
        except OSError as e:
            QMessageBox.critical(self, "Trailbox", f"세션 폴더 생성 실패:\n{e}")
            return

        self._session = session
        max_fps = self.launcher.capture_fps()
        audio_on = self.launcher.audio_enabled()

        # Show transitional UI ("🟡 준비 중…") + flush the repaint before the
        # synchronous recorder spin-up runs. Without processEvents the button
        # press appears to do nothing for ~1-2s until set_recording(True) below.
        self.recorder.set_transitioning("starting")
        QApplication.processEvents()

        # Snapshot host PC profile once at start (OS/CPU/RAM/GPU/displays).
        # Stashed on self so finalize can include it in the meta JSON.
        self._system_info = gather_system_info()

        # t0 = the perf_counter instant log entries are timestamped against.
        # Capture it just before starting the screen recorder so log offsets
        # align with the first written video frame within a few ms.
        t0_perf = time.perf_counter()

        screen_recorder = ScreenRecorder(
            output_path=session.dir / VIDEO_TMP,
            target=target,
            max_fps=max_fps,
            frames_log_path=session.dir / "metrics" / "frames.jsonl",
        )
        try:
            screen_recorder.start()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Trailbox", f"화면 녹화 시작 실패:\n{e}")
            session.finalize(
                extra={"aborted": True, "error": str(e), "max_fps": max_fps}
            )
            self._session = None
            # Roll the panel back from "준비 중…" to "대기 중".
            self.recorder.set_recording(False)
            return
        self._screen_recorder = screen_recorder

        if audio_on:
            audio_recorder = AudioRecorder(output_path=session.dir / AUDIO_TMP)
            try:
                audio_recorder.start()
                self._audio_recorder = audio_recorder
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Trailbox", f"오디오 녹음 실패 (계속 진행):\n{e}"
                )

        log_dirs = [Path(p) for p in self.launcher.log_dirs()]
        if log_dirs:
            log_collector = LogCollector(
                log_dirs=log_dirs,
                output_dir=session.dir / "logs",
                t0_perf=t0_perf,
                recursive=self.launcher.log_recursive(),
                extensions=self.launcher.log_extensions(),
            )
            try:
                log_collector.start()
                self._log_collectors.append(log_collector)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Trailbox", f"로그 수집 시작 실패 (계속 진행):\n{e}"
                )

        if self.launcher.input_enabled():
            window_hwnd = target.hwnd if isinstance(target, WindowTarget) else None
            input_recorder = InputRecorder(
                output_dir=session.dir / "inputs",
                t0_perf=t0_perf,
                window_hwnd=window_hwnd,
            )
            try:
                input_recorder.start()
                self._input_recorder = input_recorder
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Trailbox", f"입력 기록 시작 실패 (계속 진행):\n{e}"
                )

        target_pid = self._resolve_target_pid(target)
        self._metrics_target_pid = None
        self._metrics_target_name = ""
        if self.launcher.metrics_enabled() and target_pid is not None:
            metrics_recorder = MetricsRecorder(
                pid=target_pid,
                output_path=session.dir / "metrics" / "process.jsonl",
                t0_perf=t0_perf,
                interval_s=1.0,
            )
            try:
                metrics_recorder.start()
                self._metrics_recorder = metrics_recorder
                self._metrics_target_pid = target_pid
                # Record the process name so later analysis can tell which
                # PID was sampled (Chrome browser process vs GPU child process
                # look very different at the metrics level).
                try:
                    import psutil as _ps
                    self._metrics_target_name = _ps.Process(target_pid).name()
                except Exception:  # noqa: BLE001
                    pass
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Trailbox",
                    f"텔레메트리 시작 실패 (계속 진행):\n{e}",
                )

        self.recorder.set_recording(True)
        self.recorder.set_session_id(session_id)
        audio_status = "오디오 ON" if self._audio_recorder else "오디오 OFF"
        log_status = "로그 ON" if self._log_collector else "로그 OFF"
        input_status = "입력 ON" if self._input_recorder else "입력 OFF"
        self.statusBar().showMessage(
            f"녹화 시작: {session.dir} (max {max_fps}fps, "
            f"{audio_status}, {log_status}, {input_status})",
            5000,
        )

        # On-screen "● REC" overlay (visible over windowed/borderless games)
        # + global stop hotkey active only while recording.
        self._overlay = RecordingOverlay(stop_hotkey_label=STOP_HOTKEY_LABEL)
        self._overlay.begin()
        self._stop_hotkey = GlobalHotkey(STOP_HOTKEY)
        self._stop_hotkey.triggered.connect(self._on_stop_requested)
        self._stop_hotkey.start()

    def _on_stop_requested(self) -> None:
        session = self._session
        if session is None:
            self.recorder.set_recording(False)
            return

        # "⏳ 마무리 중…" before the recorder teardown + post-mux begins.
        # processEvents flushes the repaint; the dot animation will tick
        # in the gaps between sync steps below (it freezes during mux_av,
        # but the static label is enough to tell the user we're working).
        self.recorder.set_transitioning("stopping")
        QApplication.processEvents()

        # Immediately tear down the overlay + hotkey so the user gets visual
        # feedback before the (potentially multi-second) mux/finalize chain.
        if self._overlay is not None:
            self._overlay.end()
            self._overlay.deleteLater()
            self._overlay = None
        if self._stop_hotkey is not None:
            self._stop_hotkey.stop()
            self._stop_hotkey = None

        recorder_error: Exception | None = None
        audio_error: Exception | None = None
        mux_error: Exception | None = None

        frames_written = 0
        effective_fps = 0.0
        frame_stats: dict = {}
        if self._screen_recorder is not None:
            try:
                self._screen_recorder.stop()
                frames_written = self._screen_recorder.frames_written()
                effective_fps = self._screen_recorder.effective_fps()
                frame_stats = self._screen_recorder.frame_stats()
            except Exception as e:  # noqa: BLE001
                recorder_error = e
            self._screen_recorder = None

        audio_seconds = 0.0
        audio_device = ""
        if self._audio_recorder is not None:
            try:
                self._audio_recorder.stop()
                audio_seconds = self._audio_recorder.duration_seconds()
                audio_device = self._audio_recorder.device_name()
            except Exception as e:  # noqa: BLE001
                audio_error = e
            self._audio_recorder = None

        log_lines = 0
        log_error: Exception | None = None
        # Stop every collector even if one of them raises — we don't want a
        # crashed logcat to leave a PC LogCollector running, or vice versa.
        for coll in self._log_collectors:
            try:
                coll.stop()
                log_lines += coll.lines_written()
            except Exception as e:  # noqa: BLE001
                # Keep the first error for surfacing; later ones we just log
                # silently (the partial files we already wrote are still
                # usable, and the warning dialog only shows one anyway).
                if log_error is None:
                    log_error = e
        self._log_collectors = []

        input_events = 0
        input_error: Exception | None = None
        if self._input_recorder is not None:
            try:
                self._input_recorder.stop()
                input_events = self._input_recorder.events_written()
            except Exception as e:  # noqa: BLE001
                input_error = e
            self._input_recorder = None

        metric_samples = 0
        metric_error: Exception | None = None
        if self._metrics_recorder is not None:
            try:
                self._metrics_recorder.stop()
                metric_samples = self._metrics_recorder.samples_written()
                # For Android follow_foreground sessions the target package
                # drifts during the recording. Read the last-tracked value
                # so session_meta.metrics_target_name reflects what was
                # actually sampled at the end, not what __init__ saw.
                if hasattr(self._metrics_recorder, "current_package"):
                    last_pkg = self._metrics_recorder.current_package()
                    if last_pkg:
                        self._metrics_target_name = last_pkg
            except Exception as e:  # noqa: BLE001
                metric_error = e
            self._metrics_recorder = None

        # Mux video + audio (or just rename video) into final screen.mp4.
        video_tmp = session.dir / VIDEO_TMP
        audio_tmp = session.dir / AUDIO_TMP
        final = session.dir / FINAL_NAME

        # Pump events so the "⏳ 마무리 중…" animation advances a frame
        # before ffmpeg blocks the event loop during mux_av.
        QApplication.processEvents()

        if video_tmp.exists():
            if audio_tmp.exists() and audio_error is None:
                try:
                    mux_av(video_tmp, audio_tmp, final)
                    # Intermediate files removed after a successful mux.
                    video_tmp.unlink(missing_ok=True)
                    audio_tmp.unlink(missing_ok=True)
                except Exception as e:  # noqa: BLE001
                    mux_error = e
                    # Leave intermediates so the user has something to recover.
            else:
                # No audio: just rename the video to final.
                try:
                    if final.exists():
                        final.unlink()
                    video_tmp.rename(final)
                except OSError as e:
                    mux_error = e

        meta_path = session.finalize(
            extra={
                "max_fps": self.launcher.capture_fps(),
                "screen_frames": frames_written,
                "effective_fps": round(effective_fps, 2),
                "frame_stats": frame_stats,
                "system": self._system_info,
                "audio_enabled": self.launcher.audio_enabled(),
                "audio_device": audio_device,
                "audio_seconds": round(audio_seconds, 2),
                "log_lines": log_lines,
                "log_dirs": self.launcher.log_dirs(),
                "log_recursive": self.launcher.log_recursive(),
                "log_extensions": sorted(self.launcher.log_extensions()) or ["*"],
                "input_enabled": self.launcher.input_enabled(),
                "input_events": input_events,
                "metrics_enabled": self.launcher.metrics_enabled(),
                "metric_samples": metric_samples,
                "metrics_target_pid": self._metrics_target_pid,
                "metrics_target_name": self._metrics_target_name,
                # For Android sessions the cores belong to the *device*, not
                # the host PC running Trailbox. Source from the system_info
                # snapshot (which is device-side on Android, host on PC) so
                # the viewer header reflects whichever was actually captured.
                "cpu_cores": (
                    (self._system_info.get("cpu") or {}).get("logical_cores")
                    or os.cpu_count()
                ),
                **({"screen_error": str(recorder_error)} if recorder_error else {}),
                **({"audio_error": str(audio_error)} if audio_error else {}),
                **({"mux_error": str(mux_error)} if mux_error else {}),
                **({"log_error": str(log_error)} if log_error else {}),
                **({"input_error": str(input_error)} if input_error else {}),
                **({"metric_error": str(metric_error)} if metric_error else {}),
            }
        )

        # Generate self-contained viewer.html (best-effort; don't fail the session).
        viewer_error: Exception | None = None
        try:
            meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
            generate_viewer(session.dir, meta_obj)
        except Exception as e:  # noqa: BLE001
            viewer_error = e

        self.recorder.set_recording(False)
        self.recorder.set_session_id(None)
        self.statusBar().showMessage(
            f"세션 저장됨: {meta_path} (frames: {frames_written}, "
            f"~{round(effective_fps, 1)}fps)",
            8000,
        )

        errs = [
            e
            for e in (
                recorder_error,
                audio_error,
                mux_error,
                log_error,
                input_error,
                metric_error,
                viewer_error,
            )
            if e is not None
        ]
        if errs:
            QMessageBox.warning(
                self, "Trailbox", "녹화 중 일부 오류:\n" + "\n".join(str(e) for e in errs)
            )

        if self.recorder.auto_upload_enabled():
            from ui.hub_dialogs import auto_upload_session
            auto_upload_session(session.dir, self)

        self._session = None

    def _on_view_requested(self) -> None:
        """Show the session picker dialog; open chosen session's viewer.html."""
        dialog = SessionPickerDialog(OUTPUT_ROOT, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        selected = dialog.selected_session()
        if selected is None:
            return
        self._open_session_viewer(selected)

    def _open_session_viewer(self, session_dir: Path) -> None:
        viewer = session_dir / "viewer.html"
        if not viewer.exists():
            meta_path = session_dir / "session_meta.json"
            if not meta_path.exists():
                QMessageBox.warning(
                    self, "Trailbox", f"메타 파일이 없어 뷰어 생성 불가:\n{session_dir}"
                )
                return
            try:
                meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
                generate_viewer(session_dir, meta_obj)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Trailbox", f"뷰어 생성 실패:\n{e}")
                return
        try:
            os.startfile(str(viewer))
        except OSError as e:
            QMessageBox.critical(self, "Trailbox", f"뷰어 열기 실패:\n{e}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.launcher.stop_pickers()
        if self._screen_recorder is not None:
            try:
                self._screen_recorder.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._audio_recorder is not None:
            try:
                self._audio_recorder.stop()
            except Exception:  # noqa: BLE001
                pass
        for coll in self._log_collectors:
            try:
                coll.stop()
            except Exception:  # noqa: BLE001
                pass
        self._log_collectors = []
        if self._input_recorder is not None:
            try:
                self._input_recorder.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._metrics_recorder is not None:
            try:
                self._metrics_recorder.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._stop_hotkey is not None:
            try:
                self._stop_hotkey.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._overlay is not None:
            try:
                self._overlay.end()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)


def _icon_path() -> Path:
    """Locate the bundled trailbox.ico (works for source + PyInstaller).

    PyInstaller extracts ``--add-data`` payloads to ``sys._MEIPASS``; in
    source layout the file lives at ``assets/trailbox.ico``.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    return base / "assets" / "trailbox.ico"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Trailbox")
    icon_file = _icon_path()
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))
    window = TrailboxWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
