"""Trailbox entry point: PyQt6 main window wiring launcher and recorder panels.

When invoked with ``--mcp-server`` (or via the Trailbox-mcp.exe build), the
entry point dispatches to the MCP stdio server BEFORE any Qt/dxcam imports,
so the same codebase ships as both a GUI binary and an MCP-server binary
without one path dragging the other path's deps into memory or touching
stdio at import time.
"""
from __future__ import annotations

__version__ = "0.1.1"

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
from PyQt6.QtGui import QCloseEvent
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
from core.screen_recorder import ScreenRecorder, WindowTarget
from core.audio_recorder import AudioRecorder
from core.input_recorder import InputRecorder
from core.log_collector import LogCollector
from core.metrics_recorder import MetricsRecorder
from core.post_mux import mux_av
from core.session import Session
from core.viewer_generator import generate_viewer
from ui.launcher_panel import LauncherPanel
from ui.recorder_panel import RecorderPanel
from ui.session_picker import SessionPickerDialog

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"

VIDEO_TMP = "screen.video.mp4"
AUDIO_TMP = "screen.audio.wav"
FINAL_NAME = "screen.mp4"


class TrailboxWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trailbox - QA Session Recorder")
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
        self._screen_recorder: ScreenRecorder | None = None
        self._audio_recorder: AudioRecorder | None = None
        self._log_collector: LogCollector | None = None
        self._input_recorder: InputRecorder | None = None
        self._metrics_recorder: MetricsRecorder | None = None

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

        # t0 = the perf_counter instant log entries are timestamped against.
        # Capture it just before starting the screen recorder so log offsets
        # align with the first written video frame within a few ms.
        t0_perf = time.perf_counter()

        screen_recorder = ScreenRecorder(
            output_path=session.dir / VIDEO_TMP,
            target=target,
            max_fps=max_fps,
        )
        try:
            screen_recorder.start()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Trailbox", f"화면 녹화 시작 실패:\n{e}")
            session.finalize(
                extra={"aborted": True, "error": str(e), "max_fps": max_fps}
            )
            self._session = None
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

        log_dir = self.launcher.log_dir()
        if log_dir:
            log_collector = LogCollector(
                log_dir=Path(log_dir),
                output_dir=session.dir / "logs",
                t0_perf=t0_perf,
            )
            try:
                log_collector.start()
                self._log_collector = log_collector
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

    def _on_stop_requested(self) -> None:
        session = self._session
        if session is None:
            self.recorder.set_recording(False)
            return

        recorder_error: Exception | None = None
        audio_error: Exception | None = None
        mux_error: Exception | None = None

        frames_written = 0
        effective_fps = 0.0
        if self._screen_recorder is not None:
            try:
                self._screen_recorder.stop()
                frames_written = self._screen_recorder.frames_written()
                effective_fps = self._screen_recorder.effective_fps()
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
        if self._log_collector is not None:
            try:
                self._log_collector.stop()
                log_lines = self._log_collector.lines_written()
            except Exception as e:  # noqa: BLE001
                log_error = e
            self._log_collector = None

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
            except Exception as e:  # noqa: BLE001
                metric_error = e
            self._metrics_recorder = None

        # Mux video + audio (or just rename video) into final screen.mp4.
        video_tmp = session.dir / VIDEO_TMP
        audio_tmp = session.dir / AUDIO_TMP
        final = session.dir / FINAL_NAME

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
                "audio_enabled": self.launcher.audio_enabled(),
                "audio_device": audio_device,
                "audio_seconds": round(audio_seconds, 2),
                "log_lines": log_lines,
                "input_enabled": self.launcher.input_enabled(),
                "input_events": input_events,
                "metrics_enabled": self.launcher.metrics_enabled(),
                "metric_samples": metric_samples,
                "cpu_cores": os.cpu_count(),
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
        if self._log_collector is not None:
            try:
                self._log_collector.stop()
            except Exception:  # noqa: BLE001
                pass
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
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Trailbox")
    window = TrailboxWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
