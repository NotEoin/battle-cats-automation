"""What a run is trying to unlock, and how badly it wants each thing.

The planner already scores a roll by rarity, tier and whether the unit is new.
A goal sits on top of that: it names a specific set of units and orders them,
so the route bends towards a wanted Legend first, then the strongest unowned
Ubers, rather than simply taking whatever the next good position offers.

Priorities are additive bonuses rather than hard constraints. A hard constraint
would make the planner refuse perfectly good rolls on the way to its target;
a bonus lets it collect what it passes while still aiming at the right thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import LEGEND, UBER, Banner, Dataset
from .tiers import TierList, UNRANKED

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
    legendaries: set[int] = field(default_factory=set)
    ubers: set[int] = field(default_factory=set)
    platinum: set[int] = field(default_factory=set)
    priority: dict[int, float] = field(default_factory=dict)
    preferred_banner: str | None = None

    @property
    def wanted(self) -> set[int]:
        return self.legendaries | self.ubers | self.platinum

    def remaining(self, owned: set[int]) -> set[int]:
        return {c for c in self.wanted if c not in owned}

    def complete(self, owned: set[int]) -> bool:
        return not self.remaining(owned)

    def describe(self, dataset: Dataset, tiers: TierList | None, owned: set[int]) -> str:
        lines = []
        for label, group in (
            ("legendary", self.legendaries),
            ("uber", self.ubers),
            ("platinum", self.platinum),
        ):
            left = sorted(
                (c for c in group if c not in owned),
                key=lambda c: -self.priority.get(c, 0.0),
            )
            lines.append(f"{label}: {len(group) - len(left)}/{len(group)} unlocked")
            for cat in left[:6]:
                tier = tiers.tier_of(cat) if tiers else "?"
                lines.append(f"    {tier:<4} {dataset.cat_name(cat)}")
            if len(left) > 6:
                lines.append(f"    ... and {len(left) - 6} more")
        return "\n".join(lines)


def build(
    dataset: Dataset,
    tiers: TierList | None,
    owned: set[int],
    banners: list[Banner],
    platinum_banner: Banner | None,
    platinum_tickets: int = 0,
    preferred_banner: str | None = None,
) -> Goal:
    """Every unowned Legend and Uber the live banners can produce, ranked.

    `preferred_banner` nudges the ordering so a Legend obtainable there is
    chased before an equally-ranked one elsewhere.
    """
    from .planner import platinum_targets

    goal = Goal(preferred_banner=preferred_banner)

    def tier_fraction(cat: int) -> float:
        if tiers is None:
            return 0.5
        rank = tiers.rank_of(cat)
        if rank >= UNRANKED:
            return 0.5                     # unranked: treat as middling
        return 1.0 - rank / max(UNRANKED - 1, 1)

    for banner in banners:
        for cat in banner.slots.get(LEGEND) or []:
            if cat in owned:
                continue
            goal.legendaries.add(cat)
            bonus = LEGEND_BONUS + tier_fraction(cat) * UBER_TIER_SPREAD
            if preferred_banner and banner.key == preferred_banner:
                bonus += PREFERRED_BANNER_BONUS
            goal.priority[cat] = max(goal.priority.get(cat, 0.0), bonus)
        for cat in banner.slots.get(UBER) or []:
            if cat in owned:
                continue
            goal.ubers.add(cat)
            bonus = UBER_BONUS + tier_fraction(cat) * UBER_TIER_SPREAD
            goal.priority[cat] = max(goal.priority.get(cat, 0.0), bonus)

    for cat in platinum_targets(tiers, owned, dataset, platinum_banner, platinum_tickets):
        goal.platinum.add(cat)
        goal.priority.setdefault(cat, UBER_BONUS + tier_fraction(cat) * UBER_TIER_SPREAD)

    # A unit that is both a Legend and reachable on the preferred banner must
    # not lose its ranking to an Uber that happens to share an id in a pool.
    goal.ubers -= goal.legendaries
    return goal


def simulate(
    planner,
    goal: Goal,
    seed: int,
    index: int,
    track: int,
    previous_cat: int | None,
    rare_tickets: int,
    platinum_tickets: int = 0,
) -> list[dict]:
    """Play a goal out on paper, and report what it would unlock.

    Costs nothing and takes a second, which makes it the right way to answer
    "is this goal even reachable with the tickets I have" before spending any
    of them. The roll sequence is deterministic, so this is a prediction rather
    than an estimate.
    """
    from .gacha import next_position
    from .planner import PLATINUM_TICKET

    unlocked: list[dict] = []
    platinum_left = platinum_tickets
    for roll in range(rare_tickets):
        step = planner.plan(
            seed, rolls=14, index=index, track=track, previous_cat=previous_cat
        ).steps[0]
        if step.currency == PLATINUM_TICKET:
            if platinum_left <= 0:
                planner.platinum_tickets = 0
                planner.platinum_wanted = set()
                continue
            platinum_left -= 1
        if step.is_new and step.rarity >= UBER:
            unlocked.append({
                "roll": roll + 1,
                "position": step.position,
                "cat_id": step.cat_id,
                "rarity": step.rarity,
                "platinum": step.currency == PLATINUM_TICKET,
                "banner": step.banner_key,
            })
        planner.scorer.owned.add(step.cat_id)
        delta, track = next_position(track, step.reroll_steps)
        index += delta
        previous_cat = step.cat_id
        if goal.complete(planner.scorer.owned):
            break
    return unlocked
