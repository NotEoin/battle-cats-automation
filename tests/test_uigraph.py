"""Structural invariants for the UI map.

These are the properties that make position-free navigation work. Each one
corresponds to a failure the roll loop actually hit.
"""

from pathlib import Path

import cv2
import pytest

from bcgacha.uigraph import UIGraph, find_buttons


def _graph():
    return UIGraph.load()


def test_every_screen_can_be_identified():
    """A screen with neither a title nor anchors can never be recognised."""
    graph = _graph()
    blind = [
        s.name for s in graph.screens.values()
        if not s.title and not s.anchors and not s.forbidden
    ]
    assert not blind, f"unidentifiable: {blind}"


def test_every_screen_reaches_the_cat_base():
    """Whatever the bot wakes up on, it must be able to get home."""
    graph = _graph()
    stranded = []
    for name, screen in graph.screens.items():
        if screen.forbidden or name == "cat_base":
            continue
        try:
            graph.route(name, "cat_base")
        except Exception:
            stranded.append(name)
    assert not stranded, f"cannot reach cat_base from: {stranded}"


def test_both_capsule_machines_are_routable():
    """Platinum has no fixed tab, so it is reached by a routine, not a tap."""
    graph = _graph()
    for destination in ("rare_capsules", "platinum_capsules"):
        path = graph.route("cat_base", destination)
        assert path, destination
    hop = graph.route("rare_capsules", "platinum_capsules")[-1]
    assert hop.action, "platinum must be reached by an action, not a memorised tab"


def test_no_route_passes_through_settings():
    graph = _graph()
    assert graph.screens["settings"].forbidden
    for name in graph.screens:
        if graph.screens[name].forbidden:
            continue
        try:
            path = graph.route(name, "cat_base")
        except Exception:
            continue
        assert all(t.dst != "settings" for t in path), name


def test_only_reactive_screens_have_nothing_leading_to_them():
    """Reveals and popups appear on their own; everything else is navigable."""
    graph = _graph()
    incoming = {t.dst for t in graph.transitions}
    orphans = [
        n for n, s in graph.screens.items()
        if n not in incoming and n != "opening" and not s.reactive and not s.forbidden
    ]
    assert not orphans, f"unreachable and not marked reactive: {orphans}"


def test_every_screen_has_a_way_out():
    graph = _graph()
    outgoing = {t.src for t in graph.transitions}
    stuck = [
        n for n, s in graph.screens.items() if n not in outgoing and not s.forbidden
    ]
    assert not stuck, f"no exit recorded: {stuck}"


def test_the_post_draw_overlay_can_exit_to_either_machine():
    """The reveal looks the same on both machines, so it must not assume one."""
    graph = _graph()
    exits = {t.dst for t in graph.transitions if t.src == "sent_to_storage"}
    assert {"rare_capsules", "platinum_capsules"} <= exits


def test_no_duplicate_transitions():
    """Two edges may share a destination, but not a destination AND a tap.

    Convergence is normal and expected -- every chapter enters a Cat Base, and
    every saga opens the same chapter carousel. What is not normal is the same
    button recorded twice, which is what a crawler leaves behind.
    """
    graph = _graph()
    seen = set()
    for t in graph.transitions:
        key = (t.src, t.dst, t.action, round(t.x, 2), round(t.y, 2))
        assert key not in seen, f"duplicate edge {key}"
        seen.add(key)


def test_convergent_routes_are_distinct_buttons():
    """Where several edges share a destination, each must be its own control."""
    graph = _graph()
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
