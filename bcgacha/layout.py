"""Where things are on the Rare Capsule screen.

Coordinates are fractions of the frame, because the game authors to a fixed
landscape layout and stretches it to whatever aspect the device has. Taps are
sent in the HID's own 0..65535 normalised space, so a fraction converts
straight across without ever needing the pixel size.

Measured against a 2532x1170 capture from an iPhone 16e.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class Target:
    """A tappable point, as a fraction of the landscape screen."""

    name: str
    x: float
    y: float

    def hid(self) -> tuple[int, int]:
        return landscape_to_hid(self.x, self.y)


CAPSULE_SCREEN = {
    "try_once": Target("try_once", 0.694, 0.779),
    "storage": Target("storage", 0.172, 0.800),
    "back": Target("back", 0.084, 0.890),
    "info": Target("info", 0.927, 0.125),
    "banner_prev": Target("banner_prev", 0.035, 0.400),
    "banner_next": Target("banner_next", 0.963, 0.400),
}

# The carousel tabs are variable width and scroll once there are more banners
# than fit, so their centres move. Prefer the prev/next arrows, which step one
# banner at a time and can be confirmed against the banner name afterwards.
# These are the observed centres on a four-tab carousel, for reference only.
BANNER_TABS = [
    Target(f"tab_{i}", x, 0.120)
    for i, x in enumerate((0.168, 0.295, 0.459, 0.605))
]


def all_targets() -> dict[str, Target]:
    out = dict(CAPSULE_SCREEN)
    out.update({t.name: t for t in BANNER_TABS})
    return out


STORAGE_SCREEN = {
    "back": Target("back", 0.088, 0.877),
    "use_all": Target("use_all", 0.474, 0.900),
    "exchange_all": Target("exchange_all", 0.628, 0.900),
}


RESULT_SCREEN = {
    "ok": Target("ok", 0.7355, 0.8139),
    "use_now": Target("use_now", 0.220, 0.814),
    "exchange": Target("exchange", 0.296, 0.814),
}


# The "Sent to Cat Storage" notice that follows each draw. Its Ok is nowhere
# near the result screen's Ok, so it needs its own target.
SENT_TO_STORAGE_SCREEN = {
    "ok": Target("ok", 0.6501, 0.6265),
}


# The Platinum Capsules screen. Its draw button sits well right of the Rare
# Capsule one and carries a Platinum Ticket icon, so it needs its own target
# and its own template -- the rare-capsule safety check correctly refuses it.
PLATINUM_SCREEN = {
    "try_once": Target("try_once", 0.855, 0.776),
    "storage": Target("storage", 0.172, 0.800),
    "back": Target("back", 0.091, 0.872),
}
