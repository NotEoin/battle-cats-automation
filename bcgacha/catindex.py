"""Work out which cats the account already owns, by reading the Cat Guide.

The Guide's rarity filter hides anything not yet unlocked, so a filtered grid is
already the owned list -- there is no locked/unlocked signal to detect, only the
question of which cat each cell is. Cells are therefore opened one at a time and
the name read off the description panel, because the thumbnails alone cannot be
told apart without reference art.

Walking is done from one detail view to the next rather than by returning to
the grid each time, which roughly halves the taps. The detail view's arrows do
not answer synthetic taps, so each step is a flick across the artwork.

Two things the game does that get in the way:

  * A cat whose entry has never been opened carries a NEW! badge, and opening it
    pops up a Cat Food reward that must be dismissed before the detail view is
    usable.
  * OCR of a stylised game font drops the odd letter, so names are matched
    fuzzily against the dataset rather than by equality.

Positions are fractions of the landscape frame, measured on a 2532x1170
iPhone; other screen shapes are untested.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from rapidfuzz import fuzz, process

from .data import BASIC, EX, LEGEND, RARE, SUPER_RARE, UBER
from .layout import landscape_to_hid
from .paths import STATE

INDEX_FILE = STATE / "owned.json"

# The Guide grid's first cell, which opens the first entry's detail view.
FIRST_CELL = (0.285, 0.258)
# A flick from right to left across the artwork steps to the next entry; the
# panel is still sliding for a moment after it lands.
FLICK_FROM, FLICK_TO = (0.72, 0.42), (0.26, 0.42)
FLICK_STEPS, FLICK_SECONDS = 24, 0.28
FLICK_SETTLE = 0.85

# The name sits on the first line of the description panel.
NAME_BOX = (0.245, 0.595, 0.760, 0.680)
# OCR renders the locked placeholder as ???, ?7?, 277 and similar. It must
# match the WHOLE name, because "Rei Ayanami (???)" is a real unit whose name
# contains the same characters and would otherwise read as locked.
LOCKED_RE = re.compile(r"^[\s\[\]()?72]+$")

# Consecutive static frames that mean the list will not move any further.
# The cat artwork animates, so the comparison uses two regions that do not:
# the description panel and the evolution-form strip. Agreeing on both is
# strong enough evidence to call the end after a short run, which keeps the
# walk from flicking into the void for ten swipes once it reaches the last
# entry.
END_OF_LIST_FRAMES = 4

# The evolution-form thumbnails, top left of the detail view.
FORMS_BOX = (0.015, 0.120, 0.230, 0.250)
# Frames differing by less than this on average are treated as the same.
FRAME_SAME_TOLERANCE = 0.8
# The panel itself, used to tell "detail view" from "a popup is covering it".
PANEL_BOX = (0.245, 0.590, 0.760, 0.800)


def _frames_match(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape:
        return False
    return float(np.mean(cv2.absdiff(a, b))) < FRAME_SAME_TOLERANCE


@dataclass
class OwnedIndex:
    """The cats the account owns, as one walk of the Cat Guide read them."""

    owned: set[int] = field(default_factory=set)
    unresolved: list[str] = field(default_factory=list)
    scanned_rarities: list[int] = field(default_factory=list)
    locked_seen: int = 0      # entries showing ??? -- present but not unlocked
    entries_walked: int = 0
    # Only a walk that reached the end of the Guide is the owned list. A
    # partial one would make every cat it did not reach look like a target.
    complete: bool = False
    scanned_at: str = ""        # UTC ISO 8601, "2026-10-15T08:15:30Z"

    def save(self, path: Path | None = None) -> Path:
        """Write the index aside and swap it in; returns where it went."""
        path = Path(path or INDEX_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "owned": sorted(self.owned),
            "unresolved": self.unresolved,
            "scanned_rarities": self.scanned_rarities,
            "locked_seen": self.locked_seen,
            "entries_walked": self.entries_walked,
            "complete": self.complete,
            "scanned_at": self.scanned_at,
        }, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "OwnedIndex":
        """The index saved at `path`, or an empty one if there is none."""
        path = Path(path or INDEX_FILE)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            owned=set(raw.get("owned", [])),
            unresolved=raw.get("unresolved", []),
            scanned_rarities=raw.get("scanned_rarities", []),
            locked_seen=raw.get("locked_seen", 0),
            entries_walked=raw.get("entries_walked", 0),
            complete=raw.get("complete", False),
            scanned_at=raw.get("scanned_at", ""),
        )

    def to_json(self, dataset: Any = None) -> dict:
        """A summary for the live page, counted by rarity when `dataset` is given."""
        from collections import Counter

        by = Counter(dataset.rarity_of(c) for c in self.owned) if dataset else {}
        names = {BASIC: "normal", EX: "special", RARE: "rare", SUPER_RARE: "super rare",
                 UBER: "uber", LEGEND: "legend"}
        return dict(owned=len(self.owned), complete=self.complete, scanned_at=self.scanned_at,
                    walked=self.entries_walked, locked=self.locked_seen,
                    unresolved=self.unresolved[-20:],
                    by_rarity={names.get(k, k): v for k, v in sorted(by.items())})


def _crop(frame: np.ndarray, box) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]


# A confident match either scores very highly, or clearly beats the runner-up.
# OCR of a stylised game font mangles enough letters that a flat high cutoff
# throws away real matches, but a low one alone invites false positives.
STRONG_SCORE = 88.0
WEAK_SCORE = 70.0
REQUIRED_MARGIN = 6.0


def match_name(raw: str, choices: list[str]) -> str | None:
    """Best dataset name for an OCR reading, or None if it is ambiguous."""
    hits = process.extract(
        raw, choices, scorer=fuzz.WRatio, processor=str.lower, limit=2
    )
    if not hits:
        return None
    best, best_score = hits[0][0], hits[0][1]
    if best_score >= STRONG_SCORE:
        return best
    if best_score < WEAK_SCORE:
        return None
    runner_up = hits[1][1] if len(hits) > 1 else 0.0
    return best if best_score - runner_up >= REQUIRED_MARGIN else None


def clean_name(raw: str) -> str:
    """Strip the game's bracket decoration and OCR noise."""
    text = re.sub(r"[\[\]\u3010\u3011]", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def next_entry(session: Any) -> None:
    """Step the Guide to its next entry.

    The Guide's arrows do not respond to synthetic taps at all -- neither a
    short nor a long press moves it -- but a flick across the artwork does.
    """
    session.swipe(*landscape_to_hid(*FLICK_FROM), *landscape_to_hid(*FLICK_TO),
                  steps=FLICK_STEPS, duration=FLICK_SECONDS)
    time.sleep(FLICK_SETTLE)


# -- the device-independent scan ------------------------------------------------------

PARTIAL_FILE = INDEX_FILE.with_name("owned.partial.json")
# Name reading: the plate is upscaled and every OCR piece kept; a name must be
# close and clearly closer than the next-best cat.
NAME_SCALE = 2
NAME_MATCH = 78
NAME_MARGIN = 6
# OCR pieces whose tops lie within this many pixels of the upscaled plate are
# one line of the name.
LINE_PX = 30
# An exact reading: any lead over the next cat will do.
EXACT = 99.5
# The detail panel is dark; brighter than this on average, something covers it.
PANEL_DARK = 90
# Frames in a row without the detail panel before the walk is lost.
MAX_MISSES = 8
# Every this many entries, the partial list is saved and a line logged.
SAVE_EVERY = 25
# The detail view's arrows: their band down the frame, the left and right
# columns, their yellow in OpenCV HSV, and the share of it that means shown
# (or, below the other, gone).
ARROW_Y = (0.36, 0.56)
ARROW_LEFT, ARROW_RIGHT = (0.06, 0.14), (0.86, 0.94)
ARROW_HSV = ((22, 70, 60), (45, 255, 210))
ARROW_SHOWN, ARROW_GONE = 0.05, 0.02
# The OCR engine: an image in, (results, timings) out, as RapidOCR returns.
OCR = Callable[[np.ndarray], tuple]


def read_plate(frame: np.ndarray, ocr: OCR) -> str:
    """The whole name on the detail panel, all pieces in reading order."""
    crop = _crop(frame, NAME_BOX)
    if crop.size == 0:
        return ""
    crop = cv2.resize(crop, None, fx=NAME_SCALE, fy=NAME_SCALE, interpolation=cv2.INTER_CUBIC)
    result, _ = ocr(crop)
    pieces = sorted(result or [], key=lambda r: (round(min(p[1] for p in r[0]) / LINE_PX), r[0][0][0]))
    return clean_name(" ".join(str(r[1]) for r in pieces))


def at_end(frame: np.ndarray) -> bool:
    """Whether this is the Guide's last entry: its left arrow shows, and the
    right one, which leads on to the next entry, is gone."""
    h, w = frame.shape[:2]

    def arrow(x0, x1):
        crop = frame[int(ARROW_Y[0] * h): int(ARROW_Y[1] * h), int(x0 * w): int(x1 * w)]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        return float((cv2.inRange(hsv, *ARROW_HSV) > 0).mean())

    return arrow(*ARROW_LEFT) >= ARROW_SHOWN and arrow(*ARROW_RIGHT) < ARROW_GONE


def match_cat(raw: str, table: dict[str, int]) -> tuple[int | None, float, float]:
    """(cat id, score, margin) for a plate reading, strictly."""
    # OCR reads the apostrophe out of "Li'l": "Li Gross Cat", "Lii cat".
    raw = re.sub(r"^(lil|lii|li)\s+", "li'l ", raw.strip().lower())
    if len(raw) < 3:
        return None, 0.0, 0.0
    best: dict[int, float] = {}
    for name, cat in table.items():
        n = name.lower()
        score = max(fuzz.ratio(raw, n), fuzz.token_sort_ratio(raw, n))
        if score > best.get(cat, 0.0):
            best[cat] = score
    ranked = sorted(((v, c) for c, v in best.items()), reverse=True)
    if not ranked:
        return None, 0.0, 0.0
    score, cat = ranked[0]
    margin = score - (ranked[1][0] if len(ranked) > 1 else 0.0)
    # An exact reading no other cat also matches exactly is the cat, however
    # close its twins are: "Ancient Egg: N202" beside N201, Evil beside Devil.
    exact = score >= EXACT and margin > 0
    if not exact and (score < NAME_MATCH or margin < NAME_MARGIN):
        return None, score, margin
    return cat, score, margin


# The name plate must be the same in this many frames in a row before it is
# read: a flick is still sliding the panel for a moment after it lands, and a
# half-arrived plate reads "vil Cat" for Evil Cat.
STILL_FRAMES = 2


def still_frame(session: Any, frame: np.ndarray | None = None, tries: int = 8) -> np.ndarray:
    """A frame taken once the name plate has stopped moving."""
    frame = frame if frame is not None else session.screenshot()
    for _ in range(tries):
        nxt = session.screenshot()
        if _frames_match(_crop(frame, NAME_BOX), _crop(nxt, NAME_BOX)):
            return nxt
        frame = nxt
    return frame


def _reward_popup(frame: np.ndarray, ocr: OCR) -> tuple[float, float] | None:
    from .perception import reward_ok

    return reward_ok(frame, ocr)


def scan(session: Any, graph: Any, dataset: Any, ocr: OCR, log: Callable[[str], None] = print,
         on_entry: Callable[[dict], None] | None = None, should_stop: Callable[[], bool] | None = None,
         human: Any = None, limit: int | None = None) -> OwnedIndex:
    """Read every Cat Guide entry and return the cats this account owns.

    Reaches the Guide through the UI map, from wherever the game is, and
    re-enters it so it starts on its first page. Every tap is made only once
    the screen is confirmed: the filter dialog by its own words, the reward
    popup by its text. The owned list is only saved as the owned list when the
    walk reaches the end of the Guide; until then it is a partial file.
    """
    from .perception import perceive
    from .uigraph import Navigator

    nav = Navigator(session, graph, humaniser=human)
    if not (nav.goto("cat_base", log=log) and nav.goto("cat_guide", log=log)):
        raise RuntimeError("could not reach the Cat Guide")
    frame = session.screenshot()
    percept = perceive(frame, ocr)
    filt = percept.find("Filter")
    if filt is not None:
        # Clear every filter, so the walk covers the whole Guide.
        nav._tap(*filt.tap, 1.6)
        dialog = perceive(session.screenshot(), ocr)
        clear, ok = dialog.find("Clear"), dialog.find("OK")
        if clear is None or ok is None:
            raise RuntimeError("the Guide's filter dialog did not read as expected")
        nav._tap(*clear.tap, 0.8)
        nav._tap(*ok.tap, 2.0)
    if graph.identify(session.screenshot()) != "cat_guide":
        raise RuntimeError("not on the Cat Guide grid")
    nav._tap(*FIRST_CELL, 2.0)

    table: dict[str, int] = {}
    for cat_id, entry in dataset.cats.items():
        for form in entry.get("name") or []:
            if form and form.strip():
                table.setdefault(form.strip(), cat_id)
    index = OwnedIndex(scanned_rarities=sorted({BASIC, EX, RARE, SUPER_RARE, UBER, LEGEND}))
    # Room past the dataset's count for entries it does not list yet.
    limit = limit or len(dataset.cats) + 80

    def dismissed(frame) -> bool:
        ok = _reward_popup(frame, ocr)
        if ok is None:
            return False
        log("  unlock reward: OK")
        nav._tap(*ok, 1.0)
        return True

    previous, stuck, misses, last_raw = None, 0, 0, None
    for step in range(limit):
        if should_stop and should_stop():
            index.save(PARTIAL_FILE)
            raise RuntimeError("owned scan stopped part way; partial list kept aside")
        frame = still_frame(session)
        signature = (_crop(frame, PANEL_BOX), _crop(frame, FORMS_BOX))
        if previous is not None and all(_frames_match(a, b) for a, b in zip(previous, signature)):
            stuck += 1
            if stuck >= END_OF_LIST_FRAMES:
                # A static screen is the end of the Guide only if nothing is
                # standing in front of it holding the flicks back.
                if dismissed(frame):
                    stuck, previous = 0, None
                    continue
                index.complete = True
                break
        else:
            stuck = 0
        previous = signature
        panel = _crop(frame, PANEL_BOX)
        if not panel.size or float(panel.mean()) >= PANEL_DARK:
            if dismissed(frame):
                continue
            misses += 1
            if misses >= MAX_MISSES:
                index.save(PARTIAL_FILE)
                raise RuntimeError(f"lost the Guide's detail view at entry {step}")
            next_entry(session)
            continue
        misses = 0
        raw = read_plate(frame, ocr)
        if raw and raw == last_raw:
            # The flick did not move on: an unlock popup is in the way, or
            # this is the last entry. Clear the popup and look again.
            if dismissed(frame):
                continue
            next_entry(session)
            continue
        last_raw = raw
        index.entries_walked += 1
        if not raw or LOCKED_RE.search(raw):
            index.locked_seen += 1
            cat, score, margin, status = None, 0.0, 0.0, "locked"
        else:
            cat, score, margin = match_cat(raw, table)
            if cat is not None:
                index.owned.add(cat)
                status = "owned"
            else:
                index.unresolved.append(raw)
                status = "unresolved"
        if at_end(frame):
            index.complete = True
        if on_entry:
            on_entry(dict(step=step, raw=raw, cat_id=cat, name=dataset.cat_name(cat) if cat is not None else None,
                          score=round(score, 1), margin=round(margin, 1), status=status,
                          owned=len(index.owned), locked=index.locked_seen))
        if step % SAVE_EVERY == 0:
            index.save(PARTIAL_FILE)
            log(f"  {step:>4} {raw[:34]:<34} owned={len(index.owned)} locked={index.locked_seen}")
        if index.complete:
            log(f"  last entry of the Guide reached at step {step}")
            break
        next_entry(session)
    if not index.complete:
        index.save(PARTIAL_FILE)
        raise RuntimeError("the Guide walk ended without reaching its last entry")
    index.scanned_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index.save()
    log(f"  Cat Guide read: {len(index.owned)} owned, {index.locked_seen} locked, "
        f"{len(index.unresolved)} unread")
    return index
