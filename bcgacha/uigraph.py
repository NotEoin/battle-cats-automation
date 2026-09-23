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
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import fuzz

GRAPH_FILE = Path(__file__).resolve().parent.parent / "data" / "ui_graph.json"
# Two threads meeting a new resolution at once must share one Profile.
_PROFILES_LOCK = threading.Lock()

# Most screens print their name here.
TITLE_BOX = (0.015, 0.005, 0.260, 0.060)
TITLE_SCALE = 2
TITLE_MATCH = 78
# A title found inside a longer reading must line up with whole words and
# match this closely. Loosely, "Storage" passes for the "Stage S" of
# "Stage Select" at 83.
TITLE_PART_MATCH = 90


def title_match(expected: str, read: str, within: bool = True) -> float:
    """How well an OCR reading shows `expected`, 0..100.

    The whole reading is compared first. Failing that, and when `within`
    allows it, the title may sit among other words -- but only as whole
    words, closely, and never the reverse: "Back" read off a card is not
    "Take Back Earth!". A carousel card holds nothing but its name, so card
    screens pass within=False: the Back card must not claim "The Ancients
    Arise: Take Back Earth!". A notice's line may carry more, and keeps it.
    """
    expected, read = expected.lower(), read.lower()
    whole = fuzz.ratio(expected, read)
    if not within:
        # A card's two-line name can come back with its lines swapped, and an
        # event's subtitle with its spaces gone.
        squashed = fuzz.ratio(re.sub(r"[^a-z0-9]", "", expected), re.sub(r"[^a-z0-9]", "", read))
        return max(whole, fuzz.token_sort_ratio(expected, read), squashed)
    if whole >= TITLE_MATCH:
        return whole
    words, n = read.split(), len(expected.split())
    best = 0.0
    for k in (n - 1, n, n + 1):
        if k < 1 or k > len(words) or k == len(words):
            continue
        for i in range(len(words) - k + 1):
            best = max(best, fuzz.ratio(expected, " ".join(words[i:i + k])))
    return best if best >= TITLE_PART_MATCH else whole


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
    # Where to read `title` from, when it is not the top-left name -- the
    # centre card of a carousel, a line of text on a notice.
    title_box: tuple[float, float, float, float] | None = None
    # A more specific version of another screen: one card of a carousel is
    # still that carousel, so reaching it counts as reaching the parent.
    parent: str | None = None
    # Text that must be somewhere on screen, and text that must not be. Read,
    # never matched against captured images, so it holds on any device.
    marks: tuple[str, ...] = ()
    absent_marks: tuple[str, ...] = ()
    # Controls known by shape rather than text: "close" (a gold disc with an X).
    shapes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Transition:
    """A move from one screen to another.

    Most are a tap at a fixed point. Some need a routine instead: the banner
    carousel has no fixed tab for a given event, so reaching the Platinum
    machine means running the picker rather than tapping a memorised spot.
    Those carry an `action` and their x/y are ignored.

    `target` names what to press, so the tap is found on whatever device is
    attached: a control's label ("Rare Capsule"), or "@back", "@close" or
    "@card" (the centred carousel card). x/y are a hint from one device, used
    only when the target cannot be found.
    """

    src: str
    dst: str
    x: float = 0.0
    y: float = 0.0
    label: str = ""
    settle: float = 1.8
    action: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class Candidate:
    score: float
    name: str
    verified: bool          # every piece of evidence was checked, none assumed
    # Some text -- its title or a mark -- was actually read. A shape alone (a
    # gold X) is on too many panels to name a screen by itself.
    read: bool = True


@dataclass
class Recognition:
    here: str | None
    candidates: list
    percept: object | None  # the full look, when one was needed
    chapter: str | None = None      # which chapter's Cat Base, from its background
    door: tuple | None = None       # the background region that was compared


class UnknownScreen(RuntimeError):
    pass


class NoRoute(RuntimeError):
    pass


@dataclass
class UIGraph:
    screens: dict[str, Screen] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    _ocr: object | None = field(default=None, repr=False)
    # Where learned device profiles live; None is state/devices.
    profile_root: Path | None = field(default=None, repr=False)
    _profiles: dict = field(default_factory=dict, repr=False)
    # The gacha events live today, each a screen of the map (see events.py).
    events: list = field(default_factory=list, repr=False)

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None, carousels: bool | Path = True,
             events: bool = True) -> "UIGraph":
        """The base map, plus this save's sagas and chapters when they are known.

        The base file describes screens every save has. Which sagas and
        chapters exist depends on how far a save has got, so those are scanned
        from the device into state/ and layered on top (see carousel.py).
        Pass carousels=False for the base map alone.
        """
        path = Path(path or GRAPH_FILE)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        graph = cls(
            screens={
                s["name"]: Screen(
                    name=s["name"],
                    title=s.get("title"),
                    anchors=tuple(s.get("anchors", ())),
                    absent=tuple(s.get("absent", ())),
                    forbidden=s.get("forbidden", False),
                    reactive=s.get("reactive", False),
                    note=s.get("note", ""),
                    title_box=tuple(s["title_box"]) if s.get("title_box") else None,
                    parent=s.get("parent"),
                    marks=tuple(s.get("marks", ())),
                    absent_marks=tuple(s.get("absent_marks", ())),
                    shapes=tuple(s.get("shapes", ())),
                )
                for s in raw.get("screens", [])
            },
            transitions=[Transition(**t) for t in raw.get("transitions", [])],
        )
        if carousels:
            from . import carousel

            catalogue = carousel.load_catalogue(None if carousels is True else carousels)
            if catalogue:
                carousel.extend(graph, catalogue)
        if events:
            from . import events as live
            from .data import load as load_dataset

            try:
                live.extend(graph, live.live_events(load_dataset()))
            except FileNotFoundError:
                pass                    # no dataset fetched yet: no event screens
        return graph

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or GRAPH_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "screens": [
                {
                    "name": s.name, "title": s.title,
                    **({"marks": list(s.marks)} if s.marks else {}),
                    **({"absent_marks": list(s.absent_marks)} if s.absent_marks else {}),
                    **({"shapes": list(s.shapes)} if s.shapes else {}),
                    **({"anchors": list(s.anchors)} if s.anchors else {}),
                    **({"absent": list(s.absent)} if s.absent else {}),
                    "forbidden": s.forbidden, "reactive": s.reactive, "note": s.note,
                    **({"title_box": list(s.title_box)} if s.title_box else {}),
                    **({"parent": s.parent} if s.parent else {}),
                }
                for s in sorted(self.screens.values(), key=lambda s: s.name)
            ],
            "transitions": [{k: v for k, v in vars(t).items() if k != "target" or v}
                            for t in self.transitions],
        }, indent=1))
        return path

    # -- recognition --------------------------------------------------------

    @property
    def ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        return self._ocr

    def read_title(self, frame: np.ndarray, box=TITLE_BOX, largest: bool = False) -> str:
        """Text in `box`, in reading order. `largest` keeps only title-sized
        lettering, dropping smaller text that strays into the box."""
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = box
        crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
        if crop.size == 0:
            return ""
        # Scaled against a 2532-wide frame, so small and large screens read alike.
        scale = TITLE_SCALE * 2532 / w
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        result, _ = self.ocr(crop)
        result = result or []

        def top(r):
            return min(p[1] for p in r[0])

        def bottom(r):
            return max(p[1] for p in r[0])

        if largest and result:
            tall = max(bottom(r) - top(r) for r in result)
            result = [r for r in result if bottom(r) - top(r) >= 0.6 * tall]
        # Pieces come back in detection order; a two-line card name needs
        # reading order -- line by line, top to bottom, then left to right.
        # A piece joins a line when its middle is within half its own height.
        lines: list[list] = []
        for r in sorted(result, key=lambda r: top(r) + bottom(r)):
            middle, height = (top(r) + bottom(r)) / 2, bottom(r) - top(r)
            if lines:
                last = lines[-1]
                last_middle = sum(top(p) + bottom(p) for p in last) / (2 * len(last))
                if abs(middle - last_middle) <= 0.5 * height:
                    last.append(r)
                    continue
            lines.append([r])
        pieces = [r for line in lines for r in sorted(line, key=lambda r: r[0][0][0])]
        return " ".join(r[1] for r in pieces).strip()

    def profile_for(self, frame: np.ndarray):
        """What has been learned about the device this frame came from."""
        from .profile import Profile

        h, w = frame.shape[:2]
        with _PROFILES_LOCK:
            if (w, h) not in self._profiles:
                self._profiles[(w, h)] = Profile(w, h, self.profile_root)
            return self._profiles[(w, h)]

    def identify(self, frame: np.ndarray, title: str | None = None) -> str | None:
        """Name the screen in `frame`, or None if it is not in the map."""
        return self.recognise(frame, title=title).here

    def recognise(self, frame: np.ndarray, title: str | None = None, slow: bool = True,
                  ocr: bool = True):
        """Identify the screen, learning about this device when that takes a full look.

        The fast path uses only what the device profile already knows: the
        learned title box and templates of controls seen before. When that
        cannot vouch for every piece of a screen's evidence -- always, the first
        time a screen is met on a device -- the frame is read in full (OCR and
        shape segmentation), identified from that, and the screen's controls
        and title box are learned so the next look is fast.

        `ocr` False reads nothing: a title not remembered as it looks is
        unknown. That is the look for watching a screen change, many times a
        second; `slow` must be False with it.
        """
        from .perception import perceive

        reads: dict = {}
        found = self._evaluate(frame, None, title, reads, ocr=ocr)
        sure = [c for c in found if c.verified]
        best_sure = max((c.score for c in sure), default=None)
        # Answer fast only if no unverified screen, with evidence already in
        # its favour, might still outscore the best verified one.
        doubt = [c for c in found if not c.verified and c.score > 0
                 and (best_sure is None or c.score >= best_sure)]
        if (sure and not doubt) or not slow:
            best = max(sure or found, default=None, key=lambda c: c.score)
            if best is not None and best.verified and sure and not doubt:
                self._remember_titles(frame, best.name, reads)
            return self._with_chapter(frame, Recognition(best.name if best else None, found, None))
        percept = perceive(frame, self.ocr)
        profile = self.profile_for(frame)
        reads = {}
        found = self._evaluate(frame, percept, title, reads)
        # Only a screen whose text was read is named. One known by a shape
        # alone -- any panel with a gold X -- is left unknown, so the caller
        # backs out rather than tapping into an unmapped popup.
        best = max((c for c in found if c.read), default=None, key=lambda c: c.score)
        if best is not None:
            screen = self.screens[best.name]
            # The title box is placed only from a title that has just
            # identified its screen: the logo on the title screen, or a
            # carousel card's name, is not where screen names are printed.
            if (screen.title and not screen.title_box and percept.title is not None
                    and title_match(screen.title, percept.title.text) >= TITLE_MATCH):
                old_box = profile.title_box
                if profile.learn_title(percept.title.box) and old_box in reads:
                    # The full look read the whole title: it stands for the
                    # widened box too, so it is remembered there.
                    reads[profile.title_box] = reads[old_box]
            profile.learn(best.name, frame, percept.controls, wanted=self.wanted(best.name))
            if best.verified:
                self._remember_titles(frame, best.name, reads)
        return self._with_chapter(frame, Recognition(best.name if best else None, found, percept))

    def _remember_titles(self, frame: np.ndarray, name: str, reads: dict) -> None:
        if name in RESULT_SCREENS:
            self.profile_for(frame).learn_text(frame, RESULT_OK_BOX, RESULT_OK)
        self._remember_title_reads(frame, name, reads)

    def _remember_title_reads(self, frame: np.ndarray, name: str, reads: dict) -> None:
        """Keep a picture of each title OCR has just read on a screen now named,
        and on the screen it is a card or event of, so the next look is a
        template match. Only a reading that matched its title is kept."""
        profile = self.profile_for(frame)
        while name:
            screen = self.screens.get(name)
            if screen is None:
                break
            box = screen.title_box or profile.title_box
            read = reads.get(box)
            if screen.title and box is not None and read is not None and read[1] \
                    and title_match(screen.title, read[0], within=screen.parent is None) >= TITLE_MATCH:
                profile.learn_text(frame, box, screen.title)
            name = screen.parent

    def wanted(self, screen: str) -> set[str]:
        """What is worth learning on `screen`: the controls its exits press,
        and any text a screen is recognised by."""
        names = {t.target for t in self.transitions
                 if t.src == screen and t.target and t.target != "@card"}
        for s in self.screens.values():
            names.update(s.marks, s.absent_marks)
        return names

    def _with_chapter(self, frame: np.ndarray, recognition):
        """Name the chapter of a Cat Base from the door behind its buttons."""
        if recognition.here == "cat_base":
            from . import bases

            recognition.chapter, recognition.door = bases.chapter_of(
                frame, self, recognition.percept)
        return recognition

    def candidates(
        self, frame: np.ndarray, title: str | None = None, percept=None
    ) -> list[tuple[float, str]]:
        """Every screen the frame could be, scored. `identify` takes the best."""
        return [(c.score, c.name) for c in self._evaluate(frame, percept, title)]

    def _evaluate(self, frame: np.ndarray, percept, title: str | None, reads: dict | None = None,
                  ocr: bool = True):
        """Weigh each screen's evidence: title, marks, and shapes.

        Evidence is True, False or unknown. False rules a screen out; unknown
        -- a mark never yet seen on this device, a title box not yet placed --
        leaves it possible but unverified, which is what sends identification
        down the slow path to find out.

        `reads` collects each box's text as (text, read by OCR), so that a
        title OCR had to read can be remembered once it has named its screen.
        """
        from .perception import CLOSE_SCORE, close_glyph_score, find_discs

        profile = self.profile_for(frame)
        texts: dict[tuple, str] = {} if reads is None else reads
        title_box = profile.title_box

        def text_in(box) -> str | None:
            if box is None or box == title_box:
                # A full look has just read the title itself; use that.
                if percept is not None:
                    texts[box] = (percept.title.text if percept.title else "", True)
                    return texts[box][0]
                if title is not None:
                    texts[box] = (title, True)
                    return title
            if box is None:
                return None
            if box not in texts:
                known = profile.known_text(frame, box)
                if known is None and not ocr:
                    texts[box] = (None, False)      # unknown, and not to be asked again
                else:
                    texts[box] = ((known, False) if known is not None else
                                  (self.read_title(frame, box, largest=box == title_box), True))
            return texts[box][0]

        shapes: dict[str, bool] = {}

        def shape_seen(kind: str, screen: Screen) -> bool | None:
            # Once this screen (or the carousel it is a card of) has learned
            # where its X sits, the X must be there: a gold X somewhere else
            # belongs to some other panel.
            key = f"@{kind}"
            homes = [n for n in (screen.name, screen.parent) if n and key in profile.controls(n)]
            if homes and percept is None:
                return any(profile.find(frame, n, key) for n in homes)
            if percept is None and not ocr:
                # The look that reads nothing does not search the frame for
                # shapes either: an X not yet learned here is unknown.
                return None
            if kind not in shapes:
                if kind == "close":
                    # Found on a half-size frame: a quarter of the pixels, and
                    # an X disc is still dozens across. Boxes are fractions.
                    half = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                    shapes[kind] = any(close_glyph_score(half, box) >= CLOSE_SCORE
                                       for box, _ in find_discs(half))
                elif kind == "back":
                    shapes[kind] = find_back_arrow(frame) is not None
                else:
                    shapes[kind] = False
            return shapes[kind]

        found_marks: dict[str, bool] = {}

        def mark_seen(mark: str, screen: str, absent: bool = False) -> bool | None:
            # A control learned under this name, on any screen, is looked for
            # by its template first: that costs milliseconds, not an OCR pass.
            # Whether it is anywhere is the same for every screen asking.
            learned_on = set(profile.learned_on(mark))
            if mark not in found_marks:
                found_marks[mark] = any(profile.locate(frame, name, mark) is not None
                                        for name in sorted(learned_on))
            if found_marks[mark]:
                return True
            if percept is not None:
                return any(title_match(mark, t.text, within=True) >= TITLE_MATCH
                           for t in percept.readings())
            # Not where it was learned. For a mark this screen must show, that
            # settles it only if it was learned on this screen: the same word
            # elsewhere sits elsewhere. A mark that must be absent is absent
            # when it is at none of the places it has ever been seen.
            if absent:
                return False if learned_on else None
            return False if screen in learned_on else None

        top_titles = {s.title for s in self.screens.values() if s.title and not s.title_box}

        def named_other(read: str) -> bool:
            return any(title_match(t, read) >= TITLE_MATCH for t in top_titles)

        out = []
        # Parents first: a card or event is only worth reading when the screen
        # it belongs to is still possible, which spares an OCR on most frames.
        ordered = sorted(self.screens.values(), key=lambda s: s.parent is not None)
        for screen in ordered:
            # Without OCR, a parent that nothing was seen of stays possible
            # but can confirm nothing: its cards are not worth a look either.
            if screen.parent and not any(c.name == screen.parent and (ocr or c.read) for c, _ in out):
                continue
            # Forbidden screens are still identified. Refusing to recognise one
            # would leave the bot blind exactly where it most needs to know
            # where it is, so that it can leave deliberately rather than tap
            # about. Forbidding governs routing INTO a screen, nothing else.
            if not (screen.title or screen.marks or screen.shapes):
                continue
            score, verified, ruled_out, read_any = 0.0, True, False, False
            for kind in screen.shapes:
                seen = shape_seen(kind, screen)
                if seen is None:
                    verified = False
                    continue
                if not seen:
                    ruled_out = True
                    break
                score += 40.0
            if ruled_out:
                continue
            if screen.title:
                read = text_in(screen.title_box or title_box)
                if read is None:
                    verified = False            # no title box placed yet
                else:
                    # A carousel card holds only its name, so it must match whole.
                    match = title_match(screen.title, read, within=screen.parent is None)
                    # Titles differ by a word: "Cat Capsules" reads 80 as
                    # "Rare Capsules". A reading that names another screen's
                    # title better is that screen's.
                    # A tie goes to the title the whole reading is closer to:
                    # "Cat Base" lies inside "Cat Base Select" and reads 100 too.
                    if match >= TITLE_MATCH and not screen.title_box and any(
                            (title_match(t, read), fuzz.ratio(t.lower(), read.lower()))
                            > (match, fuzz.ratio(screen.title.lower(), read.lower()))
                            for t in top_titles if t != screen.title):
                        continue
                    if match >= TITLE_MATCH:
                        score += match
                        read_any = True
                        # The title box read loses the end of a longer title:
                        # "Lucky Capsules G" comes back "Lucky Capsules", "Cat
                        # Base Select" as "Cat ! Base". A reading that fits
                        # another title too, or whose title begins another,
                        # is left to a full look, which reads the whole frame.
                        via_ocr = texts.get(screen.title_box or title_box, (None, True))[1]
                        if percept is None and via_ocr and not screen.title_box and any(
                                title_match(t, read) >= TITLE_MATCH
                                or t.lower().startswith(screen.title.lower() + " ")
                                for t in top_titles if t != screen.title):
                            verified = False
                    elif percept is None and not screen.title_box and not named_other(read):
                        # A quick read through the learned box that misses,
                        # and names no other screen either, may be an OCR
                        # flake: leave it to a full look, not a ruling out.
                        verified = False
                    else:
                        continue
            missed = 0
            for mark in screen.marks:
                seen = mark_seen(mark, screen.name)
                if seen is False and percept is not None and (screen.title or screen.shapes):
                    # OCR misses the odd word, so on a full look one missed
                    # mark is forgiven -- but only on a screen with other
                    # evidence, and most of its marks must still read. The
                    # Legend Stages stage list keeps the Cat Base title with
                    # neither Start!! nor Equip on it; a roll result, with no
                    # title at all, needs every mark.
                    missed += 1
                    if 2 * missed > len(screen.marks):
                        ruled_out = True
                        break
                    continue
                if seen is False:
                    ruled_out = True
                    break
                if seen is None:
                    verified = False
                else:
                    score += 60.0
                    read_any = True
            if ruled_out:
                continue
            unsure_absent = set()
            for mark in screen.absent_marks:
                seen = mark_seen(mark, screen.name, absent=True)
                if seen:
                    ruled_out = True
                    break
                if seen is None:
                    unsure_absent.add(mark)
            if ruled_out:
                continue
            out.append((Candidate(score, screen.name, verified and read_any, read_any), unsure_absent))
        # A mark that must be absent but has never been learned here only
        # matters if some screen that shows it is still possible: with no X on
        # screen the menu is ruled out, so its Enemy Guide cannot be showing.
        alive = {c.name for c, _ in out}
        out = [c if not unsure or not any(
                   set(self.screens[n].marks) & unsure for n in alive if n != c.name)
               else Candidate(c.score, c.name, False, c.read)
               for c, unsure in out]
        # A card that fits beats the carousel it belongs to: the generic
        # carousel is only the answer when no card's name reads.
        refined = {self.screens[c.name].parent for c in out if self.screens[c.name].parent}
        return [c for c in out if c.name not in refined]

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
            # A card or an event is still its parent screen, and leaves by
            # the parent's exits as well as its own.
            parent = self.screens[node].parent if node in self.screens else None
            for t in outgoing.get(node, []) + outgoing.get(parent, []):
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
BACK_MIN_AREA = 4000            # pixels, on a REFERENCE_HEIGHT frame



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
    smallest = BACK_MIN_AREA * (h / REFERENCE_HEIGHT) ** 2
    best = None
    for i in range(1, count):
        area = stats[i, 4]
        ratio = stats[i, 2] / max(stats[i, 3], 1)
        if area > smallest and 0.6 < ratio < 1.7:     # roughly circular
            if best is None or area > best[0]:
                best = (area, cent[i][0], cent[i][1])
    if best is None:
        return None
    return (
        x0 + (best[1] / region.shape[1]) * (x1 - x0),
        y0 + (best[2] / region.shape[0]) * (y1 - y0),
    )


def frame_changed(a: np.ndarray, b: np.ndarray, fraction: float = 0.08) -> bool:
    """Whether two frames differ by more than an idle screen's own movement:
    over `fraction` of a small grey thumbnail changed clearly."""
    size = (96, 44)
    ga = cv2.cvtColor(cv2.resize(a, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(cv2.resize(b, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return float((cv2.absdiff(ga, gb) > 30).mean()) > fraction


# Targets whose lettering OCR cannot read, so the recorded spot is all there is.
BLIND_TARGETS = {"Ok"}
# Every capsule result -- a cat, an item, an XP reward -- puts its Ok pill
# here, and the glyph inside it is the same on all of them (1.000 apart). The
# XP reward carries nothing else the map can read, so it is known by this
# glyph alone, as learned from results the map does name.
RESULT_SCREENS = ("roll_result", "normal_result")
RESULT_OK_BOX = (0.717, 0.765, 0.753, 0.825)
RESULT_OK = "result Ok"


def result_ok(graph: "UIGraph", frame: np.ndarray) -> tuple[float, float] | None:
    """Where to press Ok if `frame` shows a capsule result's Ok pill."""
    if graph.profile_for(frame).known_text(frame, RESULT_OK_BOX) != RESULT_OK:
        return None
    x0, y0, x1, y1 = RESULT_OK_BOX
    return (x0 + x1) / 2, (y0 + y1) / 2
# Controls never pressed, whatever a map says: they spend Cat Food or money,
# give a cat away, start a battle, or play an advert.
NEVER_PRESS = ("Store", "Buy", "Attack!", "Draw for Free!", "Trade for Ticket",
               "Change to XP", "Exchange", "Exchange all", "Cat Food")
# How long a tapped event tab has to show its event.
TAB_CONFIRM = 4.0
# A person takes this long, jittered, to find the button on a new screen.
REACTION = 0.35
# After a tap the screen is watched for up to WATCH times the step's settle.
WATCH = 2.0
MIN_WATCH = 2.5


def never_press(label: str) -> bool:
    return any(title_match(n, label, within=False) >= 85 for n in NEVER_PRESS)


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

    def _press(self, x: float, y: float) -> None:
        """Look, then tap: a person takes a moment to find a button. What
        follows is watched for, not slept through (see _settle)."""
        from .layout import landscape_to_hid

        self.human.sleep(REACTION)
        self.session.tap(*self.human.jitter_point(*landscape_to_hid(x, y)))

    def _settle(self, here: str, settle: float):
        """Watch the screen after a tap until it rests somewhere else.

        Returns (screen, frame) once it does: the same screen read on two
        still frames running. One frame is not enough: the top bar stays put
        while the body fades, so a Cat Base title over a half-gone Cat Base
        reads as the Legend Stages list. Returns (None, last frame) if it has
        not left `here` in time -- a slow screen, a popup, or a tap that did
        nothing.
        """
        deadline = time.monotonic() + max(MIN_WATCH, WATCH * settle)
        last = frame = None
        while time.monotonic() < deadline:
            frame = self.session.screenshot()
            name = self.graph.recognise(frame, slow=False, ocr=False).here
            if name is not None and name != here and last is not None and last[0] == name \
                    and not frame_changed(last[1], frame):
                return name, frame
            last = (name, frame)
        return None, frame

    def _answer_dialog(self, frame: np.ndarray, percept=None, log=None) -> bool:
        """Say No to a question standing in the way -- above all "use Cat
        Food?". Found by reading it, not by a captured picture of one."""
        from .perception import perceive

        percept = percept or perceive(frame, self.graph.ocr)
        answer = percept.find("No") or percept.find("Cancel")
        if answer is None or not any("?" in t.text for t in percept.readings()):
            return False
        if log:
            asked = next(t.text for t in percept.readings() if "?" in t.text)
            log(f"    answering No to {asked!r}")
        self._tap(*answer.tap, 1.0)
        return True

    def _resolve(self, here: str, step: Transition, frame: np.ndarray, log=None):
        """Where to press for this step on this device, or None if it is not there."""
        if never_press(step.target or step.label):
            if log:
                log(f"    refusing to press {step.target or step.label!r}")
            return None
        if not step.target or step.target == "@card":
            return step.x, step.y           # the centred card sits mid-screen on any iPhone
        profile = self.graph.profile_for(frame)
        hit = profile.locate(frame, here, step.target)
        if hit is not None:
            return hit
        if step.target in BLIND_TARGETS and (step.x or step.y) and here != "storage":
            return step.x, step.y       # no reading it: go straight to its spot
        from .perception import perceive

        percept = perceive(frame, self.graph.ocr)
        profile.learn(here, frame, percept.controls, wanted=self.graph.wanted(here))
        control = percept.find(step.target)
        if control is not None and not never_press(control.label):
            return control.tap
        # A label that can be read but was not is not on this screen: pressing
        # where it sat on some other screen is how a stage gets opened. Only
        # the Ok pill, whose lettering OCR cannot read, falls back to its spot.
        # Never on Storage: a stray tap there can exchange cats away.
        if step.target in BLIND_TARGETS and (step.x or step.y) and here != "storage":
            if log:
                log(f"    {step.target!r} not read; using the recorded position")
            return step.x, step.y
        return None

    def _tap_tab(self, wanted, log=None) -> bool:
        """Select an event by tapping its tab, found by its remembered picture.
        False if it is not remembered, not found, or the tap did not take."""
        from .bannerpick import TAB_STRIP

        frame = self.session.screenshot()
        spot = self.graph.profile_for(frame).find_image(f"tab {wanted.key}", frame, TAB_STRIP)
        if spot is None:
            return False
        self._press(*spot)
        # Confirmed on a still frame by a quick look that may read: some
        # events' subtitles move, so no remembered picture of them holds.
        deadline, last, landed = time.monotonic() + TAB_CONFIRM, None, None
        while time.monotonic() < deadline:
            frame = self.session.screenshot()
            if last is not None and not frame_changed(last, frame):
                landed = self.graph.recognise(frame, slow=False).here
                if landed == wanted.screen:
                    return True
            last = frame
        if log:
            log(f"    the {wanted.label} tab did not select it ({landed}); stepping through the tabs")
        return False

    def _run_action(self, step: Transition, log=None) -> bool:
        """Carry out a transition that needs a routine rather than a tap."""
        kind, _, argument = (step.action or "").partition(":")
        if kind in ("swipe", "drag"):
            # Carousels do not respond to taps on their side items at all --
            # only the centre one is live, and the selection moves by drag.
            from . import carousel

            carousel.drag(self.session, argument)
            return True
        if kind == "seek":
            from . import carousel

            carousel.seek_end(self.session, self.graph, argument)
            return True
        if kind == "event":
            from .bannerpick import BannerPicker
            from .data import load

            wanted = next((e for e in self.graph.events if e.key == argument), None)
            if wanted is None:
                if log:
                    log(f"  {argument!r} is not a live event")
                return False
            if self._tap_tab(wanted, log):
                return True
            picker = BannerPicker(self.session, load(), ocr=self.graph.ocr)
            chosen = picker.select(wanted.banner, [e.banner for e in self.graph.events])
            # Remember every tab the picker saw, so the next switch is one tap.
            from .bannerpick import tab_box

            for key, ((x, y), frame) in picker.seen_tabs.items():
                self.graph.profile_for(frame).learn_image(f"tab {key}", frame, tab_box(x, y))
            if not chosen:
                return False
            # The new banner fades in: give the screen a few looks to read as
            # the event before calling the switch done.
            for _ in range(6):
                if self.graph.identify(self.session.screenshot()) == wanted.screen:
                    return True
                self.human.sleep(0.8)
            return False
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
        # A step taken again and again that keeps landing elsewhere -- GAMATOTO
        # while it is away, which only ever opens the Ongoing screen -- cannot
        # reach its screen in the game's present state, so stop trying it.
        tries: dict[tuple, int] = {}
        forgiven = False
        settled = None                  # the frame a tap was watched settling on
        for _ in range(max_steps):
            frame = settled if settled is not None else self.session.screenshot()
            settled = None
            rec = self.graph.recognise(frame)
            here = rec.here
            if here == destination or (
                here and self.graph.screens[here].parent == destination
            ):
                # The frame that showed arrival, for a caller that acts next.
                self.arrival = (here, frame)
                return True
            if here is None:
                ok = result_ok(self.graph, frame)
                if ok is not None:
                    # A capsule result the map cannot name: an XP reward.
                    if log:
                        log("    a capsule result: Ok")
                    self._press(*ok)
                    landed, after = self._settle(None, 1.0)
                    settled = after if landed is not None else None
                    continue
                if self._answer_dialog(frame, rec.percept, log):
                    continue
                # Not on the map. Backing out is almost always right: nearly
                # every screen has a back arrow in the same corner, and the
                # places it leads to are ones the map does know.
                lost += 1
                if lost > 10:
                    if log:
                        log("  lost: backing out is not reaching a known screen")
                    return False
                self._tap(*self._way_out(frame), 1.6)
                continue

            lost = 0
            try:
                path = self.graph.route(here, destination, exclude=barren)
            except NoRoute:
                if barren and not forgiven:
                    # Every way on has been written off, perhaps one that was
                    # only slow to answer. Give them all one more chance.
                    forgiven = True
                    barren.clear()
                    tries.clear()
                    continue
                if log:
                    log(f"no route from {here!r} to {destination!r}")
                return False
            step = path[0]
            key = (step.src, step.dst, round(step.x, 3), round(step.y, 3))
            tries[key] = tries.get(key, 0) + 1
            if tries[key] > 3:
                barren.add(key)
                if log:
                    log(f"    {step.label!r} never reaches {step.dst}; giving it up")
                continue
            if log:
                log(f"  {here} --{step.label}--> {step.dst}")
            if step.action:
                if not self._run_action(step, log=log):
                    barren.add(key)
                    if log:
                        log(f"    {step.label!r} did not take; trying another way")
                continue
            point = self._resolve(here, step, frame, log=log)
            if point is None:
                barren.add(key)
                if log:
                    log(f"    no {step.target!r} on screen; trying another way")
                continue
            self._press(*point)
            landed, after = self._settle(here, step.settle)
            if landed is not None:
                settled = after
                continue
            # Watched and never left: a last, closer look before the tap is blamed.
            if self._unmoved(here, frame, wait=0.5):
                # An unlock reward popup holds every tap until its OK.
                from .perception import reward_ok

                ok = reward_ok(self.session.screenshot(), self.graph.ocr)
                if ok is not None:
                    if log:
                        log("    unlock reward popup in the way: OK")
                    self._tap(*ok, 1.0)
                    continue
                barren.add(key)
                if log:
                    log(f"    {step.label!r} changed nothing; trying another way")
        return False

    @staticmethod
    def _way_out(frame: np.ndarray) -> tuple[float, float]:
        """Where to press to leave a screen the map does not know: its back
        arrow, else the X of a panel standing over everything, else where the
        back arrow usually is."""
        back = find_back_arrow(frame)
        if back:
            return back
        from .perception import CLOSE_SCORE, close_glyph_score, find_discs

        scored = [(close_glyph_score(frame, box), centre) for box, centre in find_discs(frame)]
        best = max(scored, default=None)
        return best[1] if best and best[0] >= CLOSE_SCORE else GENERIC_BACK

    def _unmoved(self, here: str, before: np.ndarray, wait: float = 1.5) -> bool:
        """Whether a tap left the game exactly as it was, on `here`.

        A screen still animating out reads as unchanged, so it gets a second
        look before the tap is blamed. One that changed without leaving did
        answer -- Back on Upgrade first steps from a unit list up to the
        Characters overview -- so the same tap is left to be tried again.
        """
        for look in range(2):
            if look:
                self.human.sleep(wait)
            frame = self.session.screenshot()
            if self.graph.identify(frame) != here or frame_changed(before, frame):
                return False
        return True


# The game draws nearly every control as a gold button with a dark outline, at
# a consistent hue. Detecting them beats hand-measuring coordinates: it finds
# controls on screens nobody has mapped yet, and it survives layout drift.
BUTTON_HSV_LOW = (16, 120, 140)
BUTTON_HSV_HIGH = (34, 255, 255)
# Pixel sizes below were measured on a 1170-high frame. The game scales its
# layout with the screen's height, so they are scaled by height to match.
REFERENCE_HEIGHT = 1170
BUTTON_MIN_AREA = 2600
BUTTON_CLOSE_KERNEL = (25, 15)
BUTTON_MAX_AREA_FRACTION = 0.22
BUTTON_ASPECT = (0.45, 9.0)
# Share of its bounding box a blob must fill. Gold scattered across the frame --
# the XP and Cat Food counters, the floor, joined by the frame edge -- merges
# into one sprawling blob at 10%, and title lettering reaches 16%. The round
# Use now button is the sparsest real control, at 22%.
BUTTON_MIN_FILL = 0.19


@dataclass(frozen=True)
class Button:
    """A detected control, in screen fractions.

    x, y is the centroid, which is where to tap; left, top, w, h is the
    bounding box, which a lopsided blob does not share a centre with.
    """

    x: float
    y: float
    w: float
    h: float
    area: int
    left: float = 0.0
    top: float = 0.0

    @property
    def centre(self) -> tuple[float, float]:
        return self.x, self.y


def find_buttons(frame: np.ndarray) -> list[Button]:
    """Every gold control on the screen, ordered top-to-bottom then left-to-right."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BUTTON_HSV_LOW, BUTTON_HSV_HIGH)
    k = h / REFERENCE_HEIGHT
    # Close the dark glyphs printed on top of a button so it reads as one blob.
    kernel = tuple(max(3, round(v * k)) for v in BUTTON_CLOSE_KERNEL)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, kernel)
    )
    count, _lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    limit = BUTTON_MAX_AREA_FRACTION * h * w
    smallest = BUTTON_MIN_AREA * k * k
    out: list[Button] = []
    for i in range(1, count):
        area = int(stats[i, 4])
        bw, bh = int(stats[i, 2]), int(stats[i, 3])
        if area < smallest or area > limit or bh == 0:
            continue
        if not (BUTTON_ASPECT[0] <= bw / bh <= BUTTON_ASPECT[1]):
            continue
        if area < BUTTON_MIN_FILL * bw * bh:
            continue
        out.append(Button(
            x=float(cent[i][0]) / w, y=float(cent[i][1]) / h,
            w=bw / w, h=bh / h, area=area,
            left=float(stats[i, 0]) / w, top=float(stats[i, 1]) / h,
        ))
    out.sort(key=lambda b: (round(b.y, 2), b.x))
    return out
