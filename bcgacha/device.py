"""Talk to a USB-attached iPhone or iPad: read the screen, and tap it.

Reading the screen works from iOS 17 upwards once Developer Mode is on and the
Developer Disk Image is mounted; on iOS 17.4+ the tunnel runs in userspace, so
none of this needs root.

Tapping is the half that is version-gated.  Apple's CoreDevice remote-control
feature, which is what supplies synthetic touches at absolute coordinates,
refuses with error 9021 below iOS 27 (iPadOS 27 on an iPad).  `capabilities()`
reports that up front rather than letting a bot discover it mid-run.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# pymobiledevice3 run by the interpreter running bcgacha, so it is always the
# copy installed beside it, on any platform and in any kind of install.
PMD3 = [sys.executable, "-m", "pymobiledevice3"]

# CoreDevice's refusal when the feature is not on this OS version.
REMOTE_CONTROL_UNSUPPORTED = 9021

# HID coordinates are normalised across the screen, independent of resolution.
HID_MAX = 65535

# The long side over the short side of every screen bcgacha has been run on:
# 2532x1170, an iPhone 16e. Positions that are not learned were measured
# there, so another shape may need them checked.
TESTED_ASPECTS = (2532 / 1170,)
ASPECT_TOLERANCE = 0.02

# Seconds to wait for usbmuxd to list what is plugged in.
LIST_TIMEOUT = 10


class DeviceError(RuntimeError):
    """The phone is missing, refused, or cannot do what was asked."""


@dataclass
class Capabilities:
    """What the attached phone supports, and why tapping is blocked if it is."""

    product_type: str
    ios_version: str
    developer_mode: bool
    ddi_mounted: bool
    can_screenshot: bool
    can_tap: bool
    tap_blocked_reason: str | None
    native_size: tuple[int, int] | None


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*PMD3, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _json_tail(text: str):
    """Pull the JSON document out of output that also carries log lines."""
    text = _strip_ansi(text)
    start = text.find("{")
    if start < 0:
        raise DeviceError(f"no JSON in output: {text[:200]}")
    return json.loads(text[start:])


def attached() -> list[str]:
    """Serials of the iPhones and iPads plugged in by USB, found in a moment."""
    import asyncio

    from pymobiledevice3.usbmux import list_devices

    try:
        devices = asyncio.run(asyncio.wait_for(list_devices(), LIST_TIMEOUT))
    except Exception:  # no usbmuxd, or no answer from it, means nothing can be reached
        return []
    return [d.serial for d in devices if d.connection_type == "USB"]


def lockdown_info() -> dict:
    """The phone's lockdown record: model, OS version and the rest."""
    proc = _run(["lockdown", "info"])
    if proc.returncode != 0 and not proc.stdout:
        raise DeviceError(f"no device: {_strip_ansi(proc.stderr)[:300]}")
    return _json_tail(proc.stdout)


def developer_mode_enabled() -> bool:
    """True when Developer Mode is on."""
    return "true" in _strip_ansi(_run(["amfi", "developer-mode-status"]).stdout).lower()


def ddi_mounted() -> bool:
    """True when the Developer Disk Image is mounted."""
    out = _strip_ansi(_run(["mounter", "list"]).stdout)
    return "ImageSignature" in out or "Personalized" in out


def mount_ddi() -> None:
    """Mount the Developer Disk Image, which a restart of the phone takes off."""
    proc = _run(["mounter", "auto-mount"], timeout=600)
    combined = _strip_ansi(proc.stdout + proc.stderr)
    if "mounted successfully" not in combined and "already mounted" not in combined.lower():
        raise DeviceError(f"DDI mount failed: {combined[-400:]}")


def display_info() -> dict:
    """CoreDevice's description of the phone's displays."""
    return _json_tail(_run(["developer", "core-device", "get-display-info"]).stdout)


def native_size() -> tuple[int, int] | None:
    """The primary display's native pixel size, portrait, or None if unsaid."""
    for display in display_info().get("displays", []):
        if display.get("primary"):
            size = display.get("nativeSize") or []
            if len(size) == 2 and size[0]:
                return int(size[0]), int(size[1])
    return None


def reveal_developer_mode() -> None:
    """Make the Developer Mode switch appear in the device's Settings.

    iOS hides it until a developer tool has connected; this changes no
    setting itself.
    """
    proc = _run(["amfi", "reveal-developer-mode"])
    if proc.returncode != 0:
        raise DeviceError(f"could not reveal Developer Mode: {_strip_ansi(proc.stderr)[-300:]}")


def tested_shape(width: int, height: int) -> bool:
    """True when a screen of this size has the shape bcgacha was tested on."""
    aspect = max(width, height) / min(width, height)
    return any(abs(aspect - tested) <= ASPECT_TOLERANCE for tested in TESTED_ASPECTS)


def screenshot(dest: Path) -> Path:
    """Grab the screen as a PNG. Needs Developer Mode and a mounted DDI."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(["developer", "dvt", "screenshot", str(dest)], timeout=180)
    if not dest.exists() or dest.stat().st_size == 0:
        raise DeviceError(
            f"screenshot failed: {_strip_ansi(proc.stdout + proc.stderr)[-400:]}"
        )
    return dest


def tap(x: int, y: int) -> None:
    """Tap at normalised coordinates (0..65535 on both axes).

    Raises `DeviceError` carrying the OS requirement when the device predates the
    CoreDevice remote-control feature.
    """
    proc = _run(
        ["developer", "core-device", "universal-hid-service", "tap", str(x), str(y)],
        timeout=120,
    )
    combined = _strip_ansi(proc.stdout + proc.stderr)
    if f"code {REMOTE_CONTROL_UNSUPPORTED}" in combined or "iOS 27.0 or later" in combined:
        raise DeviceError(
            "synthetic touch needs iOS 27 or later (CoreDevice error 9021); "
            "this device cannot be tapped over USB"
        )
    if "ERROR" in combined:
        raise DeviceError(f"tap failed: {combined[-300:]}")


def tap_points(x: float, y: float, width: int, height: int) -> None:
    """Tap using pixel coordinates, converted to the normalised HID space."""
    tap(round(x / width * HID_MAX), round(y / height * HID_MAX))


def version_tuple(version: str) -> tuple[int, ...]:
    """`"27.0.1"` as `(27, 0, 1)`, stopping at the first part that is not a number."""
    out = []
    for part in version.split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)


def capabilities() -> Capabilities:
    """Probe what this device actually supports, without changing anything."""
    info = lockdown_info()
    dev_mode = developer_mode_enabled()
    mounted = ddi_mounted() if dev_mode else False

    size = None
    can_tap = False
    reason: str | None = None
    if mounted:
        try:
            size = native_size()
        except Exception as exc:  # display info is best-effort
            reason = f"display info unavailable: {exc}"
        # Decide by OS version rather than firing a probe tap: a real tap on a
        # live screen is not something a capability check should be doing.
        if version_tuple(info.get("ProductVersion", "0")) >= (27,):
            can_tap = True
        else:
            reason = (
                "CoreDevice remote control requires iOS 27.0 or later (error 9021)"
            )
    else:
        reason = "Developer Mode off or Developer Disk Image not mounted"

    return Capabilities(
        product_type=info.get("ProductType", "?"),
        ios_version=info.get("ProductVersion", "?"),
        developer_mode=dev_mode,
        ddi_mounted=mounted,
        can_screenshot=mounted,
        can_tap=can_tap,
        tap_blocked_reason=reason,
        native_size=size,
    )
