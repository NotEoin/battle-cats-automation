"""See a screen with no prior templates: its text, its controls, where to tap.

Nothing here depends on images captured from one particular device. Text comes
from OCR of the frame; controls come from shape -- the game draws them as gold
pills and gold circles -- and take the text inside or on them as their label.
Picture tiles such as Menu or GAMATOTO are not gold, but carry a text tag on
the art, so a label with no gold around it is still somewhere to tap.

This is the slow, general path: one full-frame OCR costs about a second. What
it finds is cached per device (see profile.py), so a screen seen once is
recognised again from small template matches instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .uigraph import find_back_arrow, find_buttons

# Full-frame OCR works on the frame resized to this width, whatever the
# device's resolution: halving a 2532-wide frame reads well, halving a
# 1280-wide one loses "Start!!".
OCR_WIDTH = 1280

# The top-left screen name is set larger than any other text up there; the
# "Record and save this number" line sits in the same corner at half the size.
TITLE_ZONE = (0.0, 0.0, 0.40, 0.12)
TITLE_MIN_HEIGHT = 0.035

# A gold shape this large is a panel holding several controls, not one control.
CONTROL_MAX_AREA = 0.06


@dataclass(frozen=True)
class Text:
    text: str
    box: tuple[float, float, float, float]      # x0, y0, x1, y1 as frame fractions
    conf: float

    @property
    def centre(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


@dataclass(frozen=True)
class Control:
    """Somewhere to press, and what the screen calls it."""

    label: str
    kind: str                                  # "button", "round", "tag", "back", "close"
    box: tuple[float, float, float, float]
    tap: tuple[float, float]


@dataclass
class Percept:
    width: int
    height: int
    texts: list[Text] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    title: Text | None = None
    groups: list[Text] = field(default_factory=list)       # texts joined across lines

    def text(self) -> str:
        return " ".join(t.text for t in self.texts)

    def find(self, label: str) -> Control | None:
        """The control a transition names: a label, or "@back" / "@close"."""
        from .uigraph import title_match

        if label.startswith("@"):
            kind = label[1:]
            return next((c for c in self.controls if c.kind == kind), None)
        best, best_score = None, 0.0
        for c in self.controls:
            if c.kind in ("back", "close"):
                continue            # named by shape; "Back" is a label, not the arrow
            score = title_match(label, c.label, within=True)
            if score > best_score:
                best, best_score = c, score
        return best if best_score >= 85 else None


def _box(points, w, h, scale) -> tuple[float, float, float, float]:
    xs = [p[0] / scale for p in points]
    ys = [p[1] / scale for p in points]
    return min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h


def read_texts(frame: np.ndarray, ocr, width: int = OCR_WIDTH) -> list[Text]:
    h, w = frame.shape[:2]
    scale = width / w
    small = cv2.resize(frame, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    result, _ = ocr(small)
    return [Text(str(t).strip(), _box(b, w, h, scale), float(c))
            for b, t, c in (result or []) if str(t).strip()]


def group_lines(texts: list[Text]) -> list[Text]:
    """Join stacked lines that belong together: "Rare" over "Capsule"."""
    pending = sorted(texts, key=lambda t: (t.box[1], t.box[0]))
    groups: list[list[Text]] = []
    for t in pending:
        for g in groups:
            last = g[-1]
            gap = t.box[1] - last.box[3]
            overlap = min(t.box[2], last.box[2]) - max(t.box[0], last.box[0])
            narrow = min(t.box[2] - t.box[0], last.box[2] - last.box[0])
            if -0.3 * last.height <= gap <= 0.6 * last.height and overlap > 0.5 * narrow \
                    and abs(t.height - last.height) < 0.5 * last.height:
                g.append(t)
                break
        else:
            groups.append([t])
    out = []
    for g in groups:
        box = (min(t.box[0] for t in g), min(t.box[1] for t in g),
               max(t.box[2] for t in g), max(t.box[3] for t in g))
        out.append(Text(" ".join(t.text for t in g), box, min(t.conf for t in g)))
    return out


def find_title(texts: list[Text]) -> Text | None:
    """The screen's name: the largest text in the top-left corner, if any."""
    x0, y0, x1, y1 = TITLE_ZONE
    up_left = [t for t in texts if t.box[0] < x1 and t.box[3] < y1 and t.height >= TITLE_MIN_HEIGHT]
    return max(up_left, key=lambda t: t.height, default=None)


def _inside(point, box, pad=0.0) -> bool:
    return box[0] - pad <= point[0] <= box[2] + pad and box[1] - pad <= point[1] <= box[3] + pad


def _x_template(size: int = 48) -> np.ndarray:
    """A fat white X, drawn rather than captured, to test a gold disc's glyph against."""
    t = np.zeros((size, size), np.uint8)
    a, b = int(size * 0.28), int(size * 0.72)
    cv2.line(t, (a, a), (b, b), 255, max(3, size // 5))
    cv2.line(t, (a, b), (b, a), 255, max(3, size // 5))
    return t


def find_discs(frame: np.ndarray) -> list[tuple[tuple, tuple]]:
    """Gold circles: the X and other round controls, as (box, centre).

    The gold is separated without smoothing: a close button's thin dark ring is
    all that keeps its disc apart from an orange sky behind it.
    """
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, (16, 120, 140), (34, 255, 255))
    contours, _ = cv2.findContours(gold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        area = cv2.contourArea(c)              # filled: the glyph's hole does not count
        if not (0.0015 * w * h <= area <= 0.03 * w * h):
            continue
        perimeter = cv2.arcLength(c, True)
        x, y, bw, bh = cv2.boundingRect(c)
        if perimeter == 0 or not (0.8 <= bw / bh <= 1.25):
            continue
        if 4 * np.pi * area / perimeter ** 2 < 0.8:
            continue
        out.append(((x / w, y / h, (x + bw) / w, (y + bh) / h), ((x + bw / 2) / w, (y + bh / 2) / h)))
    return out


X_GLYPH = _x_template()


def close_glyph_score(frame: np.ndarray, box) -> float:
    """How much a gold disc's glyph looks like the white X that closes a panel, 0..1."""
    h, w = frame.shape[:2]
    crop = frame[int(box[1] * h): int(box[3] * h), int(box[0] * w): int(box[2] * w)]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(cv2.resize(crop, X_GLYPH.shape[::-1]), cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 200), (180, 70, 255))
    shape = float(cv2.matchTemplate(white, X_GLYPH, cv2.TM_CCOEFF_NORMED).max())
    # An X looks the same a quarter turn round; the cat-head and star badges
    # that share its gold disc do not. Real Xs score 0.63-0.83, badges 0.24-0.51.
    on = white > 0
    turned = np.rot90(on)
    symmetry = (on & turned).sum() / max((on | turned).sum(), 1)
    return (shape + symmetry) / 2


CLOSE_SCORE = 0.57


def is_close_glyph(frame: np.ndarray, box) -> bool:
    return close_glyph_score(frame, box) >= CLOSE_SCORE


def perceive(frame: np.ndarray, ocr) -> Percept:
    h, w = frame.shape[:2]
    texts = read_texts(frame, ocr)
    percept = Percept(width=w, height=h, texts=texts, title=find_title(texts))

    shapes = []
    for b in find_buttons(frame):
        box = (b.left, b.top, b.left + b.w, b.top + b.h)
        round_ = 0.75 <= (b.w * w) / max(b.h * h, 1) <= 1.33
        shapes.append((box, (b.x, b.y), "round" if round_ else "button", b.w * b.h))

    percept.groups = group_lines(texts)
    groups = [g for g in percept.groups
              if percept.title is None or not _inside(g.centre, percept.title.box)]
    # A gold shape holding several labels is a panel of controls, not one.
    labels_in = {s[0]: sum(_inside(g.centre, s[0]) for g in groups) for s in shapes}
    used = set()
    for group in groups:
        # The smallest single-control gold shape around the label, if any.
        around = [s for s in shapes if s[3] <= CONTROL_MAX_AREA and labels_in[s[0]] == 1
                  and _inside(group.centre, s[0])]
        if around:
            box, tap, kind, _ = min(around, key=lambda s: s[3])
            used.add(box)
            percept.controls.append(Control(group.text, kind, box, tap))
        else:
            percept.controls.append(Control(group.text, "tag", group.box, group.centre))

    back = find_back_arrow(frame)
    if back:
        percept.controls.append(Control("back", "back", (back[0] - 0.03, back[1] - 0.05,
                                                         back[0] + 0.03, back[1] + 0.05), back))
    # A gold disc with a white X closes whatever panel it sits on; take the
    # most X-like, since a card's badge can pass for one.
    scored = [(close_glyph_score(frame, box), box, centre) for box, centre in find_discs(frame)]
    best = max(scored, default=None)
    if best and best[0] >= CLOSE_SCORE:
        percept.controls.append(Control("close", "close", best[1], best[2]))
    return percept
