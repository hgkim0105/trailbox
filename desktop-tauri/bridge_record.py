"""Headless recording daemon for Tauri IPC.

Protocol (JSON-lines over stdin/stdout):

    → {"cmd":"start","target":{"kind":"window","hwnd":123},"exe_path":"...","log_dirs":[],"max_fps":60,"audio":true,"input":true,"metrics":true}
    ← {"event":"started","session_id":"..."}
    ← {"event":"status","elapsed":1,"frames":30,"events":42,"cpu_pct":35.2,"rss_mb":210.4}
    ...
    → {"cmd":"stop"}
    ← {"event":"stopping"}
    ← {"event":"done","session_id":"...","duration":42.5,"frames":1280}
    ← {"event":"exit"}

Errors:
    ← {"event":"error","message":"..."}
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stdin.reconfigure(encoding="utf-8")   # type: ignore[union-attr]


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _output_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "output"
    return _REPO_ROOT / "output"


def main() -> int:
    from core.screen_recorder import ScreenRecorder, WindowTarget, MonitorTarget, AndroidDeviceTarget
    from core.audio_recorder import AudioRecorder
    from core.input_recorder import InputRecorder
    from core.log_collector import LogCollector
    from core.metrics_recorder import MetricsRecorder
    from core.post_mux import mux_av
    from core.session import Session
    from core.system_info import gather as gather_system_info
    from core.viewer_generator import generate_viewer

    VIDEO_TMP = "screen.video.mp4"
    AUDIO_TMP = "screen.audio.wav"
    FINAL_NAME = "screen.mp4"

    _emit({"event": "ready"})

    # Wait for start command
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _emit({"event": "error", "message": f"invalid JSON: {line}"})
            continue

        if msg.get("cmd") != "start":
            _emit({"event": "error", "message": f"expected 'start', got '{msg.get('cmd')}'"})
            continue

        # Parse config
        cfg = msg
        target_cfg = cfg.get("target", {})
        kind = target_cfg.get("kind", "monitor")
        exe_path = cfg.get("exe_path", "")
        log_dirs = [Path(p) for p in cfg.get("log_dirs", []) if p]
        max_fps = cfg.get("max_fps", 60)
        audio_on = cfg.get("audio", True)
        input_on = cfg.get("input", True)
        metrics_on = cfg.get("metrics", True)
        recursive = cfg.get("log_recursive", True)
        extensions = cfg.get("log_extensions", [".log", ".txt"])

        # Resolve target
        if kind == "window":
            hwnd = target_cfg.get("hwnd", 0)
            title = target_cfg.get("title", "")
            target = WindowTarget(hwnd=hwnd, title=title)
        elif kind == "android":
            serial = target_cfg.get("serial", "")
            capture_audio = target_cfg.get("capture_audio", True)
            backend = target_cfg.get("backend", "auto")
            target = AndroidDeviceTarget(
                serial=serial, package=None,
                capture_audio=capture_audio, backend=backend,
            )
        else:
            target = MonitorTarget(index=0)

        if not exe_path:
            exe_path = f"capture_{kind}"

        is_android = kind == "android"
        app_name = f"android_{target_cfg.get('serial', 'dev')}" if is_android else None

        # Create session
        output_root = _output_root()
        session = Session(
            exe_path=exe_path if not is_android else None,
            log_dir=str(log_dirs[0]) if log_dirs else None,
            output_root=output_root,
            target_pid=None,
            app_name=app_name,
        )
        try:
            session_id = session.start()
        except OSError as e:
            _emit({"event": "error", "message": f"session create failed: {e}"})
            continue

        system_info = {}
        try:
            system_info = gather_system_info()
        except Exception:
            pass

        t0_perf = time.perf_counter()

        # Start recorders
        screen_rec = ScreenRecorder(
            output_path=session.dir / VIDEO_TMP,
            target=target,
            max_fps=max_fps,
            frames_log_path=session.dir / "metrics" / "frames.jsonl",
        )
        try:
            screen_rec.start()
        except Exception as e:
            _emit({"event": "error", "message": f"screen recorder failed: {e}"})
            session.finalize(extra={"aborted": True, "error": str(e)})
            continue

        audio_rec = None
        if audio_on:
            try:
                audio_rec = AudioRecorder(output_path=session.dir / AUDIO_TMP)
                audio_rec.start()
            except Exception:
                audio_rec = None

        log_collectors: list = []
        if log_dirs:
            try:
                lc = LogCollector(
                    log_dirs=log_dirs,
                    output_dir=session.dir / "logs",
                    t0_perf=t0_perf,
                    recursive=recursive,
                    extensions=extensions,
                )
                lc.start()
                log_collectors.append(lc)
            except Exception:
                pass

        input_rec = None
        if input_on:
            try:
                window_hwnd = target.hwnd if isinstance(target, WindowTarget) else None
                input_rec = InputRecorder(
                    output_dir=session.dir / "inputs",
                    t0_perf=t0_perf,
                    window_hwnd=window_hwnd,
                )
                input_rec.start()
            except Exception:
                input_rec = None

        metrics_rec = None
        metrics_pid = None
        if metrics_on and kind == "window":
            hwnd_val = target_cfg.get("hwnd", 0)
            if hwnd_val:
                try:
                    import win32process
                    _, pid = win32process.GetWindowThreadProcessId(hwnd_val)
                    if pid:
                        metrics_pid = pid
                        metrics_rec = MetricsRecorder(
                            pid=pid,
                            output_path=session.dir / "metrics" / "process.jsonl",
                            t0_perf=t0_perf,
                            interval_s=1.0,
                        )
                        metrics_rec.start()
                except Exception:
                    pass

        _emit({"event": "started", "session_id": session_id})

        # Status loop — read stdin in a thread to watch for "stop"
        stop_flag = threading.Event()

        def stdin_reader():
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("cmd") == "stop":
                    stop_flag.set()
                    return

        reader_thread = threading.Thread(target=stdin_reader, daemon=True)
        reader_thread.start()

        # GPU monitor for real-time metrics
        gpu_mon = None
        if metrics_pid:
            try:
                from core.gpu_monitor import GpuMonitor
                gpu_mon = GpuMonitor(metrics_pid)
                gpu_mon.start()
            except Exception:
                gpu_mon = None

        start_time = time.time()
        while not stop_flag.is_set():
            stop_flag.wait(timeout=1.0)
            elapsed = time.time() - start_time
            frames = screen_rec.frames_written() if screen_rec else 0
            cpu_pct = 0.0
            rss_mb = 0.0
            gpu_pct = 0.0
            gpu_vram_mb = 0.0
            if metrics_pid:
                try:
                    import psutil
                    p = psutil.Process(metrics_pid)
                    cpu_pct = p.cpu_percent(interval=0) / (psutil.cpu_count() or 1)
                    rss_mb = p.memory_info().rss / (1024 * 1024)
                except Exception:
                    pass
            if gpu_mon:
                try:
                    gpu_data = gpu_mon.sample()
                    gpu_pct = gpu_data.get("gpu_pct", 0.0)
                    gpu_vram_mb = gpu_data.get("gpu_vram_mb", 0.0)
                except Exception:
                    pass
            _emit({
                "event": "status",
                "elapsed": round(elapsed, 1),
                "frames": frames,
                "cpu_pct": round(cpu_pct, 1),
                "rss_mb": round(rss_mb, 1),
                "gpu_pct": round(gpu_pct, 1),
                "gpu_vram_mb": round(gpu_vram_mb, 1),
            })

        # ── Stop recording ──
        _emit({"event": "stopping"})
        if gpu_mon:
            try:
                gpu_mon.stop()
            except Exception:
                pass

        frames_written = 0
        effective_fps = 0.0
        frame_stats: dict = {}
        recorder_error = None
        try:
            screen_rec.stop()
            frames_written = screen_rec.frames_written()
            effective_fps = screen_rec.effective_fps()
            frame_stats = screen_rec.frame_stats()
        except Exception as e:
            recorder_error = e

        audio_seconds = 0.0
        audio_device = ""
        audio_error = None
        if audio_rec:
            try:
                audio_rec.stop()
                audio_seconds = audio_rec.duration_seconds()
                audio_device = audio_rec.device_name()
            except Exception as e:
                audio_error = e

        log_lines = 0
        for coll in log_collectors:
            try:
                coll.stop()
                log_lines += coll.lines_written()
            except Exception:
                pass

        input_events = 0
        if input_rec:
            try:
                input_rec.stop()
                input_events = input_rec.events_written()
            except Exception:
                pass

        metric_samples = 0
        if metrics_rec:
            try:
                metrics_rec.stop()
                metric_samples = metrics_rec.samples_written()
            except Exception:
                pass

        # Post-mux
        video_tmp = session.dir / VIDEO_TMP
        audio_tmp = session.dir / AUDIO_TMP
        final = session.dir / FINAL_NAME
        if video_tmp.exists():
            if audio_tmp.exists() and audio_error is None:
                try:
                    mux_av(video_tmp, audio_tmp, final)
                    video_tmp.unlink(missing_ok=True)
                    audio_tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                try:
                    if final.exists():
                        final.unlink()
                    video_tmp.rename(final)
                except Exception:
                    pass

        # Finalize
        import psutil as _ps
        extra = {
            "max_fps": max_fps,
            "screen_frames": frames_written,
            "effective_fps": round(effective_fps, 2),
            "frame_stats": frame_stats,
            "system": system_info,
            "audio_enabled": audio_on,
            "audio_device": audio_device,
            "audio_seconds": round(audio_seconds, 1),
            "log_lines": log_lines,
            "log_dirs": [str(d) for d in log_dirs],
            "log_recursive": recursive,
            "log_extensions": extensions,
            "input_enabled": input_on,
            "input_events": input_events,
            "metrics_enabled": metrics_on,
            "metric_samples": metric_samples,
            "metrics_target_pid": metrics_pid,
            "cpu_cores": _ps.cpu_count(logical=True),
        }
        if recorder_error:
            extra["recorder_error"] = str(recorder_error)
        session.finalize(extra=extra)

        try:
            meta = json.loads((session.dir / "session_meta.json").read_text("utf-8"))
            generate_viewer(session.dir, meta)
        except Exception:
            pass

        duration = time.time() - start_time
        _emit({
            "event": "done",
            "session_id": session_id,
            "duration": round(duration, 1),
            "frames": frames_written,
            "log_lines": log_lines,
            "input_events": input_events,
        })
        _emit({"event": "exit"})
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
