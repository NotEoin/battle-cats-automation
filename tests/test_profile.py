"""What a device profile learns, and what it leaves alone.

Learning runs on every full look, so it must settle: a screen seen again as it
was rewrites nothing, and only the controls the map names are kept. Frames here
are seeded noise, so each control's template is unlike any other patch of the
frame, as a real control is.
"""

import os
import threading

import numpy as np
import pytest

from bcgacha.perception import Control
from bcgacha.profile import MOVE_TOLERANCE, Profile

SIZE = (640, 296)
START = (0.15, 0.24, 0.25, 0.31)
EQUIP = (0.15, 0.49, 0.25, 0.56)
LABEL = (0.40, 0.60, 0.50, 0.66)
BACK = (0.05, 0.82, 0.13, 0.95)
CLOSE = (0.85, 0.30, 0.93, 0.47)


def _frame(seed=0):
    """A textured frame: no patch of it looks like any other."""
    w, h = SIZE
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def _control(label, box, kind="button"):
    return Control(label, kind, box, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))


def _centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _files(root):
    """Every file under `root`, with its bytes and when it was last written."""
    return {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def _backdate(root):
    """Stamp every file under `root` as written long ago, so any rewrite shows."""
    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, ns=(0, 0))
    return _files(root)


# -- the title box -------------------------------------------------------------

def test_the_title_box_grows_to_cover_every_title_read(tmp_path):
    """A longer title widens the box to the union of both, and no further than a little padding."""
    profile = Profile(*SIZE, root=tmp_path)
    short, long = (0.02, 0.01, 0.12, 0.05), (0.02, 0.012, 0.22, 0.052)
    assert profile.learn_title(short)
    assert profile.learn_title(long)

    box = profile.title_box
    for seen in (short, long):
        assert box[0] <= seen[0] and box[1] <= seen[1] and box[2] >= seen[2] and box[3] >= seen[3]
    assert box[2] <= long[2] + 0.02 and box[3] <= long[3] + 0.02
    assert Profile(*SIZE, root=tmp_path).title_box == box, "kept for the next run"


def test_a_title_inside_the_box_rewrites_nothing(tmp_path):
    """A shorter title seen again changes neither the box nor profile.json."""
    profile = Profile(*SIZE, root=tmp_path)
    profile.learn_title((0.02, 0.01, 0.22, 0.05))
    box, before = profile.title_box, _backdate(tmp_path)

    assert not profile.learn_title((0.03, 0.015, 0.15, 0.045))
    assert not profile.learn_title((0.02, 0.01, 0.22, 0.05))
    assert profile.title_box == box
    assert _files(tmp_path) == before


# -- controls --------------------------------------------------------------------

def test_a_control_is_kept_under_the_name_the_map_uses(tmp_path):
    """OCR's "Start!" is learned as the map's "Start!!", and found by that name."""
    frame = _frame()
    profile = Profile(*SIZE, root=tmp_path)
    profile.learn("cat_base", frame, [_control("Start!", START)], wanted={"Start!!"})

    assert set(profile.controls("cat_base")) == {"Start!!"}
    assert profile.locate(frame, "cat_base", "Start!!") == pytest.approx(_centre(START), abs=0.005)


def test_timers_and_counters_are_not_learned(tmp_path):
    """Only what the map names is kept; "0809h6" and "+66" change by the minute."""
    profile = Profile(*SIZE, root=tmp_path)
    controls = [_control("Start!!", START), _control("Equip", EQUIP),
                _control("0809h6", (0.70, 0.05, 0.80, 0.10), "tag"),
                _control("+66", (0.85, 0.05, 0.95, 0.10), "tag")]
    profile.learn("cat_base", _frame(), controls, wanted={"Start!!", "Equip", "Menu", "@back"})

    assert set(profile.controls("cat_base")) == {"Start!!", "Equip"}


def test_back_and_close_are_learned_by_shape_and_back_the_label_by_its_text(tmp_path):
    """"@back" takes the arrow, never a label reading "Back"; "Back" never takes the arrow."""
    profile = Profile(*SIZE, root=tmp_path)
    controls = [_control("back", BACK, "back"), _control("close", CLOSE, "close"),
                _control("Back", LABEL, "tag")]

    profile.learn("upgrade", _frame(), controls, wanted={"@back", "@close"})
    learned = profile.controls("upgrade")
    assert set(learned) == {"@back", "@close"}
    assert learned["@back"]["kind"] == "back" and learned["@back"]["box"] == pytest.approx(BACK)
    assert learned["@close"]["kind"] == "close"

    profile.learn("base_select", _frame(), controls, wanted={"Back"})
    learned = profile.controls("base_select")
    assert set(learned) == {"Back"}
    assert learned["Back"]["kind"] == "tag" and learned["Back"]["box"] == pytest.approx(LABEL)


def test_each_name_takes_one_control_and_each_control_one_name(tmp_path):
    """Two names that read alike share out two controls, and never share one."""
    a, b = START, EQUIP
    profile = Profile(*SIZE, root=tmp_path)
    names = {"Rare Capsule", "Rare Capsules"}

    profile.learn("one", _frame(), [_control("Rare Capsule", a)], wanted=names)
    assert set(profile.controls("one")) == {"Rare Capsule"}

    profile.learn("two", _frame(), [_control("Rare Capsules", b), _control("Rare Capsule", a)],
                  wanted=names)
    learned = profile.controls("two")
    assert learned["Rare Capsule"]["box"] == pytest.approx(a)
    assert learned["Rare Capsules"]["box"] == pytest.approx(b)


def test_learning_the_same_frame_twice_changes_nothing(tmp_path):
    """A second look, however OCR spells it this time, rewrites no file."""
    frame = _frame()
    wanted = {"Start!!", "Equip", "@back", "@close"}
    controls = [_control("Start!!", START), _control("Equip", EQUIP),
                _control("back", BACK, "back"), _control("close", CLOSE, "close")]
    profile = Profile(*SIZE, root=tmp_path)
    assert profile.learn("cat_base", frame, controls, wanted=wanted) == 4
    before = _backdate(tmp_path)

    assert profile.learn("cat_base", frame, controls, wanted=wanted) == 0
    respelled = [_control("Start!", START), _control("Equip.", EQUIP)] + controls[2:]
    assert profile.learn("cat_base", frame, respelled, wanted=wanted) == 0
    assert Profile(*SIZE, root=tmp_path).learn("cat_base", frame, controls, wanted=wanted) == 0
    assert _files(tmp_path) == before


def test_a_control_still_where_it_was_keeps_its_template(tmp_path):
    """A glow that widens the perceived box is not a move: the template still finds it."""
    frame = _frame()
    profile = Profile(*SIZE, root=tmp_path)
    profile.learn("cat_base", frame, [_control("Start!!", START)], wanted={"Start!!"})
    before = _backdate(tmp_path)

    grow = 1.5 * MOVE_TOLERANCE
    glowing = (START[0] - grow, START[1] - grow, START[2] + grow, START[3] + grow)
    assert profile.learn("cat_base", frame, [_control("Start!!", glowing)], wanted={"Start!!"}) == 0
    assert _files(tmp_path) == before
    assert profile.locate(frame, "cat_base", "Start!!") == pytest.approx(_centre(START), abs=0.005)


def test_a_control_that_moved_is_learned_where_it_is_now(tmp_path):
    """Once its template no longer finds it, the control is cut again at its new place."""
    frame = _frame()
    profile = Profile(*SIZE, root=tmp_path)
    profile.learn("cat_base", frame, [_control("Start!!", START)], wanted={"Start!!"})

    moved = np.roll(frame, int(0.3 * SIZE[0]), axis=1)
    there = (START[0] + 0.3, START[1], START[2] + 0.3, START[3])
    assert profile.locate(moved, "cat_base", "Start!!") is None
    assert profile.learn("cat_base", moved, [_control("Start!!", there)], wanted={"Start!!"}) == 1
    assert profile.locate(moved, "cat_base", "Start!!") == pytest.approx(_centre(there), abs=0.005)


def test_the_back_arrow_and_a_back_label_keep_separate_templates(tmp_path):
    """"@back" and "Back" on one screen are two files, and each still finds its own control."""
    frame = _frame()
    profile = Profile(*SIZE, root=tmp_path)
    controls = [_control("back", BACK, "back"), _control("Back", LABEL, "tag")]
    assert profile.learn("upgrade", frame, controls, wanted={"@back", "Back"}) == 2

    learned = profile.controls("upgrade")
    assert learned["@back"]["template"] != learned["Back"]["template"]
    fresh = Profile(*SIZE, root=tmp_path)       # templates read back from disk
    assert fresh.locate(frame, "upgrade", "@back") == pytest.approx(_centre(BACK), abs=0.005)
    assert fresh.locate(frame, "upgrade", "Back") == pytest.approx(_centre(LABEL), abs=0.005)


def test_a_shape_is_never_looked_up_through_a_label_that_reads_like_it(tmp_path):
    """With only "Back" and "Close" labels learned, "@back" and "@close" are not there."""
    frame = _frame()
    profile = Profile(*SIZE, root=tmp_path)
    labels = [_control("Back", LABEL, "tag"), _control("Close", START, "tag")]
    profile.learn("upgrade", frame, labels, wanted={"Back", "Close"})

    assert profile.key_for("upgrade", "@back") is None
    assert profile.key_for("upgrade", "@close") is None
    assert profile.locate(frame, "upgrade", "@back") is None
    assert profile.locate(frame, "upgrade", "@close") is None
    assert profile.key_for("upgrade", "back") == "Back", "a label is still matched loosely"


def test_controls_and_bases_hand_out_copies(tmp_path):
    """Clearing or adding to what controls() or bases() returned leaves the profile as it was."""
    profile = Profile(*SIZE, root=tmp_path)
    profile.learn("cat_base", _frame(), [_control("Start!!", START)], wanted={"Start!!"})
    profile.learn_base("chapter:a:1", [0.5] * 8)

    controls = profile.controls("cat_base")
    controls.clear()
    controls["Menu"] = {"box": [0, 0, 1, 1]}
    doors = profile.bases()
    doors.clear()
    doors["chapter:a:2"] = [0.1] * 8

    assert set(profile.controls("cat_base")) == {"Start!!"}
    assert profile.bases() == {"chapter:a:1": [0.5] * 8}


def test_changing_an_entry_handed_out_leaves_the_profile_as_it_was(tmp_path):
    """Editing a handed-out control's box or door signature does not reach the profile."""
    profile = Profile(*SIZE, root=tmp_path)
    profile.learn("cat_base", _frame(), [_control("Start!!", START)], wanted={"Start!!"})
    profile.learn_base("chapter:a:1", [0.5] * 8)

    profile.controls("cat_base")["Start!!"]["box"][0] = 0.9
    profile.bases()["chapter:a:1"][0] = 0.9

    assert profile.controls("cat_base")["Start!!"]["box"][0] == pytest.approx(START[0])
    assert profile.bases()["chapter:a:1"][0] == 0.5


def test_reading_while_another_thread_learns(tmp_path):
    """The debug view reads the profile while the navigator learns into it: no torn dicts."""
    frame = _frame()
    profile = Profile(*SIZE, root=tmp_path)
    errors, done = [], threading.Event()

    def learn():
        try:
            for i in range(50):
                profile.learn(f"screen_{i}", frame, [_control(f"Label {i}", START),
                                                     _control("back", BACK, "back")])
        except Exception as e:          # noqa: BLE001 -- reported below
            errors.append(e)
        finally:
            done.set()

    learner = threading.Thread(target=learn)
    learner.start()
    reads = 0
    try:
        while not done.is_set() or reads == 0:
            for name in profile.screen_names():
                for key, entry in profile.controls(name).items():
                    assert entry["box"], key
            reads += 1
    except RuntimeError as e:
        errors.append(e)
    learner.join()

    assert not errors, errors
    assert len(profile.screen_names()) == 50


# -- pictures found anywhere in a region -----------------------------------------

def test_a_remembered_tab_is_found_where_the_strip_has_moved_it(tmp_path):
    """An event's tab, learned at one place, is found again shifted along the strip."""
    profile = Profile(*SIZE, root=tmp_path)
    frame = _frame(7)
    tab = (0.30, 0.10, 0.40, 0.16)
    assert profile.learn_image("tab 2026-09-21_979", frame, tab)

    shifted = _frame(8)
    w, h = SIZE
    x0, y0, x1, y1 = (int(tab[0] * w), int(tab[1] * h), int(tab[2] * w), int(tab[3] * h))
    dx = int(0.2 * w)
    shifted[y0:y1, x0 + dx:x1 + dx] = frame[y0:y1, x0:x1]
    spot = profile.find_image("tab 2026-09-21_979", shifted, (0.0, 0.05, 1.0, 0.2))
    assert spot is not None
    assert abs(spot[0] - ((tab[0] + tab[2]) / 2 + 0.2)) < 0.01
    assert profile.find_image("tab 2026-09-21_979", _frame(9), (0.0, 0.05, 1.0, 0.2)) is None
    assert profile.find_image("tab never seen", shifted, (0.0, 0.05, 1.0, 0.2)) is None
