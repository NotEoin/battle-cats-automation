"""Decide which banner to roll on at each position, and when to spend Platinum.

One seed drives every banner, so the position in the stream is fixed but the
cat it produces is not: banner choice is a free variable at every roll. Rarity,
though, is NOT free -- it comes from the seed compared against the banner's
weights, and every standard banner shares the same 7000/2500/500 split. So an
Uber position is an Uber position everywhere, and the real decision at one is
*which* Uber to take.

Platinum Capsules are the exception worth planning around. They read the same
seed but are 100% Uber, so they can turn any position into an Uber. Platinum
Tickets are scarce, so they are only spent where they buy a strong unit the
account does not already have.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import LEGEND, RARE, SUPER_RARE, UBER, Banner, Dataset
from .tiers import TierList
from .gacha import TRACK_A, Gacha, next_position
from .scoring import Scorer

RARE_TICKET = "rare_ticket"
PLATINUM_TICKET = "platinum_ticket"

# How far the planner looks past the roll it is choosing. Two was far too
# shallow: switching banner can hand you a consecutive duplicate Rare, and the
# reroll that follows flips the track, which can divert the path away from an
# Uber several rolls out. The planner has to see that far to avoid trading a
# 12-point Rare for a 600-point Uber.
# Six is where this stops mattering: it finds the same route as eight and does
# it ten times faster, while two misses Ubers entirely.
DEFAULT_LOOKAHEAD = 6


def platinum_targets(
    tier_list: TierList | None,
    owned: set[int],
    dataset: Dataset,
    platinum_banner: Banner | None,
    tickets: int,
) -> set[int]:
    """The best `tickets` unowned units the Platinum machine can produce.

    Platinum Tickets are scarce, so they are earmarked in advance rather than
    spent on whatever happens to come up: take every unit in the Platinum pool
    the account does not own, order it by community rank, and reserve exactly
    as many as there are tickets. Holding seven tickets with all of S and most
    of A already owned therefore reserves the three missing A-tier units and
    the four best B-tier ones.
    """
    if platinum_banner is None or tickets <= 0:
        return set()
    pool: set[int] = set()
    for rarity in (UBER, LEGEND):
        pool.update(platinum_banner.slots.get(rarity) or [])
    missing = [c for c in pool if c not in owned]
    rank = (lambda c: tier_list.rank_of(c)) if tier_list else (lambda c: 0)
    missing.sort(key=lambda c: (rank(c), dataset.cat_name(c)))
    return set(missing[:tickets])


@dataclass
class PlanStep:
    index: int
    track: int
    banner_key: str
    banner_name: str
    cat_id: int
    rarity: int
    currency: str = RARE_TICKET
    score: float = 0.0
    is_new: bool = False
    rerolled_from: int | None = None
    # Extra seed advances a dupe reroll consumed. Odd values flip the track,
    # so the run loop must apply this rather than assuming a clean step.
    reroll_steps: int = 0

    @property
    def track_name(self) -> str:
        return "AB"[self.track]

    @property
    def position(self) -> str:
        return f"{self.index}{self.track_name}"


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return sum(s.score for s in self.steps)

    @property
    def new_units(self) -> list[PlanStep]:
        return [s for s in self.steps if s.is_new]

    @property
    def platinum_spent(self) -> int:
        return sum(1 for s in self.steps if s.currency == PLATINUM_TICKET)

    def banner_switches(self) -> int:
        return sum(
            1 for a, b in zip(self.steps, self.steps[1:]) if a.banner_key != b.banner_key
        )

    def summary(self, dataset: Dataset) -> str:
        lines = []
        for n, s in enumerate(self.steps, 1):
            tag = "NEW" if s.is_new else "dup"
            cur = "PLAT" if s.currency == PLATINUM_TICKET else "    "
            lines.append(
                f"{n:>4}. {s.position:>6} {cur} {dataset.cat_name(s.cat_id):<26} "
                f"{tag} {s.score:7.1f}  {s.banner_name[:34]}"
            )
        return "\n".join(lines)


class Planner:
    def __init__(
        self,
        dataset: Dataset,
        banners: list[Banner],
        scorer: Scorer,
        platinum_banner: Banner | None = None,
        platinum_tickets: int = 0,
        platinum_wanted: set[int] | None = None,
    ):
        self.dataset = dataset
        self.banners = banners
        self.scorer = scorer
        self.platinum_banner = platinum_banner
        self.platinum_tickets = platinum_tickets
        # Reserved in advance; a ticket is spent only on one of these.
        self.platinum_wanted = (
            platinum_wanted
            if platinum_wanted is not None
            else platinum_targets(
                scorer.tiers, scorer.owned, dataset, platinum_banner, platinum_tickets
            )
        )

    def _gacha(self, seed: int, banner: Banner, cache: dict) -> Gacha:
        if banner.key not in cache:
            cache[banner.key] = Gacha(banner, seed, self.dataset)
        return cache[banner.key]

    def _evaluate(self, gacha, index, track, previous_cat):
        """The roll a banner gives here, with any dupe reroll applied."""
        roll = gacha.cell(index, track)
        if (
            roll.rarity == RARE
            and previous_cat is not None
            and roll.cat_id == previous_cat
        ):
            gacha._reroll(roll)
        return roll

    def _platinum_worth_it(self, cat_id: int) -> bool:
        """A ticket is only ever spent on one of the reserved units."""
        return self.scorer.is_new(cat_id) and cat_id in self.platinum_wanted

    def plan(
        self,
        seed: int,
        rolls: int,
        index: int = 1,
        track: int = TRACK_A,
        previous_cat: int | None = None,
        lookahead: int = DEFAULT_LOOKAHEAD,
    ) -> Plan:
        cache: dict = {}
        plan = Plan()
        platinum_left = self.platinum_tickets
        owned_snapshot = set(self.scorer.owned)

        for _ in range(rolls):
            options = []
            for banner in self.banners:
                roll = self._evaluate(self._gacha(seed, banner, cache), index, track, previous_cat)
                options.append((banner, roll, RARE_TICKET))
            if self.platinum_banner is not None and platinum_left > 0:
                roll = self._evaluate(
                    self._gacha(seed, self.platinum_banner, cache), index, track, previous_cat
                )
                if self._platinum_worth_it(roll.cat_id):
                    options.append((self.platinum_banner, roll, PLATINUM_TICKET))

            best = None
            for banner, roll, currency in options:
                value = self.scorer.value(roll.cat_id, roll.rarity)
                # A Platinum ticket must clearly beat simply rolling normally.
                if currency == PLATINUM_TICKET:
                    value *= 0.9
                delta, nxt_track = next_position(track, roll.reroll_steps)
                future = self._best_ahead(
                    seed, cache, index + delta, nxt_track, roll.cat_id, lookahead
                )
                total = value + 0.85 * future
                if best is None or total > best[0]:
                    best = (total, banner, roll, currency, value, index + delta, nxt_track)

            _, banner, roll, currency, value, next_index, next_track = best
            step = PlanStep(
                index=index, track=track,
                banner_key=banner.key, banner_name=banner.name,
                cat_id=roll.cat_id, rarity=roll.rarity,
                currency=currency, score=value,
                is_new=self.scorer.is_new(roll.cat_id),
                rerolled_from=roll.duped_from,
                reroll_steps=roll.reroll_steps,
            )
            plan.steps.append(step)
            if currency == PLATINUM_TICKET:
                platinum_left -= 1
            # Assume we keep what we pull, so later dupes are scored as dupes.
            self.scorer.owned.add(roll.cat_id)
            previous_cat = roll.cat_id
            index, track = next_index, next_track

        self.scorer.owned = owned_snapshot
        return plan

    def _best_ahead(self, seed, cache, index, track, previous_cat, depth) -> float:
        if depth <= 0:
            return 0.0
        best = 0.0
        for banner in self.banners:
            roll = self._evaluate(self._gacha(seed, banner, cache), index, track, previous_cat)
            value = self.scorer.value(roll.cat_id, roll.rarity)
            delta, nxt = next_position(track, roll.reroll_steps)
            value = max(
                value,
                0.85 * self._best_ahead(seed, cache, index + delta, nxt, roll.cat_id, depth - 1),
            )
            best = max(best, value)
        return best

    def find_cat(
        self,
        seed: int,
        cat_id: int,
        horizon: int = 400,
        index: int = 1,
        track: int = TRACK_A,
    ) -> list[tuple[int, int, str]]:
        """Every position within the horizon where some banner yields `cat_id`.

        Returns (index, track, banner key). Used to answer "how far away is this
        cat, and which banner do I need to be on when I get there".
        """
        cache: dict = {}
        found = []
        banners = list(self.banners)
        if self.platinum_banner is not None:
            banners.append(self.platinum_banner)
        for banner in banners:
            gacha = self._gacha(seed, banner, cache)
            for n in range(index, index + horizon):
                for t in (TRACK_A, 1):
                    if gacha.cell(n, t).cat_id == cat_id:
                        found.append((n, t, banner.key))
        found.sort()
        return found
