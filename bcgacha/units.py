"""Find a unit by what a person calls it.

A cat goes by several names: one per evolution form ("Kasli the Daughter",
"Kasli the Scourge", "Kasli the Bane"), and a community nickname or two
("Dark Kasli"). Any of them finds it, as does its id or a close misspelling.
Each hit says what it is, how the tier list ranks it, whether this account
owns it, and which live event can roll it -- so a target is chosen knowing
whether the run can reach it at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .data import LEGEND, RARE, RARITY_NAMES, SUPER_RARE, UBER, Dataset

# Only the rarities a capsule can give are worth searching.
GACHA_RARITIES = (RARE, SUPER_RARE, UBER, LEGEND)
# How well a name fits the query: the whole name, its start, the start of
# one of its words, anywhere in it. A fuzzy hit scores below all of them.
EXACT, STARTS, WORD, INSIDE = 100.0, 97.0, 94.0, 88.0
FUZZY_WEIGHT = 0.85
# A fuzzy hit below this is not offered at all.
FUZZY_CUTOFF = 62
# The best hit is the one meant only when it leads the next by this much.
CLEAR_MARGIN = 5


@dataclass
class Unit:
    id: int
    name: str
    rarity: int
    forms: list[str]
    matched: str = ""               # the name or nickname the query hit
    score: float = 0.0              # 100 for the exact name
    tier: str = "?"
    owned: bool | None = None
    events: list[str] = field(default_factory=list)     # live events that roll it
    platinum: bool = False                              # in the Platinum pool

    @property
    def rarity_name(self) -> str:
        return RARITY_NAMES.get(self.rarity, str(self.rarity))

    @property
    def obtainable(self) -> bool:
        return bool(self.events) or self.platinum

    def where(self) -> str:
        found = list(self.events) + (["Platinum"] if self.platinum else [])
        return ", ".join(found) if found else "not in any live event"

    def to_json(self) -> dict:
        return dict(id=self.id, name=self.name, rarity=self.rarity, rarity_name=self.rarity_name,
                    forms=self.forms, matched=self.matched, score=round(self.score),
                    tier=self.tier, owned=self.owned, events=self.events, platinum=self.platinum,
                    obtainable=self.obtainable, where=self.where())

    def line(self) -> str:
        owned = {True: "owned", False: "not owned", None: "owned ?"}[self.owned]
        also = f"  (as {self.matched!r})" if self.matched and self.matched != self.name else ""
        return (f"{self.name:<30} {self.rarity_name:<11} tier {self.tier:<4} {owned:<10} "
                f"{self.where()}{also}")


class Catalogue:
    """Every capsule unit's names, and what the account and today know of it."""

    def __init__(self, dataset: Dataset, tiers=None, owned: set[int] | None = None, events=None):
        from .tiers import OVERRIDE_FILE

        self.dataset, self.tiers, self.owned, self.events = dataset, tiers, owned, events or []
        self.names: dict[str, int] = {}             # lower-cased name -> cat id
        self.shown: dict[str, str] = {}             # lower-cased name -> as written
        for cat_id, entry in dataset.cats.items():
            if entry.get("rarity") not in GACHA_RARITIES:
                continue
            for form in entry.get("name") or []:
                if form and form.strip():
                    self._add(form.strip(), cat_id)
        # Community nicknames name a form; they find its cat.
        aliases = json.loads(OVERRIDE_FILE.read_text()) if OVERRIDE_FILE.exists() else {}
        for nickname, form in aliases.items():
            cat_id = self.names.get(form.strip().lower())
            if cat_id is not None:
                self._add(nickname.replace("’", "'"), cat_id)
        self._choices = list(self.shown.values())

    def _add(self, name: str, cat_id: int) -> None:
        self.names.setdefault(name.lower(), cat_id)
        self.shown.setdefault(name.lower(), name)

    def unit(self, cat_id: int, matched: str = "", score: float = 100.0) -> Unit:
        entry = self.dataset.cats.get(cat_id, {})
        forms = [n for n in entry.get("name") or [] if n]
        events = [e.label for e in self.events if not e.platinum
                  and any(cat_id in (e.banner.slots.get(r) or []) for r in GACHA_RARITIES)]
        platinum = any(e.platinum and cat_id in (e.banner.slots.get(UBER) or []) for e in self.events)
        return Unit(id=cat_id, name=self.dataset.cat_name(cat_id), rarity=self.dataset.rarity_of(cat_id),
                    forms=forms, matched=matched, score=score,
                    tier=self.tiers.tier_of(cat_id) if self.tiers else "?",
                    owned=None if self.owned is None else cat_id in self.owned,
                    events=events, platinum=platinum)

    def search(self, query: str, limit: int = 10) -> list[Unit]:
        """The units `query` could mean, best first, one hit per cat."""
        q = query.strip()
        if not q:
            return []
        m = re.fullmatch(r"#?(\d{1,4})", q)
        if m and int(m.group(1)) in self.dataset.cats:
            cat_id = int(m.group(1))
            if self.dataset.rarity_of(cat_id) in GACHA_RARITIES:
                return [self.unit(cat_id, f"#{cat_id}")]
        low = q.lower()
        scored: dict[int, tuple[float, str]] = {}

        def offer(cat_id: int, score: float, name: str) -> None:
            if score > scored.get(cat_id, (-1.0, ""))[0]:
                scored[cat_id] = (score, name)

        for name, cat_id in self.names.items():
            if name == low:
                offer(cat_id, EXACT, self.shown[name])
            elif name.startswith(low):
                offer(cat_id, STARTS, self.shown[name])
            elif f" {low}" in f" {name}":
                # A whole word of the name: "legend" finds "Kasli the Legend".
                offer(cat_id, WORD, self.shown[name])
            elif low in name:
                offer(cat_id, INSIDE, self.shown[name])
        for name, score, _ in process.extract(q, self._choices, scorer=fuzz.WRatio,
                                              processor=str.lower, limit=limit * 3,
                                              score_cutoff=FUZZY_CUTOFF):
            offer(self.names[name.lower()], score * FUZZY_WEIGHT, name)
        order = sorted(scored.items(), key=lambda kv: (-kv[1][0], len(kv[1][1]),
                                                       self.dataset.cat_name(kv[0])))
        return [self.unit(cat_id, name, score) for cat_id, (score, name) in order[:limit]]

    def resolve(self, query: str) -> tuple[Unit | None, list[Unit]]:
        """(the one unit `query` means, or None; the candidates weighed)."""
        hits = self.search(query, limit=6)
        if not hits:
            return None, []
        best = hits[0]
        runner_up = hits[1].score if len(hits) > 1 else 0.0
        # Several cats can share a word ("Shirou"): then only a clear lead,
        # or the one exact name, settles it.
        if best.score - runner_up >= CLEAR_MARGIN or best.score == EXACT > runner_up:
            return best, hits
        return None, hits


def load(dataset: Dataset | None = None, owned: set[int] | None = None, events=None) -> Catalogue:
    """A catalogue with whatever is saved: tier list, owned list, live events."""
    from . import data
    from . import events as live
    from .catindex import OwnedIndex
    from .tiers import TierList

    dataset = dataset or data.load()
    try:
        tiers = TierList.load()
    except FileNotFoundError:
        tiers = None
    if owned is None:
        index = OwnedIndex.load()
        owned = index.owned if index.complete else None
    return Catalogue(dataset, tiers, owned, events if events is not None else live.live_events(dataset))
