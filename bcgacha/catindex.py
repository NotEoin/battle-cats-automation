"""Work out which cats the account already owns, by reading the Cat Guide.

The Guide's rarity filter hides anything not yet unlocked, so a filtered grid is
already the owned list -- there is no locked/unlocked signal to detect, only the
question of which cat each cell is. Cells are therefore opened one at a time and
the name read off the description panel, because the thumbnails alone cannot be
told apart without reference art.

Walking is done with the detail view's own next arrow rather than by returning
to the grid each time, which roughly halves the taps.

Two things the game does that get in the way:

  * A cat whose entry has never been opened carries a NEW! badge, and opening it
    pops up a Cat Food reward that must be dismissed before the detail view is
    usable.
  * OCR of a stylised game font drops the odd letter, so names are matched
    fuzzily against the dataset rather than by equality.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import fuzz, process

from .data import BASIC, EX, LEGEND, RARE, SUPER_RARE, Dataset
from .layout import landscape_to_hid
from .session import DeviceSession

INDEX_FILE = Path(__file__).resolve().parent.parent / "state" / "owned.json"

# Cat Guide, measured on the landscape frame.
GUIDE = {
    "filter": (0.292, 0.142),
    "back": (0.089, 0.872),
    "first_cell": (0.285, 0.258),
    "detail_next": (0.910, 0.450),
    "detail_prev": (0.090, 0.450),
}

CAT_BASE = {
    "menu": (0.124, 0.719),
    "upgrade": (0.200, 0.413),
    "rare_capsule": (0.526, 0.776),
    "storage": (0.377, 0.776),
}

MENU_DIALOG = {
    "cat_guide": (0.4158, 0.3425),
    "close": (0.671, 0.178),
}

FILTER_DIALOG = {
    "Normal": (0.397, 0.205),
    "Special": (0.540, 0.205),
    "Rare": (0.684, 0.205),
    "Super Rare": (0.397, 0.301),
    "Uber Rare": (0.540, 0.301),
    "Legend Rare": (0.684, 0.301),
    "ok": (0.500, 0.877),
    "clear": (0.744, 0.877),
}

RARITY_FILTER_NAME = {
    BASIC: "Normal",
    EX: "Special",
    RARE: "Rare",
    SUPER_RARE: "Super Rare",
    4: "Uber Rare",
    LEGEND: "Legend Rare",
}

# The name sits on the first line of the description panel.
NAME_BOX = (0.245, 0.595, 0.760, 0.680)
# OCR renders the locked placeholder as ???, ?7?, 277 and similar.
LOCKED_RE = re.compile(r"[?72]{2,}")

# Consecutive identical description panels that mean the list will not move.
# The cat artwork animates, so only the static text panel can be compared, and
# the run has to be long enough that a stretch of identical locked entries does
# not look like the end.
END_OF_LIST_FRAMES = 8
# Frames differing by less than this on average are treated as the same.
FRAME_SAME_TOLERANCE = 0.8


def _frames_match(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape:
        return False
    return float(np.mean(cv2.absdiff(a, b))) < FRAME_SAME_TOLERANCE
# The panel itself, used to tell "detail view" from "a popup is covering it".
PANEL_BOX = (0.245, 0.590, 0.760, 0.800)


@dataclass
class OwnedIndex:
    owned: set[int] = field(default_factory=set)
    unresolved: list[str] = field(default_factory=list)
    scanned_rarities: list[int] = field(default_factory=list)
    locked_seen: int = 0      # entries showing ??? -- present but not unlocked
    entries_walked: int = 0

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or INDEX_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "owned": sorted(self.owned),
            "unresolved": self.unresolved,
            "scanned_rarities": self.scanned_rarities,
            "locked_seen": self.locked_seen,
            "entries_walked": self.entries_walked,
        }, indent=1))
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "OwnedIndex":
        path = Path(path or INDEX_FILE)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(
            owned=set(raw.get("owned", [])),
            unresolved=raw.get("unresolved", []),
            scanned_rarities=raw.get("scanned_rarities", []),
            locked_seen=raw.get("locked_seen", 0),
            entries_walked=raw.get("entries_walked", 0),
        )


def _crop(frame: np.ndarray, box) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]


def clean_name(raw: str) -> str:
    """Strip the game's bracket decoration and OCR noise."""
    text = re.sub(r"[\[\]【】]", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


class CatIndexer:
    def __init__(self, session: DeviceSession, dataset: Dataset, ocr=None):
        self.session = session
        self.dataset = dataset
        self._ocr = ocr
        self._names: dict[str, int] | None = None

    @property
    def ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        return self._ocr

    def name_table(self, rarities: set[int]) -> dict[str, int]:
        """Every form name of every cat in the rarities being scanned."""
        table: dict[str, int] = {}
        for cat_id, entry in self.dataset.cats.items():
            if entry.get("rarity") not in rarities:
                continue
            for form in entry.get("name") or []:
                if form and form.strip():
                    table.setdefault(form.strip(), cat_id)
        return table

    def tap(self, point, settle: float = 1.1) -> None:
        self.session.tap(*landscape_to_hid(*point))
        time.sleep(settle)

    def read_name(self, frame: np.ndarray) -> str | None:
        result, _ = self.ocr(_crop(frame, NAME_BOX))
        if not result:
            return None
        return clean_name(result[0][1])

    def find_ok_button(self, frame: np.ndarray) -> tuple[float, float] | None:
        """Locate a bright yellow confirm button in the middle of the screen.

        The unlock reward popup sits over the description panel and its OK is
        not where any other Ok in the game is, so it is found by colour rather
        than by a memorised coordinate.
        """
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (18, 150, 180), (32, 255, 255))
        band = np.zeros_like(mask)
        band[int(0.50 * h): int(0.75 * h), int(0.30 * w): int(0.80 * w)] = 255
        count, _lab, stats, cent = cv2.connectedComponentsWithStats(
            cv2.bitwise_and(mask, band), 8
        )
        best = None
        for i in range(1, count):
            area = stats[i, 4]
            ratio = stats[i, 2] / max(stats[i, 3], 1)
            if area > 9000 and 1.5 < ratio < 6.0:
                if best is None or area > best[0]:
                    best = (area, cent[i][0] / w, cent[i][1] / h)
        return (best[1], best[2]) if best else None

    def on_detail(self, frame: np.ndarray) -> bool:
        """True when the description panel is readable and nothing covers it."""
        panel = _crop(frame, PANEL_BOX)
        if not panel.size or float(panel.mean()) >= 90:
            return False
        return self.find_ok_button(frame) is None

    def dismiss_popup(self) -> bool:
        """Clear the 'X unlocked! You got N Cat Food!' reward popup."""
        for _ in range(4):
            frame = self.session.screenshot()
            point = self.find_ok_button(frame)
            if point is None:
                return self.on_detail(frame)
            self.tap(point, settle=0.9)
        return False

    def open_guide(self, timeout: float = 45.0, log=print) -> bool:
        """Get to a freshly opened Cat Guide, from wherever the game is.

        The Guide's own back and arrow buttons ignore synthetic taps, so the
        only dependable way to rewind it is to leave entirely and come back:
        out to the Cat Base, then Menu, then Cat Guide. That also guarantees
        the grid starts on page one.
        """
        from . import vision

        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.session.screenshot()
            screen = vision.classify(frame)
            if screen is vision.Screen.CAT_GUIDE:
                return True
            if screen is vision.Screen.MENU:
                self.tap(MENU_DIALOG["cat_guide"], settle=2.4)
                continue
            if screen is vision.Screen.CAT_BASE:
                self.tap(CAT_BASE["menu"], settle=2.0)
                continue
            if self.find_ok_button(frame) is not None:
                self.dismiss_popup()
                continue
            # Anywhere else: back out one level and look again.
            self.tap(GUIDE["back"], settle=1.6)
        log("could not reach the Cat Guide")
        return False

    def clear_filter(self) -> None:
        """Drop every filter so unowned cats show up as [???] too."""
        self.tap(GUIDE["filter"], settle=1.6)
        self.tap(FILTER_DIALOG["clear"], settle=0.8)
        self.tap(FILTER_DIALOG["ok"], settle=2.2)

    def rewind(self, pages: int = 14) -> None:
        """Flick back to the first page of the grid."""
        for _ in range(pages):
            self.session.swipe(
                *landscape_to_hid(0.28, 0.45), *landscape_to_hid(0.72, 0.45),
                steps=20, duration=0.24,
            )
            time.sleep(0.45)

    def set_filter(self, rarities: set[int]) -> None:
        self.tap(GUIDE["filter"], settle=1.6)
        self.tap(FILTER_DIALOG["clear"], settle=0.8)
        for rarity in sorted(rarities):
            name = RARITY_FILTER_NAME.get(rarity)
            if name:
                self.tap(FILTER_DIALOG[name], settle=0.6)
        self.tap(FILTER_DIALOG["ok"], settle=2.2)

    def walk(
        self,
        rarities: set[int],
        limit: int | None = None,
        log=print,
        checkpoint: bool = True,
    ) -> OwnedIndex:
        """Step through every Guide entry, recording the ones that are unlocked.

        The Guide wraps, so this can start anywhere: it walks until the opening
        run of names comes round again, or until `limit` entries. No attempt is
        made to return to the first entry first, because the Guide's arrow and
        back buttons do not respond to synthetic taps -- only flicks move it.
        """
        table = self.name_table(rarities)
        choices = list(table)
        # The Guide holds roughly one entry per known cat; a margin covers
        # entries the dataset has not caught up with yet.
        if limit is None:
            limit = len(self.dataset.cats) + 80
        index = OwnedIndex(scanned_rarities=sorted(rarities))
        seen: list[str] = []
        misses = 0
        stuck = 0
        previous: np.ndarray | None = None

        for step in range(limit):
            frame = self.session.screenshot()

            # The Guide does NOT wrap: it dead-ends on the last entry and
            # further flicks do nothing at all. An unchanging frame is the
            # only reliable end signal, so stop once the screen stops moving.
            panel = _crop(frame, PANEL_BOX)
            if previous is not None and _frames_match(previous, panel):
                stuck += 1
                if stuck >= END_OF_LIST_FRAMES:
                    log(f"  screen stopped changing at step {step}: end of the guide")
                    break
            else:
                stuck = 0
            previous = panel
            if not self.on_detail(frame):
                self.dismiss_popup()
                frame = self.session.screenshot()
            if not self.on_detail(frame):
                misses += 1
                if misses >= 8:
                    log(f"  lost the detail view at step {step}, stopping")
                    break
                self.advance()
                continue
            misses = 0

            raw = self.read_name(frame) or ""
            index.entries_walked += 1

            if not raw or LOCKED_RE.search(raw):
                index.locked_seen += 1
                label = "[???]"
            else:
                hit = process.extractOne(
                    raw, choices, scorer=fuzz.WRatio,
                    processor=str.lower, score_cutoff=82,
                )
                if hit:
                    index.owned.add(table[hit[0]])
                    label = hit[0]
                else:
                    index.unresolved.append(raw)
                    label = f"?{raw}"

            seen.append(label)
            # Checkpoint as we go: a walk of this length is too expensive to
            # lose to an interrupted run.
            if checkpoint and step % 25 == 0:
                index.save()
            if step % 25 == 0:
                log(f"  {step:>4} {label[:34]:<34} owned={len(index.owned)} "
                    f"locked={index.locked_seen}", flush=True)
            self.advance()
        return index

    def advance(self) -> None:
        """Step to the next entry.

        The Guide's arrows do not respond to synthetic taps at all -- neither a
        short nor a long press moves it -- but a flick across the artwork does.
        """
        self.session.swipe(
            *landscape_to_hid(0.72, 0.42), *landscape_to_hid(0.26, 0.42),
            steps=24, duration=0.28,
        )
        time.sleep(0.85)
