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

NOTE: the AVFoundation + CoreMediaIO calls require on-device validation on real
macOS + iPhone hardware; they cannot be exercised in CI / non-mac environments.
"""
from __future__ import annotations

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
        import objc
        import CoreMediaIO
        from Foundation import NSMutableData

        # kCMIOObjectSystemObject == 1; property selector is a 4-char-code.
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

def _usbmux_devices() -> list[tuple[str, str, str]]:
    """[(udid, name, ios_version)] from pymobiledevice3, or [] if unavailable."""
    try:
        from pymobiledevice3.usbmux import list_devices
        from pymobiledevice3.lockdown import create_using_usbmux
    except Exception:  # noqa: BLE001 - lib absent (non-mac dev box, etc.)
        return []

    out: list[tuple[str, str, str]] = []
    try:
        for dev in list_devices():
            udid = getattr(dev, "serial", "") or getattr(dev, "udid", "")
            if not udid:
                continue
            name, ver = udid, ""
            try:
                ld = create_using_usbmux(serial=udid)
                name = ld.get_value(key="DeviceName") or udid
                ver = ld.get_value(key="ProductVersion") or ""
            except Exception:  # noqa: BLE001 - device locked / not trusted yet
                pass
            out.append((udid, name, ver))
    except Exception:  # noqa: BLE001
        return out
    return out


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
    """Best-effort foreground app bundle id via pymobiledevice3, else None.

    Requires Developer Mode + a mounted Developer Disk Image on iOS 16+; returns
    None on any failure (the session still records, session_id falls back to
    'unknown').
    """
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import (
            DvtSecureSocketProxyService,
        )
        from pymobiledevice3.services.dvt.instruments.application_listing import (
            ApplicationListing,  # noqa: F401 - presence check
        )
    except Exception:  # noqa: BLE001
        return None

    try:
        ld = create_using_usbmux(serial=udid) if udid else create_using_usbmux()
        with DvtSecureSocketProxyService(ld) as dvt:
            from pymobiledevice3.services.dvt.instruments.device_info import DeviceInfo

            running = DeviceInfo(dvt).foreground_running_process()
            return getattr(running, "bundle_identifier", None) or running.get(
                "bundleIdentifier"
            )
    except Exception:  # noqa: BLE001
        return None
