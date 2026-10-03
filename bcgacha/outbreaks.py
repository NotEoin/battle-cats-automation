"""Beat the Zombie Outbreaks, one chapter after another, with the Cat CPU.

An outbreak puts zombies on one cleared stage of a saga's chapter at a time.
Each chapter is visited in turn, from anywhere in the game:

  chapter card     reached through the saga and chapter carousels, and entered
  Stage Select     Start!! on the chapter's Cat Base. A chapter with an
                   outbreak shows a purple OUTBREAK button on the left, the
                   stage's name under it; pressing it selects that stage.
  the deck         the Equip button beside Attack! names the deck in use. If
                   it is not the zombie deck, Equip opens Organize Cats, whose
                   arrows step through the decks until the zombie one is up,
                   and Back returns to the stage, still selected.
  battle           the Cat CPU on, then Attack!, as in the Uncanny Legends
                   (legends.py): Cat Food is never spent, energy is refilled
                   only with Leadership.

A stage is attacked until it is cleared or lost three times running; then the
next chapter. Once a won stage no longer shows, the chapter is done; one that
is won and still shown is left, so a run cannot loop on it.

Positions and colours were measured on a 2532x1170 iPhone, as fractions of
the landscape frame and OpenCV HSV; other screen shapes are untested.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from .legends import ATTEMPTS, LegendRun, _hsv

# -- Stage Select -----------------------------------------------------------------
OUTBREAK_BOX = (0.095, 0.42, 0.20, 0.56)        # the purple button, skull and all
OUTBREAK_TAP = (0.146, 0.50)
OUTBREAK_STAGE = (0.09, 0.575, 0.205, 0.625)    # the stage's name under it
SELECTED_TAB = (0.43, 0.11, 0.56, 0.20)         # the selected tab sits mid-strip
PURPLE_HUE = (125, 155)
PURPLE_MIN = (80, 80)                           # saturation and value above
PURPLE_BUTTON = 0.2                             # the button measures 0.38 purple
PURPLE_TAB = 0.4                                # an outbreak's tab, 0.75
# -- the deck -----------------------------------------------------------------------
DECK = "zombie"
DECK_LABEL = (0.665, 0.615, 0.72, 0.657)        # the deck's name on Equip
EQUIP_TAP = (0.690, 0.667)
DECK_NAME = (0.18, 0.145, 0.29, 0.192)          # on Organize Cats, under "Slot n"
DECK_NEXT = (0.792, 0.274)
MAX_DECKS = 25                                  # the game has 20 slots; they wrap
DECK_SETTLE = 0.6                               # seconds for the next deck to slide in
BACK = (0.091, 0.872)
# Stages won in one chapter before it is left, should outbreaks keep coming.
MAX_STAGES = 6


def _purple(frame: np.ndarray, box) -> float:
    r = _hsv(frame, box)
    hit = ((r[:, :, 0] >= PURPLE_HUE[0]) & (r[:, :, 0] <= PURPLE_HUE[1])
           & (r[:, :, 1] > PURPLE_MIN[0]) & (r[:, :, 2] > PURPLE_MIN[1]))
    return float(hit.mean()) if hit.size else 0.0


def outbreak_shown(frame: np.ndarray) -> bool:
    """The purple OUTBREAK button on a chapter's Stage Select."""
    return _purple(frame, OUTBREAK_BOX) > PURPLE_BUTTON


def outbreak_selected(frame: np.ndarray) -> bool:
    """The selected stage tab is the purple one of an outbreak."""
    return _purple(frame, SELECTED_TAB) > PURPLE_TAB


def is_deck(name: str) -> bool:
    """True when a deck's name, as read, is the zombie deck's."""
    return DECK in name.lower().replace(" ", "")


class OutbreakRun(LegendRun):
    """Beat each saga chapter's Zombie Outbreak in turn, with the zombie deck."""

    who = "outbreaks"

    def __init__(self, ctx: Any, attempts: int = ATTEMPTS):
        super().__init__(ctx, attempts)
        self.chapters: dict[str, str] = {}      # chapter -> how it ended

    def publish(self) -> None:
        """Show the run so far, chapter by chapter, on the live page."""
        self.ctx.put("outbreaks", dict(self.state.to_json(), chapters=dict(self.chapters)))

    # -- where -------------------------------------------------------------------------

    @staticmethod
    def chapter_list() -> list[tuple[str, str]]:
        """(screen, "Saga n: name") for every chapter this save has, in carousel order."""
        from . import carousel

        catalogue = carousel.load_catalogue() or {}
        return [(carousel.chapter_screen(saga, c["number"]), f"{saga['name']} {c['number']}")
                for saga in catalogue.get("sagas", []) if saga.get("enters") == "chapters"
                for c in saga.get("chapters", [])]

    def _stage_select(self) -> np.ndarray | None:
        if not self.nav.goto("stage_select", log=self.ctx.log):
            return None
        return self._still()

    # -- the deck -----------------------------------------------------------------------

    def ensure_deck(self, frame: np.ndarray) -> np.ndarray | None:
        """The zombie deck on Equip. Returns Stage Select's frame, or None."""
        label = self._read(frame, DECK_LABEL)
        if is_deck(label):
            return frame
        ctx = self.ctx
        ctx.log(f"{self.who}: deck is {label or '?'!r}: switching to the {DECK} deck")
        self._press(*EQUIP_TAP)
        if not self._arrive("organize_cats"):
            self.state.reason = "Equip did not open Organize Cats"
            return None
        seen = []
        for _ in range(MAX_DECKS):
            ctx.check()
            name = self._read(self._still(), DECK_NAME)
            seen.append(name)
            if is_deck(name):
                break
            self._press(*DECK_NEXT)
            time.sleep(DECK_SETTLE)
        else:
            self.state.reason = f"no deck named {DECK!r} among {sorted(set(n for n in seen if n))}"
            return None
        ctx.log(f"{self.who}: on the {name!r} deck, back to the stage")
        self._press(*BACK)
        if not self._arrive("stage_select"):
            self.state.reason = "Back from Organize Cats did not return to Stage Select"
            return None
        frame = self._still()
        label = self._read(frame, DECK_LABEL)
        if not is_deck(label):
            self.state.reason = f"Equip still reads {label!r} after switching decks"
            return None
        return frame

    # -- one chapter -----------------------------------------------------------------------

    def chapter(self, screen: str, title: str) -> tuple[str, bool]:
        """Clear the outbreaks in one chapter. Returns (what happened, whether the
        run may go on)."""
        ctx, s = self.ctx, self.state
        if not self.nav.goto(screen, log=ctx.log):
            return "could not reach its card", True
        frame = self._stage_select()
        if frame is None:
            return "could not reach its Stage Select", True
        won: list[str] = []
        while True:
            ctx.check()
            if not outbreak_shown(frame):
                return (f"cleared {', '.join(won)}" if won else "no outbreak"), True
            stage = " ".join(self._read(frame, OUTBREAK_STAGE).split()) or "?"
            if stage in won:
                return f"cleared {', '.join(won)}; {stage} still shows", True
            if len(won) >= MAX_STAGES:
                return f"cleared {', '.join(won)}; more keep coming", True
            if not outbreak_selected(frame):
                ctx.log(f"{self.who}: {title}: selecting the outbreak on {stage}")
                self._press(*OUTBREAK_TAP)
                frame = self._still()
                if not outbreak_selected(frame):
                    return f"OUTBREAK did not select {stage}", True
            frame = self.ensure_deck(frame)
            if frame is None or not self.arm(frame):
                return s.reason, False
            key = f"{title}: {stage}"
            if key != s.stage:
                s.stage, s.streak = key, 0
            ctx.log(f"{self.who}: attacking {key} (try {s.streak + 1} of {self.attempts})")
            outcome = self.fight()
            s.battles += 1
            if outcome == "won":
                s.wins += 1
                s.streak = 0
                s.cleared.append(key)
                won.append(stage)
                ctx.log(f"{self.who}: won {key} ({s.wins} won, {s.losses} lost)")
            elif outcome == "lost":
                s.losses += 1
                s.streak += 1
                ctx.log(f"{self.who}: lost {key}, {s.streak} time{'s' if s.streak > 1 else ''} running")
                if s.streak >= self.attempts:
                    self.publish()
                    return f"{stage} lost {s.streak} times running", True
            else:
                s.reason = outcome
                return outcome, False
            self.publish()
            frame = self._stage_select()
            if frame is None:
                return "could not get back to its Stage Select", True

    # -- the loop -------------------------------------------------------------------------

    def run(self) -> str:
        """Visit every chapter, stopping early only when one needs a person; returns why it ended."""
        from .pipeline import Stopped

        ctx, s = self.ctx, self.state
        chapters = self.chapter_list()
        if not chapters:
            s.reason = "no saga chapters known: the map task scans them"
        try:
            for screen, title in chapters:
                ctx.check()
                ctx.log(f"{self.who}: -- {title}")
                what, go_on = self.chapter(screen, title)
                self.chapters[title] = what
                ctx.log(f"{self.who}: {title}: {what}")
                self.publish()
                if not go_on:
                    s.reason = f"{title}: {what}"
                    break
            else:
                if chapters:
                    left = [f"{t} ({w})" for t, w in self.chapters.items()
                            if not w.startswith("cleared") and w != "no outbreak"]
                    s.reason = (f"every chapter visited; left standing: {'; '.join(left)}" if left
                                else "every chapter visited, no outbreak left standing")
        except Stopped:
            s.reason = "stopped by request"
        self.publish()
        ctx.log(f"{self.who}: {s.reason}")
        return s.reason
