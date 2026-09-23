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
from pathlib import Path

import cv2
import numpy as np

DEVICES_DIR = Path(__file__).resolve().parent.parent / "state" / "devices"

# How far from its last position a template is searched for, and how well it
# must match there to count as the same control.
SEARCH_PAD = 0.04
TEMPLATE_MATCH = 0.8
# A control has moved if its box shifts by more than this; below it, jitter.
MOVE_TOLERANCE = 0.01
# How closely a perceived label must read as a name the map uses.
LABEL_MATCH = 85


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

    @classmethod
    def for_frame(cls, frame: np.ndarray, root: Path | None = None) -> "Profile":
        h, w = frame.shape[:2]
        return cls(w, h, root)

    def _told(self, message: str) -> None:
        for listen in list(self.listeners):
            listen(f"[{self.key}] {message}")

    def save(self) -> None:
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
        with self._lock:
            return copy.deepcopy(self.data["screens"].get(screen, {}).get("controls", {}))

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
            changed += 1
        if changed:
            self.save()
            self._told(f"{screen}: learned {changed} control{'s' if changed != 1 else ''} "
                       f"({', '.join(sorted(known)[:6])}{'...' if len(known) > 6 else ''})")
        return changed

    def _template(self, entry) -> np.ndarray | None:
        path = str(self.root / entry["template"])
        with self._lock:
            if path not in self._templates:
                self._templates[path] = cv2.imread(path)
            return self._templates[path]

    def key_for(self, screen: str, target: str) -> str | None:
        """The learned control a transition's target names; OCR drops spaces."""
        controls = self.controls(screen)
        if target in controls:
            return target
        if target.startswith("@"):
            return None                 # a shape is never a label that reads like it
        from .uigraph import title_match

        scored = [(title_match(target, e.get("label", k), within=True), k)
                  for k, e in controls.items() if not k.startswith("@")]
        best = max(scored, default=(0, None))
        return best[1] if best[0] >= 85 else None

    def locate(self, frame: np.ndarray, screen: str, key: str):
        """Where a learned control is now, from its template, or None if not there."""
        found = self.find(frame, screen, key)
        return found["tap"] if found else None

    def find(self, frame: np.ndarray, screen: str, key: str) -> dict | None:
        """A learned control's tap point and box as they are in this frame."""
        key = self.key_for(screen, key) or key
        entry = self.controls(screen).get(key)
        if not entry or "template" not in entry:
            return None
        template = self._template(entry)
        if template is None:
            return None
        x0, y0, x1, y1 = entry["box"]
        window = (x0 - SEARCH_PAD, y0 - SEARCH_PAD, x1 + SEARCH_PAD, y1 + SEARCH_PAD)
        region = _crop(frame, window)
        th, tw = template.shape[:2]
        if region.shape[0] < th or region.shape[1] < tw:
            return None
        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if score < TEMPLATE_MATCH:
            return None
        h, w = frame.shape[:2]
        dx = (max(0.0, window[0]) * w + loc[0]) / w - x0
        dy = (max(0.0, window[1]) * h + loc[1]) / h - y0
        return dict(key=key, label=entry.get("label", key), kind=entry.get("kind"),
                    score=round(float(score), 3),
                    tap=(entry["tap"][0] + dx, entry["tap"][1] + dy),
                    box=(x0 + dx, y0 + dy, entry["box"][2] + dx, entry["box"][3] + dy))

    # -- Cat Base backgrounds ------------------------------------------------------

    def bases(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data["bases"])

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
