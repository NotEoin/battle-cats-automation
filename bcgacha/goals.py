"""What a run is trying to unlock, and how badly it wants each thing.

The planner already scores a roll by rarity, tier and whether the unit is new.
A goal sits on top of that: it names a specific set of units and orders them,
so the route bends towards the units a person named first, in the order they
named them, then a wanted Legend, then the strongest unowned Ubers, rather
than simply taking whatever the next good position offers.

Priorities are additive bonuses rather than hard constraints. A hard constraint
would make the planner refuse perfectly good rolls on the way to its target;
a bonus lets it collect what it passes while still aiming at the right thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import CAPSULE_RARITIES, LEGEND, UBER, Banner, Dataset
from .tiers import UNRANKED, TierList

# A unit a person named outranks everything else, the first named most.
TARGET_BONUS = 100_000.0
TARGET_STEP = 2_000.0
TARGET_FLOOR = 60_000.0
# Legends are rarer than Ubers and the goal names them first, so they outrank
# every Uber regardless of tier.
LEGEND_BONUS = 40_000.0
PREFERRED_BANNER_BONUS = 8_000.0
UBER_BONUS = 12_000.0
# Spread across tier so a strong Uber outranks a weak one without ever
# approaching a Legend's bonus.
UBER_TIER_SPREAD = 6_000.0


@dataclass
class Goal:
    """What a run wants, how much each unit is worth to it, and why."""

    legendaries: set[int] = field(default_factory=set)
    ubers: set[int] = field(default_factory=set)
    platinum: set[int] = field(default_factory=set)
    priority: dict[int, float] = field(default_factory=dict)
    preferred_banner: str | None = None
    # Units a person named, most wanted first; those no live event can roll.
    targets: list[int] = field(default_factory=list)
    unreachable: list[int] = field(default_factory=list)
    # Why each unit is wanted, for a person reading the goal.
    why: dict[int, str] = field(default_factory=dict)

    @property
    def wanted(self) -> set[int]:
        """Every unit the goal wants that some live banner can roll."""
        return (self.legendaries | self.ubers | self.platinum | set(self.targets)) - set(self.unreachable)

    def reason(self, cat: int) -> str:
        """Why `cat` is wanted, or "" when it is not."""
        return self.why.get(cat, "")

    def remaining(self, owned: set[int]) -> set[int]:
        """The wanted units not yet owned."""
        return {c for c in self.wanted if c not in owned}

    def complete(self, owned: set[int]) -> bool:
        """True when every wanted unit is owned."""
        return not self.remaining(owned)


def build(
    dataset: Dataset,
    tiers: TierList | None,
    owned: set[int],
    banners: list[Banner],
    platinum_banner: Banner | None,
    platinum_tickets: int = 0,
    preferred_banner: str | None = None,
    only: set[str] | None = None,
    legends: bool = True,
    targets: list[int] | tuple = (),
    event_units: bool = True,
    labels: dict[str, str] | None = None,
) -> Goal:
    """Every unowned Legend and Uber the live banners can produce, ranked.

    `targets` are units a person named, most wanted first: they outrank all
    else, and a Platinum ticket goes on one before any tier-list pick.
    `event_units` False wants the targets alone -- no event's Ubers, no
    tier-list picks. `preferred_banner` nudges the ordering so a Legend
    obtainable there is chased before an equally-ranked one elsewhere. `only`
    names the banner keys whose units are wanted, None for all; `legends`
    False wants their Ubers alone. The planner still rolls on any banner to
    reach them. `labels` names banners for the reasons: key -> "Iron Legion".
    """
    from .planner import platinum_targets

    goal = Goal(preferred_banner=preferred_banner)
    labels = labels or {}

    def tier_fraction(cat: int) -> float:
        if tiers is None:
            return 0.5
        rank = tiers.rank_of(cat)
        if rank >= UNRANKED:
            return 0.5                     # unranked: treat as middling
        return 1.0 - rank / max(UNRANKED - 1, 1)

    pool = {c for b in banners for r in CAPSULE_RARITIES for c in b.slots.get(r) or []}
    platinum_pool = set(platinum_banner.slots.get(UBER) or []) if platinum_banner else set()
    for n, cat in enumerate(dict.fromkeys(targets)):
        goal.targets.append(cat)
        if cat not in pool and cat not in platinum_pool:
            goal.unreachable.append(cat)
            goal.why[cat] = f"target #{n + 1}, but no live event rolls it"
            continue
        goal.why[cat] = f"target #{n + 1}"
        if cat not in owned:
            goal.priority[cat] = max(TARGET_FLOOR, TARGET_BONUS - n * TARGET_STEP)

    for banner in banners if event_units else []:
        if only is not None and banner.key not in only:
            continue
        label = labels.get(banner.key, banner.name)
        for cat in (banner.slots.get(LEGEND) or []) if legends else []:
            if cat in owned:
                continue
            goal.legendaries.add(cat)
            goal.why.setdefault(cat, f"Legend of {label}")
            bonus = LEGEND_BONUS + tier_fraction(cat) * UBER_TIER_SPREAD
            if preferred_banner and banner.key == preferred_banner:
                bonus += PREFERRED_BANNER_BONUS
            goal.priority[cat] = max(goal.priority.get(cat, 0.0), bonus)
        for cat in banner.slots.get(UBER) or []:
            if cat in owned:
                continue
            goal.ubers.add(cat)
            goal.why.setdefault(cat, f"Uber of {label}")
            bonus = UBER_BONUS + tier_fraction(cat) * UBER_TIER_SPREAD
            goal.priority[cat] = max(goal.priority.get(cat, 0.0), bonus)

    # Platinum tickets go on named targets first, then the tier list's best.
    named = [c for c in goal.targets if c in platinum_pool and c not in owned]
    goal.platinum.update(named[:platinum_tickets] if platinum_tickets else [])
    picks = platinum_targets(tiers, owned | set(named), dataset, platinum_banner,
                             platinum_tickets - len(goal.platinum)) if event_units else set()
    for cat in picks:
        goal.platinum.add(cat)
        goal.why.setdefault(cat, f"Platinum pick, tier {tiers.tier_of(cat) if tiers else '?'}")
        goal.priority.setdefault(cat, UBER_BONUS + tier_fraction(cat) * UBER_TIER_SPREAD)

    # A unit that is both a Legend and reachable on the preferred banner must
    # not lose its ranking to an Uber that happens to share an id in a pool.
    goal.ubers -= goal.legendaries
    goal.legendaries -= set(goal.targets)
    goal.ubers -= set(goal.targets)
    return goal
