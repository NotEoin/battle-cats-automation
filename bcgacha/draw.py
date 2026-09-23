"""Decide whether the draw button is about to spend a ticket -- or Cat Food.

The "Try once!" button does not move when the tickets run out: the same button
in the same place starts spending 150 Cat Food, and nothing but its face says
so. The face is therefore read before every draw, from the button as this
device draws it, with nothing captured from another phone:

  - the icon: a gold (or, for Platinum, a silver-rainbow) ticket. The Cat
    Food can is red, and red has no business on a ticket button;
  - the cost: a single "1". Cat Food costs "150", three digits.

Both must pass. A button that cannot be found, or read either way, is refused.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# More red than this on the button face means the Cat Food can is on it.
RED_LIMIT = 0.004
# A digit is an outlined shape in the right half of the button at least this
# tall, as a share of the button's height.
DIGIT_HEIGHT = 0.30
# ... and at least this much area, as a share of the height squared: smaller
# enclosed specks are the outline's own gaps, not a digit.
DIGIT_AREA = 0.02
# The Cat Food can's red, in OpenCV HSV: hue wraps round, so two bands.
RED_BANDS = (((0, 120, 90), (9, 255, 255)), ((170, 120, 90), (180, 255, 255)))
# A digit's outline: anything this dark, whatever its hue.
OUTLINE_MAX_VALUE = 70


@dataclass
class Gate:
    """Whether the draw button may be pressed, and what its face showed."""

    ok: bool
    reason: str
    box: tuple | None = None
    tap: tuple | None = None
    red: float | None = None
    digits: int | None = None

    def to_json(self) -> dict:
        """The verdict as plain JSON, for the live page."""
        return dict(ok=self.ok, reason=self.reason, box=list(self.box) if self.box else None,
                    tap=list(self.tap) if self.tap else None,
                    red=None if self.red is None else round(self.red, 4), digits=self.digits)


def _crop(frame: np.ndarray, box) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[max(0, int(y0 * h)): int(y1 * h), max(0, int(x0 * w)): int(x1 * w)]


def red_share(face: np.ndarray) -> float:
    """The share of the button face that is Cat Food can red."""
    hsv = cv2.cvtColor(face, cv2.COLOR_BGR2HSV)
    (lo1, hi1), (lo2, hi2) = RED_BANDS
    red = cv2.inRange(hsv, lo1, hi1) | cv2.inRange(hsv, lo2, hi2)
    return float((red > 0).mean())


def cost_digits(face: np.ndarray) -> int:
    """How many digits the cost in the button's right half has."""
    h, w = face.shape[:2]
    right = face[:, w // 2:]
    dark = cv2.inRange(cv2.cvtColor(right, cv2.COLOR_BGR2HSV), (0, 0, 0), (180, 255, OUTLINE_MAX_VALUE))
    # Each digit is a filled glyph inside a dark outline: its fill is what is
    # enclosed by dark, so count enclosed bright blobs of a digit's height.
    inside = cv2.bitwise_not(dark)
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(inside, 8)
    count = 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches = x == 0 or y == 0 or x + bw >= right.shape[1] or y + bh >= h
        if not touches and bh >= DIGIT_HEIGHT * h and area >= DIGIT_AREA * h * h:
            count += 1
    return count


def check(frame: np.ndarray, button: dict | object | None) -> Gate:
    """Whether pressing `button` (a perceived or learned control with a box)
    spends one ticket. `button` None: the draw button was not found."""
    if button is None:
        return Gate(False, "the Try once! button was not found")
    box = button["box"] if isinstance(button, dict) else button.box
    tap = button["tap"] if isinstance(button, dict) else button.tap
    face = _crop(frame, box)
    if face.size == 0:
        return Gate(False, "the button is off the frame", box, tap)
    red = red_share(face)
    digits = cost_digits(face)
    if red > RED_LIMIT:
        return Gate(False, f"red on the button ({red:.1%}): the Cat Food can", box, tap, red, digits)
    if digits != 1:
        return Gate(False, f"the cost has {digits} digits, not the single 1 a ticket costs",
                    box, tap, red, digits)
    return Gate(True, "ticket icon, cost 1", box, tap, red, digits)
