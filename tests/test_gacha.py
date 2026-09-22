"""Check the roll engine against saved bc.godfat.org tables.

The fixtures are real responses from the reference tracker, one per banner
shape: a plain banner with a Legend slot, a collab, an 11-roll guaranteed, a
15-roll step-up, and the 100%-uber Platinum machine.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from parse_godfat import parse  # noqa: E402

from bcgacha.data import load  # noqa: E402
from bcgacha.gacha import Gacha  # noqa: E402
from bcgacha.prng import advance, retreat  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

CASES = [
    ("collab", "2026-09-21_1081", 123456789),
    ("plain_legend", "2026-08-01_1015", 123456789),
    ("guaranteed", "2026-08-21_1075", 4242424242),
    ("stepup", "2026-09-25_523", 987654321),
    ("platinum", "2026-07-24_1063", 123456789),
]


@pytest.mark.parametrize("tag,event,seed", CASES)
def test_table_matches_reference(tag, event, seed):
    ref = parse((FIXTURES / f"{tag}.html").read_text())
    assert ref, f"{tag}: fixture parsed to nothing"
    ds = load()
    gacha = Gacha(ds.find_banner(event), seed, ds)
    mismatches = [
        (pos, name, ds.cat_name(gacha.cell(*pos).cat_id))
        for pos, name in sorted(ref.items())
        if ds.cat_name(gacha.cell(*pos).cat_id) != name
    ]
    assert not mismatches, f"{tag}: {len(mismatches)}/{len(ref)} wrong, first={mismatches[:3]}"


def test_prng_round_trips():
    for value in (0, 1, 123456789, 0xFFFFFFFF, 0xDEADBEEF):
        assert retreat(advance(value)) == value
        assert advance(retreat(value)) == value


def test_backtrack_matches_reference_link():
    # bc.godfat.org's Backtrack link for seed 123456789 points at this seed.
    assert retreat(retreat(123456789)) == 3181816245


def test_rarity_weights_sum_to_base():
    ds = load()
    for banner in list(ds.banners.values())[:400]:
        total = banner.rare + banner.supa + banner.uber + banner.legend
        assert total == 10000, f"{banner.key} weights sum to {total}"


def test_seed_search_recovers_known_seed():
    """A narrow scan around a known seed must return it, and nothing else."""
    from bcgacha.seedfind import search

    ds = load()
    banner = ds.find_banner("2026-09-21_1081")
    observed = [38, 33, 198, 524, 373, 496, 31, 200]  # seed 123456789
    found = search(banner, observed, ds, seed_range=(123456789 - (1 << 20), 123456789 + 1))
    assert [c.seed for c in found] == [123456789]


def test_resolve_names_rejects_cats_outside_pool():
    from bcgacha.seedfind import resolve_names

    ds = load()
    banner = ds.find_banner("2026-09-21_1081")
    assert resolve_names(["Pogo Cat", "Hip Hop Cat"], banner, ds) == [38, 33]
    with pytest.raises(KeyError):
        resolve_names(["Not A Real Cat"], banner, ds)


def test_guaranteed_uber_matches_reference():
    """The 11th-roll uber is read off the table, not rolled -- check every cell."""
    from parse_godfat import parse_guaranteed

    ref = parse_guaranteed((FIXTURES / "guaranteed.html").read_text())
    assert ref
    ds = load()
    gacha = Gacha(ds.find_banner("2026-08-21_1075"), 4242424242, ds)
    wrong = [
        (pos, expected, ds.cat_name(gacha._guaranteed_for(*pos)))
        for pos, (_, expected) in sorted(ref.items())
        if ds.cat_name(gacha._guaranteed_for(*pos)) != expected
    ]
    assert not wrong, f"{len(wrong)}/{len(ref)} guaranteed ubers wrong: {wrong[:3]}"
