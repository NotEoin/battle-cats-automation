"""Counters in the game's own digits: tickets and Cat Food.

OCR reads a counter of two digits or more well, and a lone digit not at all:
its text detector does not take one glyph for a word. The Platinum Ticket
count is nearly always one digit. Every counter is drawn in the same blocky
yellow font, so a lone glyph is read three ways, and trusted only when every
way that gives an answer gives the same one:

  remembered  each glyph of a number read for certain is kept as the digit it
              was (state/digits.json), and a lone glyph is named by the one it
              matches closely -- never by a merely nearest one: a 9 is closer
              to an 8 than two 2s drawn on different counters are to each other
  in company  the glyph is set among remembered digits -- "?28", "8?2" -- and
              the whole read as a number, which OCR does well; a read whose
              known digits come out wrong is thrown away
  repeated    the glyph drawn as a run of itself, "999", a word the detector
              takes; the run must read as one digit throughout

Nothing is guessed: a counter that cannot be read is None.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from itertools import product
from pathlib import Path

import cv2
import numpy as np

ATLAS_FILE = Path(__file__).resolve().parent.parent / "state" / "digits.json"
# A glyph, resized into a box of this many pixels, wide by high.
CELL = (20, 28)
# Remembered pictures of each digit.
KEEP = 8
# A glyph is a digit when this close to one remembered, and the next digit
# at least this many times further. The same digit sits 0.01-0.02 from itself
# on one counter, and a 9 only 0.07 from an 8.
MATCH = 0.035
MARGIN = 2.0
# OCR reads these fonts best with glyphs this many pixels high.
READ_HEIGHTS = (40, 48)
# Runs a lone glyph is read as: (copies, glyph height, gap as a share of it).
RUNS = ((3, 40, 0.1), (4, 48, 0.1), (3, 48, 0.1), (5, 40, 0.1))
# In company: at least this many readings, and this share of them agreeing.
COMPANY_VOTES = 4
COMPANY_SHARE = 0.8


def ink(frame: np.ndarray, box) -> np.ndarray:
    """The counter's lettering, white on black."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
    if crop.size == 0:
        return np.zeros((1, 1), np.uint8)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (15, 80, 150), (40, 255, 255)) | cv2.inRange(hsv, (0, 0, 200), (180, 60, 255))


def glyphs(mask: np.ndarray) -> list[np.ndarray]:
    """The digits of a counter, left to right: solid blobs of one height and
    one baseline with the rightmost, which is always a digit -- the ticket
    or Cat Food icon beside them is a different size."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    tall = mask.shape[0]
    blobs = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if 0.35 * tall <= h <= 0.9 * tall and area >= 0.45 * w * h and w <= 0.85 * h:
            blobs.append((x, y, w, h, i))
    if not blobs:
        return []
    right = max(blobs, key=lambda b: b[0])
    row = [b for b in blobs if abs(b[3] - right[3]) <= 0.12 * right[3]
           and abs(b[1] - right[1]) <= 0.12 * right[3]]
    return [(labels[y:y + h, x:x + w] == i).astype(np.uint8) * 255
            for x, y, w, h, i in sorted(row)]


def cell(glyph: np.ndarray) -> np.ndarray:
    """A glyph in a fixed box, its shape kept: a "1" stays narrow."""
    h, w = glyph.shape
    side = max(h, int(w * CELL[1] / CELL[0]) + 1)
    canvas = np.zeros((side, int(side * CELL[0] / CELL[1]) + 1), np.uint8)
    x = (canvas.shape[1] - w) // 2
    canvas[(side - h) // 2:(side - h) // 2 + h, x:x + w] = glyph
    return cv2.resize(canvas, CELL, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def _pack(glyph: np.ndarray) -> dict:
    return dict(h=int(glyph.shape[0]), w=int(glyph.shape[1]),
                bits=np.packbits(glyph > 0).tobytes().hex())


def _unpack(raw: dict) -> np.ndarray:
    bits = np.unpackbits(np.frombuffer(bytes.fromhex(raw["bits"]), np.uint8))[: raw["h"] * raw["w"]]
    return bits.reshape(raw["h"], raw["w"]).astype(np.uint8) * 255


class Atlas:
    """Remembered pictures of each digit, as the counters showed them: small
    ones to name a glyph by, and one whole glyph of each to set a lone
    glyph among."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or ATLAS_FILE)
        self.samples: dict[str, list[np.ndarray]] = {}
        self.whole: dict[str, np.ndarray] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            cells = raw.get("cells", raw if "whole" not in raw else {})
            self.samples = {d: [np.array(s, np.float32).reshape(CELL[1], CELL[0]) / 255.0 for s in v]
                            for d, v in cells.items() if isinstance(v, list)}
            self.whole = {d: _unpack(g) for d, g in raw.get("whole", {}).items()}

    def known(self) -> str:
        return "".join(sorted(self.samples))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = dict(cells={d: [np.round(s * 255).astype(int).ravel().tolist() for s in v]
                          for d, v in self.samples.items()},
                   whole={d: _pack(g) for d, g in self.whole.items()})
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw))
        os.replace(tmp, self.path)

    def learn(self, shapes: list[np.ndarray], value: int) -> bool:
        """Remember each glyph of a counter known to read `value`. Refused
        outright unless the glyphs and digits pair up one to one, and if any
        glyph already matches another digit: a misread must not teach.
        True if anything new was kept."""
        text = str(value)
        if len(shapes) != len(text):
            return False
        for glyph, d in zip(shapes, text):
            named = self.name(glyph)[0]
            if named is not None and named != d:
                return False
        grew = False
        for glyph, d in zip(shapes, text):
            c = cell(glyph)
            have = self.samples.setdefault(d, [])
            # A picture much like one kept already adds nothing.
            if all(float(np.abs(c - s).mean()) > 0.02 for s in have) and len(have) < KEEP:
                have.append(c)
                grew = True
            if d not in self.whole:
                self.whole[d] = glyph
                grew = True
        return grew

    def name(self, glyph: np.ndarray) -> tuple[str | None, float, float]:
        """(digit, distance, how many times further the next digit is)."""
        c = cell(glyph)
        dist = sorted((min(float(np.abs(c - s).mean()) for s in v), d) for d, v in self.samples.items() if v)
        if not dist:
            return None, 1.0, 0.0
        best, digit = dist[0]
        second = dist[1][0] if len(dist) > 1 else 1.0
        ratio = second / max(best, 1e-6)
        return (digit if best <= MATCH and ratio >= MARGIN else None), best, ratio


# -- reading pages ------------------------------------------------------------------

def _page(mask: np.ndarray, pad: int = 20, scale: float = 2.0) -> np.ndarray:
    page = cv2.copyMakeBorder(255 - mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    page = cv2.resize(page, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)


def _strip(parts: list[np.ndarray], height: int, gap: float) -> np.ndarray:
    """Glyphs side by side as a number is drawn, on a page OCR reads well."""
    h = max(p.shape[0] for p in parts)
    parts = [cv2.resize(p, (max(1, round(p.shape[1] * h / p.shape[0])), h), interpolation=cv2.INTER_NEAREST)
             for p in parts]
    space = np.zeros((h, max(2, int(h * gap))), np.uint8)
    strip = np.hstack([x for p in parts for x in (p, space)][:-1])
    pad = h // 2
    page = cv2.copyMakeBorder(255 - strip, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    scale = 2 * height / page.shape[0]
    page = cv2.resize(page, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)


def _text(ocr, page) -> str:
    result, _ = ocr(page)
    return "".join(str(r[1]) for r in result or []).replace(" ", "")


def read_runs(glyph: np.ndarray, ocr) -> str | None:
    """A lone glyph read as runs of itself; the digit only if every run that
    reads says the same one, and at least two do."""
    votes = Counter()
    for copies, height, gap in RUNS:
        text = _text(ocr, _strip([glyph] * copies, height, gap))
        if text:
            votes[text[0] if len(text) == copies and text.isdigit() and len(set(text)) == 1 else "?"] += 1
    if len(votes) == 1 and "?" not in votes and sum(votes.values()) >= 2:
        return next(iter(votes))
    return None


def read_in_company(glyph: np.ndarray, atlas: Atlas, ocr) -> str | None:
    """A lone glyph set between remembered digits and read as a number: the
    digit most readings give, if nearly all do. A reading that gets a known
    digit wrong says nothing and is dropped."""
    known = sorted(atlas.whole)
    if not known:
        return None
    pairs = [(a, b) for a, b in product(known, repeat=2) if a != b][:2] or [(known[0], known[0])]
    votes = Counter()
    for (a, b), height in product(pairs, READ_HEIGHTS):
        for place in range(3):
            company = [a, b]
            parts = [atlas.whole[a], atlas.whole[b]]
            parts.insert(place, glyph)
            company.insert(place, "?")
            text = _text(ocr, _strip(parts, height, 0.2))
            if len(text) != 3 or not text.isdigit():
                continue
            if all(t == c for t, c in zip(text, company) if c != "?"):
                votes[text[place]] += 1
    if not votes:
        return None
    digit, n = votes.most_common(1)[0]
    return digit if n >= COMPANY_VOTES and n >= COMPANY_SHARE * sum(votes.values()) else None


def read_lone(glyph: np.ndarray, ocr, atlas: Atlas) -> tuple[str | None, str]:
    """A lone digit by every way that gives an answer; all must agree."""
    answers = {"remembered": atlas.name(glyph)[0],
               "in company": read_in_company(glyph, atlas, ocr),
               "repeated": read_runs(glyph, ocr)}
    given = {how: d for how, d in answers.items() if d is not None}
    if not given:
        return None, f"a lone digit none of the ways could read (knows {atlas.known() or 'none'})"
    if len(set(given.values())) > 1:
        return None, "the ways disagree: " + ", ".join(f"{how} {d}" for how, d in given.items())
    return next(iter(given.values())), "read " + " and ".join(given)


def read(frame: np.ndarray, box, ocr, atlas: Atlas | None = None) -> tuple[int | None, str]:
    """(the counter in `box`, or None; how it was read). Reads alone: see
    teach() for remembering what was read."""
    atlas = atlas if atlas is not None else Atlas()
    mask = ink(frame, box)
    shapes = glyphs(mask)
    result, _ = ocr(_page(mask))
    found = [str(r[1]).strip() for r in result or [] if str(r[1]).strip().isdigit()]
    if len(found) == 1:
        return int(found[0]), "read"
    if not shapes:
        return None, "no digits"
    if len(shapes) == 1:
        digit, how = read_lone(shapes[0], ocr, atlas)
        return (int(digit) if digit is not None else None), how
    named = [atlas.name(g)[0] for g in shapes]
    if all(named):
        return int("".join(named)), "matched remembered digits"
    return None, f"{len(shapes)} digits, not all known (knows {atlas.known() or 'none'})"


def teach(frame: np.ndarray, box, value: int, atlas: Atlas | None = None) -> bool:
    """Remember the glyphs of a counter known for certain to show `value`:
    read the same on two fresh frames, or the count the run itself kept.
    True if anything new was kept."""
    atlas = atlas if atlas is not None else Atlas()
    if atlas.learn(glyphs(ink(frame, box)), value):
        atlas.save()
        return True
    return False
