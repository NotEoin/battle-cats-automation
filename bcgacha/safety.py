"""Guards that sit between the bot's intent and an actual tap.

The rule this module exists to enforce: never tap a coordinate without first
looking at what is underneath it. An early version of this project sent
landscape coordinates into a HID space anchored to the device's portrait frame,
so a tap meant for the Storage button arrived on the 11-draw purchase and put a
750 Cat Food confirmation on screen. The transform is fixed, but a bot that
taps blind will find another way to be wrong.

So every tap goes through `SafeTapper`, which screenshots first, confirms the
screen is the one the caller expects, and refuses anything it cannot verify.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import device, vision
from .layout import Target, landscape_to_hid

# Buttons on the game's confirmation dialogs, measured at full resolution.
DIALOG_YES = (0.4003, 0.6173)
DIALOG_NO = (0.5988, 0.6176)

DIALOG_TEXT_BOX = (0.30, 0.42, 0.72, 0.56)


class UnsafeTap(RuntimeError):
    """Raised rather than tapping something that was not verified."""


@dataclass
class Dialog:
    present: bool
    spends_cat_food: bool
    confidence: float


def _crop(frame: np.ndarray, box) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]


def _match(region: np.ndarray, template_name: str) -> float:
    path = vision.TEMPLATE_DIR / f"{template_name}.png"
    if not path.exists() or region.size == 0:
        return 0.0
    template = cv2.imread(str(path))
    if template.shape[:2] != region.shape[:2]:
        template = cv2.resize(template, (region.shape[1], region.shape[0]))
    return float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max())


def inspect_dialog(frame: np.ndarray) -> Dialog:
    """Is a confirmation dialog up, and would confirming it spend Cat Food?"""
    text = _crop(frame, DIALOG_TEXT_BOX)
    cat_food = _match(text, "dialog_catfood_text")
    frame_score = _match(_crop(frame, (0.28, 0.36, 0.72, 0.40)), "dialog_frame")
    return Dialog(
        present=frame_score > 0.7 or cat_food > 0.7,
        spends_cat_food=cat_food > 0.7,
        confidence=max(cat_food, frame_score),
    )


class SafeTapper:
    """Taps only after confirming what is on screen."""

    def __init__(self, capture_dir: Path | None = None, settle: float = 1.2):
        self.capture_dir = Path(capture_dir) if capture_dir else None
        self.settle = settle
        self._shot = 0

    def capture(self) -> np.ndarray:
        self._shot += 1
        if self.capture_dir:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            path = self.capture_dir / f"frame_{self._shot:05d}.png"
        else:
            path = Path("/tmp") / f"bcgacha_frame_{self._shot:05d}.png"
        device.screenshot(path)
        return vision.load(path)

    def tap(
        self,
        target: Target,
        expect: vision.Screen,
        require_anchor: str | None = None,
    ) -> np.ndarray:
        """Tap `target`, but only if the screen is `expect` first.

        Returns the frame captured *after* the tap.
        """
        before = self.capture()
        actual = vision.classify(before)
        if actual is not expect:
            raise UnsafeTap(
                f"refusing to tap {target.name}: expected {expect.value}, saw {actual.value}"
            )
        if require_anchor:
            score = vision.match(before, vision.ANCHORS[require_anchor])
            if score < vision.ANCHORS[require_anchor].threshold:
                raise UnsafeTap(
                    f"refusing to tap {target.name}: anchor {require_anchor} scored {score:.2f}"
                )
        dialog = inspect_dialog(before)
        if dialog.present:
            raise UnsafeTap(
                f"refusing to tap {target.name}: a dialog is already open "
                f"(cat food={dialog.spends_cat_food})"
            )
        device.tap(*target.hid())
        time.sleep(self.settle)
        return self.capture()

    def dismiss_dialog(self, frame: np.ndarray | None = None) -> bool:
        """Press No on whatever dialog is up. Never presses Yes."""
        frame = frame if frame is not None else self.capture()
        dialog = inspect_dialog(frame)
        if not dialog.present:
            return False
        device.tap(*landscape_to_hid(*DIALOG_NO))
        time.sleep(self.settle)
        return True
