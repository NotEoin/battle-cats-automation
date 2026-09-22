"""Drive single draws on the Rare Capsule screen.

Every roll is bracketed by checks, because the failure modes here cost real
currency. The draw button does not move when your tickets run out -- it simply
starts spending 150 Cat Food instead -- so its appearance is compared against a
known ticket-bearing template before each draw, and the ticket counter is
required to fall by exactly one afterwards.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import vision
from .layout import (
    CAPSULE_SCREEN,
    PLATINUM_SCREEN,
    RESULT_SCREEN,
    SENT_TO_STORAGE_SCREEN,
)
from .safety import SafeTapper, UnsafeTap

REVEAL_TIMEOUT = 30.0
POLL_INTERVAL = 0.35


class RollAborted(RuntimeError):
    pass


@dataclass
class RollResult:
    index: int
    frame_path: Path
    tickets_before: int | None
    tickets_after: int | None


class Roller:
    def __init__(self, tapper: SafeTapper, out_dir: Path):
        self.tapper = tapper
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.atlas = vision.DigitAtlas()

    def _tickets(self, frame: np.ndarray) -> int | None:
        return vision.read_counter(frame, "tickets", self.atlas)

    def settle_to_capsule(self, timeout: float = 25.0) -> np.ndarray:
        """Get back to the capsule screen from wherever we are.

        Screens cross-fade, so a capture taken immediately after a tap often
        lands mid-transition and classifies as unknown. Poll instead of
        assuming the next frame is settled.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.tapper.capture()
            screen = vision.classify(frame)
            if screen is vision.Screen.CAPSULE:
                return frame
            if screen is vision.Screen.SENT_TO_STORAGE:
                self.tapper.tap(
                    SENT_TO_STORAGE_SCREEN["ok"],
                    expect=vision.Screen.SENT_TO_STORAGE,
                    require_anchor="sent_to_storage",
                )
                continue
            if screen is vision.Screen.RESULT:
                self.tapper.tap(
                    RESULT_SCREEN["ok"],
                    expect=vision.Screen.RESULT,
                    require_anchor="result_actions",
                )
                continue
            if self.tapper.dismiss_dialog(frame):
                continue
            time.sleep(POLL_INTERVAL)  # unknown screen: give the UI a moment
        raise RollAborted("could not get back to the capsule screen")

    def _wait_for_reveal(self) -> np.ndarray:
        """Poll until the result action row appears."""
        frame = self.tapper.wait_for(vision.Screen.RESULT, timeout=REVEAL_TIMEOUT)
        if frame is None:
            raise RollAborted("reveal did not finish within the timeout")
        return frame

    def roll_once(self, index: int, platinum: bool = False) -> RollResult:
        """Draw once. `platinum` spends a Platinum Ticket instead of a Rare one.

        The two machines are separate screens with separate buttons in separate
        places, and each button is checked against its own template before it
        is pressed -- that check is what stops a draw button quietly becoming a
        Cat Food spend, so it must not be loosened to cover both.
        """
        screen = vision.Screen.PLATINUM if platinum else vision.Screen.CAPSULE
        anchor = "plat_try_once" if platinum else "try_once_button"
        target = PLATINUM_SCREEN["try_once"] if platinum else CAPSULE_SCREEN["try_once"]
        counter = "platinum" if platinum else "tickets"

        before = self.settle_to_capsule() if not platinum else self.tapper.capture()
        if vision.classify(before) is not screen:
            raise RollAborted(
                f"expected the {screen.value} screen, saw "
                f"{vision.classify(before).value}"
            )

        score = vision.match(before, vision.ANCHORS[anchor])
        if score < 0.75:
            raise RollAborted(
                f"draw button does not match the {counter} template ({score:.2f}); "
                "it may be spending something else"
            )
        tickets_before = vision.read_counter(before, counter, self.atlas)
        if tickets_before is not None and tickets_before < 1:
            raise RollAborted(f"no {counter} left")

        try:
            self.tapper.tap(target, expect=screen, require_anchor=anchor, frame=before)
        except UnsafeTap as exc:
            raise RollAborted(str(exc)) from exc

        result_frame = self._wait_for_reveal()
        path = self.out_dir / f"roll_{index:03d}.png"
        cv2.imwrite(str(path), result_frame)

        after = self.tapper.tap(
            RESULT_SCREEN["ok"], expect=vision.Screen.RESULT, require_anchor="result_actions"
        )
        tickets_after = vision.read_counter(after, counter, self.atlas)
        if (
            tickets_before is not None
            and tickets_after is not None
            and tickets_after not in (tickets_before - 1, tickets_before)
        ):
            raise RollAborted(
                f"ticket count moved unexpectedly: {tickets_before} -> {tickets_after}"
            )
        return RollResult(index, path, tickets_before, tickets_after)

    def roll(self, count: int) -> list[RollResult]:
        out = []
        for i in range(1, count + 1):
            out.append(self.roll_once(i))
        return out
