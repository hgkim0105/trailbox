"""Probe: can we trigger the iPhone *screen* (muxed 'iOS Device') to appear
WITHOUT QuickTime?

Diagnosis so far: the iPhone screen-capture device only shows up in
AVFoundation enumeration while QuickTime actively runs a capture session. The
CMIO ``AllowScreenCaptureDevices`` flag alone (now set correctly via ctypes) is
not enough on this macOS. Hypothesis: QuickTime's act of *starting an
AVCaptureSession* is what makes coremediaiod scan USB and expose the iPhone
screen device. This script tests that by starting a throwaway session on the
built-in Mac camera, then polling for the muxed iPhone device.

Run from your OWN Terminal.app (needs the Camera permission you granted):

    cd /Users/hgkim/Projects/trailbox
    .venv/bin/python scripts/ios_trigger_probe.py

Keep the iPhone unlocked, screen ON. Paste the full output back.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Foundation import NSRunLoop, NSDate
from AVFoundation import (
    AVCaptureSession,
    AVCaptureDevice,
    AVCaptureDeviceInput,
    AVMediaTypeMuxed,
    AVMediaTypeVideo,
)

from core import ios_device


def muxed():
    return [(str(d.localizedName()), str(d.modelID()))
            for d in (AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed) or [])]


def pump(secs):
    rl = NSRunLoop.currentRunLoop()
    end = time.perf_counter() + secs
    while time.perf_counter() < end:
        rl.runMode_beforeDate_("kCFRunLoopDefaultMode",
                               NSDate.dateWithTimeIntervalSinceNow_(0.1))


def main():
    ios_device.enable_screen_capture_devices()
    print("[0] CMIO flag set. muxed before trigger:", muxed())

    # Find the built-in Mac camera to start a throwaway session on.
    builtin = None
    for d in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo) or []:
        if not ios_device._looks_like_ios_model(str(d.modelID())):
            builtin = d
            break
    print("[1] built-in camera:", str(builtin.localizedName()) if builtin else None)
    if builtin is None:
        print("    no built-in camera to trigger with — aborting")
        return

    session = AVCaptureSession.alloc().init()
    inp, err = AVCaptureDeviceInput.deviceInputWithDevice_error_(builtin, None)
    if inp is None:
        print("    couldn't make camera input:", err)
        return
    if session.canAddInput_(inp):
        session.addInput_(inp)
    print("[2] starting throwaway camera session...")
    session.startRunning()
    print("    isRunning:", session.isRunning())

    # Poll for the iPhone screen device to materialize while the session runs.
    for i in range(20):  # ~10s
        pump(0.5)
        m = muxed()
        print(f"    {(i+1)*0.5:.1f}s muxed={m}")
        if m:
            print(">>> SUCCESS: iPhone screen device appeared via dummy session!")
            break
    else:
        print(">>> no muxed screen device appeared (trigger hypothesis failed)")

    session.stopRunning()
    print("[3] done. muxed after stop:", muxed())


if __name__ == "__main__":
    main()
