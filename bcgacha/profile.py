"""What the bot has learned about one device's screens, kept under state/devices/.

Nothing about a device's layout ships with the project. The first time a screen
is recognised the slow way -- full OCR and shape segmentation, perception.py --
its controls are written here with a small template of each, keyed by the
frame's resolution. After that the screen is recognised, and its controls are
found, from those templates in milliseconds, near where they were last seen.

Learning only ever records what it has just seen, so running it again leaves an
up-to-date profile unchanged: the file and templates are rewritten only when a
control has actually moved or is new.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from pathlib import Path

import cv2
import numpy as np

DEVICES_DIR = Path(__file__).resolve().parent.parent / "state" / "devices"

# How far from its last position a template is searched for, and how well it
# must match there to count as the same control.
SEARCH_PAD = 0.04
# Whether a mark is on screen at all is asked of the place it was learned,
# where the game draws it to the pixel: a narrow look, a fifteenth the sums.
MARK_PAD = 0.012
TEMPLATE_MATCH = 0.8
# A control has moved if its box shifts by more than this; below it, jitter.
MOVE_TOLERANCE = 0.01
# How closely a perceived label must read as a name the map uses.
LABEL_MATCH = 85
# A remembered piece of text is on screen when its picture matches this well
# where it was read, give or take TEXT_PAD, and at the same brightness: a
# screen fading in or out matches in shape at any level, and is not yet the
# screen. OCR of a title costs most of a second; this costs a millisecond.
# The same title on the same phone scores 1.000; "Lucky Capsules" scores 0.931
# against "Lucky Capsules G", the one letter more.
TEXT_MATCH = 0.97
TEXT_PAD = 0.006
# A match this close to the text last seen in a box settles it: no rival
# can match better than a copy of the same pixels.
TEXT_SURE = 0.995
# A remembered picture that stops matching is replaced no sooner than this,
# in seconds.
TEXT_KEEP = 600
TEXT_LEVEL = 18


def _slug(text: str) -> str:
    # "@back" names a shape, "Back" a label: they must not share a file.
    shape = "shape_" if text.startswith("@") else ""
    return shape + (re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "control")


def _choose(controls, wanted) -> list[tuple[str, object]]:
    """(name, control) for each wanted name some control on screen answers to.

    "@back" and "@close" are the shapes of those kinds; any other name is a
    label, matched loosely since OCR drops spaces and doubles letters. Each
    name takes its best-matching control, and each control serves one name.
    """
    from .uigraph import title_match

    scored = []
    for name in wanted:
        for i, c in enumerate(controls):
            if name.startswith("@"):
                score = 100.0 if c.kind == name[1:] else 0.0
            elif c.kind in ("back", "close"):
                continue
            else:
                score = title_match(name, c.label, within=True)
            if score >= LABEL_MATCH:
                scored.append((score, name, i))
    chosen, names, used = [], set(), set()
    for score, name, i in sorted(scored, key=lambda s: (-s[0], s[1], s[2])):
        if name not in names and i not in used:
            names.add(name)
            used.add(i)
            chosen.append((name, controls[i]))
    return chosen


def _copy(value):
    """A copy deep enough that nothing handed out reaches the profile: its
    data is only dicts, lists and plain values. Far cheaper than deepcopy."""
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


# Templates are matched in grey at this share of the frame's size: sixteen
# times fewer sums than full-size colour, and a control is still tens of
# pixels across.
MATCH_SCALE = 0.5


def _small_grey(image: np.ndarray) -> np.ndarray:
    # Halved first, then made grey: the colour conversion runs on a quarter
    # of the pixels.
    small = cv2.resize(image, None, fx=MATCH_SCALE, fy=MATCH_SCALE, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small


def _crop(frame, box):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[max(0, int(y0 * h)): int(y1 * h), max(0, int(x0 * w)): int(x1 * w)]


class Profile:
    """Title box, controls and Cat Base backgrounds learned for one resolution."""

    def __init__(self, width: int, height: int, root: Path | None = None):
        self.key = f"{width}x{height}"
        self.size = (width, height)
        self.root = Path(root or DEVICES_DIR) / self.key
        self.file = self.root / "profile.json"
        # The debug view recognises frames on one thread while the navigator
        # or a scan learns on another: every read and write of `data` holds it.
        self._lock = threading.RLock()
        self._templates: dict[str, np.ndarray] = {}
        # Called with a sentence each time something new is learned, so a
        # watcher such as the debug view can show the profile filling in.
        self.listeners: list = []
        self.data = json.loads(self.file.read_text()) if self.file.exists() else {}
        self.data.setdefault("title_box", None)
        self.data.setdefault("screens", {})
        self.data.setdefault("bases", {})
        self.data.setdefault("texts", {})
        # Bumped on every change; what is worked out from `data` is kept per
        # revision, since recognition asks the same questions every frame.
        self._rev = 0
        self._derived: dict = {}
        # Lookups already made on the frame each thread is looking at: the
        # debug page asks for the same controls recognition just found.
        self._memo = threading.local()
        # The text last known in each box, tried first: most frames show the
        # screen the frame before did.
        self._last_text: dict[str, str] = {}

    @classmethod
    def for_frame(cls, frame: np.ndarray, root: Path | None = None) -> "Profile":
        h, w = frame.shape[:2]
        return cls(w, h, root)

    def _told(self, message: str) -> None:
        for listen in list(self.listeners):
            listen(f"[{self.key}] {message}")

    def _cached(self, key, compute):
        with self._lock:
            hit = self._derived.get(key)
            if hit is None or hit[0] != self._rev:
                hit = (self._rev, compute())
                self._derived[key] = hit
            return hit[1]

    def save(self) -> None:
        with self._lock:
            self._rev += 1
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
        os.replace(tmp, self.file)

    # -- the top-left title --------------------------------------------------

    @property
    def title_box(self):
        with self._lock:
            box = self.data["title_box"]
        return tuple(box) if box else None

    def learn_title(self, text_box) -> bool:
        """Grow the title box to cover a title just read. True if it changed.

        Titles differ in length, so the box is the union of every title seen,
        padded. It grows only to titles actually read: reaching further would
        take in the small banner some screens print beside their name. A longer
        title met later reads cut short, fails, and is learned from a full look.
        """
        x0, y0, x1, y1 = text_box
        pad = 0.008
        seen = (max(0.0, x0 - pad), max(0.0, y0 - pad), x1 + 2 * pad, y1 + pad)
        with self._lock:
            old = self.title_box
            new = seen if old is None else (min(old[0], seen[0]), min(old[1], seen[1]),
                                            max(old[2], seen[2]), max(old[3], seen[3]))
            new = tuple(round(v, 4) for v in new)
            if new == old:
                return False
            self.data["title_box"] = list(new)
            self.save()
        self._told(f"title box {'placed' if old is None else 'widened'} at "
                   f"({new[0]:.3f}, {new[1]:.3f})-({new[2]:.3f}, {new[3]:.3f})")
        return True

    # -- controls ----------------------------------------------------------------

    def controls(self, screen: str) -> dict:
        """A copy of what is learned on `screen`, safe to loop over while learning goes on."""
        return _copy(self._controls(screen))

    def _controls(self, screen: str) -> dict:
        """What is learned on `screen`, for reading only: never handed out."""
        return self._cached(("controls", screen), lambda: _copy(
            self.data["screens"].get(screen, {}).get("controls", {})))

    def learned_on(self, name: str) -> list[str]:
        """The screens a control of this name was learned on."""
        index = self._cached("learned_on", lambda: {
            key: [n for n, sc in self.data["screens"].items() if key in sc.get("controls", {})]
            for sc in self.data["screens"].values() for key in sc.get("controls", {})})
        return list(index.get(name, ()))

    def screen_names(self) -> list[str]:
        with self._lock:
            return sorted(self.data["screens"])

    def learn(self, screen: str, frame: np.ndarray, controls, wanted=None) -> int:
        """Record a screen's controls and cut a template of each. Returns how many changed.

        `wanted` names the controls worth keeping -- what the map presses or
        recognises screens by -- and each is kept under that name, however OCR
        spelled it this time. Everything else on screen (timers, counters,
        prices) is left alone: it changes by the minute, and learning it would
        rewrite the profile on every look.
        """
        chosen = _choose(controls, wanted) if wanted is not None else [
            (c.label if c.kind not in ("back", "close") else f"@{c.kind}", c) for c in controls]
        with self._lock:
            return self._learn(screen, frame, chosen)

    def _learn(self, screen: str, frame: np.ndarray, chosen) -> int:
        known = self.data["screens"].setdefault(screen, {}).setdefault("controls", {})
        changed = 0
        for key, c in chosen:
            entry = dict(box=[round(v, 4) for v in c.box], tap=[round(v, 4) for v in c.tap],
                         kind=c.kind, label=c.label)
            old = known.get(key)
            if old and max(abs(a - b) for a, b in zip(old["box"], entry["box"])) <= MOVE_TOLERANCE:
                continue
            if old and "template" in old:
                # Its template still finds it where it was perceived: the
                # control is where it was, only drawn with a different glow,
                # badge or reading. Keep the template it already has.
                if self.find(frame, screen, key):
                    continue
            crop = _crop(frame, c.box)
            if crop.size == 0:
                continue
            path = self.root / "templates" / _slug(screen) / f"{_slug(key)}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), crop)
            entry["template"] = str(path.relative_to(self.root))
            known[key] = entry
            self._templates.pop(str(path), None)
            self._templates.pop(str(path) + ":small", None)
            changed += 1
        if changed:
            self.save()
            self._told(f"{screen}: learned {changed} control{'s' if changed != 1 else ''} "
                       f"({', '.join(sorted(known)[:6])}{'...' if len(known) > 6 else ''})")
        return changed

    def _flat(self, rel: str, template: np.ndarray) -> bool:
        with self._lock:
            flat = self._templates.get(rel + ":flat")
            if flat is None:
                flat = self._templates[rel + ":flat"] = float(template.std()) < 4
            return flat

    def _small_template(self, entry) -> np.ndarray | None:
        path = str(self.root / entry["template"]) + ":small"
        with self._lock:
            if path not in self._templates:
                full = self._template(entry)
                small = None if full is None else _small_grey(full)
                # A flat picture correlates with anything: never matched.
                self._templates[path] = small if small is not None and float(small.std()) >= 1 else None
            return self._templates[path]

    def _template(self, entry, grey: bool = False) -> np.ndarray | None:
        path = str(self.root / entry["template"])
        key = path + (":grey" if grey else "")
        with self._lock:
            if key not in self._templates:
                self._templates[key] = cv2.imread(path, cv2.IMREAD_GRAYSCALE if grey else cv2.IMREAD_COLOR)
            return self._templates[key]

    def key_for(self, screen: str, target: str) -> str | None:
        """The learned control a transition's target names; OCR drops spaces."""
        controls = self._controls(screen)
        if target in controls:
            return target
        if target.startswith("@"):
            return None                 # a shape is never a label that reads like it
        from .uigraph import title_match

        scored = [(title_match(target, e.get("label", k), within=True), k)
                  for k, e in controls.items() if not k.startswith("@")]
        best = max(scored, default=(0, None))
        return best[1] if best[0] >= 85 else None

    def locate(self, frame: np.ndarray, screen: str, key: str, pad: float = SEARCH_PAD):
        """Where a learned control is now, from its template, or None if not there."""
        found = self.find(frame, screen, key, pad)
        return found["tap"] if found else None

    def _memo_for(self, frame: np.ndarray) -> dict:
        memo = self._memo
        if getattr(memo, "frame", None) is not frame or getattr(memo, "rev", None) != self._rev:
            memo.frame, memo.rev, memo.found = frame, self._rev, {}
        return memo.found

    def find(self, frame: np.ndarray, screen: str, key: str, pad: float = SEARCH_PAD) -> dict | None:
        """A learned control's tap point and box as they are in this frame,
        looked for within `pad` of where it was learned."""
        key = self.key_for(screen, key) or key
        found = self._memo_for(frame)
        if (screen, key, pad) not in found:
            # A wide look that found it answers a narrow one too.
            wide = found.get((screen, key, SEARCH_PAD)) if pad < SEARCH_PAD else None
            found[(screen, key, pad)] = wide or self._find(frame, screen, key, pad)
        hit = found[(screen, key, pad)]
        return dict(hit) if hit else None

    def _find(self, frame: np.ndarray, screen: str, key: str, pad: float = SEARCH_PAD) -> dict | None:
        entry = self._controls(screen).get(key)
        if not entry or "template" not in entry:
            return None
        template = self._small_template(entry)
        if template is None:
            return None
        x0, y0, x1, y1 = entry["box"]
        h, w = frame.shape[:2]
        # The window starts on the template's own pixel parity, so at the
        # place it was cut from the halved grids line up exactly.
        step = round(1 / MATCH_SCALE)

        def span(a, b, size, pad):
            lo, hi = int(a * size), int(b * size)
            reach = int(pad * size) // step * step
            start = lo - reach if lo - reach >= 0 else lo % step
            return start, min(size, hi + reach)

        sx, ex = span(x0, x1, w, pad)
        sy, ey = span(y0, y1, h, pad)
        region = _small_grey(frame[sy:ey, sx:ex])
        th, tw = template.shape[:2]
        if region.shape[0] < th or region.shape[1] < tw:
            return None
        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if score < TEMPLATE_MATCH:
            return None
        dx = (sx + loc[0] * step) / w - x0
        dy = (sy + loc[1] * step) / h - y0
        return dict(key=key, label=entry.get("label", key), kind=entry.get("kind"),
                    score=round(float(score), 3),
                    tap=(entry["tap"][0] + dx, entry["tap"][1] + dy),
                    box=(x0 + dx, y0 + dy, entry["box"][2] + dx, entry["box"][3] + dy))

    # -- text, remembered as it looks ---------------------------------------------

    @staticmethod
    def _box_key(box) -> str:
        return ",".join(f"{v:.4f}" for v in box)

    def known_text(self, frame: np.ndarray, box) -> str | None:
        """The text last read in `box`, if it is there again as it looked then.

        Each reading that named a screen keeps a grey picture of the box. The
        best of those that matches is the reading; none matching is None, and
        the box is read with OCR as before.
        """
        with self._lock:
            known = dict(self.data["texts"].get(self._box_key(box), {}))
        if not known:
            return None
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = box
        window = _crop(frame, (x0 - TEXT_PAD, y0 - TEXT_PAD, x1 + TEXT_PAD, y1 + TEXT_PAD))
        if window.size == 0:
            return None
        grey = cv2.cvtColor(window, cv2.COLOR_BGR2GRAY)
        best, best_score = None, TEXT_MATCH
        box_key = self._box_key(box)
        last = self._last_text.get(box_key)
        order = sorted(known.items(), key=lambda kv: kv[0] != last)
        for text, rel in order:
            template = self._template(dict(template=rel), grey=True)
            if template is None or grey.shape[0] < template.shape[0] or grey.shape[1] < template.shape[1]:
                continue
            if self._flat(rel, template):
                continue            # a flat picture correlates with anything
            result = cv2.matchTemplate(grey, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (lx, ly) = cv2.minMaxLoc(result)
            if score < best_score:
                continue
            th, tw = template.shape[:2]
            patch = grey[ly: ly + th, lx: lx + tw]
            if abs(float(patch.mean()) - float(template.mean())) > TEXT_LEVEL:
                continue
            best, best_score = text, score
            if text == last and score >= TEXT_SURE:
                break               # the same screen as last time, beyond doubt
        if best is not None:
            self._last_text[box_key] = best
        return best

    def learn_text(self, frame: np.ndarray, box, text: str) -> bool:
        """Keep a picture of `text` as it looks in `box`. True if one was written.

        Only a reading that has just named its screen is kept. One already kept
        that still matches is left alone, so going over the same screens again
        rewrites nothing. One that does not match is replaced only once it is
        TEXT_KEEP old: a pulsing outline or a scrolling subtitle would have it
        rewritten -- the whole profile with it -- on every look, while a
        picture taken badly still gives way to a good one in time.
        """
        if self.known_text(frame, box) == text:
            return False
        crop = _crop(frame, box)
        if crop.size == 0:
            return False
        key = self._box_key(box)
        path = self.root / "texts" / _slug(key) / f"{_slug(text)}.png"
        with self._lock:
            kept = text in self.data["texts"].get(key, {})
        if kept and path.exists() and time.time() - path.stat().st_mtime < TEXT_KEEP:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        rel = str(path.relative_to(self.root))
        with self._lock:
            self._templates.pop(str(path) + ":grey", None)
            self._templates.pop(rel + ":flat", None)
            self.data["texts"].setdefault(key, {})[text] = rel
            self.save()
        self._told(f"remembered {text!r} as it looks")
        return True

    # -- pictures looked for anywhere in a region -----------------------------------

    def learn_image(self, name: str, frame: np.ndarray, box) -> bool:
        """Keep a grey picture of `box` as `name`, to be found again anywhere in
        a region: an event's tab, wherever the strip has scrolled it."""
        crop = _crop(frame, box)
        if crop.size == 0 or float(crop.std()) < 4:
            return False
        path = self.root / "images" / f"{_slug(name)}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        with self._lock:
            self._templates.pop(str(path) + ":grey", None)
            self.data.setdefault("images", {})[name] = dict(
                template=str(path.relative_to(self.root)), box=[round(v, 4) for v in box])
            self.save()
        self._told(f"remembered {name!r} as it looks")
        return True

    def find_image(self, name: str, frame: np.ndarray, region, match: float = 0.85):
        """Where the picture `name` is centred in `region` of `frame`, or None."""
        with self._lock:
            entry = copy.deepcopy(self.data.get("images", {}).get(name))
        if not entry:
            return None
        template = self._template(entry, grey=True)
        window = _crop(frame, region)
        if template is None or window.shape[0] < template.shape[0] or window.shape[1] < template.shape[1]:
            return None
        result = cv2.matchTemplate(cv2.cvtColor(window, cv2.COLOR_BGR2GRAY), template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (lx, ly) = cv2.minMaxLoc(result)
        if score < match:
            return None
        h, w = frame.shape[:2]
        th, tw = template.shape[:2]
        return (max(0.0, region[0]) + (lx + tw / 2) / w, max(0.0, region[1]) + (ly + th / 2) / h)

    # -- Cat Base backgrounds ------------------------------------------------------

    def bases(self) -> dict:
        with self._lock:
            return {k: list(v) for k, v in self.data["bases"].items()}

    def learn_base(self, chapter: str, signature: list[float]) -> bool:
        """Keep `chapter`'s door signature. Seeing the same door again, as it is
        on every visit, leaves the profile untouched."""
        from .bases import SAME_DOOR, distance

        with self._lock:
            old = self.data["bases"].get(chapter)
            if old is not None and distance(old, signature) <= SAME_DOOR:
                return False
            self.data["bases"][chapter] = [round(float(v), 4) for v in signature]
            self.save()
        self._told(f"learned the Cat Base background of {chapter}")
        return True
