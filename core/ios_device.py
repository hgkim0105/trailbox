"""iOS device discovery + helpers for the macOS iOS-capture build.

Sibling of ``core/adb.py`` (Android). Two data sources are crossed:

* **pymobiledevice3** (usbmux/lockdown) — gives the udid, device name and iOS
  version, and is the channel used later for syslog + metrics.
* **AVFoundation / CoreMediaIO** — the QuickTime "movie recording → iPhone"
  mechanism that exposes a tethered iPhone as a *muxed* capture device. This
  is the only frame-accurate USB screen path, and it is **macOS-only**.

Everything here imports its platform-only deps lazily inside the function that
needs them, so this module imports cleanly on every platform (the same rule
the recorders follow for dxcam / windows-capture / pyobjc). On non-macOS hosts
the discovery functions simply return empty / None.

pymobiledevice3 v9 turned the usbmux + lockdown surface async; we keep the
public callers (UI, bridge) sync by running the async probe via ``asyncio.run``
inside each facade. Side-effect-free, no shared event loop required.
"""
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class IOSDeviceInfo:
    udid: str
    name: str
    ios_version: str = ""
    capturable: bool = False   # True when AVFoundation also sees it (screen capturable)

    @property
    def label(self) -> str:
        """Human-readable label for the UI dropdown."""
        ver = f" (iOS {self.ios_version})" if self.ios_version else ""
        cap = "" if self.capturable else "  [화면 캡처 불가 — 신뢰/케이블 확인]"
        return f"{self.name}{ver}{cap}"


def _is_macos() -> bool:
    return sys.platform == "darwin"


# ---- CoreMediaIO: make tethered iPhones appear as capture devices ----------

def enable_screen_capture_devices() -> None:
    """Flip the CMIO property that surfaces iOS devices as capture devices.

    By default AVFoundation does not list a connected iPhone as a video
    capture device; QuickTime sets ``kCMIOHardwarePropertyAllowScreenCapture
    Devices = 1`` to reveal it. We do the same once before enumerating /
    capturing. No-op (and silent) off macOS.

    Needs on-device validation — the CMIO property-setting path is the part
    most likely to need iteration on real hardware.
    """
    if not _is_macos():
        return
    try:
        import ctypes
        import CoreMediaIO

        # pyobjc's CMIOObjectSetPropertyData binding can't marshal the trailing
        # ``const void *data`` (it raises "converting to a C array" for bytes /
        # array / memoryview / NSData alike on pyobjc 12.x), so the property set
        # silently no-op'd and the iPhone never surfaced as a screen-capture
        # device. Call the C function directly via ctypes instead — verified to
        # return OSStatus 0. (Constants are read from the pyobjc module so the
        # fourcc values stay correct.)
        cmio = ctypes.CDLL(
            "/System/Library/Frameworks/CoreMediaIO.framework/CoreMediaIO"
        )

        class _Addr(ctypes.Structure):
            _fields_ = [
                ("mSelector", ctypes.c_uint32),
                ("mScope", ctypes.c_uint32),
                ("mElement", ctypes.c_uint32),
            ]

        cmio.CMIOObjectSetPropertyData.restype = ctypes.c_int32
        addr = _Addr(
            int(CoreMediaIO.kCMIOHardwarePropertyAllowScreenCaptureDevices),
            int(CoreMediaIO.kCMIOObjectPropertyScopeGlobal),
            int(CoreMediaIO.kCMIOObjectPropertyElementMain),
        )
        val = ctypes.c_uint32(1)
        cmio.CMIOObjectSetPropertyData(
            ctypes.c_uint32(int(CoreMediaIO.kCMIOObjectSystemObject)),
            ctypes.byref(addr),
            ctypes.c_uint32(0),
            None,
            ctypes.c_uint32(4),
            ctypes.byref(val),
        )
    except Exception:  # noqa: BLE001 - best-effort; capture may still partly work
        pass


def _muxed_ios_screen_devices():
    """AVCaptureDevices that are the tethered iPhone's *screen* (not camera).

    The screen-capture device is a **muxed** device whose modelID is the
    literal ``"iOS Device"`` and whose name is the bare device name (e.g.
    ``형근의 iPhone``). The iPhone's Continuity Camera is a separate *video*
    device with a real hardware modelID (``iPhone18,1``) and a ``…카메라`` /
    ``…Camera`` name — capturing that gives the rear-camera feed, NOT the
    screen, which is the black-screen bug we hit. So we match on the muxed
    media type only.
    """
    if not _is_macos():
        return []
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeMuxed
        return list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed) or [])
    except Exception:  # noqa: BLE001
        return []


def trigger_screen_capture_devices(timeout: float = 5.0):
    """Make the tethered iPhone's screen device enumerate, returning a live
    "trigger" ``AVCaptureSession`` the caller MUST keep running until it has
    claimed the iPhone device (then stop it), or ``None`` on failure.

    On macOS 26 / iOS 26 the CMIO ``AllowScreenCaptureDevices`` flag is *not*
    enough on its own — the muxed ``iOS Device`` only materializes once some
    process actually **starts an AVCaptureSession** (this is what QuickTime's
    "New Movie Recording" was secretly doing). Starting a throwaway session on
    the built-in Mac camera reproduces that trigger; the iPhone screen device
    then appears and stays. Verified on-device 2026-06-07.

    The trigger session uses the built-in camera (so it needs Camera TCC, which
    the iOS capture path already requires). We hand the live session back rather
    than stopping it here so the device can't vanish in the gap before the real
    recording session claims it.
    """
    if not _is_macos():
        return None
    enable_screen_capture_devices()
    if _muxed_ios_screen_devices():
        return None  # already exposed (e.g. QuickTime open) — no trigger needed
    try:
        from AVFoundation import (
            AVCaptureSession,
            AVCaptureDevice,
            AVCaptureDeviceInput,
            AVMediaTypeVideo,
        )
        from Foundation import NSRunLoop, NSDate
    except Exception:  # noqa: BLE001
        return None

    builtin = None
    for d in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo) or []:
        try:
            if not _looks_like_ios_model(str(d.modelID())):
                builtin = d
                break
        except Exception:  # noqa: BLE001
            continue
    if builtin is None:
        return None

    session = AVCaptureSession.alloc().init()
    inp, _err = AVCaptureDeviceInput.deviceInputWithDevice_error_(builtin, None)
    if inp is None or not session.canAddInput_(inp):
        return None
    session.addInput_(inp)
    session.startRunning()

    rl = NSRunLoop.currentRunLoop()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if _muxed_ios_screen_devices():
            return session
        rl.runMode_beforeDate_(
            "kCFRunLoopDefaultMode", NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )
    try:
        session.stopRunning()
    except Exception:  # noqa: BLE001
        pass
    return None


# ---- Discovery --------------------------------------------------------------

async def _usbmux_devices_async() -> list[tuple[str, str, str]]:
    """[(udid, name, ios_version)] from pymobiledevice3 v9 (async usbmux/lockdown)."""
    try:
        from pymobiledevice3.usbmux import list_devices
        from pymobiledevice3.lockdown import create_using_usbmux
    except Exception:  # noqa: BLE001 - lib absent (non-mac dev box, etc.)
        return []

    try:
        devices = await list_devices()
    except Exception:  # noqa: BLE001 - usbmux daemon down / not running
        return []

    out: list[tuple[str, str, str]] = []
    for dev in devices:
        udid = getattr(dev, "serial", "") or getattr(dev, "udid", "")
        if not udid:
            continue
        name, ver = udid, ""
        ld = None
        try:
            ld = await create_using_usbmux(serial=udid)
            name = (await ld.get_value(key="DeviceName")) or udid
            ver = (await ld.get_value(key="ProductVersion")) or ""
        except Exception:  # noqa: BLE001 - device locked / not trusted yet
            pass
        finally:
            if ld is not None:
                try:
                    await ld.close()
                except Exception:  # noqa: BLE001
                    pass
        out.append((udid, name, ver))
    return out


def _usbmux_devices() -> list[tuple[str, str, str]]:
    """Sync facade so UI / bridge callers don't deal with asyncio."""
    try:
        return asyncio.run(_usbmux_devices_async())
    except Exception:  # noqa: BLE001
        return []


def _looks_like_ios_model(model_id: str) -> bool:
    """True for AVFoundation modelIDs that denote a tethered iOS device.

    A tethered iPhone reports modelID like ``iPhone18,1``; an iPad ``iPad…``.
    The Mac's own webcam reports a localized human string (e.g.
    ``MacBook Pro 카메라``), so this filter keeps built-in / USB webcams from
    being mistaken for a phone when we scan *Video* devices.
    """
    m = model_id.strip().lower()
    return m.startswith(("iphone", "ipad", "ipod"))


def _normalize_name(s: str) -> str:
    """Strip typographic quotes + collapse whitespace + lowercase.

    AVFoundation wraps the device name in curly quotes and appends a localized
    suffix (``'형근의 iPhone' 카메라`` / ``… Camera``); usbmux returns the bare
    ``형근의 iPhone``. Normalizing both makes one a substring of the other
    regardless of UI language.
    """
    for ch in ("‘", "’", "“", "”", "'", '"'):
        s = s.replace(ch, "")
    return " ".join(s.split()).lower()


def names_match(usbmux_name: str, avf_name: str) -> bool:
    """Whether a usbmux name and an AVFoundation localizedName refer to the
    same physical device (containment after normalization)."""
    u, a = _normalize_name(usbmux_name), _normalize_name(avf_name)
    return bool(u) and (u in a or a in u)


def _has_builtin_camera() -> bool:
    """True if a non-iOS video device exists to trigger screen capture with.

    The iPhone screen device only enumerates after we start a throwaway session
    on some other camera (see ``trigger_screen_capture_devices``). With no
    built-in/USB camera there's nothing to trigger with, so capture can't work.
    """
    if not _is_macos():
        return False
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
        for d in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo) or []:
            try:
                if not _looks_like_ios_model(str(d.modelID())):
                    return True
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return False


def list_devices() -> list[IOSDeviceInfo]:
    """Return connected iOS devices (from usbmux).

    ``capturable`` reflects whether the iPhone *screen* can be recorded. We do
    NOT enumerate AVFoundation here to decide it: the screen device only appears
    after a trigger session is started (which would flash the Mac camera on
    every dropdown refresh), and the only iOS device AVFoundation lists *without*
    the trigger is the Continuity **Camera** — recording that gives the rear
    camera, not the screen, so treating it as "capturable" was the source of the
    black-screen bug. Instead a usbmux device is capturable when we have a camera
    to trigger the screen device with at capture time. Off macOS, never.
    """
    usb = _usbmux_devices()
    can_trigger = _has_builtin_camera()
    return [
        IOSDeviceInfo(udid=udid, name=name, ios_version=ver, capturable=can_trigger)
        for udid, name, ver in usb
    ]


def get_foreground_app(udid: str) -> str | None:
    """Always None under pymobiledevice3 v9 — kept as a sync stub.

    v4 had ``DeviceInfo.foreground_running_process()`` which gave the
    frontmost bundle id straight from DVT; v9 removed it. The remaining DVT
    surfaces (``proclist`` / ``ApplicationListing.applist``) don't expose a
    direct frontmost flag, and rebuilding the heuristic isn't worth it for v1
    — the caller already handles None by falling back to ``"unknown"`` for
    the session id and skipping bundle-based metric filtering.

    Phase 2 UI work is the better place to fix this: let the user pick the
    bundle explicitly from the device's installed apps (we can get that via
    ``ApplicationListing.applist`` async) and pass it down as
    ``IOSDeviceTarget.bundle_id``.
    """
    return None
