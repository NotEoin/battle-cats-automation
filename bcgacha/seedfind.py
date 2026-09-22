"""Recover an account's seed from a handful of observed rolls.

The seed is 32 bits, so the search is a brute force over 2**32 candidates.  That
is only tractable because the first roll alone throws away almost all of them:
matching one cat costs a rarity weight times a pool size, typically better than
1 in 30.  The first two rolls are filtered with numpy over the whole space, and
the survivors are then replayed properly -- dupe rerolls included -- in Python.

Track A and track B need no separate search.  Sitting on track B at seed S is
the same as sitting on track A at advance(S), so scanning every seed on track A
already covers both.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import BASE, RARE, Banner, Dataset
from .gacha import Gacha

MASK = 0xFFFFFFFF
CHUNK = 1 << 24


def _advance_np(seed: np.ndarray) -> np.ndarray:
    seed ^= (seed << np.uint32(13))
    seed ^= (seed >> np.uint32(17))
    seed ^= (seed << np.uint32(15))
    return seed


def _rarity_bounds(banner: Banner) -> list[tuple[int, int, int]]:
    """(low, high, rarity) score bands, so a score maps to a rarity."""
    bands = []
    low = 0
    for rarity, weight in (
        (RARE, banner.rare),
        (RARE + 1, banner.supa),
        (RARE + 2, banner.uber),
        (RARE + 3, banner.legend),
    ):
        if weight:
            bands.append((low, low + weight, rarity))
            low += weight
    return bands


@dataclass
class SeedCandidate:
    """A seed that reproduces the observed draws, on the track they fit."""

    seed: int
    track: str
    rolls: list[str]


def _cat_of(banner: Banner, rarity_seed: np.ndarray, slot_seed: np.ndarray) -> np.ndarray:
    """Vectorised cat-id lookup, -1 where the rarity's pool is empty."""
    score = rarity_seed % np.uint32(BASE)
    out = np.full(score.shape, -1, dtype=np.int32)
    for low, high, rarity in _rarity_bounds(banner):
        pool = banner.slots.get(rarity) or []
        if not pool:
            continue
        sel = (score >= low) & (score < high)
        if not sel.any():
            continue
        lut = np.array(pool, dtype=np.int32)
        out[sel] = lut[slot_seed[sel] % np.uint32(len(pool))]
    return out


def search(
    banner: Banner,
    observed: list[int],
    dataset: Dataset,
    progress=None,
    seed_range: tuple[int, int] = (0, 1 << 32),
    previous_cat: int | None = None,
) -> list[SeedCandidate]:
    """Find every seed whose next rolls on `banner` are exactly `observed`.

    `observed` is a list of cat ids, in the order they came out of the machine,
    including any cat the game substituted for a consecutive duplicate.
    `seed_range` narrows the scan, which is only useful for tests.
    """
    if len(observed) < 2:
        raise ValueError("need at least two rolls to filter on")

    lo, hi = seed_range
    survivors: list[int] = []
    for base in range(lo, hi, CHUNK):
        seeds = np.arange(base, min(base + CHUNK, hi), dtype=np.uint32)
        # A roll costs TWO advances: one for rarity, one for the slot. Roll n
        # on track A therefore reads S[2n-1] and S[2n] -- stepping a single
        # advance between rolls would read track B of the previous row.
        s1 = _advance_np(seeds.copy())          # S[1]  roll 1 rarity
        s2 = _advance_np(s1.copy())             # S[2]  roll 1 slot
        keep = _cat_of(banner, s1, s2) == observed[0]
        if keep.any():
            s3 = _advance_np(s2[keep].copy())   # S[3]  roll 2 rarity
            s4 = _advance_np(s3.copy())         # S[4]  roll 2 slot
            second = _cat_of(banner, s3, s4)
            idx = np.nonzero(keep)[0][second == observed[1]]
            survivors.extend(seeds[idx].tolist())
        if progress:
            progress(base + CHUNK, len(survivors))

    # Replay each survivor for real, so dupe rerolls are honoured.
    out: list[SeedCandidate] = []
    for seed in survivors:
        rolls = Gacha(banner, seed, dataset).walk(
            len(observed), previous_cat=previous_cat
        )
        if [r.cat_id for r in rolls] == observed:
            out.append(
                SeedCandidate(
                    seed=seed,
                    track="A",
                    rolls=[dataset.cat_name(r.cat_id) for r in rolls],
                )
            )
    return out


def resolve_names(names: list[str], banner: Banner, dataset: Dataset) -> list[int]:
    """Turn typed cat names into ids, restricted to this banner's pools."""
    pool = {
        cid
        for rarity, ids in banner.slots.items()
        if rarity >= RARE
        for cid in ids
    }
    by_name: dict[str, int] = {}
    for cid in pool:
        for form in dataset.cats.get(cid, {}).get("name", []) or []:
            by_name.setdefault(form.strip().lower(), cid)
    out = []
    for raw in names:
        key = raw.strip().lower()
        if key not in by_name:
            raise KeyError(f"{raw!r} is not in this banner's pool")
        out.append(by_name[key])
    return out
