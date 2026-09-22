"""Persist what we know about the account between runs.

The seed never changes, but the position in the stream advances with every
rare-capsule roll, so it has to survive restarts. Losing the position means
redoing the ten-roll discovery, which costs real tickets.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .gacha import TRACK_A, TRACK_NAMES
from .prng import advance

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "account.json"


@dataclass
class Account:
    seed: int                    # the seed as of `origin`, not as of now
    index: int = 1               # current row in the tracker table
    track: int = TRACK_A
    rolls_made: int = 0
    last_cat_id: int | None = None   # needed to judge the next dupe reroll
    storage_used: int = 0
    storage_capacity: int = 128
    tickets: int | None = None
    notes: str = ""
    history: list[str] = field(default_factory=list)

    @property
    def position(self) -> str:
        return f"{self.index}{TRACK_NAMES[self.track]}"

    def current_seed(self) -> int:
        """The seed to hand to bc.godfat.org to see the table from here."""
        seed = self.seed
        for _ in range(2 * (self.index - 1) + self.track):
            seed = advance(seed)
        return seed

    @property
    def storage_free(self) -> int:
        return max(0, self.storage_capacity - self.storage_used)

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or STATE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "Account":
        path = Path(path or STATE_PATH)
        if not path.exists():
            raise FileNotFoundError(f"{path} missing -- run find-seed first")
        return cls(**json.loads(path.read_text()))


def resync(
    account: "Account",
    observed_cat: int,
    banners: list,
    dataset,
    window: int = 40,
) -> tuple[int, int] | None:
    """Find the position that would have produced `observed_cat`, and move there.

    Rolls made outside the bot -- by hand, or by a test that forgot to record
    them -- leave the saved position behind the game. Rather than spending ten
    more tickets rediscovering a seed that has not changed, search forward from
    where we think we are for the position that matches what was actually seen.

    Returns the corrected (index, track) *after* consuming that roll, or None
    when the match is not unique.
    """
    from .gacha import Gacha, next_position

    matches = []
    for banner in banners:
        gacha = Gacha(banner, account.seed, dataset)
        index, track = account.index, account.track
        previous = account.last_cat_id
        for _ in range(window):
            roll = gacha.cell(index, track)
            if (
                roll.rarity == 2
                and previous is not None
                and roll.cat_id == previous
            ):
                gacha._reroll(roll)
            if roll.cat_id == observed_cat:
                delta, nxt = next_position(track, roll.reroll_steps)
                matches.append((index, track, index + delta, nxt, banner.key))
            previous = roll.cat_id
            delta, track = next_position(track, roll.reroll_steps)
            index += delta

    positions = {(m[2], m[3]) for m in matches}
    if len(positions) != 1:
        return None
    account.index, account.track = matches[0][2], matches[0][3]
    account.last_cat_id = observed_cat
    return account.index, account.track
