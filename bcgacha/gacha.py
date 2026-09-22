"""Compute exactly which cats a seed will produce on a given banner.

Every rare capsule draw on an account is determined by one 32-bit seed, so the
whole result sequence can be worked out offline.  The bot never has to read a
roll result off the screen -- it already knows what it is going to get.

The model, in the terms godfat's tracker uses:

  A roll of a cat costs two seed advances, one picking the rarity and one
  picking which cat of that rarity.  Because rolls are two advances wide but the
  table is indexed one advance apart, there are two interleaved readings of the
  same stream -- track A and track B.  Track B's rarity draw is track A's slot
  draw.

  Drawing the same Rare cat twice in a row triggers a reroll: the game drops
  that cat from the pool, advances once more, and draws again.  The extra
  advance is odd, so it lands you on the other track -- this is the only thing
  that moves a player between tracks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data import BASE, LEGEND, RARE, SUPER_RARE, UBER, Banner, Dataset
from .prng import advance

TRACK_A, TRACK_B = 0, 1
TRACK_NAMES = {TRACK_A: "A", TRACK_B: "B"}


@dataclass
class Roll:
    """One draw as it actually happened on a player's path."""

    sequence: int          # 1-based row in the tracker table
    track: int             # TRACK_A or TRACK_B
    cat_id: int
    rarity: int
    slot: int
    rarity_seed: int
    slot_seed: int
    reroll_steps: int = 0  # extra advances a dupe reroll consumed
    duped_from: int | None = None   # the cat this replaced, if rerolled
    guaranteed_cat_id: int | None = None

    @property
    def track_name(self) -> str:
        """The track as the tracker writes it: "A" or "B"."""
        return TRACK_NAMES[self.track]

    @property
    def was_rerolled(self) -> bool:
        """True when a dupe reroll replaced the cat first drawn."""
        return self.reroll_steps > 0


def dig_rarity(score: int, banner: Banner) -> int:
    """Map a 0..9999 score onto a rarity using cumulative weights."""
    if score < banner.rare:
        return RARE
    if score < banner.rare + banner.supa:
        return SUPER_RARE
    if score < banner.rare + banner.supa + banner.uber:
        return UBER
    return LEGEND


def next_position(track: int, steps: int) -> tuple[int, int]:
    """Where the next roll lands, given how many extra advances a reroll took.

    Returns (index_delta, next_track).  With steps=0 this is simply "one row
    down, same track"; an odd number of extra advances flips the track.
    """
    index_delta = ((track + steps) // 2) + 1
    next_track = ((track + steps - 1) ^ 1) & 1
    return index_delta, next_track


class Gacha:
    """A seed read through one banner's pools."""

    def __init__(self, banner: Banner, seed: int, dataset: Dataset | None = None):
        self.banner = banner
        self.dataset = dataset
        # The game advances once before the first roll, so the first rarity
        # draw uses S[1] rather than the seed as entered.
        self.seed = seed
        self._stream: list[int] = [seed]

    def _at(self, k: int) -> int:
        """S[k]: the seed after k advances. S[0] is the seed as entered."""
        while len(self._stream) <= k:
            self._stream.append(advance(self._stream[-1]))
        return self._stream[k]

    def cell(self, index: int, track: int) -> Roll:
        """The raw draw at a table position, before any dupe reroll is applied."""
        rarity_seed = self._at(2 * index - 1 + track)
        slot_seed = self._at(2 * index + track)
        rarity = dig_rarity(rarity_seed % BASE, self.banner)
        slots = self.banner.slots.get(rarity) or []
        if not slots:
            return Roll(index, track, -1, rarity, 0, rarity_seed, slot_seed)
        slot = slot_seed % len(slots)
        return Roll(index, track, slots[slot], rarity, slot, rarity_seed, slot_seed)

    def _reroll(self, roll: Roll) -> Roll:
        """Replace a consecutive duplicate Rare, consuming extra advances."""
        pool = list(self.banner.slots[RARE])
        seed = roll.slot_seed
        slot = roll.slot
        cat_id = roll.cat_id
        steps = 0
        for _ in range(pool.count(cat_id)):
            seed = advance(seed)
            steps += 1
            del pool[slot]
            if not pool:
                break
            slot = seed % len(pool)
            if pool[slot] != cat_id:
                break
        roll.cat_id = pool[slot] if pool else -1
        roll.slot = slot
        roll.reroll_steps = steps
        roll.duped_from = cat_id
        return roll

    def walk(
        self,
        count: int,
        index: int = 1,
        track: int = TRACK_A,
        previous_cat: int | None = None,
    ) -> list[Roll]:
        """Play `count` draws forward from a position, honouring dupe rerolls.

        `previous_cat` is the cat drawn immediately before this walk started; it
        matters because the very first draw can itself be a duplicate.
        """
        out: list[Roll] = []
        for _ in range(count):
            roll = self.cell(index, track)
            if roll.rarity == RARE and previous_cat is not None and roll.cat_id == previous_cat:
                self._reroll(roll)
            if self.banner.guaranteed_rolls:
                roll.guaranteed_cat_id = self._guaranteed_for(index, track)
            out.append(roll)
            previous_cat = roll.cat_id
            delta, track = next_position(track, roll.reroll_steps)
            index += delta
        return out

    def _guaranteed_for(self, index: int, track: int) -> int | None:
        """The uber handed out at the end of a guaranteed multi-draw started here.

        The guarantee costs a single extra advance and reuses the rarity seed of
        the position the multi-draw ends on, so it is read off the table rather
        than rolled fresh.
        """
        n = self.banner.guaranteed_rolls
        if not n:
            return None
        ubers = self.banner.slots.get(UBER) or []
        if not ubers:
            return None
        # Follow the player's own path n-1 hops to reach the final position.
        cur_index, cur_track = index, track
        prev_cat: int | None = None
        for _ in range(n - 1):
            roll = self.cell(cur_index, cur_track)
            if roll.rarity == RARE and prev_cat is not None and roll.cat_id == prev_cat:
                self._reroll(roll)
            prev_cat = roll.cat_id
            delta, cur_track = next_position(cur_track, roll.reroll_steps)
            cur_index += delta
        last = self.cell(cur_index, cur_track)
        return ubers[last.rarity_seed % len(ubers)]

    def table(self, rows: int) -> list[tuple[Roll, Roll]]:
        """Both tracks for the first `rows` positions, as the tracker displays them."""
        return [(self.cell(i, TRACK_A), self.cell(i, TRACK_B)) for i in range(1, rows + 1)]
