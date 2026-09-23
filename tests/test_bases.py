"""Telling one chapter's Cat Base from another by the door behind its buttons.

The door strip is placed from where Start!! and Equip are on this device, and
a chapter is named only when its learned door is close and clearly the
closest: a wrong chapter would send the bot to the wrong stage map.
"""

import os

import pytest

from bcgacha import bases
from bcgacha.profile import Profile

START, EQUIP = (0.2, 0.275), (0.2, 0.525)


def test_the_door_strip_is_measured_in_start_to_equip_gaps():
    """One layout at two resolutions gives one strip; twice the gap gives twice the strip."""
    big = bases.door_region(START, EQUIP, (2532, 1170))
    small = bases.door_region(START, EQUIP, (1266, 585))
    assert small == pytest.approx(big)

    x0, y0, x1, y1 = big
    assert x0 > START[0], "the strip lies right of the buttons"
    assert y0 < START[1] and y1 > EQUIP[1], "it runs from above Start!! to below Equip"

    far = bases.door_region(START, (EQUIP[0], START[1] + 2 * (EQUIP[1] - START[1])), (2532, 1170))
    assert far[2] - far[0] == pytest.approx(2 * (x1 - x0))
    assert far[3] - far[1] == pytest.approx(2 * (y1 - y0))
    assert far[0] - START[0] == pytest.approx(2 * (x0 - START[0]))


def test_no_chapter_is_named_before_any_door_is_learned():
    """A device that has learned no doors cannot tell chapters apart."""
    assert bases.classify_distances({}) is None


def test_a_door_far_from_every_learned_one_is_no_chapter():
    """The nearest learned door must actually be near."""
    too_far = bases.MATCH_DISTANCE * 1.2
    assert bases.classify_distances({"chapter:a:1": too_far, "chapter:a:2": too_far * 3}) is None


def test_a_door_nearly_as_close_to_two_chapters_is_neither():
    """Two plain grey doors a flower apart: a near tie names no chapter."""
    near = bases.MATCH_DISTANCE / 3
    runner_up = near * bases.MARGIN * 0.9
    assert bases.classify_distances({"chapter:a:1": near, "chapter:a:2": runner_up}) is None


def test_a_clear_winner_is_named():
    """Near, and clearly nearer than the runner-up: that chapter."""
    near = bases.MATCH_DISTANCE / 3
    runner_up = near * bases.MARGIN * 1.5
    assert bases.classify_distances({"chapter:a:1": near, "chapter:a:2": runner_up,
                                     "saga:legend_stages": 1.0}) == "chapter:a:1"
    assert bases.classify_distances({"chapter:a:1": near}) == "chapter:a:1"


def test_seeing_the_same_door_again_rewrites_nothing(tmp_path):
    """Every visit shows the same door; only the first one is written down."""
    profile = Profile(2532, 1170, root=tmp_path)
    door = [0.5, 0.25, 0.75, 0.125] * 4
    assert profile.learn_base("chapter:a:1", door)
    os.utime(profile.file, ns=(0, 0))
    written = profile.file.read_bytes()

    assert not profile.learn_base("chapter:a:1", door)
    assert not Profile(2532, 1170, root=tmp_path).learn_base("chapter:a:1", door)
    assert profile.file.read_bytes() == written
    assert profile.file.stat().st_mtime_ns == 0, "profile.json was rewritten"


def test_a_door_within_same_door_of_the_learned_one_is_the_same_door(tmp_path):
    """Doors closer than SAME_DOOR are one door seen again; further apart, it is relearned."""
    profile = Profile(2532, 1170, root=tmp_path)
    door = [0.5] * 16
    profile.learn_base("chapter:a:1", door)
    # Shifting every value by d puts the doors exactly d apart.
    assert not profile.learn_base("chapter:a:1", [v + bases.SAME_DOOR * 0.8 for v in door])
    assert profile.bases()["chapter:a:1"] == door
    assert profile.learn_base("chapter:a:1", [v + bases.SAME_DOOR * 2 for v in door])
    assert profile.bases()["chapter:a:1"] != door
