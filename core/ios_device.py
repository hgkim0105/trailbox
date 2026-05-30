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
        import CoreMediaIO
        from Foundation import NSMutableData

        prop = CoreMediaIO.CMIOObjectPropertyAddress(
            CoreMediaIO.kCMIOHardwarePropertyAllowScreenCaptureDevices,
            CoreMediaIO.kCMIOObjectPropertyScopeGlobal,
            CoreMediaIO.kCMIOObjectPropertyElementMain,
        )
        enable = NSMutableData.dataWithLength_(4)
        # write uint32(1) into the buffer
        enable.replaceBytesInRange_withBytes_length_((0, 4), b"\x01\x00\x00\x00", 4)
        CoreMediaIO.CMIOObjectSetPropertyData(
            CoreMediaIO.kCMIOObjectSystemObject, prop, 0, None, 4, enable
        )
    except Exception:  # noqa: BLE001 - best-effort; capture may still partly work
        pass


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


def _avfoundation_capture_names() -> set[str]:
    """Localized names of AVFoundation muxed (iOS) capture devices, or empty."""
    if not _is_macos():
        return set()
    try:
        enable_screen_capture_devices()
        from AVFoundation import AVCaptureDevice, AVMediaTypeMuxed

        names: set[str] = set()
        for dev in AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed) or []:
            try:
                names.add(str(dev.localizedName()))
            except Exception:  # noqa: BLE001
                continue
        return names
    except Exception:  # noqa: BLE001
        return set()


def list_devices() -> list[IOSDeviceInfo]:
    """Return connected iOS devices, cross-referencing usbmux + AVFoundation.

    ``capturable`` is True when AVFoundation also sees the device by name (i.e.
    screen capture should work). usbmux-only devices still appear so the UI can
    explain why capture is unavailable (untrusted / wrong cable).
    """
    usb = _usbmux_devices()
    cap_names = _avfoundation_capture_names()
    out: list[IOSDeviceInfo] = []
    for udid, name, ver in usb:
        out.append(
            IOSDeviceInfo(
                udid=udid,
                name=name,
                ios_version=ver,
                capturable=name in cap_names,
            )
        )
    # AVFoundation may surface a device usbmux missed (e.g. usbmux race on
    # first plug-in). Add capture-only entries so the user can still record.
    known = {d.name for d in out}
    for name in cap_names - known:
        out.append(IOSDeviceInfo(udid="", name=name, capturable=True))
    return out


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
