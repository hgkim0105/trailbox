"""iOS screen-capture diagnostic — pinpoints why the .mov comes out empty.

Run from your OWN Terminal.app (so the Camera TCC grant attaches to a process
that can show the prompt), NOT via an embedded shell:

    cd /Users/hgkim/Projects/trailbox
    .venv/bin/python scripts/ios_capture_diag.py

Unlock the iPhone and keep its screen ON while it runs. Paste the full output
back. This deliberately re-implements the AVCaptureSession wiring inline (with
verbose prints) instead of calling ScreenRecorder, so every step is visible.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow `python scripts/ios_capture_diag.py` from anywhere: put the project
# root (this file's parent's parent) on sys.path so `core` imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Foundation import NSURL, NSObject, NSRunLoop, NSDate
from AVFoundation import (
    AVCaptureSession,
    AVCaptureDevice,
    AVCaptureDeviceInput,
    AVCaptureMovieFileOutput,
    AVMediaTypeMuxed,
    AVMediaTypeVideo,
    AVMediaTypeAudio,
)

from core import ios_device


def p(*a):
    print(*a, flush=True)


def main() -> None:
    status_map = {0: "notDetermined", 1: "restricted", 2: "denied", 3: "authorized"}
    cam = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo)
    p(f"[auth] camera = {status_map.get(cam, cam)} ({cam})")
    if cam != 3:
        p("  -> request access (answer the prompt if it appears)")
        done = []
        AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            AVMediaTypeVideo, lambda g: done.append(g)
        )
        rl = NSRunLoop.currentRunLoop()
        t = time.perf_counter() + 60
        while not done and time.perf_counter() < t:
            rl.runMode_beforeDate_("kCFRunLoopDefaultMode",
                                   NSDate.dateWithTimeIntervalSinceNow_(0.1))
        cam = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo)
        p(f"[auth] camera now = {status_map.get(cam, cam)} ({cam})")
        if cam != 3:
            p("  !! still not authorized — grant Terminal in System Settings > "
              "Privacy & Security > Camera, then re-run.")
            return

    ios_device.enable_screen_capture_devices()

    # Enumerate every candidate device, both media types.
    p("\n[devices] AVMediaTypeMuxed:")
    for d in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed) or []:
        p(f"    muxed name={d.localizedName()!r} model={d.modelID()!r}")
    p("[devices] AVMediaTypeVideo:")
    for d in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo) or []:
        p(f"    video name={d.localizedName()!r} model={d.modelID()!r} "
          f"connected={d.isConnected()}")

    muxed = next((d for d in (AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed) or [])
                  if ios_device._looks_like_ios_model(str(d.modelID()))), None)
    if muxed is not None:
        video_dev = muxed
        p(f"\n[pick] using MUXED device: {video_dev.localizedName()!r}")
    else:
        video_dev = next((d for d in (AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo) or [])
                          if ios_device._looks_like_ios_model(str(d.modelID()))), None)
        p(f"\n[pick] using VIDEO device: "
          f"{video_dev.localizedName()!r}" if video_dev else "[pick] NO iOS device!")
    if video_dev is None:
        return

    # Active format / frame-rate ranges.
    try:
        fmt = video_dev.activeFormat()
        p(f"[format] activeFormat = {fmt}")
        for r in (fmt.videoSupportedFrameRateRanges() or []):
            p(f"    fps range: min={r.minFrameRate()} max={r.maxFrameRate()}")
    except Exception as e:  # noqa: BLE001
        p(f"[format] error: {e!r}")

    session = AVCaptureSession.alloc().init()
    p(f"\n[session] sessionPreset = {session.sessionPreset()!r}")

    dev_input, err = AVCaptureDeviceInput.deviceInputWithDevice_error_(video_dev, None)
    p(f"[input] deviceInput = {dev_input!r} err = {err!r}")
    if dev_input is None:
        return
    p(f"[input] canAddInput = {session.canAddInput_(dev_input)}")
    session.addInput_(dev_input)

    movie_out = AVCaptureMovieFileOutput.alloc().init()
    p(f"[output] canAddOutput = {session.canAddOutput_(movie_out)}")
    session.addOutput_(movie_out)

    # Inspect the connection between input and movie output.
    conns = movie_out.connections() or []
    p(f"[conn] movie_out has {len(conns)} connection(s)")
    for c in conns:
        try:
            p(f"    active={c.isActive()} enabled={c.isEnabled()} "
              f"mediaType(s)={[str(p_.mediaType()) for p_ in (c.inputPorts() or [])]}")
        except Exception as e:  # noqa: BLE001
            p(f"    conn introspect error: {e!r}")

    finished = []
    err_box = {}

    class Delegate(NSObject):
        def captureOutput_didStartRecordingToOutputFileAtURL_fromConnections_(self, o, u, c):  # noqa: N802,E501
            p(f"[delegate] didStart -> {u.path()}")

        def captureOutput_didFinishRecordingToOutputFileAtURL_fromConnections_error_(self, o, u, c, e):  # noqa: N802,E501
            if e is not None:
                err_box["msg"] = str(e.localizedDescription())
                err_box["full"] = str(e)
            p(f"[delegate] didFinish error={e!r}")
            finished.append(True)

    delegate = Delegate.alloc().init()

    out = Path("output/_ios_diag")
    out.mkdir(parents=True, exist_ok=True)
    mov = out / "diag.mov"
    if mov.exists():
        mov.unlink()
    mov_url = NSURL.fileURLWithPath_(str(mov))

    p("\n[run] startRunning()")
    session.startRunning()
    p(f"[run] session.isRunning = {session.isRunning()}")
    # Let the session warm up a beat before recording (USB devices need it).
    rl = NSRunLoop.currentRunLoop()
    for _ in range(10):
        rl.runMode_beforeDate_("kCFRunLoopDefaultMode",
                               NSDate.dateWithTimeIntervalSinceNow_(0.1))
    p(f"[run] session.isRunning after warmup = {session.isRunning()}")

    # Re-check connection state after the session is live.
    for c in (movie_out.connections() or []):
        try:
            p(f"[conn-live] active={c.isActive()} enabled={c.isEnabled()}")
        except Exception:  # noqa: BLE001
            pass

    p("[run] startRecordingToOutputFileURL")
    movie_out.startRecordingToOutputFileURL_recordingDelegate_(mov_url, delegate)

    for i in range(12):  # ~6s
        rl.runMode_beforeDate_("kCFRunLoopDefaultMode",
                               NSDate.dateWithTimeIntervalSinceNow_(0.5))
        d = movie_out.recordedDuration()
        ts = getattr(d, "timescale", 0)
        secs = (d.value / ts) if ts else 0.0
        size = mov.stat().st_size if mov.exists() else 0
        p(f"  t~{(i+1)*0.5:.1f}s recordedDuration={secs:.3f}s "
          f"isRecording={movie_out.isRecording()} mov_bytes={size}")

    p("[run] stopRecording")
    movie_out.stopRecording()
    deadline = time.perf_counter() + 15
    while not finished and movie_out.isRecording() and time.perf_counter() < deadline:
        rl.runMode_beforeDate_("kCFRunLoopDefaultMode",
                               NSDate.dateWithTimeIntervalSinceNow_(0.1))

    size = mov.stat().st_size if mov.exists() else 0
    p(f"\n[result] mov exists={mov.exists()} bytes={size}")
    if err_box:
        p(f"[result] delegate error: {err_box.get('msg')}")
        p(f"[result] delegate error (full): {err_box.get('full')}")
    p("[result] run `ffprobe output/_ios_diag/diag.mov` to inspect tracks.")

    session.stopRunning()


if __name__ == "__main__":
    main()
