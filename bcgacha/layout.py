"""From a point on the landscape screen to a tap.

Coordinates are fractions of the frame, because the game authors to a fixed
landscape layout and stretches it to whatever aspect the device has. Taps are
sent in the HID's own 0..65535 normalised space, so a fraction converts
straight across without ever needing the pixel size.
"""

from __future__ import annotations

from .device import HID_MAX

# The two ways a landscape game can be held, as SpringBoard reports them: the
# phone turned one way, or the other. Screenshots arrive already turned the
# way the screen shows; touches do not, so which way matters for every tap.
LANDSCAPE, LANDSCAPE_OTHER_WAY = 3, 4
# Which way the attached phone is turned now; the device session keeps it true.
orientation = LANDSCAPE


def landscape_to_hid(x: float, y: float) -> tuple[int, int]:
    """Convert a landscape screen fraction to HID's normalised coordinates.

    The HID space is anchored to the device's NATIVE PORTRAIT frame, not to
    whatever orientation the app is drawing in. The Battle Cats is landscape
    only, so every coordinate here has to be rotated before it is sent.

    Sending landscape fractions straight through lands the tap somewhere else
    entirely: a tap meant for Storage at (0.172, 0.800) arrives at landscape
    (0.800, 0.828), which on the capsule screen is the Cat Food purchase.

    Which rotation depends on which way the phone is turned: held the other
    way, a tap meant for a panel's X at the top right lands on Back at the
    bottom left, and Back lands on the info button.
    """
    if orientation == LANDSCAPE_OTHER_WAY:
        return round(y * HID_MAX), round((1.0 - x) * HID_MAX)
    return round((1.0 - y) * HID_MAX), round(x * HID_MAX)
