"""Which events there are: what the capsule screen's tabs show, not the
computer's calendar."""

import datetime as dt

from bcgacha import events as live
from bcgacha.data import load


def test_a_tab_can_be_an_event_the_computer_thinks_has_not_started():
    """A phone whose clock is a day on shows tomorrow's events already."""
    ds = load()
    day = dt.date(2026, 9, 24)
    starting = {b.key for b in ds.banners.values() if b.start_on == day + dt.timedelta(days=1) and b.uber < 10000}
    assert starting, "test needs an event starting the next day"
    assert starting <= {b.key for b in live.candidates(ds, day)}
    assert not starting & {e.key for e in live.live_events(ds, day)}


def test_the_events_planned_over_are_the_tabs_last_read(tmp_path, monkeypatch):
    ds = load()
    monkeypatch.setattr(live, "SCREEN_FILE", tmp_path / "capsule_screen.json")
    assert [e.key for e in live.current(ds)] == [e.key for e in live.live_events(ds)], "no look yet: the schedule"
    shown = ["2026-09-25_523", "2026-09-25_772"]
    live.save_screen({k: True for k in shown}, shown=shown)
    events = live.current(ds)
    assert [e.key for e in events][:2] == shown
    assert events[-1].platinum, "Platinum is always there, last"
