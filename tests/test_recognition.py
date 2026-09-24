"""How a frame is named: which evidence counts, and what is learned from it.

A screen's evidence -- its title, the marks it must or must not show, the
shapes on it -- is each True, False or unknown. Unknown leaves a screen possible
but unverified, which sends recognition to a full look; only False rules it
out. The rules are tested on small maps built here, so they hold whatever the
shipped map says, with OCR stubbed and a gold X put on screen by patching the
shape detector.
"""

import numpy as np
import pytest

from bcgacha import perception
from bcgacha.perception import Control, Percept, Text
from bcgacha.profile import Profile
from bcgacha.uigraph import Screen, Transition, UIGraph

SIZE = (640, 296)
X_BOX, X_CENTRE = (0.87, 0.31, 0.95, 0.40), (0.91, 0.355)
TITLE_READ = (0.02, 0.01, 0.15, 0.06)       # where a screen prints its name


class StubOCR:
    """Reads the same words off any image it is given, as RapidOCR would.

    Each read is (text, (x0, y0, x1, y1)) in fractions of that image.
    """

    def __init__(self, *reads):
        self.reads = reads

    def __call__(self, image):
        h, w = image.shape[:2]
        result = [([[x0 * w, y0 * h], [x1 * w, y0 * h], [x1 * w, y1 * h], [x0 * w, y1 * h]],
                   text, 0.95) for text, (x0, y0, x1, y1) in self.reads]
        return result or None, 0.01


def _graph(tmp_path, screens, transitions=(), ocr=None):
    graph = UIGraph(screens={s.name: s for s in screens}, transitions=list(transitions),
                    profile_root=tmp_path)
    graph._ocr = ocr or StubOCR()
    return graph


def _plain():
    return np.zeros((SIZE[1], SIZE[0], 3), np.uint8)


def _textured(seed):
    """A frame no template cut from another seed will match."""
    return np.random.default_rng(seed).integers(0, 256, (SIZE[1], SIZE[0], 3), dtype=np.uint8)


def _centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


@pytest.fixture
def gold_x(monkeypatch):
    """A gold disc with a white X on screen, however the frame is looked at."""
    monkeypatch.setattr(perception, "find_discs", lambda frame: [(X_BOX, X_CENTRE)])
    monkeypatch.setattr(perception, "close_glyph_score", lambda frame, box: 1.0)


# -- a shape alone names nothing -----------------------------------------------------

def test_an_unmapped_panel_with_a_gold_x_is_unknown_on_the_real_map(tmp_path, gold_x):
    """Many panels carry an X: with no mapped screen's text read, it is not the saga carousel."""
    graph = UIGraph.load(carousels=False)
    graph.profile_root = tmp_path
    graph._ocr = StubOCR(("Daily login bonus!", (0.35, 0.45, 0.65, 0.52)))
    frame = _plain()

    assert graph.recognise(frame).here is None
    profile = graph.profile_for(frame)
    assert profile.controls("saga_select") == {}
    assert profile.screen_names() == [] and profile.title_box is None


def test_a_screen_that_fits_by_its_shape_alone_is_never_named(tmp_path, gold_x):
    """A screen whose only evidence seen is an X stays unnamed until some text of it is read."""
    graph = _graph(tmp_path, [Screen("saga_select", shapes=("close",), absent_marks=("Chapter",)),
                              Screen("menu", marks=("Enemy Guide",), shapes=("close",))])
    frame = _plain()

    rec = graph.recognise(frame)
    assert rec.here is None
    assert "saga_select" in [c.name for c in rec.candidates], "it fits, but by shape alone"
    assert graph.profile_for(frame).screen_names() == [], "nothing learned from it"

    graph._ocr = StubOCR(("Enemy Guide", (0.30, 0.30, 0.50, 0.36)))
    assert graph.recognise(frame).here == "menu"


# -- a mark not where it was learned -----------------------------------------------------

SETTINGS_MAP = [
    Screen("title", marks=("Play",)),
    Screen("settings", marks=("Settings",), shapes=("close",), forbidden=True),
    Screen("saga_select", marks=("Show Code",), absent_marks=("Chapter",), shapes=("close",)),
]
TO_SETTINGS = Transition("title", "settings", 0.5, 0.712, "Settings", target="Settings")
BUTTON = (0.42, 0.68, 0.58, 0.745)          # Settings, a button on the title screen
HEADING = (0.42, 0.08, 0.58, 0.14)          # Settings, the heading of its own panel


def _learned_on(graph, screen, box, frame):
    settings = Control("Settings", "button", box, _centre(box))
    graph.profile_for(frame).learn(screen, frame, [settings], wanted=graph.wanted(screen))


def test_a_mark_learned_on_another_screen_and_missing_leaves_it_unverified(tmp_path, gold_x):
    """"Settings" learned as the title screen's button is not proof against the Settings panel."""
    graph = _graph(tmp_path, SETTINGS_MAP, [TO_SETTINGS])
    _learned_on(graph, "title", BUTTON, _textured(1))

    found = {c.name: c for c in graph._evaluate(_textured(2), None, None)}
    assert "settings" in found, "ruled out by a mark that was never learned on it"
    assert not found["settings"].verified


def test_a_mark_learned_on_the_screen_itself_and_missing_rules_it_out(tmp_path, gold_x):
    """Where a screen has shown its own mark before, the mark must be there again."""
    graph = _graph(tmp_path, SETTINGS_MAP, [TO_SETTINGS])
    seen = _textured(1)
    _learned_on(graph, "settings", HEADING, seen)

    assert "settings" in [c.name for c in graph._evaluate(seen, None, None)]
    assert "settings" not in [c.name for c in graph._evaluate(_textured(2), None, None)]


def test_the_settings_panel_is_named_by_its_heading(tmp_path, gold_x):
    """With the title screen's Settings button learned, the Settings panel is still settings."""
    graph = _graph(tmp_path, SETTINGS_MAP, [TO_SETTINGS], StubOCR(("Settings", HEADING)))
    _learned_on(graph, "title", BUTTON, _textured(1))

    assert graph.recognise(_textured(2)).here == "settings"


# -- the top-left title --------------------------------------------------------------------

def test_a_missed_read_of_the_learned_title_box_leaves_the_screen_to_a_full_look(tmp_path):
    """One empty OCR read through the title box is not proof of another screen."""
    graph = _graph(tmp_path, [Screen("storage", title="Storage")],
                   ocr=StubOCR(("Storage", TITLE_READ)))
    frame = _plain()
    graph.profile_for(frame).learn_title(TITLE_READ)
    graph.read_title = lambda frame, box=None, largest=False: ""       # the flake

    found = {c.name: c for c in graph._evaluate(frame, None, None)}
    assert "storage" in found and not found["storage"].verified
    rec = graph.recognise(frame)
    assert rec.here == "storage"
    assert rec.percept is not None, "named by a full look"

    # A full look that reads another title does rule it out.
    upgrade = Text("Upgrade", TITLE_READ, 0.9)
    other = Percept(*SIZE, texts=[upgrade], title=upgrade)
    assert "storage" not in [c.name for c in graph._evaluate(frame, other, None)]


TITLES_MAP = [Screen("cat_guide", title="Cat Guide"), Screen("title", marks=("Play", "Mailbox"))]


def test_the_title_box_is_placed_by_a_title_that_named_its_screen(tmp_path):
    """"Cat Guide" read top-left places the box over it, and the next look reads only that box."""
    graph = _graph(tmp_path, TITLES_MAP, ocr=StubOCR(("Cat Guide", TITLE_READ)))
    frame = _plain()

    assert graph.recognise(frame).here == "cat_guide"
    box = graph.profile_for(frame).title_box
    assert box is not None
    assert box[0] <= TITLE_READ[0] and box[1] <= TITLE_READ[1]
    assert box[2] >= TITLE_READ[2] and box[3] >= TITLE_READ[3]

    again = graph.recognise(frame)
    assert again.here == "cat_guide" and again.percept is None


def test_a_screen_without_a_title_places_no_title_box(tmp_path):
    """The title screen's logo is its largest top-left text, but it is no screen's name."""
    graph = _graph(tmp_path, TITLES_MAP, ocr=StubOCR(
        ("THE BATTLE CATS", (0.03, 0.02, 0.38, 0.11)),
        ("Play", (0.46, 0.55, 0.54, 0.60)),
        ("Mailbox", (0.80, 0.86, 0.92, 0.91)),
    ))
    frame = _plain()

    rec = graph.recognise(frame)
    assert rec.here == "title"
    assert rec.percept.title.text == "THE BATTLE CATS", "the logo sits where a title would"
    assert graph.profile_for(frame).title_box is None


# -- titles remembered as they look ---------------------------------------------------

class CountingOCR(StubOCR):
    def __init__(self, *reads):
        super().__init__(*reads)
        self.calls = 0

    def __call__(self, image):
        self.calls += 1
        return super().__call__(image)


CAPSULE_MAP = [Screen("rare_capsules", title="Rare Capsules"),
               Screen("cat_capsules", title="Cat Capsules")]


def test_a_title_that_named_its_screen_is_read_next_time_without_ocr(tmp_path):
    """Once OCR has named a screen by its title, the same title is known by its picture."""
    ocr = CountingOCR(("Cat Guide", TITLE_READ))
    graph = _graph(tmp_path, TITLES_MAP, ocr=ocr)
    frame = _textured(1)

    assert graph.recognise(frame).here == "cat_guide"          # a full look, then the title box
    assert graph.recognise(frame).here == "cat_guide"          # the box, read by OCR, remembered
    calls = ocr.calls
    again = graph.recognise(frame)
    assert again.here == "cat_guide" and again.percept is None
    assert ocr.calls == calls, "no OCR once the title is remembered"


def test_a_remembered_title_is_not_seen_on_a_screen_fading_out(tmp_path):
    """A darkened frame matches the title's shape, but not its brightness: it is not there yet."""
    profile = Profile(*SIZE, root=tmp_path)
    frame = _textured(2)
    box = (0.02, 0.01, 0.30, 0.08)
    assert profile.learn_text(frame, box, "Rare Capsules")
    assert profile.known_text(frame, box) == "Rare Capsules"
    faded = (frame * 0.6).astype(np.uint8)
    assert profile.known_text(faded, box) is None
    assert profile.known_text(_textured(3), box) is None, "other text in the box"


def test_remembering_a_title_seen_again_rewrites_nothing(tmp_path):
    profile = Profile(*SIZE, root=tmp_path)
    frame = _textured(4)
    box = (0.02, 0.01, 0.30, 0.08)
    assert profile.learn_text(frame, box, "Storage")
    assert not profile.learn_text(frame, box, "Storage")


def test_a_title_one_word_off_another_is_that_other_screen(tmp_path):
    """"Cat Capsules" reads 80 against "Rare Capsules": it names the Cat Capsules screen alone."""
    graph = _graph(tmp_path, CAPSULE_MAP, ocr=StubOCR(("Cat Capsules", TITLE_READ)))
    frame = _textured(5)
    found = [c.name for c in graph._evaluate(frame, None, "Cat Capsules")]
    assert found == ["cat_capsules"]


def test_a_remembered_title_that_stops_matching_is_kept_until_it_is_old(tmp_path, monkeypatch):
    """A pulsing outline must not rewrite the picture on every look; a stale one gives way."""
    import os
    import time

    from bcgacha import profile as profile_mod

    profile = Profile(*SIZE, root=tmp_path)
    box = (0.02, 0.01, 0.30, 0.08)
    assert profile.learn_text(_textured(10), box, "Ok")
    assert not profile.learn_text(_textured(11), box, "Ok"), "rewritten while fresh"
    path = next((tmp_path / profile.key / "texts").rglob("ok.png"))
    old = time.time() - profile_mod.TEXT_KEEP - 5
    os.utime(path, (old, old))
    assert profile.learn_text(_textured(11), box, "Ok"), "a stale picture gives way"
    assert profile.known_text(_textured(11), box) == "Ok"


def test_a_title_remembered_dimmed_under_a_dialog_gives_way_at_once(tmp_path):
    """Learned while a dialog dimmed the screen, it would never match the lit title again."""
    profile = Profile(*SIZE, root=tmp_path)
    box = (0.02, 0.01, 0.30, 0.08)
    lit = _textured(12)
    dimmed = (lit // 3).astype(lit.dtype)
    assert profile.learn_text(dimmed, box, "Stage Select")
    assert profile.known_text(lit, box) is None
    assert profile.learn_text(lit, box, "Stage Select"), "a dimmed picture kept while fresh"
    assert profile.known_text(lit, box) == "Stage Select"
