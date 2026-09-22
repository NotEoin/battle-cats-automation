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

from . import vision
from .layout import Target, landscape_to_hid
from .session import DeviceSession
from .timing import Humaniser

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

    def __init__(
        self,
        session: DeviceSession,
        capture_dir: Path | None = None,
        settle: float = 0.45,
        humaniser: Humaniser | None = None,
    ):
        self.session = session
        self.capture_dir = Path(capture_dir) if capture_dir else None
        self.settle = settle
        self.human = humaniser or Humaniser()
        self._shot = 0

    def capture(self, keep: bool = False) -> np.ndarray:
        """Grab a frame. Frames are kept only when asked, to save disk."""
        frame = self.session.screenshot()
        self._shot += 1
        if keep and self.capture_dir:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(self.capture_dir / f"frame_{self._shot:05d}.png"), frame)
        return frame

    def wait_for(
        self,
        wanted: "vision.Screen | set",
        timeout: float = 25.0,
        poll: float = 0.35,
    ) -> np.ndarray | None:
        """Poll until one of `wanted` is on screen. None on timeout.

        Polling beats sleeping a fixed time: Uber and Legend reveals animate for
        noticeably longer than Rare ones, so any constant is either too slow for
        the common case or too short for the interesting one.
        """
        targets = wanted if isinstance(wanted, set) else {wanted}
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.capture()
            if vision.classify(frame) in targets:
                return frame
            time.sleep(poll)
        return None

    def tap(
        self,
        target: Target,
        expect: vision.Screen,
        require_anchor: str | None = None,
        frame: np.ndarray | None = None,
    ) -> np.ndarray:
        """Tap `target`, but only if the screen is `expect` first.

        Pass `frame` when the caller has already looked: re-capturing would
        both cost a round trip and open a race, because the screen can move
        between the caller's decision and this check, which then refuses a tap
        that was perfectly valid when it was chosen.

        Returns the frame captured *after* the tap.
        """
        before = frame if frame is not None else self.capture()
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
        self.session.tap(*self.human.jitter_point(*target.hid()))
        self.human.sleep(self.settle)
        return self.capture()

    def confirm_dialog(self, frame: np.ndarray | None = None) -> bool:
        """Press Yes on a dialog. Only for prompts that spend nothing.

        Refuses outright if the dialog is the Cat Food one, so a mis-sequenced
        call can never buy anything.
        """
        frame = frame if frame is not None else self.capture()
        dialog = inspect_dialog(frame)
        if not dialog.present:
            return False
        if dialog.spends_cat_food:
            raise UnsafeTap("refusing to confirm a Cat Food purchase")
        self.session.tap(*self.human.jitter_point(*landscape_to_hid(*DIALOG_YES)))
        self.human.sleep(self.settle)
        return True

    def dismiss_dialog(self, frame: np.ndarray | None = None) -> bool:
        """Press No on whatever dialog is up. Never presses Yes."""
        frame = frame if frame is not None else self.capture()
        dialog = inspect_dialog(frame)
        if not dialog.present:
            return False
        self.session.tap(*self.human.jitter_point(*landscape_to_hid(*DIALOG_NO)))
        self.human.sleep(self.settle)
        return True
