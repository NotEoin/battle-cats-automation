"""Read what a draw produced off its result screen.

The seed says what every draw will be, so reading the result is a check, not
the source of truth -- but a check is only worth anything if it can say "I
don't know". A name is matched only against the cats the draw could have
produced, and only when it is clearly nearer one of them than any other; an
unreadable name plate is None, never a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np
from rapidfuzz import fuzz

# The name plate, generous around it. The name is small white text on a dark
# panel, so it is upscaled before reading; at native size it is missed.
NAME_BOX = (0.320, 0.772, 0.690, 0.858)
NAME_SCALE = 3
# The capsule title stays in the corner through the reveal: it says which
# machine the draw came from.
TITLE_BOX = (0.05, 0.0, 0.35, 0.07)
# A name must read at least this close to a candidate, and this much closer
# than the next candidate. OCR clips a first letter ("akura the Cat") but the
# live pools hold near twins (Rin, Rider, Archer the Cat).
MATCH = 70
MARGIN = 8


@dataclass
class ResultRead:
    raw: str
    cat_id: int | None
    score: float
    margin: float
    platinum: bool | None       # the Platinum Capsules title, when it read

    def to_json(self, dataset=None) -> dict:
        return dict(raw=self.raw, cat_id=self.cat_id,
                    name=dataset.cat_name(self.cat_id) if dataset and self.cat_id is not None else None,
                    score=round(self.score, 1), margin=round(self.margin, 1), platinum=self.platinum)


def _read(frame: np.ndarray, box, ocr, scale: float = 1.0) -> str:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
    if crop.size == 0:
        return ""
    if scale != 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    result, _ = ocr(crop)
    pieces = sorted(result or [], key=lambda r: (round(min(p[1] for p in r[0]) / 20), r[0][0][0]))
    return " ".join(str(r[1]) for r in pieces).strip()


def match(raw: str, dataset, candidates: Iterable[int]) -> tuple[int | None, float, float]:
    """(cat id, score, margin over the runner-up) of the candidate `raw` names."""
    raw = raw.strip().lower()
    if len(raw) < 3:
        return None, 0.0, 0.0
    scored = []
    for cat in set(candidates):
        forms = [f for f in dataset.cats.get(cat, {}).get("name") or [] if f]
        if forms:
            scored.append((max(max(fuzz.ratio(raw, f.lower()), fuzz.token_sort_ratio(raw, f.lower()))
                               for f in forms), cat))
    if not scored:
        return None, 0.0, 0.0
    scored.sort(reverse=True)
    best, cat = scored[0]
    margin = best - (scored[1][0] if len(scored) > 1 else 0.0)
    exact = best >= 99.5 and margin > 0
    if not exact and (best < MATCH or margin < MARGIN):
        return None, best, margin
    return cat, best, margin


def read_result(frame: np.ndarray, ocr, dataset, candidates: Iterable[int]) -> ResultRead:
    """The cat on a result screen, among `candidates`, or cat_id None if unsure."""
    candidates = set(candidates)
    raw = _read(frame, NAME_BOX, ocr, NAME_SCALE)
    cat, score, margin = match(raw, dataset, candidates)
    if cat is None:
        # An Uber or Legend reveal sets the plate differently and the box can
        # read nothing: read the whole frame, and take the one piece of text
        # that names a candidate. Nothing else on a result screen does.
        from .perception import read_texts

        hits = []
        for t in read_texts(frame, ocr):
            c, sc, mg = match(t.text, dataset, candidates)
            if c is not None:
                hits.append((sc, mg, c, t.text))
        if len({h[2] for h in hits}) == 1:
            score, margin, cat, raw = max(hits)
    title = _read(frame, TITLE_BOX, ocr).lower().replace(" ", "")
    platinum = True if "platinum" in title else (False if "rare" in title else None)
    return ResultRead(raw, cat, score, margin, platinum)
