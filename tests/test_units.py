"""Finding a unit by any of its names, a nickname, its id or a slip of the keys."""

import pytest

from bcgacha import units
from bcgacha.data import load


@pytest.fixture(scope="module")
def cat():
    # No owned list and no live events: the answers must not depend on the
    # account this runs beside, nor on today's date.
    return units.Catalogue(load(), tiers=None, owned=None, events=[])


def test_an_exact_form_name_finds_its_cat(cat):
    unit, _ = cat.resolve("Kasli the Bane")
    assert unit is not None and "Kasli the Bane" in unit.forms


def test_a_community_nickname_finds_the_cat(cat):
    unit, _ = cat.resolve("Dark Kasli")
    assert unit is not None and "Kasli the Bane" in unit.forms


def test_a_later_form_finds_the_cat_under_its_first_name(cat):
    bane, _ = cat.resolve("Kasli the Bane")
    assert bane.name == bane.forms[0]


def test_an_id_finds_the_cat(cat):
    unit, _ = cat.resolve("#800")
    assert unit.id == 800


def test_a_shared_word_is_left_for_a_person_to_choose(cat):
    """Two cats called Shirou-something: neither is guessed at."""
    unit, hits = cat.resolve("shirou")
    assert unit is None
    names = {h.name for h in hits}
    assert {"Shirou Emiya", "Li'l Shirou"} <= names


def test_the_start_of_a_name_is_enough_when_only_one_cat_fits(cat):
    unit, _ = cat.resolve("morta")
    assert unit.name == "Mighty Morta-Loncha"


def test_a_typo_still_offers_the_cat(cat):
    hits = cat.search("Mighty Morta Loncah")
    assert hits and hits[0].name == "Mighty Morta-Loncha"


def test_nothing_is_offered_for_nothing(cat):
    assert cat.search("   ") == []


def test_a_unit_says_where_it_can_be_rolled():
    ds = load()
    from bcgacha import events as live
    import datetime as dt

    events = live.live_events(ds, dt.date(2026, 9, 24))
    iron = next(e for e in events if e.label == "Iron Legion")
    cat = units.Catalogue(ds, tiers=None, owned={800}, events=events)
    unit = cat.unit(iron.ubers[0])
    assert "Iron Legion" in unit.events and unit.obtainable
    assert cat.unit(800).owned is True
