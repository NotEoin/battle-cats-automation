"""A save's sagas and chapters, layered onto the fixed map.

The fixture is what one real save's carousels scanned to: three story sagas of
three chapters, Legend Stages behind a reward notice, and the Catclaw Dojo's
own base screen.
"""

from pathlib import Path

from bcgacha import carousel
from bcgacha.uigraph import UIGraph

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "carousels.json"


def _graph():
    return UIGraph.load(carousels=FIXTURE)


def test_every_saga_and_chapter_becomes_a_screen():
    graph = _graph()
    for name in ("saga:empire_of_cats", "saga:catclaw_dojo",
                 "chapter:into_the_future:3", "chapter:cats_of_the_cosmos:1"):
        assert name in graph.screens, name
    chapter = graph.screens["chapter:into_the_future:2"]
    assert chapter.title == "Alien Intrigue: A Maiden's Revenge"
    assert chapter.parent == "base_select"
    assert chapter.title_box == carousel.CARD_NAME_BOX


def test_a_chapter_is_reached_one_drag_at_a_time():
    """No fixed tap reaches a card: the walk drags there and reads each card."""
    path = _graph().route("title", "chapter:into_the_future:3")
    assert path[-1].dst == "chapter:into_the_future:3"
    drags = [t for t in path if t.action and t.action.startswith("drag:")]
    assert drags, "expected drags between neighbouring cards"
    assert all(t.action in ("drag:left", "drag:right", "seek:start") for t in path if t.action)


def test_sagas_without_chapters_open_what_the_scan_found():
    graph = _graph()
    legend = {t.dst for t in graph.transitions if t.src == "saga:legend_stages"}
    assert {"cat_base", "stage_reward_notice"} <= legend
    dojo = graph.screens["catclaw_dojo"]
    assert dojo.title == "Catclaw Dojo"
    assert any(t.src == "catclaw_dojo" and t.dst == "saga:catclaw_dojo" for t in graph.transitions)


def test_the_base_map_stands_alone():
    graph = UIGraph.load(carousels=False)
    assert not any(n.startswith(("saga:", "chapter:")) for n in graph.screens)


def test_a_half_scanned_save_is_still_a_map():
    """The debug view draws the catalogue as the scan fills it in."""
    graph = UIGraph.load(carousels=False)
    carousel.extend(graph, {"sagas": [
        {"name": "Empire of Cats"},
        {"name": "Into The Future", "enters": "chapters",
         "chapters": [{"number": 1, "name": "Time Enough For Cats"}]},
    ]})
    assert "saga:empire_of_cats" in graph.screens
    assert "chapter:into_the_future:1" in graph.screens
    graph.route("saga_select", "chapter:into_the_future:1")


def test_card_names_are_matched_whole_not_inside_longer_titles():
    """The Back card reads "Back"; that must not pass for "Take Back Earth!"."""
    import numpy as np

    graph = _graph()
    frame = np.zeros((1170, 2532, 3), np.uint8)
    here = graph.screens["chapter:into_the_future:3"]
    assert carousel.same("The Ancients Arise: Take Back Earth!", here.title)
    assert not carousel.same("Back", here.title)
    # With nothing readable on screen no refined card may be claimed.
    assert not any(n.startswith(("saga:", "chapter:")) for _, n in graph.candidates(frame, title=""))


def test_ocr_pieces_are_read_in_line_order():
    """A two-line card name comes back line by line, not in detection order."""
    graph = UIGraph.load(carousels=False)

    class FakeOCR:
        def __call__(self, crop):
            # (box, text, confidence), deliberately out of reading order
            return [
                ([[40, 60], [120, 60], [120, 90], [40, 90]], "Rising", 0.9),
                ([[10, 5], [60, 5], [60, 35], [10, 35]], "The", 0.9),
                ([[70, 5], [200, 5], [200, 35], [70, 35]], "Battle Cats", 0.9),
            ], None

    graph._ocr = FakeOCR()
    import numpy as np

    frame = np.zeros((1170, 2532, 3), np.uint8)
    assert graph.read_title(frame, carousel.CARD_NAME_BOX) == "The Battle Cats Rising"
