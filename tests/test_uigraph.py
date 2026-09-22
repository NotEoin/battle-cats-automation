"""Structural invariants for the UI map.

These are the properties that make position-free navigation work. Each one
corresponds to a failure the roll loop actually hit.
"""

from pathlib import Path

import cv2
import pytest

from bcgacha.uigraph import UIGraph, find_buttons

FIXTURE_CAROUSELS = Path(__file__).resolve().parent / "fixtures" / "carousels.json"


@pytest.fixture(params=["base", "with-carousels"])
def graph(request):
    """Every invariant holds for the base map and with a save's carousels on top."""
    if request.param == "base":
        return UIGraph.load(carousels=False)
    return UIGraph.load(carousels=FIXTURE_CAROUSELS)


def test_every_screen_can_be_identified(graph):
    """A screen with neither a title nor anchors can never be recognised."""
    blind = [
        s.name for s in graph.screens.values()
        if not s.title and not s.anchors and not s.forbidden
    ]
    assert not blind, f"unidentifiable: {blind}"


def test_every_screen_reaches_the_cat_base(graph):
    """Whatever the bot wakes up on, it must be able to get home."""
    stranded = []
    for name, screen in graph.screens.items():
        if screen.forbidden or name == "cat_base":
            continue
        try:
            graph.route(name, "cat_base")
        except Exception:
            stranded.append(name)
    assert not stranded, f"cannot reach cat_base from: {stranded}"


def test_both_capsule_machines_are_routable(graph):
    """Platinum has no fixed tab, so it is reached by a routine, not a tap."""
    for destination in ("rare_capsules", "platinum_capsules"):
        path = graph.route("cat_base", destination)
        assert path, destination
    hop = graph.route("rare_capsules", "platinum_capsules")[-1]
    assert hop.action, "platinum must be reached by an action, not a memorised tab"


def test_no_route_passes_through_settings(graph):
    assert graph.screens["settings"].forbidden
    for name in graph.screens:
        if graph.screens[name].forbidden:
            continue
        try:
            path = graph.route(name, "cat_base")
        except Exception:
            continue
        assert all(t.dst != "settings" for t in path), name


def test_only_reactive_screens_have_nothing_leading_to_them(graph):
    """Reveals and popups appear on their own; everything else is navigable."""
    incoming = {t.dst for t in graph.transitions}
    orphans = [
        n for n, s in graph.screens.items()
        if n not in incoming and n != "opening" and not s.reactive and not s.forbidden
    ]
    assert not orphans, f"unreachable and not marked reactive: {orphans}"


def test_every_screen_has_a_way_out(graph):
    outgoing = {t.src for t in graph.transitions}
    stuck = [
        n for n, s in graph.screens.items() if n not in outgoing and not s.forbidden
    ]
    assert not stuck, f"no exit recorded: {stuck}"


def test_the_post_draw_overlay_can_exit_to_either_machine(graph):
    """The reveal looks the same on both machines, so it must not assume one."""
    exits = {t.dst for t in graph.transitions if t.src == "sent_to_storage"}
    assert {"rare_capsules", "platinum_capsules"} <= exits


def test_no_duplicate_transitions(graph):
    """Two edges may share a destination, but not a destination AND a tap.

    Convergence is normal and expected -- every chapter enters a Cat Base, and
    every saga opens the same chapter carousel. What is not normal is the same
    button recorded twice, which is what a crawler leaves behind.
    """
    seen = set()
    for t in graph.transitions:
        key = (t.src, t.dst, t.action, round(t.x, 2), round(t.y, 2))
        assert key not in seen, f"duplicate edge {key}"
        seen.add(key)


def test_convergent_routes_are_distinct_buttons(graph):
    """Where several edges share a destination, each must be its own control."""
    grouped: dict[tuple[str, str], list] = {}
    for t in graph.transitions:
        grouped.setdefault((t.src, t.dst), []).append(t)
    for (src, dst), edges in grouped.items():
        if len(edges) < 2:
            continue
        # An action is its own control and carries no coordinates, so it is
        # identified by the action rather than by where it would be tapped.
        controls = {t.action or (round(t.x, 2), round(t.y, 2)) for t in edges}
        assert len(controls) == len(edges), f"{src} -> {dst} repeats a control"


def test_find_buttons_keeps_controls_and_drops_scattered_gold():
    """The result screen's three controls survive; the backdrop and title do not."""
    path = Path(__file__).resolve().parent / "fixtures" / "result_viking_cat.png"
    if not path.exists():
        pytest.skip("screenshots are machine-local (*.png is git-ignored)")
    buttons = find_buttons(cv2.imread(str(path)))

    def hit(x, y):
        return any(b.left <= x <= b.left + b.w and b.top <= y <= b.top + b.h for b in buttons)

    assert hit(0.7355, 0.8139), "Ok"
    assert hit(0.223, 0.78), "Use now"
    assert hit(0.295, 0.78), "Exchange"
    assert not any(b.h > 0.5 for b in buttons), "backdrop merged into a button"
    assert not hit(0.13, 0.035), "title lettering taken for a button"


def test_a_similar_title_does_not_pass_for_another():
    """Stage Select is not Storage, though "Stage S" and "Storage" are 83% alike."""
    from bcgacha.uigraph import TITLE_MATCH, title_match

    assert title_match("Storage", "Stage Select") < TITLE_MATCH
    assert title_match("Take Back Earth!", "Back") < TITLE_MATCH
    # A card holds only its own name: the Back card is not a chapter called "... Back ...".
    assert title_match("Back", "The Ancients Arise: Take Back Earth!", within=False) < TITLE_MATCH
    # Real readings still match: exact, OCR-mangled, and with a stray word.
    assert title_match("Cat Base", "Cat Base") >= TITLE_MATCH
    assert title_match("Revival of Bahamut-Cat", "Revival of Bahamut, Cat") >= TITLE_MATCH
    assert title_match("Rare Capsules", "Rare Capsules 3") >= TITLE_MATCH


def test_a_notice_is_read_with_the_extra_words_on_its_line():
    """Legend Stages' notice reads "Stage Clear Reward (13 more)"."""
    import numpy as np

    graph = UIGraph.load(carousels=False)

    class NoticeReads:
        def __call__(self, crop):
            return [([[0, 0], [300, 0], [300, 30], [0, 30]], "Stage Clear Reward (13 more)", 0.9)], None

    graph._ocr = NoticeReads()
    names = [n for _, n in graph.candidates(np.zeros((1170, 2532, 3), np.uint8), title="")]
    assert "stage_reward_notice" in names


def test_stage_select_is_entered_by_start_and_left_by_back(graph):
    """Attack! on the stage map spends energy, so the map knows no other way out."""
    assert [t.label for t in graph.route("cat_base", "stage_select")] == ["Start!!"]
    exits = [t for t in graph.transitions if t.src == "stage_select"]
    assert [(t.label, t.dst) for t in exits] == [("Back", "cat_base")]
