"""How much a given roll outcome is worth to this account.

Three things decide it, in order of weight:

  * Whether the cat is new. Unlocking a unit you do not have is the whole point,
    so a first copy dominates everything else.
  * How good the cat is. A duplicate Uber is not worthless -- extra copies raise
    a unit's level cap through the +N system -- but it is worth far less than a
    new one, and a bad Uber is worth less than a good one. Community tier
    rankings supply that ordering.
  * Rarity. New Rares and Super Rares are still progress, just cheaper progress.

Platinum Tickets are scored separately in the planner: they are scarce enough
that spending one on anything but a strong, unowned Uber is a waste.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data import LEGEND, RARE, SUPER_RARE, UBER
from .tiers import TIER_ORDER, TierList, UNRANKED

# A brand-new unit of each rarity, before any tier adjustment.
NEW_VALUE = {RARE: 12.0, SUPER_RARE: 45.0, UBER: 600.0, LEGEND: 900.0}

# A duplicate, as a fraction of the new value. Duplicates feed the +N level
# system, so they are not zero, but they must never outrank a new unit.
DUPLICATE_FRACTION = {RARE: 0.02, SUPER_RARE: 0.03, UBER: 0.08, LEGEND: 0.12}

# How much the tier ranking can swing an Uber's value, multiplicatively.
BEST_TIER_MULTIPLIER = 2.2
WORST_TIER_MULTIPLIER = 0.25


def tier_multiplier(rank: int) -> float:
    """Map a tier position onto a multiplier, best to worst."""
    if rank >= UNRANKED:
        return 1.0          # unranked: treat as average rather than penalising
    span = max(len(TIER_ORDER) - 1, 1)
    t = rank / span
    return BEST_TIER_MULTIPLIER + t * (WORST_TIER_MULTIPLIER - BEST_TIER_MULTIPLIER)


@dataclass
class Scorer:
    owned: set[int]
    tiers: TierList | None = None
    targets: set[int] | None = None
    target_bonus: float = 5000.0
    # Per-unit bonuses from a goal, applied only while the unit is still
    # missing. These dwarf the ordinary rarity and tier values on purpose:
    # a goal is a statement about what the run is for, not a mild preference.
    priority: dict[int, float] | None = None

    def is_new(self, cat_id: int) -> bool:
        return cat_id not in self.owned

    def value(self, cat_id: int, rarity: int) -> float:
        if cat_id < 0:
            return 0.0
        base = NEW_VALUE.get(rarity, 0.0)
        if rarity in (UBER, LEGEND) and self.tiers is not None:
            base *= tier_multiplier(self.tiers.rank_of(cat_id))
        if not self.is_new(cat_id):
            base *= DUPLICATE_FRACTION.get(rarity, 0.02)
        if self.targets and cat_id in self.targets and self.is_new(cat_id):
            base += self.target_bonus
        if self.priority and self.is_new(cat_id):
            base += self.priority.get(cat_id, 0.0)
        return base

    def describe(self, cat_id: int, rarity: int, dataset) -> str:
        tier = self.tiers.tier_of(cat_id) if self.tiers else "?"
        flag = "NEW" if self.is_new(cat_id) else "dup"
        return f"{dataset.cat_name(cat_id)} [{tier}] {flag}"
