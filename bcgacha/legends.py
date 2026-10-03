"""Play the Uncanny Legends through, one stage after another, with the Cat CPU.

The loop, from anywhere in the game:

  Legend Stages list   flick to its top, page down to the first green pill
                       (the Uncanny Legends, told by the header above them)
                       and open the topmost one not greyed out; if that one
                       already says CLEAR, every chapter there is.
  Stage Select         the rightmost stage selected, the Cat CPU item in its
                       CPU state (a second tap turns it to skip-battle, which
                       refuses a stage not yet cleared), then Attack!.
  battle               the CPU plays it. Victory's notices are tapped away
                       and its Ok pressed, which leads back to the Cat Base.
                       On defeat the offer to continue for Cat Food is
                       answered No, and the tip after it closed with its Ok.

A stage lost three times running stops the run: the CPU cannot beat it and a
person is needed. Nothing is ever confirmed that spends Cat Food: a question
naming it, or one this module does not know, is answered No or stops the run.
Energy is refilled only with Leadership.

Every frame of a battle's end is kept under logs/legends, to learn from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "logs" / "legends"

# -- the Legend Stages list ----------------------------------------------------
# The list's pills are sampled down a thin column clear of their text and of
# the translucent scroll arrows over their middle.
LIST_Y = (0.075, 0.87)
LIST_COLUMN = (0.29, 0.31)
PILL_MIN = 0.025                # a run of one colour this tall is a pill
PILL_TAP_X = 0.27
GREEN_HUE = (37, 47)            # Uncanny Legends; yellow is Stories of Legend
YELLOW_HUE = (19, 30)
PILL_SATURATION = 120
BRIGHT = 150                    # a greyed-out (locked) pill is half as bright
# The CLEAR badge covers the left end of a cleared pill's lower half.
BADGE_X = (0.078, 0.108)
HEADER = "uncanny"
# Pages of drag from the top before giving up on finding the section.
MAX_PAGES = 30
# Drags, as (from y, to y) at x = 0.2. None starts near the top edge: that
# pulls down the Notification Centre.
PAGE_DOWN = (0.85, 0.2)
NUDGE_DOWN = (0.7, 0.35)
NUDGE_UP = (0.4, 0.65)
FLICK_UP = (0.3, 0.85)

# -- Stage Select ---------------------------------------------------------------
TAB_STRIP = (0.06, 0.105, 0.78, 0.19)
TAB_ROW = 0.125
TAB_MIN = 0.06
CPU_ICON = (0.695, 0.735, 0.745, 0.815)
CPU_TAP = (0.721, 0.785)
ATTACK = (0.83, 0.662)
ATTACK_BOX = (0.74, 0.625, 0.92, 0.70)

# -- battle -----------------------------------------------------------------------
END_OK = (0.498, 0.88)                      # Victory's Ok, and Defeat's
DEFEAT_WORDS = ("defeat", "youlose", "youlost", "gameover")
NOTICE_TAP = (0.5, 0.72)                    # blank ground under a victory notice
POLL = 1.5
LOOK_EVERY = 6.0                            # a full look for questions, this often
BATTLE_LIMIT = 15 * 60
ATTEMPTS = 3
ANSWER_NO = ("no", "give up", "cancel", "quit")
DIALOG_Y = (0.2, 0.78)
# On Stage Select after Attack!, look for a question this often, and press
# again if nothing is asked and the map has not moved in this long.
QUESTION_EVERY = 2.5
ATTACK_AGAIN = 5.0


def _hsv(frame: np.ndarray, box) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return cv2.cvtColor(frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)],
                        cv2.COLOR_BGR2HSV)


@dataclass
class Pill:
    kind: str           # "green", "yellow" or "other"
    y0: float
    y1: float
    bright: bool

    @property
    def y(self) -> float:
        return (self.y0 + self.y1) / 2


def pills(frame: np.ndarray) -> list[Pill]:
    """The list's pills, top to bottom, by the colour down one column."""
    h = frame.shape[0]
    col = _hsv(frame, (LIST_COLUMN[0], LIST_Y[0], LIST_COLUMN[1], LIST_Y[1])).astype(int)
    hue, sat, val = (np.median(col[:, :, i], axis=1) for i in range(3))
    kind = np.where(sat < PILL_SATURATION, "",
                    np.where((hue >= GREEN_HUE[0]) & (hue <= GREEN_HUE[1]), "green",
                             np.where((hue >= YELLOW_HUE[0]) & (hue <= YELLOW_HUE[1]),
                                      "yellow", "other")))
    top = int(LIST_Y[0] * h)
    out, start = [], None
    for i, k in enumerate(list(kind) + [""]):
        if start is not None and k != kind[start]:
            if i - start >= PILL_MIN * h:
                out.append(Pill(str(kind[start]), (top + start) / h, (top + i) / h,
                                float(np.median(val[start:i])) >= BRIGHT))
            start = None
        if start is None and k:
            start = i
    return out


def cleared(frame: np.ndarray, pill: Pill) -> bool:
    """A CLEAR badge on the pill's left end, where an uncleared one is green."""
    region = _hsv(frame, (BADGE_X[0], pill.y, BADGE_X[1], pill.y1 - 0.005))
    green = ((region[:, :, 0] >= GREEN_HUE[0]) & (region[:, :, 0] <= GREEN_HUE[1])
             & (region[:, :, 1] > PILL_SATURATION))
    return green.size > 0 and green.mean() < 0.5


def cpu_state(frame: np.ndarray) -> str:
    """The Cat CPU item: "cpu" (white, a rainbow screen), "skip" (gold) or "off"."""
    r = _hsv(frame, CPU_ICON)
    vivid = (r[:, :, 1] > 110) & (r[:, :, 2] > 150)
    gold = vivid & (r[:, :, 0] >= 12) & (r[:, :, 0] <= 32)
    white = (r[:, :, 1] < 40) & (r[:, :, 2] > 200)
    if gold.mean() > 0.1:
        return "skip"
    if white.mean() > 0.04 and (vivid & ~gold).mean() > 0.04:
        return "cpu"
    return "off"


def attack_ready(frame: np.ndarray) -> bool:
    """Attack! lit: bright gold, not the dimmed skip-battle face."""
    r = _hsv(frame, ATTACK_BOX)
    return float(np.median(r[:, :, 2])) > 190 and float(np.median(r[:, :, 1])) > 120


def tabs(frame: np.ndarray) -> tuple[tuple[float, float] | None, list[tuple[float, float]]]:
    """The selected stage tab (solid white) and the others, as x spans."""
    h, w = frame.shape[:2]
    row = cv2.cvtColor(frame[int(TAB_ROW * h): int(TAB_ROW * h) + 1], cv2.COLOR_BGR2HSV)[0].astype(int)
    x0, x1 = int(TAB_STRIP[0] * w), int(TAB_STRIP[2] * w)
    white = (row[:, 1] < 30) & (row[:, 2] > 235)
    pale = (row[:, 1] < 45) & (row[:, 2] > 140)

    def runs(mask):
        out, start = [], None
        for x in range(x0, x1 + 1):
            on = x < x1 and mask[x]
            if on and start is None:
                start = x
            elif not on and start is not None:
                if x - start >= TAB_MIN * w:
                    out.append((start / w, x / w))
                start = None
        return out

    selected = max(runs(white), key=lambda s: s[1] - s[0], default=None)
    others = [s for s in runs(pale) if selected is None or s[1] <= selected[0] or s[0] >= selected[1]]
    return selected, others


@dataclass
class LegendState:
    battles: int = 0
    wins: int = 0
    losses: int = 0
    stage: str = ""
    streak: int = 0                     # losses running on `stage`
    cleared: list = field(default_factory=list)
    started: float = field(default_factory=time.time)
    reason: str = ""

    def to_json(self) -> dict:
        return dict(battles=self.battles, wins=self.wins, losses=self.losses, stage=self.stage,
                    streak=self.streak, cleared=self.cleared[-12:], reason=self.reason,
                    minutes=round((time.time() - self.started) / 60, 1))


class LegendRun:
    who = "legends"             # how its lines start in the log

    def __init__(self, ctx, attempts: int = ATTEMPTS):
        self.ctx, self.attempts = ctx, attempts
        self.nav = ctx.navigator()
        self.state = LegendState()

    # -- small things ------------------------------------------------------------

    def _shot(self) -> np.ndarray:
        return self.ctx.session.screenshot()

    def _press(self, x: float, y: float) -> None:
        self.nav._press(x, y)

    def _move(self, y0: float, y1: float, flick: bool = False) -> None:
        from .layout import landscape_to_hid

        a, b = landscape_to_hid(0.2, y0), landscape_to_hid(0.2, y1)
        if flick:
            self.ctx.session.swipe(*a, *b, duration=0.12)
        else:
            self.ctx.session.drag(*a, *b, duration=0.5, hold=0.15)

    def _keep(self, frame: np.ndarray, what: str) -> None:
        SHOTS.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(SHOTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{what}.png"), frame)

    def _read(self, frame, box) -> str:
        return self.ctx.graph.read_title(frame, box)

    def _arrive(self, expected: str, timeout: float = 8.0) -> bool:
        """Wait for `expected` on two frames running; a screen not learned
        yet gets a full look now and then, which learns it."""
        graph, seen, look = self.ctx.graph, None, time.monotonic() + 2.5
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._shot()
            slow = time.monotonic() > look
            here = graph.recognise(frame, slow=slow, ocr=slow).here
            if slow:
                look = time.monotonic() + 2.5
            if here == expected and seen == expected:
                return True
            seen = here
        return False

    def _still(self, wait: float = 0.35) -> np.ndarray:
        """A frame once the screen has stopped scrolling."""
        from .uigraph import frame_changed

        last = self._shot()
        for _ in range(12):
            time.sleep(wait)
            frame = self._shot()
            if not frame_changed(last, frame, fraction=0.01):
                return frame
            last = frame
        return last

    # -- the list -------------------------------------------------------------------

    def open_next(self) -> str | None:
        """Open the topmost Uncanny Legends chapter not greyed out. Returns its
        name, or None with state.reason set if there is none to play."""
        ctx = self.ctx
        if not self.nav.goto("legend_stage_select", log=ctx.log):
            self.state.reason = "could not reach the Legend Stages list"
            return None
        for _ in range(10):
            self._move(*FLICK_UP, flick=True)
        time.sleep(0.8)
        frame = self._still()
        for _ in range(MAX_PAGES):
            ctx.check()
            greens = [p for p in pills(frame) if p.kind == "green"]
            if greens:
                break
            self._move(*PAGE_DOWN)
            frame = self._still()
        else:
            self.state.reason = "no green Uncanny Legends pills in the list"
            return None
        # The section's first pill, with room above it for the header.
        if greens[0].y0 < 0.2:
            self._move(*NUDGE_UP)
            frame = self._still()
            greens = [p for p in pills(frame) if p.kind == "green"]
        top = greens[0]
        header = self._read(frame, (0.07, max(top.y0 - 0.085, 0.07), 0.30, top.y0 - 0.005))
        if HEADER not in header.lower().replace(" ", ""):
            self.state.reason = f"the first green pills are not the Uncanny Legends ({header!r})"
            return None
        for _ in range(8):
            for p in greens:
                if p.bright and p.y1 < LIST_Y[1] - 0.01:
                    name = self._read(frame, (0.07, p.y0, 0.36, p.y0 + 0.07)) or "?"
                    if cleared(frame, p):
                        self.state.reason = f"every Uncanny Legends chapter is clear (top: {name})"
                        return None
                    ctx.log(f"{self.who}: opening {name}")
                    self._press(PILL_TAP_X, p.y)
                    if not self._arrive("stage_select"):
                        self.state.reason = f"{name} did not open its Stage Select"
                        return None
                    return name
                if p.bright:
                    break           # the first unlocked pill, cut off by the bottom
            self._move(*NUDGE_DOWN)
            frame = self._still()
            greens = [p for p in pills(frame) if p.kind == "green"]
        self.state.reason = "no Uncanny Legends chapter is unlocked"
        return None

    # -- Stage Select -----------------------------------------------------------------

    def prepare(self) -> str | None:
        """Rightmost stage, Cat CPU on. Returns the stage's name, or None."""
        frame = self._still()
        for _ in range(4):
            selected, others = tabs(frame)
            later = [t for t in others if selected and t[0] >= selected[1]]
            if selected is None or not later:
                break
            x0, x1 = max(later)
            self.ctx.log(f"{self.who}: selecting the rightmost stage")
            self._press((x0 + x1) / 2, (TAB_STRIP[1] + TAB_STRIP[3]) / 2)
            frame = self._still()
        if selected is None:
            self.state.reason = "no stage tab selected on Stage Select"
            return None
        stage = self._read(frame, (selected[0], TAB_STRIP[1], selected[1], TAB_STRIP[3])) or "?"
        return stage if self.arm(frame) else None

    def arm(self, frame) -> bool:
        """The Cat CPU item in its CPU state and Attack! lit, or state.reason says why not."""
        for _ in range(3):
            state = cpu_state(frame)
            if state == "cpu":
                break
            self.ctx.log(f"{self.who}: Cat CPU item is {state}: tapping it")
            self._press(*CPU_TAP)
            frame = self._still()
        else:
            self.state.reason = "the Cat CPU item would not turn to CPU (none left?)"
            return False
        if not attack_ready(frame):
            self.state.reason = "Attack! is not lit"
            return False
        return True

    # -- the battle -----------------------------------------------------------------------

    def _question(self, frame) -> str | None:
        """Answer a question in the way. Returns None if handled (or none
        there), else why the run must stop."""
        from .perception import perceive

        percept = perceive(frame, self.ctx.ocr)
        # Only what a dialog says: the bottom bar always reads "Cat Food".
        middle = [t for t in percept.readings() if DIALOG_Y[0] <= t.centre[1] <= DIALOG_Y[1]]
        asked = [t.text for t in middle if "?" in t.text]
        words = " ".join(t.text for t in middle).lower()
        # A continue offer may not ask in so many words, but names its price.
        if not asked and "cat food" not in words and "catfood" not in words:
            return None
        asked = asked or [words[:80]]
        self._keep(frame, "question")
        if "leadership" in words and "cat food" not in words:
            yes = percept.find("Yes") or percept.find("OK") or percept.find("Use")
            if yes is None:
                return f"a Leadership question with no Yes: {asked}"
            self.ctx.log(f"{self.who}: refilling energy with Leadership ({asked[0]!r})")
            self._press(*yes.tap)
            return None
        for label in ANSWER_NO:
            control = percept.find(label)
            if control is not None:
                self.ctx.log(f"{self.who}: answering {label!r} to {asked[0]!r}")
                self._press(*control.tap)
                return None
        return f"a question with no way to say No: {asked}"

    def _end_ok(self, frame) -> tuple[float, float] | None:
        """The Ok closing a battle, won or lost: the gold pill nearest where
        it was measured. Too small for OCR to read."""
        from .uigraph import find_buttons

        pills_ = [bt for bt in find_buttons(frame)
                  if abs(bt.x - END_OK[0]) < 0.08 and abs(bt.y - END_OK[1]) < 0.05]
        best = min(pills_, key=lambda bt: abs(bt.x - END_OK[0]), default=None)
        return (best.x, best.y) if best else None

    def fight(self) -> str:
        """Press Attack! and see the battle out: "won", "lost", or why not.

        One full-frame read a poll tells every state apart: "Victory!" with a
        notice over it or, once they are gone, Post to SNS beside the Ok; else
        the money counter ("1040/16500") while the battle is on. The victory
        screen keeps the enemy base's "0/600000", so victory is looked for first.
        """
        import re

        from .perception import read_texts
        from .uigraph import frame_changed

        ctx = self.ctx
        before = self._shot()
        self._press(*ATTACK)
        started = pressed_at = time.monotonic()
        presses, outcome, last, fighting, last_look = 1, None, None, False, started
        while time.monotonic() - started < BATTLE_LIMIT:
            ctx.check()
            time.sleep(POLL)
            frame = self._shot()
            now = time.monotonic()
            here = ctx.graph.recognise(frame, slow=False, ocr=False).here
            still = last is not None and not frame_changed(last, frame)
            last = frame
            if here in ("cat_base", "legend_stage_select") and still:
                return outcome or f"back on {here} without seeing the battle end"
            if here == "stage_select" and still and outcome:
                return outcome
            if here == "stage_select" and still and not fighting:
                # Still on the map: a question over it (energy, above all),
                # or a press that did not take.
                if now - last_look > QUESTION_EVERY:
                    last_look = now
                    why = self._question(frame)
                    if why:
                        return why
                    if attack_ready(frame) and not frame_changed(before, frame, fraction=0.02) \
                            and now - pressed_at > ATTACK_AGAIN:
                        if presses >= 3:
                            return "Attack! did not start a battle"
                        ctx.log(f"{self.who}: Attack! again")
                        self._press(*ATTACK)
                        presses, pressed_at = presses + 1, time.monotonic()
                continue
            texts = read_texts(frame, ctx.ocr)
            words = "".join(t.text for t in texts).lower().replace(" ", "")
            if "victory" in words:
                if outcome is None:
                    self._keep(frame, "victory")
                    ctx.log(f"{self.who}: victory ({round(now - started)}s)")
                outcome = "won"
                self._press(*((self._end_ok(frame) or END_OK) if "posttosns" in words else NOTICE_TAP))
                continue
            if outcome is None and any(w in words for w in DEFEAT_WORDS):
                self._keep(frame, "defeat")
                ctx.log(f"{self.who}: defeat ({round(now - started)}s)")
                outcome = "lost"
            if any(re.fullmatch(r"\d+/\d+\D?", t.text.strip()) for t in texts) and outcome is None:
                if not fighting:
                    ctx.log(f"{self.who}: battle on, the CPU at the helm")
                fighting = True
                continue
            asks = any("?" in t.text and DIALOG_Y[0] <= t.centre[1] <= DIALOG_Y[1] for t in texts)
            if asks or outcome == "lost" or (still and now - last_look > LOOK_EVERY):
                last_look = now
                why = self._question(frame)
                if why:
                    return why
                if outcome == "lost" and not asks:
                    # Defeat's tip panel, closed by an Ok under it.
                    ok = self._end_ok(frame)
                    if ok is not None:
                        self._press(*ok)
        return "the battle ran past its time limit"

    # -- the loop -------------------------------------------------------------------------

    def run(self) -> str:
        from .pipeline import Stopped

        ctx, s = self.ctx, self.state
        try:
            while True:
                ctx.check()
                chapter = self.open_next()
                if chapter is None:
                    break
                stage = self.prepare()
                if stage is None:
                    break
                key = f"{chapter}: {stage}"
                if key != s.stage:
                    s.stage, s.streak = key, 0
                ctx.log(f"{self.who}: attacking {key} (try {s.streak + 1} of {self.attempts})")
                outcome = self.fight()
                s.battles += 1
                if outcome == "won":
                    s.wins += 1
                    s.streak = 0
                    s.cleared.append(key)
                    ctx.log(f"{self.who}: won {key} ({s.wins} won, {s.losses} lost)")
                elif outcome == "lost":
                    s.losses += 1
                    s.streak += 1
                    ctx.log(f"{self.who}: lost {key}, {s.streak} time{'s' if s.streak > 1 else ''} running")
                    if s.streak >= self.attempts:
                        s.reason = f"{key} lost {s.streak} times running: over to a person"
                        break
                else:
                    s.reason = outcome
                    break
                ctx.put("legends", s.to_json())
        except Stopped:
            s.reason = "stopped by request"
        ctx.put("legends", s.to_json())
        ctx.log(f"{self.who}: {s.reason}")
        return s.reason
