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
    note: str = ""


@dataclass(frozen=True)
class Transition:
    """A tap that moves from one screen to another."""

    src: str
    dst: str
    x: float
    y: float
    label: str = ""
    settle: float = 1.8


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
                    "absent": list(s.absent), "forbidden": s.forbidden, "note": s.note,
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
            if screen.forbidden:
                continue
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

    def route(self, src: str, dst: str) -> list[Transition]:
        """Fewest taps from `src` to `dst`, never through a forbidden screen."""
        if src == dst:
            return []
        outgoing: dict[str, list[Transition]] = {}
        for t in self.transitions:
            if self.screens.get(t.dst) and self.screens[t.dst].forbidden:
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


# Almost every screen puts a back arrow here. It is the recovery move when the
# bot finds itself somewhere the map does not know about.
GENERIC_BACK = (0.089, 0.872)


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

    def goto(self, destination: str, max_steps: int = 30, log=None) -> bool:
        """Reach `destination`. Returns False if it could not be found."""
        lost = 0
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
                if lost > 8:
                    if log:
                        log("lost: backing out is not reaching a known screen")
                    return False
                self._tap(*GENERIC_BACK, 1.6)
                continue

            lost = 0
            try:
                path = self.graph.route(here, destination)
            except NoRoute:
                if log:
                    log(f"no route from {here!r} to {destination!r}")
                return False
            step = path[0]
            if log:
                log(f"  {here} --{step.label}--> {step.dst}")
            self._tap(step.x, step.y, step.settle)
        return False
