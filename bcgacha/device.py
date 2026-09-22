"""Talk to a USB-attached iPhone: read the screen, and tap it.

Reading the screen works from iOS 17 upwards once Developer Mode is on and the
Developer Disk Image is mounted; on iOS 17.4+ the tunnel runs in userspace, so
none of this needs root.

Tapping is the half that is version-gated.  Apple's CoreDevice remote-control
feature, which is what supplies synthetic touches at absolute coordinates,
refuses with error 9021 below iOS 27.  `capabilities()` reports that up front
rather than letting a bot discover it mid-run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PMD3 = str(Path(__file__).resolve().parent.parent / ".venv" / "bin" / "pymobiledevice3")

# CoreDevice's refusal when the feature is not on this OS version.
REMOTE_CONTROL_UNSUPPORTED = 9021

# HID coordinates are normalised across the screen, independent of resolution.
HID_MAX = 65535


class DeviceError(RuntimeError):
    pass


@dataclass
class Capabilities:
    product_type: str
    ios_version: str
    developer_mode: bool
    ddi_mounted: bool
    can_screenshot: bool
    can_tap: bool
    tap_blocked_reason: str | None
    native_size: tuple[int, int] | None


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    exe = PMD3 if Path(PMD3).exists() else shutil.which("pymobiledevice3")
    if not exe:
        raise DeviceError("pymobiledevice3 not found")
    return subprocess.run(
        [exe, *args], capture_output=True, text=True, timeout=timeout
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


def lockdown_info() -> dict:
    proc = _run(["lockdown", "info"])
    if proc.returncode != 0 and not proc.stdout:
        raise DeviceError(f"no device: {_strip_ansi(proc.stderr)[:300]}")
    return _json_tail(proc.stdout)


def developer_mode_enabled() -> bool:
    return "true" in _strip_ansi(_run(["amfi", "developer-mode-status"]).stdout).lower()


def ddi_mounted() -> bool:
    out = _strip_ansi(_run(["mounter", "list"]).stdout)
    return "ImageSignature" in out or "Personalized" in out


def mount_ddi() -> None:
    proc = _run(["mounter", "auto-mount"], timeout=600)
    combined = _strip_ansi(proc.stdout + proc.stderr)
    if "mounted successfully" not in combined and "already mounted" not in combined.lower():
        raise DeviceError(f"DDI mount failed: {combined[-400:]}")


def display_info() -> dict:
    return _json_tail(_run(["developer", "core-device", "get-display-info"]).stdout)


def native_size() -> tuple[int, int] | None:
    for display in display_info().get("displays", []):
        if display.get("primary"):
            size = display.get("nativeSize") or []
            if len(size) == 2 and size[0]:
                return int(size[0]), int(size[1])
    return None


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

    Raises DeviceError carrying the OS requirement when the device predates the
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


def _version_tuple(version: str) -> tuple[int, ...]:
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
        if _version_tuple(info.get("ProductVersion", "0")) >= (27,):
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
