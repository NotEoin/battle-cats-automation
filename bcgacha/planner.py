"""Choose which banner to roll on, position by position, to land wanted cats.

The seed is global: every banner reads the same stream. Position 7 on one banner
and position 7 on another consume the same two advances, they just index
different pools. So banner choice is a free variable at every single roll, and
targeting a cat is a search over which banner to be standing in front of when a
given position comes up.

Rerolls are what make this a search rather than a lookup. A consecutive
duplicate Rare costs an extra advance and flips the track, so the choice made at
one position can move where the next position even is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import LEGEND, RARE, SUPER_RARE, UBER, Banner, Dataset
from .gacha import TRACK_A, Gacha, next_position

# What a roll is worth when nothing is specifically targeted.
RARITY_SCORE = {RARE: 0, SUPER_RARE: 1, UBER: 40, LEGEND: 400}

TARGET_BONUS = 1000


@dataclass
class Step:
    """One planned roll."""

    index: int
    track: int
    banner_key: str
    cat_id: int
    rarity: int
    guaranteed_cat_id: int | None = None
    score: float = 0.0

    @property
    def track_name(self) -> str:
        return "AB"[self.track]


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return sum(s.score for s in self.steps)

    def targets_hit(self, targets: set[int]) -> list[Step]:
        return [s for s in self.steps if s.cat_id in targets]

    def banner_switches(self) -> int:
        return sum(
            1
            for a, b in zip(self.steps, self.steps[1:])
            if a.banner_key != b.banner_key
        )


def score_roll(cat_id: int, rarity: int, targets: set[int], owned: set[int]) -> float:
    """Rate one outcome. Wanted cats dominate; duplicates of owned ubers do not."""
    score = float(RARITY_SCORE.get(rarity, 0))
    if cat_id in targets:
        score += TARGET_BONUS
    elif cat_id in owned and rarity >= UBER:
        score *= 0.1
    return score


def plan_rolls(
    seed: int,
    banners: list[Banner],
    dataset: Dataset,
    rolls: int,
    targets: set[int] | None = None,
    owned: set[int] | None = None,
    index: int = 1,
    track: int = TRACK_A,
    lookahead: int = 2,
) -> Plan:
    """Pick a banner for each of the next `rolls` positions.

    Greedy with a short lookahead: at every position each candidate banner is
    scored by what it yields now plus the best it can reach within `lookahead`
    further rolls. That is enough to spot a position worth reaching while
    staying fast, and it respects the reroll track flips a pure lookup misses.
    """
    targets = targets or set()
    owned = owned or set()
    gachas = {b.key: Gacha(b, seed, dataset) for b in banners}
    plan = Plan()
    previous_cat: int | None = None

    for _ in range(rolls):
        best: tuple[float, Step, int, int, int] | None = None
        for banner in banners:
            gacha = gachas[banner.key]
            roll = gacha.cell(index, track)
            if (
                roll.rarity == RARE
                and previous_cat is not None
                and roll.cat_id == previous_cat
            ):
                gacha._reroll(roll)
            immediate = score_roll(roll.cat_id, roll.rarity, targets, owned)
            delta, nxt_track = next_position(track, roll.reroll_steps)
            future = (
                _best_ahead(
                    gachas, banners, dataset, index + delta, nxt_track,
                    roll.cat_id, targets, owned, lookahead,
                )
                if lookahead
                else 0.0
            )
            total = immediate + 0.9 * future
            if best is None or total > best[0]:
                step = Step(
                    index=index,
                    track=track,
                    banner_key=banner.key,
                    cat_id=roll.cat_id,
                    rarity=roll.rarity,
                    guaranteed_cat_id=(
                        gacha._guaranteed_for(index, track)
                        if banner.guaranteed_rolls
                        else None
                    ),
                    score=immediate,
                )
                best = (total, step, index + delta, nxt_track, roll.cat_id)

        assert best is not None, "no banners supplied"
        _, step, index, track, previous_cat = best
        plan.steps.append(step)

    return plan


def _best_ahead(
    gachas, banners, dataset, index, track, previous_cat, targets, owned, depth
) -> float:
    """Best single-roll score reachable within `depth` further rolls."""
    if depth <= 0:
        return 0.0
    best = 0.0
    for banner in banners:
        gacha = gachas[banner.key]
        roll = gacha.cell(index, track)
        if roll.rarity == RARE and roll.cat_id == previous_cat:
            gacha._reroll(roll)
        value = score_roll(roll.cat_id, roll.rarity, targets, owned)
        delta, nxt = next_position(track, roll.reroll_steps)
        value = max(
            value,
            0.9
            * _best_ahead(
                gachas, banners, dataset, index + delta, nxt,
                roll.cat_id, targets, owned, depth - 1,
            ),
        )
        best = max(best, value)
    return best


def uber_pool(banners: list[Banner]) -> set[int]:
    """Every uber and legend obtainable across a set of banners."""
    out: set[int] = set()
    for banner in banners:
        for rarity in (UBER, LEGEND):
            out.update(banner.slots.get(rarity) or [])
    return out


def uber_positions(
    seed: int, banner: Banner, count: int, dataset: Dataset
) -> list[tuple[int, int, str]]:
    """Positions in the next `count` rolls that yield Uber or Legend, and which cat.

    Worth knowing because rarity is NOT something banner choice can change on
    banners that share rates: the rarity comes from the seed alone, compared
    against the banner's weights. Every standard banner uses 7000/2500/500, so
    an Uber position is an Uber position on all of them, and only the cat
    differs. Rarity only moves when the weights move -- a 9% Uberfest, a 10%
    Epicfest, or the 100% Platinum machine.
    """
    gacha = Gacha(banner, seed, dataset)
    out = []
    for n in range(1, count + 1):
        roll = gacha.cell(n, TRACK_A)
        if roll.rarity >= UBER:
            out.append((n, roll.cat_id, dataset.cat_name(roll.cat_id)))
    return out
