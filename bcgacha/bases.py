"""Which chapter a Cat Base belongs to, from the scenery behind its buttons.

Every chapter's Cat Base is the same set of buttons in front of its own sliding
door: green waves in one chapter, grey flowers in the next, plum blossom in
Legend Stages. The right-hand side changes with speech bubbles and banners,
but the stretch of door just right of the Start!!, Upgrade and Equip buttons is
always clear, so that is what is compared -- colour and fine texture both, since
two chapters share a plain grey door and differ only in the flowers at its foot.
The region does not animate: one chapter seen twice measures 0.000 apart, and
the closest two different chapters 0.037.

The region is placed from where those buttons are on this device, not from
fixed coordinates, and each chapter's signature is learned into the device
profile the first time its Cat Base is seen (see carousel.py).
"""

from __future__ import annotations

import cv2
import numpy as np

# The door strip, measured in units of the gap between the Start!! and Equip
# centres, so it scales with the screen: it starts 1.12 gaps right of Start!!,
# is 0.94 gaps wide, and runs from just above Start!! to just below Equip.
# Centres, not edges: a pill's edge moves when a badge or glow touches it.
RIGHT, WIDTH, ABOVE, BELOW = 1.12, 0.94, 0.17, 0.15
THUMB = (24, 32)                # signature thumbnail, w x h
TEXTURE_WEIGHT = 3.0
# Nearest chapter wins only when close and clearly nearer than the runner-up.
MATCH_DISTANCE = 0.025
MARGIN = 1.5
# Closer than this is the same door seen again, not worth rewriting.
SAME_DOOR = 0.005


def door_region(start, equip, size) -> tuple[float, float, float, float]:
    """The door strip from the Start!! and Equip centres, for a frame of `size`."""
    w, h = size
    sx, sy = start[0] * w, start[1] * h
    gap = equip[1] * h - sy
    x0 = sx + RIGHT * gap
    return (x0 / w, (sy - ABOVE * gap) / h, (x0 + WIDTH * gap) / w,
            (equip[1] * h + BELOW * gap) / h)


def signature(frame: np.ndarray, region) -> list[float]:
    """A thumbnail of the door in Lab colour, plus its fine texture, scaled 0..1."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = region
    crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
    if crop.size == 0:
        return []
    small = cv2.resize(cv2.GaussianBlur(crop, (0, 0), 1.5), THUMB, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32) / 255.0
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    texture = (grey - cv2.GaussianBlur(grey, (0, 0), 2)) * TEXTURE_WEIGHT
    return np.concatenate([lab.ravel(), texture.ravel()]).round(4).tolist()


def distance(a: list[float], b: list[float]) -> float:
    """How far apart two signatures are; inf when they were taken at different sizes."""
    a, b = np.asarray(a), np.asarray(b)
    return float(np.sqrt(np.mean((a - b) ** 2))) if a.shape == b.shape else float("inf")


def classify(sig, known: dict) -> str | None:
    """The chapter whose learned signature this is, or None if none is clearly it."""
    return classify_distances({name: distance(sig, s) for name, s in known.items()})


def classify_distances(distances: dict[str, float]) -> str | None:
    """The nearest chapter, when it is close and clearly nearer than the runner-up."""
    ranked = sorted((d, name) for name, d in distances.items())
    if not ranked or ranked[0][0] > MATCH_DISTANCE:
        return None
    if len(ranked) > 1 and ranked[1][0] < ranked[0][0] * MARGIN:
        return None
    return ranked[0][1]


def door_of(frame: np.ndarray, graph, percept=None):
    """Where the door shows through on this Cat Base, from where its buttons are."""
    profile = graph.profile_for(frame)
    centres = {}
    for label in ("Start!!", "Equip"):
        found = profile.find(frame, "cat_base", label)
        if found:
            centres[label] = found["tap"]
        elif percept is not None:
            control = percept.find(label)
            if control is not None:
                centres[label] = control.tap
    if len(centres) < 2:
        return None
    h, w = frame.shape[:2]
    return door_region(centres["Start!!"], centres["Equip"], (w, h))


# Signatures are also compared shifted by up to this much, so a control found a
# pixel or two away from where it was learned cannot flip the answer.
SHIFT = 0.006


def chapter_of(frame: np.ndarray, graph, percept=None):
    """(chapter screen, door region) for a Cat Base frame; either may be None."""
    region = door_of(frame, graph, percept)
    if region is None:
        return None, None
    known = graph.profile_for(frame).bases()
    if not known:
        return None, region
    best: dict[str, float] = {}
    for dx in (-SHIFT, 0.0, SHIFT):
        for dy in (-SHIFT, 0.0, SHIFT):
            moved = (region[0] + dx, region[1] + dy, region[2] + dx, region[3] + dy)
            sig = signature(frame, moved)
            for name, s in known.items():
                best[name] = min(best.get(name, float("inf")), distance(sig, s))
    return classify_distances(best), region


def learn(frame: np.ndarray, graph, chapter: str, percept=None) -> bool:
    """Record this Cat Base's door as `chapter`'s. False if the buttons were not found."""
    region = door_of(frame, graph, percept)
    if region is None:
        return False
    graph.profile_for(frame).learn_base(chapter, signature(frame, region))
    return True
