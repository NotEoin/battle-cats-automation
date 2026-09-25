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

import re
import time
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz, process

from .data import Banner, Dataset
from .layout import landscape_to_hid
from .session import DeviceSession

# The event subtitle, directly under the banner artwork.
SUBTITLE_BOX = (0.16, 0.545, 0.84, 0.610)
# The tab strip. Tabs accept taps even though the side arrows beside them do
# not, so switching is done by tapping a tab and confirming the subtitle.
CAROUSEL_Y = 0.120
TAB_POSITIONS = [(x, CAROUSEL_Y) for x in (0.168, 0.295, 0.459, 0.605)]
# A tab's art, inside the border that lights up on the selected one, and the
# strip a remembered tab is looked for in.
TAB_HALF = (0.055, 0.028)
TAB_STRIP = (0.03, 0.07, 0.75, 0.19)


def tab_box(x: float, y: float = CAROUSEL_Y) -> tuple[float, float, float, float]:
    return x - TAB_HALF[0], y - TAB_HALF[1] + 0.005, x + TAB_HALF[0], y + TAB_HALF[1] + 0.005


def _squash(text: str) -> str:
    """Lowercase, alphanumerics only -- spaces are what the OCR loses."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class BannerPicker:
    session: DeviceSession
    dataset: Dataset
    ocr: object | None = None
    seen_tabs: dict = field(default_factory=dict)

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
        """Work out which of `candidates` is on screen, by its subtitle.

        The recogniser frequently loses the spaces in this font -- "NEW Uber
        Rare heroes" comes back as "NEwUber Rareheroes" -- which defeats any
        word-based comparison. Both sides are therefore stripped to bare
        alphanumerics and compared as one run of characters.
        """
        text = self.read_subtitle(frame)
        if not text:
            # A frame grabbed mid-transition reads as nothing; one retry costs
            # a third of a second and avoids a spurious "unknown banner".
            time.sleep(0.6)
            text = self.read_subtitle(self.session.screenshot())
        return self.match(text, candidates)

    @staticmethod
    def match(text: str | None, candidates: list[Banner]) -> Banner | None:
        """The candidate a subtitle names, spaces and all ignored."""
        if not text:
            return None
        squashed = {_squash(b.name): b for b in candidates}
        hit = process.extractOne(
            _squash(text), list(squashed), scorer=fuzz.partial_ratio, score_cutoff=72
        )
        return squashed[hit[0]] if hit else None

    def step(self, forward: bool = True) -> None:
        """Flick the carousel along, for when there are more tabs than fit."""
        start, end = (0.66, 0.30) if forward else (0.30, 0.66)
        self.session.swipe(
            *landscape_to_hid(start, CAROUSEL_Y),
            *landscape_to_hid(end, CAROUSEL_Y),
            steps=20, duration=0.26,
        )
        time.sleep(1.1)

    def select(
        self, wanted: Banner, candidates: list[Banner], attempts: int = 2
    ) -> bool:
        """Put `wanted` on screen by tapping its tab.

        Unlike the side arrows, the carousel tabs do respond to taps, so each
        one is tried in turn and the subtitle checked. The carousel is only
        flicked when every visible tab has been tried and none was the wanted
        banner, which means the rest are scrolled off screen.
        """
        for _ in range(attempts):
            frame = self.session.screenshot()
            current = self.identify(frame, candidates)
            if current is not None and current.key == wanted.key:
                return True
            for tab in TAB_POSITIONS:
                self.session.tap(*landscape_to_hid(*tab))
                time.sleep(1.5)
                frame = self.session.screenshot()
                current = self.identify(frame, candidates)
                if current is not None:
                    # Which tab showed which event, for the caller to
                    # remember and tap straight away next time.
                    self.seen_tabs[current.key] = (tab, frame)
                if current is not None and current.key == wanted.key:
                    return True
            self.step(forward=True)
        return False


    def sweep(self, candidates: list[Banner], is_platinum, log=print) -> list[dict]:
        """Every tab of the capsule screen, left to right: tap each, and name
        its event by the subtitle it puts up. Returns [{key, banner, read,
        point, frame}] -- key None for a tab no candidate matches, and
        "platinum" for the Platinum tab. The Platinum tab comes last, so the
        strip is flicked on only while it has not been seen."""
        tabs, seen_keys = [], set()
        for _page in range(3):
            fresh = 0
            for point in TAB_POSITIONS:
                self.session.tap(*landscape_to_hid(*point))
                time.sleep(1.5)
                frame = self.session.screenshot()
                if is_platinum(frame):
                    key, banner, read = "platinum", None, "Platinum Capsules"
                else:
                    read = self.read_subtitle(frame) or ""
                    banner = self.match(read, candidates)
                    key = banner.key if banner else None
                if (key or read) in seen_keys:
                    continue
                seen_keys.add(key or read)
                fresh += 1
                tabs.append(dict(key=key, banner=banner, read=read, point=point, frame=frame))
                log(f"  tab {len(tabs)}: {banner.name[:50] if banner else read[:50] or 'nothing read'}"
                    f"{'' if key else '  -- not an event the schedule knows'}")
                self.seen_tabs[key] = (point, frame) if key and key != "platinum" else None
            if any(t["key"] == "platinum" for t in tabs) or not fresh:
                break
            self.step(forward=True)
        self.seen_tabs = {k: v for k, v in self.seen_tabs.items() if v}
        return tabs
