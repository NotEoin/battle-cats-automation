"""Identify and change the banner selected on the Rare Capsule screen.

The planner is free to choose a different banner at every position, but that is
only worth anything if the bot can actually get there. The screen carries a
carousel of tabs across the top and a subtitle line under the artwork naming the
event; the subtitle is the reliable identifier, because tab positions shift as
the carousel scrolls.

Like the Cat Guide's arrows, the capsule screen's banner arrows ignore synthetic
taps, so the carousel is driven by flicking it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz, process

from .data import Banner, Dataset
from .layout import landscape_to_hid
from .session import DeviceSession

# The event subtitle, directly under the banner artwork.
SUBTITLE_BOX = (0.16, 0.545, 0.84, 0.610)
# The tab strip, flicked to move between banners.
CAROUSEL_Y = 0.120


@dataclass
class BannerPicker:
    session: DeviceSession
    dataset: Dataset
    ocr: object | None = None

    def _engine(self):
        if self.ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self.ocr = RapidOCR()
        return self.ocr

    def read_subtitle(self, frame: np.ndarray) -> str | None:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = SUBTITLE_BOX
        crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
        result, _ = self._engine()(crop)
        if not result:
            return None
        return " ".join(r[1] for r in result).strip()

    def identify(self, frame: np.ndarray, candidates: list[Banner]) -> Banner | None:
        """Work out which of `candidates` is on screen, by its subtitle."""
        text = self.read_subtitle(frame)
        if not text:
            return None
        names = {b.name: b for b in candidates}
        hit = process.extractOne(
            text, list(names), scorer=fuzz.token_set_ratio,
            processor=str.lower, score_cutoff=60,
        )
        return names[hit[0]] if hit else None

    def step(self, forward: bool = True) -> None:
        """Flick the carousel one banner along."""
        if forward:
            start, end = 0.66, 0.30
        else:
            start, end = 0.30, 0.66
        self.session.swipe(
            *landscape_to_hid(start, CAROUSEL_Y),
            *landscape_to_hid(end, CAROUSEL_Y),
            steps=20, duration=0.26,
        )
        time.sleep(1.1)

    def select(
        self, wanted: Banner, candidates: list[Banner], attempts: int = 10
    ) -> bool:
        """Flick along until `wanted` is the banner on screen."""
        for _ in range(attempts):
            frame = self.session.screenshot()
            current = self.identify(frame, candidates)
            if current is not None and current.key == wanted.key:
                return True
            self.step(forward=True)
        return False
