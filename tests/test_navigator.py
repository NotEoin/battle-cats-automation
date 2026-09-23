"""Whether a tap did anything, judged from the screen alone.

A tap that changed nothing is written off so the walk tries another way; one
that changed the screen without leaving it (Back on Upgrade stepping up from a
unit list) answered, and must not be written off.
"""

import cv2
import numpy as np

from bcgacha.uigraph import Navigator, UIGraph


class StillHuman:
    """Taps exactly where told and waits no time, noting each wait asked for."""

    def __init__(self):
        self.waits = []

    def sleep(self, mean, spread=0.35):
        self.waits.append(mean)
        return 0.0

    def jitter_point(self, x, y, radius=420):
        return x, y


class FakeSession:
    """Shows `before` until tapped; after a tap, each screenshot shows the next of `after`."""

    def __init__(self, before, *after):
        self.before, self.after, self.taps, self.looks = before, after, [], 0

    def screenshot(self):
        if not self.taps:
            return self.before
        self.looks += 1
        return self.after[min(self.looks, len(self.after)) - 1]

    def tap(self, x, y):
        self.taps.append((x, y))


def _unit_list():
    frame = np.full((296, 640, 3), 70, np.uint8)
    for i in range(4):
        cv2.rectangle(frame, (60 + 140 * i, 80), (170 + 140 * i, 220), (40, 160, 220), -1)
    return frame


def _overview():
    frame = _unit_list()
    frame[:, :400] = (230, 230, 230)
    return frame


def _navigator(tmp_path, session, here="upgrade"):
    graph = UIGraph(profile_root=tmp_path)
    graph.identify = lambda frame, title=None: here        # the same screen whatever it shows
    return Navigator(session, graph, humaniser=StillHuman())


def test_a_tap_that_changed_the_screen_without_leaving_it_is_not_unmoved(tmp_path):
    """Back on Upgrade steps from a unit list up to the overview: still Upgrade, but it answered."""
    before = _unit_list()
    session = FakeSession(before, _overview())
    nav = _navigator(tmp_path, session)
    nav._tap(0.089, 0.872, 1.0)

    assert session.taps
    assert not nav._unmoved("upgrade", before)


def test_a_tap_that_left_the_same_frame_twice_is_unmoved(tmp_path):
    """Nothing changed on the first look nor, after a wait, on the second."""
    before = _unit_list()
    session = FakeSession(before, before.copy())
    nav = _navigator(tmp_path, session)
    nav._tap(0.5, 0.5, 1.0)

    assert nav._unmoved("upgrade", before, wait=1.5)
    assert session.looks == 2, "given a second look before being blamed"
    assert 1.5 in nav.human.waits


def test_a_screen_slow_to_answer_is_not_unmoved(tmp_path):
    """Unchanged on the first look, changed on the second: the tap did work."""
    before = _unit_list()
    session = FakeSession(before, before.copy(), _overview())
    nav = _navigator(tmp_path, session)
    nav._tap(0.5, 0.5, 1.0)

    assert not nav._unmoved("upgrade", before)


# -- watching a tap land -------------------------------------------------------------

class Named:
    """A graph whose screens are named by the frame's grey level."""

    def __init__(self, tmp_path, names):
        self.names = names
        self.graph = UIGraph(profile_root=tmp_path)
        self.graph.recognise = lambda frame, **kw: type("R", (), dict(
            here=names.get(int(frame[0, 0, 0])), candidates=[]))()


def _grey(level):
    return np.full((296, 640, 3), level, np.uint8)


def test_a_tap_lands_once_two_still_frames_name_another_screen(tmp_path):
    """A fading frame that names somewhere new is not arrival; the steady one after it is."""
    named = Named(tmp_path, {70: "cat_base", 40: "legend_stage_select", 120: "rare_capsules"})
    session = FakeSession(_grey(70), _grey(40), _grey(120), _grey(120), _grey(120))
    nav = Navigator(session, named.graph, humaniser=StillHuman())
    nav._press(0.5, 0.5)

    landed, frame = nav._settle("cat_base", 1.0)
    assert landed == "rare_capsules"
    assert session.looks == 3, "the fading frame, then the new screen twice"


def test_a_tap_that_never_leaves_is_reported_after_the_watch(tmp_path, monkeypatch):
    import bcgacha.uigraph as ui

    monkeypatch.setattr(ui, "MIN_WATCH", 0.05)
    monkeypatch.setattr(ui, "WATCH", 0.0)
    named = Named(tmp_path, {70: "cat_base"})
    session = FakeSession(_grey(70), _grey(70))
    nav = Navigator(session, named.graph, humaniser=StillHuman())
    nav._press(0.5, 0.5)

    landed, frame = nav._settle("cat_base", 1.0)
    assert landed is None and frame is not None
