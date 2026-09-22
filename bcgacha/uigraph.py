"""A map of the game's screens, so the bot can navigate without remembering.

Tracking where you are is fragile: one swallowed tap, one unexpected popup, one
run aborted halfway, and the stored idea of "current screen" is wrong. Every
desync this project has hit came from trusting remembered state over what is
actually on the display.

So nothing is remembered. Screens are recognised from the frame itself -- most
of them announce their name in the top-left corner -- and movement between them
is a shortest path over a graph of known transitions. The bot can be started
from anywhere, at any point in any menu, and still reach the Cat Base.

It is a graph rather than a tree because routes converge: the Cat Base is
reachable from every entry in the base-select screen, and the back arrow from a
dozen places lands somewhere already known.

Settings is deliberately absent. It is marked forbidden so no route can ever be
planned through it.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import fuzz

GRAPH_FILE = Path(__file__).resolve().parent.parent / "data" / "ui_graph.json"

# Most screens print their name here.
TITLE_BOX = (0.015, 0.005, 0.260, 0.060)
TITLE_SCALE = 2
TITLE_MATCH = 78


@dataclass(frozen=True)
class Screen:
    """One recognisable screen."""

    name: str
    title: str | None = None            # text expected in the top-left
    anchors: tuple[str, ...] = ()       # template anchors that must all match
    absent: tuple[str, ...] = ()        # anchors that must NOT match
    forbidden: bool = False             # never route through this
    # Screens that appear of their own accord -- a reveal after a draw, a
    # reward popup, an offer. Nothing navigates TO them, so they look
    # unreachable, but they must still be recognised and routed OUT of.
    reactive: bool = False
    note: str = ""


@dataclass(frozen=True)
class Transition:
    """A move from one screen to another.

    Most are a tap at a fixed point. Some need a routine instead: the banner
    carousel has no fixed tab for a given event, so reaching the Platinum
    machine means running the picker rather than tapping a memorised spot.
    Those carry an `action` and their x/y are ignored.
    """

    src: str
    dst: str
    x: float = 0.0
    y: float = 0.0
    label: str = ""
    settle: float = 1.8
    action: str | None = None


class UnknownScreen(RuntimeError):
    pass


class NoRoute(RuntimeError):
    pass


@dataclass
class UIGraph:
    screens: dict[str, Screen] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    _ocr: object | None = field(default=None, repr=False)

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "UIGraph":
        path = Path(path or GRAPH_FILE)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(
            screens={
                s["name"]: Screen(
                    name=s["name"],
                    title=s.get("title"),
                    anchors=tuple(s.get("anchors", ())),
                    absent=tuple(s.get("absent", ())),
                    forbidden=s.get("forbidden", False),
                    reactive=s.get("reactive", False),
                    note=s.get("note", ""),
                )
                for s in raw.get("screens", [])
            },
            transitions=[Transition(**t) for t in raw.get("transitions", [])],
        )

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or GRAPH_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "screens": [
                {
                    "name": s.name, "title": s.title, "anchors": list(s.anchors),
                    "absent": list(s.absent), "forbidden": s.forbidden,
                    "reactive": s.reactive, "note": s.note,
                }
                for s in sorted(self.screens.values(), key=lambda s: s.name)
            ],
            "transitions": [vars(t) for t in self.transitions],
        }, indent=1))
        return path

    # -- recognition --------------------------------------------------------

    @property
    def ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        return self._ocr

    def read_title(self, frame: np.ndarray) -> str:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = TITLE_BOX
        crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
        crop = cv2.resize(
            crop, None, fx=TITLE_SCALE, fy=TITLE_SCALE, interpolation=cv2.INTER_CUBIC
        )
        result, _ = self.ocr(crop)
        return " ".join(r[1] for r in (result or [])).strip()

    def identify(self, frame: np.ndarray) -> str | None:
        """Name the screen in `frame`, or None if it is not in the map.

        Either kind of evidence is enough on its own. Titles are convenient but
        the recogniser is unreliable on them -- the very same "Cat Base" header
        reads perfectly in one capture and comes back empty in the next -- so a
        screen with matching anchors is accepted even when its title does not
        read, and a screen with no anchors is accepted on its title. Having
        both simply scores higher, which is what separates screens that share a
        header.
        """
        from . import vision

        def anchor_hit(name: str) -> bool:
            anchor = vision.ANCHORS.get(name)
            if anchor is None:
                return False
            return vision.match(frame, anchor) > anchor.threshold

        title = self.read_title(frame)
        candidates: list[tuple[float, str]] = []
        for screen in self.screens.values():
            # Forbidden screens are still identified. Refusing to recognise one
            # would leave the bot blind exactly where it most needs to know
            # where it is, so that it can leave deliberately rather than tap
            # about. Forbidding governs routing INTO a screen, nothing else.
            score = 0.0

            if screen.anchors:
                if not all(anchor_hit(a) for a in screen.anchors):
                    continue
                score += 200.0
            if any(anchor_hit(a) for a in screen.absent):
                continue

            if screen.title:
                if title:
                    match = max(
                        fuzz.partial_ratio(screen.title.lower(), title.lower()),
                        fuzz.ratio(screen.title.lower(), title.lower()),
                    )
                    if match >= TITLE_MATCH:
                        score += match
                    elif not screen.anchors:
                        continue        # title was the only evidence, and it failed
                elif not screen.anchors:
                    continue            # needed a title, did not get one
            elif not screen.anchors:
                continue                # nothing to identify this screen by

            candidates.append((score, screen.name))
        if not candidates:
            return None
        return max(candidates)[1]

    # -- routing ------------------------------------------------------------

    def route(
        self, src: str, dst: str, exclude: set | None = None
    ) -> list[Transition]:
        """Fewest taps from `src` to `dst`, never through a forbidden screen.

        `exclude` drops edges already shown to do nothing, so a second attempt
        picks a different control rather than repeating a dud.
        """
        if src == dst:
            return []
        exclude = exclude or set()
        outgoing: dict[str, list[Transition]] = {}
        for t in self.transitions:
            if self.screens.get(t.dst) and self.screens[t.dst].forbidden:
                continue
            if (t.src, t.dst, round(t.x, 3), round(t.y, 3)) in exclude:
                continue
            outgoing.setdefault(t.src, []).append(t)

        seen = {src}
        queue: deque[tuple[str, list[Transition]]] = deque([(src, [])])
        while queue:
            node, path = queue.popleft()
            for t in outgoing.get(node, []):
                if t.dst in seen:
                    continue
                if t.dst == dst:
                    return path + [t]
                seen.add(t.dst)
                queue.append((t.dst, path + [t]))
        raise NoRoute(f"no route from {src!r} to {dst!r}")


# Almost every screen puts a round yellow back arrow in the bottom-left. Its
# exact position drifts a little between screens, so it is found by colour
# rather than assumed -- a fixed point misses on enough screens to matter.
GENERIC_BACK = (0.089, 0.872)
BACK_SEARCH_REGION = (0.02, 0.74, 0.22, 0.99)



def find_back_arrow(frame: np.ndarray) -> tuple[float, float] | None:
    """Locate the round yellow back arrow, as screen fractions."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = BACK_SEARCH_REGION
    region = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
    if region.size == 0:
        return None
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (18, 140, 170), (34, 255, 255))
    count, _lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, count):
        area = stats[i, 4]
        ratio = stats[i, 2] / max(stats[i, 3], 1)
        if area > 4000 and 0.6 < ratio < 1.7:     # roughly circular
            if best is None or area > best[0]:
                best = (area, cent[i][0], cent[i][1])
    if best is None:
        return None
    return (
        x0 + (best[1] / region.shape[1]) * (x1 - x0),
        y0 + (best[2] / region.shape[0]) * (y1 - y0),
    )


class Navigator:
    """Walks the graph to a destination, from wherever the game happens to be.

    Nothing about the current position is remembered between calls. Every step
    re-reads the screen, so a swallowed tap, an unexpected popup or a run that
    died halfway simply costs one extra look rather than corrupting anything.
    """

    def __init__(self, session, graph: UIGraph | None = None, humaniser=None):
        from .timing import Humaniser

        self.session = session
        self.graph = graph or UIGraph.load()
        self.human = humaniser or Humaniser()

    def where(self, frame: np.ndarray | None = None) -> str | None:
        frame = frame if frame is not None else self.session.screenshot()
        return self.graph.identify(frame)

    def _tap(self, x: float, y: float, settle: float) -> None:
        from .layout import landscape_to_hid

        self.session.tap(*self.human.jitter_point(*landscape_to_hid(x, y)))
        self.human.sleep(settle)

    def _clear_obstruction(self, frame: np.ndarray) -> bool:
        """Dismiss a dialog or reward popup standing in the way."""
        from . import safety

        if safety.inspect_dialog(frame).present:
            self.session.tap(
                *self.human.jitter_point(
                    *__import__(
                        "bcgacha.layout", fromlist=["landscape_to_hid"]
                    ).landscape_to_hid(*safety.DIALOG_NO)
                )
            )
            self.human.sleep(1.0)
            return True
        return False

    def _run_action(self, step: Transition, log=None) -> bool:
        """Carry out a transition that needs a routine rather than a tap."""
        kind, _, argument = (step.action or "").partition(":")
        if kind == "swipe":
            # Carousels do not respond to taps on their side items at all --
            # only the centre one is live, and the selection is moved by
            # flicking. Routing never needs a particular entry, since every
            # one of them lands on a Cat Base, so this exists for completeness.
            from .layout import landscape_to_hid

            left = argument == "left"
            x0, x1 = (0.70, 0.30) if left else (0.30, 0.70)
            self.session.swipe(
                *landscape_to_hid(x0, 0.58), *landscape_to_hid(x1, 0.58),
                steps=22, duration=0.26,
            )
            self.human.sleep(1.3)
            return True
        if kind == "banner":
            import datetime as dt

            from .bannerpick import BannerPicker
            from .cli import _live_banners
            from .data import load

            dataset = load()
            normal, platinum = _live_banners(dataset, dt.date.today())
            candidates = normal + ([platinum] if platinum else [])
            wanted = next((b for b in candidates if b.key == argument), None)
            if wanted is None and argument == "platinum":
                wanted = platinum
            if wanted is None:
                if log:
                    log(f"  no banner matching {argument!r}")
                return False
            return BannerPicker(self.session, dataset).select(wanted, candidates)
        if log:
            log(f"  unknown action {step.action!r}")
        return False

    def goto(self, destination: str, max_steps: int = 30, log=None) -> bool:
        """Reach `destination`. Returns False if it could not be found."""
        lost = 0
        # Edges that were taken and left us exactly where we started. In a
        # carousel the side cards only move the selection, so tapping one for
        # a second time repeats the same nothing; without this the walk spins
        # on its first choice forever.
        barren: set[tuple[str, str, float, float]] = set()
        for _ in range(max_steps):
            frame = self.session.screenshot()
            if self._clear_obstruction(frame):
                continue

            here = self.graph.identify(frame)
            if here == destination:
                return True
            if here is None:
                # Not on the map. Backing out is almost always right: nearly
                # every screen has a back arrow in the same corner, and the
                # places it leads to are ones the map does know.
                lost += 1
                if lost > 10:
                    if log:
                        log("  lost: backing out is not reaching a known screen")
                    return False
                back = find_back_arrow(frame) or GENERIC_BACK
                self._tap(*back, 1.6)
                continue

            lost = 0
            try:
                path = self.graph.route(here, destination, exclude=barren)
            except NoRoute:
                if log:
                    log(f"no route from {here!r} to {destination!r}")
                return False
            step = path[0]
            if log:
                log(f"  {here} --{step.label}--> {step.dst}")
            if step.action:
                if not self._run_action(step, log=log):
                    return False
                continue
            self._tap(step.x, step.y, step.settle)
            if self.graph.identify(self.session.screenshot()) == here:
                barren.add((step.src, step.dst, round(step.x, 3), round(step.y, 3)))
                if log:
                    log(f"    {step.label!r} changed nothing; trying another way")
        return False


# The game draws nearly every control as a gold button with a dark outline, at
# a consistent hue. Detecting them beats hand-measuring coordinates: it finds
# controls on screens nobody has mapped yet, and it survives layout drift.
BUTTON_HSV_LOW = (16, 120, 140)
BUTTON_HSV_HIGH = (34, 255, 255)
BUTTON_MIN_AREA = 2600
BUTTON_MAX_AREA_FRACTION = 0.22
BUTTON_ASPECT = (0.45, 9.0)


@dataclass(frozen=True)
class Button:
    """A detected control, in screen fractions."""

    x: float
    y: float
    w: float
    h: float
    area: int

    @property
    def centre(self) -> tuple[float, float]:
        return self.x, self.y


def find_buttons(frame: np.ndarray) -> list[Button]:
    """Every gold control on the screen, ordered top-to-bottom then left-to-right."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BUTTON_HSV_LOW, BUTTON_HSV_HIGH)
    # Close the dark glyphs printed on top of a button so it reads as one blob.
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 15))
    )
    count, _lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    limit = BUTTON_MAX_AREA_FRACTION * h * w
    out: list[Button] = []
    for i in range(1, count):
        area = int(stats[i, 4])
        bw, bh = int(stats[i, 2]), int(stats[i, 3])
        if area < BUTTON_MIN_AREA or area > limit or bh == 0:
            continue
        if not (BUTTON_ASPECT[0] <= bw / bh <= BUTTON_ASPECT[1]):
            continue
        out.append(Button(
            x=float(cent[i][0]) / w, y=float(cent[i][1]) / h,
            w=bw / w, h=bh / h, area=area,
        ))
    out.sort(key=lambda b: (round(b.y, 2), b.x))
    return out
