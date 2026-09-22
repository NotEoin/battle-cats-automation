"""Delays that do not look like a machine's.

A bot that acts on an exact cadence is trivially separable from a person, and
PONOS's terms name automation tools explicitly. Every wait here is drawn from a
distribution rather than being a constant, and occasionally a longer pause is
inserted the way a human glancing away would produce one.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .device import HID_MAX

# No wait falls below this share of its mean, however the draw lands: a
# near-zero pause is as machine-like as a constant one.
FLOOR = 0.35


@dataclass
class Humaniser:
    """Jittered delays. `scale` below 1 speeds everything up proportionally."""

    scale: float = 1.0
    enabled: bool = True
    # Roughly one in this many waits becomes a longer "distraction" pause.
    distraction_odds: int = 40
    distraction_range: tuple[float, float] = (1.5, 4.0)

    def delay(self, mean: float, spread: float = 0.35) -> float:
        """A positive, jittered delay around `mean` seconds."""
        if not self.enabled:
            return mean * self.scale
        value = random.gauss(mean, mean * spread)
        value = max(mean * FLOOR, value)
        if random.randint(1, self.distraction_odds) == 1:
            value += random.uniform(*self.distraction_range)
        return value * self.scale

    def sleep(self, mean: float, spread: float = 0.35) -> float:
        """Wait a jittered delay around `mean` seconds, and return how long."""
        seconds = self.delay(mean, spread)
        time.sleep(seconds)
        return seconds

    def jitter_point(self, x: int, y: int, radius: int = 420) -> tuple[int, int]:
        """Scatter a tap within a button rather than hitting one exact pixel.

        Radius is in HID units (0..65535 across the screen), so ~420 is a
        handful of pixels -- comfortably inside a button, never outside it.
        """
        if not self.enabled:
            return x, y
        return (
            max(0, min(HID_MAX, x + random.randint(-radius, radius))),
            max(0, min(HID_MAX, y + random.randint(-radius, radius))),
        )
