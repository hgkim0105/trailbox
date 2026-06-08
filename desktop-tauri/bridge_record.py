"""Headless recording daemon for Tauri IPC.

Two capture modes share one bridge instance — each instance handles a single
session (recording mode) or a single buffering run that yields zero-or-many
clips (lookback mode), then exits.

Recording mode protocol:

    → {"cmd":"start","target":{"kind":"window","hwnd":123},"exe_path":"...","log_dirs":[],"max_fps":60,"audio":true,"input":true,"metrics":true}
    ← {"event":"started","session_id":"..."}
    ← {"event":"status","elapsed":1,"frames":30,"events":42,"cpu_pct":35.2,"rss_mb":210.4}
    ...
    → {"cmd":"stop"}
    ← {"event":"stopping"}
    ← {"event":"done","session_id":"...","duration":42.5,"frames":1280}
    ← {"event":"exit"}

Lookback mode protocol (Windows desktop targets only — Monitor / Window):

    → {"cmd":"start-buffering","target":{...},"buffer_seconds":30,"max_fps":60,"audio":true,"input":true,"metrics":true,"exe_path":"...","log_dirs":[]}
    ← {"event":"buffering","buffer_seconds":30}
    ← {"event":"status","elapsed":1,...}
    ...
    → {"cmd":"save-now"}
    ← {"event":"saved","session_id":"...","duration":30.0,"frames":900}
    ...   (more save-now calls may follow; buffer keeps running)
    → {"cmd":"stop-buffering"}
    ← {"event":"stopped"}
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


def _run_lookback(start_msg: dict) -> None:
    """Drive a LookbackController until ``stop-buffering``.

    The recording flow above is single-shot (start → stop → exit). Lookback
    inverts that: ``start-buffering`` spins up a continuously-running
    buffer, and the user can call ``save-now`` any number of times to
    materialize the trailing window into its own session. Each save returns
    the new ``session_id`` so the React UI can refresh the sessions list.
    """
    from core.lookback import (
        DEFAULT_BUFFER_SECONDS, MAX_BUFFER_SECONDS, MIN_BUFFER_SECONDS,
        LookbackConfig, LookbackController,
    )
    from core.screen_recorder import MonitorTarget, WindowTarget
    from core.system_info import gather as gather_system_info

    target_cfg = start_msg.get("target", {})
    kind = target_cfg.get("kind", "monitor")
    if kind == "window":
        hwnd = int(target_cfg.get("hwnd", 0) or 0)
        title = target_cfg.get("title", "")
        target = WindowTarget(hwnd=hwnd, title=title)
        window_hwnd = hwnd or None
    elif kind == "monitor":
        target = MonitorTarget(index=int(target_cfg.get("index", 0) or 0))
        window_hwnd = None
    else:
        _emit({
            "event": "error",
            "message": f"lookback supports window/monitor only (got '{kind}')",
        })
        return

    try:
        buffer_seconds = float(start_msg.get("buffer_seconds") or DEFAULT_BUFFER_SECONDS)
    except (TypeError, ValueError):
        buffer_seconds = float(DEFAULT_BUFFER_SECONDS)
    buffer_seconds = max(float(MIN_BUFFER_SECONDS), min(float(MAX_BUFFER_SECONDS), buffer_seconds))

    log_dirs = [Path(p) for p in start_msg.get("log_dirs", []) if p]
    extensions = frozenset(start_msg.get("log_extensions") or [".log", ".txt"])

    # Best-effort metrics PID resolution (window target only — matches what the
    # recording path does, see the metrics_pid block above).
    metrics_pid = None
    metrics_target_name = ""
    if start_msg.get("metrics", True) and window_hwnd:
        try:
            import win32process
            import psutil
            _, pid = win32process.GetWindowThreadProcessId(window_hwnd)
            if pid:
                metrics_pid = int(pid)
                try:
                    metrics_target_name = psutil.Process(metrics_pid).name() or ""
                except Exception:
                    pass
        except Exception:
            pass

    system_info = {}
    try:
        system_info = gather_system_info()
    except Exception:
        pass

    cfg = LookbackConfig(
        target=target,
        output_root=_output_root(),
        buffer_seconds=buffer_seconds,
        max_fps=int(start_msg.get("max_fps", 60) or 60),
        audio_enabled=bool(start_msg.get("audio", True)),
        input_enabled=bool(start_msg.get("input", True)),
        metrics_enabled=bool(start_msg.get("metrics", True)),
        metrics_pid=metrics_pid,
        metrics_target_name=metrics_target_name,
        log_dirs=log_dirs,
        log_recursive=bool(start_msg.get("log_recursive", True)),
        log_extensions=extensions,
        exe_path=start_msg.get("exe_path") or None,
        window_hwnd=window_hwnd,
        system_info=system_info,
    )

    controller = LookbackController(cfg)
    try:
        controller.start()
    except Exception as e:  # noqa: BLE001
        _emit({"event": "error", "message": f"buffer start failed: {e}"})
        return

    _emit({"event": "buffering", "buffer_seconds": buffer_seconds})

    # Inbound command queue — stdin reader drops commands onto this so the
    # main thread can pump status events without blocking on input.
    inbox: list[dict] = []
    inbox_lock = threading.Lock()
    stop_flag = threading.Event()

    def stdin_reader() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError:
                continue
            with inbox_lock:
                inbox.append(cmd)
            if cmd.get("cmd") == "stop-buffering":
                stop_flag.set()
                return

    reader_thread = threading.Thread(target=stdin_reader, daemon=True)
    reader_thread.start()

    start_perf = time.time()
    next_status_at = start_perf
    captures = 0
    try:
        while not stop_flag.is_set():
            # Drain pending commands.
            with inbox_lock:
                pending = inbox[:]
                inbox.clear()
            for cmd in pending:
                name = cmd.get("cmd")
                if name == "save-now":
                    try:
                        result = controller.capture()
                        captures += 1
                        _emit({
                            "event": "saved",
                            "session_id": str(result.session_dir.name),
                            "duration": round(result.duration_seconds, 2),
                            "frames": int(result.frames_written),
                            "errors": result.errors or [],
                        })
                    except Exception as e:  # noqa: BLE001
                        _emit({"event": "error", "message": f"save failed: {e}"})
                elif name == "stop-buffering":
                    stop_flag.set()
                # other commands ignored

            now = time.time()
            if now >= next_status_at:
                _emit({
                    "event": "status",
                    "elapsed": round(now - start_perf, 1),
                    "captures": captures,
                    "buffer_seconds": buffer_seconds,
                })
                next_status_at = now + 1.0

            stop_flag.wait(timeout=0.2)
    finally:
        try:
            controller.stop()
        except Exception:
            pass
        _emit({"event": "stopped", "captures": captures})
        _emit({"event": "exit"})


def main() -> int:
    from core.screen_recorder import (
        ScreenRecorder, WindowTarget, MonitorTarget, AndroidDeviceTarget,
        IOSDeviceTarget,
    )
    from core.audio_recorder import AudioRecorder
    from core.input_recorder import InputRecorder
    from core.ios_log_collector import IOSLogCollector
    from core.ios_metrics_recorder import IOSMetricsRecorder
    from core.log_collector import LogCollector
    from core.metrics_recorder import MetricsRecorder
    from core.post_mux import mux_av
    from core.session import Session
    from core.system_info import collect_ios_info, gather as gather_system_info
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

        cmd_name = msg.get("cmd")
        if cmd_name == "start-buffering":
            _run_lookback(msg)
            return 0
        if cmd_name != "start":
            _emit({"event": "error", "message": f"expected 'start' or 'start-buffering', got '{cmd_name}'"})
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
        elif kind == "ios":
            udid = target_cfg.get("udid", "")
            device_name = target_cfg.get("device_name", "")
            bundle_id = target_cfg.get("bundle_id") or None
            capture_audio = target_cfg.get("capture_audio", True)
            target = IOSDeviceTarget(
                udid=udid, device_name=device_name,
                bundle_id=bundle_id, capture_audio=capture_audio,
            )
        else:
            target = MonitorTarget(index=0)

        if not exe_path:
            exe_path = f"capture_{kind}"

        is_android = kind == "android"
        is_ios = kind == "ios"
        # iOS/Android are device captures → app_name stem instead of exe_path.
        if is_ios:
            app_name = f"ios_{(target_cfg.get('udid', 'dev') or 'dev')[:8]}"
        elif is_android:
            app_name = f"android_{target_cfg.get('serial', 'dev')}"
        else:
            app_name = None

        # Create session
        output_root = _output_root()
        session = Session(
            exe_path=exe_path if not (is_android or is_ios) else None,
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
            if is_ios:
                # Device-side snapshot instead of the host Mac profile.
                system_info = collect_ios_info(target_cfg.get("udid", ""))
            else:
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
        # iOS audio rides inside the AVFoundation .mov; a host AudioRecorder
        # here would wrongly capture the Mac's own output, so skip it.
        if audio_on and not is_ios:
            try:
                audio_rec = AudioRecorder(output_path=session.dir / AUDIO_TMP)
                audio_rec.start()
            except Exception:
                audio_rec = None

        log_collectors: list = []
        if is_ios:
            # Device unified log (os_log) → logs/syslog.jsonl + .vtt.
            try:
                bundle_id = target.bundle_id
                ios_log = IOSLogCollector(
                    udid=target.udid,
                    output_dir=session.dir / "logs",
                    t0_perf=t0_perf,
                    bundle_filter=bundle_id,
                )
                ios_log.start()
                log_collectors.append(ios_log)
            except Exception:
                pass
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
        # iOS exposes no host-side touch stream; a host InputRecorder would
        # capture the Mac's keyboard/mouse instead, so skip it on iOS.
        if input_on and not is_ios:
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
        if metrics_on and is_ios and target.bundle_id:
            # DVT instruments (sysmontap + graphics) → process.jsonl. Real-time
            # status gauges below stay flat (no host pid); the recorded metrics
            # file carries the real device CPU/GPU/FPS.
            try:
                metrics_rec = IOSMetricsRecorder(
                    udid=target.udid,
                    bundle_id=target.bundle_id,
                    output_path=session.dir / "metrics" / "process.jsonl",
                    t0_perf=t0_perf,
                    interval_s=1.0,
                )
                metrics_rec.start()
            except Exception:
                metrics_rec = None
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
