"""From a point on the landscape screen to a tap.

Coordinates are fractions of the frame, because the game authors to a fixed
landscape layout and stretches it to whatever aspect the device has. Taps are
sent in the HID's own 0..65535 normalised space, so a fraction converts
straight across without ever needing the pixel size.
"""

from __future__ import annotations

from .device import HID_MAX


def landscape_to_hid(x: float, y: float) -> tuple[int, int]:
    """Convert a landscape screen fraction to HID's normalised coordinates.

    The HID space is anchored to the device's NATIVE PORTRAIT frame, not to
    whatever orientation the app is drawing in. The Battle Cats is landscape
    only, so every coordinate here has to be rotated before it is sent.

    Sending landscape fractions straight through lands the tap somewhere else
    entirely: a tap meant for Storage at (0.172, 0.800) arrives at landscape
    (0.800, 0.828), which on the capsule screen is the Cat Food purchase.
    """
    return round((1.0 - y) * HID_MAX), round(x * HID_MAX)
