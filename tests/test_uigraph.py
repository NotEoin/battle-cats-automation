"""Structural invariants for the UI map.

These are the properties that make position-free navigation work. Each one
corresponds to a failure the roll loop actually hit.
"""

from bcgacha.uigraph import UIGraph


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
    graph = _graph()
    seen = set()
    for t in graph.transitions:
        if t.src == "base_select":
            continue          # three chapters legitimately land in the same place
        key = (t.src, t.dst, t.action)
        assert key not in seen, f"duplicate edge {key}"
        seen.add(key)
