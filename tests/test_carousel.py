"""A save's sagas and chapters, layered onto the fixed map.

The fixture is what one real save's carousels scanned to: three story sagas of
three chapters, Legend Stages behind a reward notice, and the Catclaw Dojo's
own base screen.
"""

from pathlib import Path

import numpy as np

from bcgacha import carousel
from bcgacha.uigraph import UIGraph

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "carousels.json"


def _graph(tmp_path, carousels=FIXTURE):
    """The map with the fixture save's carousels, learning into a scratch directory."""
    graph = UIGraph.load(carousels=carousels)
    graph.profile_root = tmp_path
    return graph


def test_every_saga_and_chapter_becomes_a_screen(tmp_path):
    graph = _graph(tmp_path)
    for name in ("saga:empire_of_cats", "saga:catclaw_dojo",
                 "chapter:into_the_future:3", "chapter:cats_of_the_cosmos:1"):
        assert name in graph.screens, name
    chapter = graph.screens["chapter:into_the_future:2"]
    assert chapter.title == "Alien Intrigue: A Maiden's Revenge"
    assert chapter.parent == "base_select"
    assert chapter.title_box == carousel.CARD_NAME_BOX


def test_a_chapter_is_reached_one_drag_at_a_time(tmp_path):
    """No fixed tap reaches a card: the walk drags there and reads each card."""
    path = _graph(tmp_path).route("title", "chapter:into_the_future:3")
    assert path[-1].dst == "chapter:into_the_future:3"
    drags = [t for t in path if t.action and t.action.startswith("drag:")]
    assert drags, "expected drags between neighbouring cards"
    assert all(t.action in ("drag:left", "drag:right", "seek:start") for t in path if t.action)


def test_sagas_without_chapters_open_what_the_scan_found(tmp_path):
    graph = _graph(tmp_path)
    legend = {t.dst for t in graph.transitions if t.src == "saga:legend_stages"}
    assert {"cat_base", "stage_reward_notice"} <= legend
    dojo = graph.screens["catclaw_dojo"]
    assert dojo.title == "Catclaw Dojo"
    assert any(t.src == "catclaw_dojo" and t.dst == "saga:catclaw_dojo" for t in graph.transitions)


def test_the_base_map_stands_alone(tmp_path):
    graph = _graph(tmp_path, carousels=False)
    assert not any(n.startswith(("saga:", "chapter:")) for n in graph.screens)


def test_a_half_scanned_save_is_still_a_map(tmp_path):
    """The debug view draws the catalogue as the scan fills it in."""
    graph = _graph(tmp_path, carousels=False)
    carousel.extend(graph, {"sagas": [
        {"name": "Empire of Cats"},
        {"name": "Into The Future", "enters": "chapters",
         "chapters": [{"number": 1, "name": "Time Enough For Cats"}]},
    ]})
    assert "saga:empire_of_cats" in graph.screens
    assert "chapter:into_the_future:1" in graph.screens
    graph.route("saga_select", "chapter:into_the_future:1")


def test_card_names_are_matched_whole_not_inside_longer_titles(tmp_path):
    """The Back card reads "Back"; that must not pass for "Take Back Earth!"."""
    graph = _graph(tmp_path)
    graph._ocr = lambda image: (None, 0.0)      # nothing readable anywhere
    frame = np.zeros((1170, 2532, 3), np.uint8)
    here = graph.screens["chapter:into_the_future:3"]
    assert carousel.same("The Ancients Arise: Take Back Earth!", here.title)
    assert not carousel.same("Back", here.title)
    # With nothing readable on screen no refined card may be claimed.
    assert not any(n.startswith(("saga:", "chapter:")) for _, n in graph.candidates(frame, title=""))


def test_ocr_pieces_are_read_in_line_order(tmp_path):
    """A two-line card name comes back line by line, not in detection order."""
    graph = _graph(tmp_path, carousels=False)

    class FakeOCR:
        def __call__(self, crop):
            # (box, text, confidence), deliberately out of reading order
            return [
                ([[40, 60], [120, 60], [120, 90], [40, 90]], "Rising", 0.9),
                ([[10, 5], [60, 5], [60, 35], [10, 35]], "The", 0.9),
                ([[70, 5], [200, 5], [200, 35], [70, 35]], "Battle Cats", 0.9),
            ], None

    graph._ocr = FakeOCR()
    frame = np.zeros((1170, 2532, 3), np.uint8)
    assert graph.read_title(frame, carousel.CARD_NAME_BOX) == "The Battle Cats Rising"


def test_the_back_card_does_not_claim_a_chapter_with_back_in_its_name(monkeypatch, tmp_path):
    """Into The Future's Chapter 3 is "The Ancients Arise: Take Back Earth!"."""
    from bcgacha import perception

    # The X present, so only the card's name can tell the screens apart.
    monkeypatch.setattr(perception, "find_discs", lambda frame: [((0.87, 0.31, 0.95, 0.40), (0.91, 0.36))])
    monkeypatch.setattr(perception, "close_glyph_score", lambda frame, box: 1.0)
    graph = _graph(tmp_path)

    class CardReads:
        def __call__(self, crop):
            return [([[0, 0], [300, 0], [300, 30], [0, 30]],
                     "The Ancients Arise: Take Back Earth!", 0.9)], None

    graph._ocr = CardReads()
    names = [n for _, n in graph.candidates(np.zeros((1170, 2532, 3), np.uint8), title="")]
    assert "chapter:into_the_future:3" in names
    assert "chapter_back_card" not in names


def test_a_card_read_with_its_lines_swapped_is_the_same_card():
    """OCR can return a two-line name's lines in either order."""
    assert carousel.same("Alien Intrigue A Maiden's Revenge", "Intrigue Alien A Maiden's Revenge")
    assert not carousel.same("Alien Intrigue A Maiden's Revenge", "Time Enough For Cats")


def test_every_chapter_and_every_saga_opening_on_a_cat_base_has_a_background():
    """Legend Stages opens straight onto a Cat Base; the Catclaw Dojo does not."""
    screens = carousel.base_screens(carousel.load_catalogue(FIXTURE))
    chapters = {f"chapter:{saga}:{n}" for saga in ("empire_of_cats", "into_the_future",
                                                   "cats_of_the_cosmos") for n in (1, 2, 3)}
    assert set(screens) == chapters | {"saga:legend_stages"}
    assert len(screens) == len(set(screens))


def test_backgrounds_the_device_has_learned_are_not_missing(tmp_path):
    """Each device learns its own backgrounds; another phone still misses them all."""
    graph = _graph(tmp_path)
    catalogue = carousel.load_catalogue(FIXTURE)
    frame = np.zeros((1170, 2532, 3), np.uint8)
    profile = graph.profile_for(frame)
    profile.learn_base("chapter:empire_of_cats:1", [0.1] * 8)
    profile.learn_base("saga:legend_stages", [0.2] * 8)

    every = carousel.base_screens(catalogue)
    missing = carousel.missing_bases(graph, catalogue, frame)
    assert set(missing) == set(every) - {"chapter:empire_of_cats:1", "saga:legend_stages"}
    other_phone = np.zeros((617, 1334, 3), np.uint8)
    assert set(carousel.missing_bases(graph, catalogue, other_phone)) == set(every)
