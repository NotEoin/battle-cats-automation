"""Read the game screen.

The Battle Cats renders through Cocos2d-x into a single GL surface, so the
device exposes no accessibility elements at all -- `accessibility list-items`
returns an empty list with the game in the foreground. Everything here therefore
works off pixels.

That is less painful than it sounds, because the bot already knows what every
roll will produce from the seed. Vision only has to answer "am I on the screen I
think I am", plus one safety question that genuinely matters: is the draw button
about to spend a ticket, or 150 Cat Food?
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

# The game authors to a fixed landscape layout and stretches it, so anchors are
# held as fractions of the frame rather than pixels.
Box = tuple[float, float, float, float]


class Screen(Enum):
    UNKNOWN = "unknown"
    CAPSULE = "capsule"
    RESULT = "result"
    STORAGE = "storage"
    SENT_TO_STORAGE = "sent_to_storage"
    CAT_BASE = "cat_base"
    DIALOG = "dialog"


@dataclass(frozen=True)
class Anchor:
    name: str
    box: Box
    threshold: float = 0.75

    def crop(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self.box
        return frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]

    def template(self) -> np.ndarray | None:
        path = TEMPLATE_DIR / f"{self.name}.png"
        if not path.exists():
            return None
        return cv2.imread(str(path))


# Anchors measured off a 2532x1170 capture of the Rare Capsule screen.
ANCHORS = {
    "storage_title": Anchor("storage_title", (0.020, 0.005, 0.110, 0.055)),
    "storage_useall": Anchor("storage_useall", (0.405, 0.860, 0.545, 0.940)),
    # The Ok button pulses a pink outline, so it is a poor anchor. The
    # Use now / Exchange pair beside the name plate is static.
    "sent_to_storage": Anchor("sent_to_storage", (0.28, 0.30, 0.72, 0.55)),
    "result_actions": Anchor("result_actions", (0.180, 0.745, 0.345, 0.855)),
    "result_ok": Anchor("result_ok", (0.677, 0.779, 0.792, 0.846), threshold=0.55),
    "storage_button": Anchor("storage_button", (0.135, 0.700, 0.215, 0.900)),
    "try_once_button": Anchor("try_once_button", (0.600, 0.690, 0.790, 0.880)),
    "back_arrow": Anchor("back_arrow", (0.055, 0.835, 0.115, 0.945)),
    "info_button": Anchor("info_button", (0.900, 0.085, 0.955, 0.165)),
    "banner_tabs": Anchor("banner_tabs", (0.020, 0.075, 0.700, 0.170)),
}

COUNTERS = {
    "tickets": (0.640, 0.870, 0.720, 0.955),
    "cat_food": (0.815, 0.860, 0.945, 0.950),
}


def load(path: str | Path) -> np.ndarray:
    frame = cv2.imread(str(path))
    if frame is None:
        raise FileNotFoundError(path)
    return frame


def match(frame: np.ndarray, anchor: Anchor) -> float:
    """How well the stored template matches this frame, 0..1."""
    template = anchor.template()
    if template is None:
        return 0.0
    region = anchor.crop(frame)
    if region.size == 0:
        return 0.0
    if region.shape[:2] != template.shape[:2]:
        template = cv2.resize(template, (region.shape[1], region.shape[0]))
    return float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max())


def visible(frame: np.ndarray) -> dict[str, float]:
    """Score every known anchor against a frame."""
    return {name: match(frame, anchor) for name, anchor in ANCHORS.items()}


def classify(frame: np.ndarray) -> Screen:
    """Best guess at which screen this frame shows."""
    scores = visible(frame)

    def hit(name: str) -> bool:
        return scores.get(name, 0) > ANCHORS[name].threshold

    # Check storage first: its title sits where the capsule title does, and
    # the capsule screen's own anchors are absent there.
    if hit("storage_title") and hit("storage_useall"):
        return Screen.STORAGE
    # Must precede RESULT: the notice overlays the result screen, whose
    # action row is still partly visible behind it.
    if hit("sent_to_storage"):
        return Screen.SENT_TO_STORAGE
    if hit("result_actions"):
        return Screen.RESULT
    if hit("storage_button") and hit("try_once_button"):
        return Screen.CAPSULE
    return Screen.UNKNOWN


# -- digit reading -----------------------------------------------------------

DIGIT_HEIGHT_RATIO = (0.35, 0.75)   # glyph height as a fraction of the crop
YELLOW_LOW = (15, 120, 150)
YELLOW_HIGH = (40, 255, 255)


def digit_boxes(crop: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find the counter glyphs in a crop, left to right.

    Counters are bright yellow with a heavy black outline, so a hue threshold
    isolates them cleanly. Components are filtered to those sharing the modal
    glyph height, which drops the currency icon sitting beside the number.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, YELLOW_LOW, YELLOW_HIGH)
    count, _lab, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    raw = [
        (stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3])
        for i in range(1, count)
        if stats[i, 4] > 150
    ]
    if not raw:
        return []
    lo, hi = DIGIT_HEIGHT_RATIO
    h = crop.shape[0]
    glyphs = [b for b in raw if lo * h <= b[3] <= hi * h]
    if not glyphs:
        return []
    # Keep only glyphs of the modal height; the icon is a different shape.
    modal = max({g[3] for g in glyphs}, key=lambda v: sum(1 for g in glyphs if g[3] == v))
    glyphs = [g for g in glyphs if abs(g[3] - modal) <= 2]
    return sorted(glyphs)


def normalise_glyph(crop: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    hsv = cv2.cvtColor(crop[y: y + h, x: x + w], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, YELLOW_LOW, YELLOW_HIGH)
    return cv2.resize(mask, (20, 32), interpolation=cv2.INTER_AREA)


class DigitAtlas:
    """Glyph templates for the counter font, learnable from labelled crops."""

    def __init__(self, path: Path | None = None):
        self.path = path or (TEMPLATE_DIR / "digits.npz")
        self.glyphs: dict[str, np.ndarray] = {}
        if self.path.exists():
            data = np.load(self.path)
            self.glyphs = {k: data[k] for k in data.files}

    def learn(self, crop: np.ndarray, value: str) -> int:
        """Teach the atlas by giving it a crop and the number it shows.

        The currency icon sits to the left of its number and can survive the
        glyph filter, so the digits are taken from the right.
        """
        boxes = digit_boxes(crop)
        if len(boxes) < len(value):
            raise ValueError(f"found {len(boxes)} glyphs but was told {value!r}")
        for box, ch in zip(boxes[-len(value):], value):
            self.glyphs.setdefault(ch, normalise_glyph(crop, box))
        return len(value)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.path, **self.glyphs)

    MIN_CONFIDENCE = 0.6

    def read(self, crop: np.ndarray) -> int | None:
        """Read a counter, or None if a digit is unrecognised.

        Leading glyphs that match nothing are dropped: that is the currency
        icon beside the number. A glyph that fails *after* digits have started
        is a real unknown, and gives up rather than returning a wrong count.
        """
        out: list[str] = []
        for box in digit_boxes(crop):
            best, score = self._best(normalise_glyph(crop, box))
            if best is None or score < self.MIN_CONFIDENCE:
                if out:
                    return None
                continue  # still in the icon, before the digits
            out.append(best)
        return int("".join(out)) if out else None

    def _best(self, glyph: np.ndarray) -> tuple[str | None, float]:
        best, score = None, 0.0
        for ch, ref in self.glyphs.items():
            value = float(cv2.matchTemplate(glyph, ref, cv2.TM_CCOEFF_NORMED).max())
            if value > score:
                best, score = ch, value
        return best, score


def read_counter(frame: np.ndarray, which: str, atlas: DigitAtlas) -> int | None:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = COUNTERS[which]
    return atlas.read(frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)])


# -- storage capacity --------------------------------------------------------
#
# The Cat Storage fraction is drawn in a plain white sans-serif on a dark
# panel, nothing like the yellow counter font, so it needs its own glyphs.

STORAGE_CAPACITY_BOX: Box = (0.868, 0.790, 0.968, 0.862)
WHITE_MIN = 185


def white_glyph_boxes(crop: np.ndarray) -> list[tuple[int, int, int, int]]:
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mask = (grey >= WHITE_MIN).astype(np.uint8) * 255
    count, _lab, stats, _c = cv2.connectedComponentsWithStats(mask, 8)
    h = crop.shape[0]
    out = [
        (stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3])
        for i in range(1, count)
        if stats[i, 4] > 40 and stats[i, 3] > 0.22 * h
    ]
    return sorted(out)


def normalise_white(crop: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    grey = cv2.cvtColor(crop[y: y + h, x: x + w], cv2.COLOR_BGR2GRAY)
    mask = (grey >= WHITE_MIN).astype(np.uint8) * 255
    return cv2.resize(mask, (20, 32), interpolation=cv2.INTER_AREA)


class StorageAtlas(DigitAtlas):
    """Glyphs for the storage fraction, including the '/' separator."""

    def __init__(self, path: Path | None = None):
        super().__init__(path or (TEMPLATE_DIR / "storage_digits.npz"))

    def learn(self, crop: np.ndarray, value: str) -> int:
        boxes = white_glyph_boxes(crop)
        if len(boxes) != len(value):
            raise ValueError(f"found {len(boxes)} glyphs but was told {value!r}")
        for box, ch in zip(boxes, value):
            self.glyphs.setdefault(ch, normalise_white(crop, box))
        return len(boxes)

    def read_text(self, crop: np.ndarray) -> str | None:
        out: list[str] = []
        for box in white_glyph_boxes(crop):
            best, score = self._best(normalise_white(crop, box))
            if best is None or score < self.MIN_CONFIDENCE:
                return None
            out.append(best)
        return "".join(out) if out else None


def read_storage(frame: np.ndarray, atlas: StorageAtlas) -> tuple[int, int] | None:
    """Return (used, capacity) off the Cat Storage screen, or None."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = STORAGE_CAPACITY_BOX
    text = atlas.read_text(frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)])
    if not text or "/" not in text:
        return None
    used, _, total = text.partition("/")
    try:
        return int(used), int(total)
    except ValueError:
        return None
