"""The gacha events running now, and how to put each one on screen.

The dataset's schedule says which events are live today; the capsule screen
shows one at a time, named by the subtitle under its artwork. Each live event
becomes a screen of the UI map -- `event:<pool id>`, a more specific capsule
screen, as a carousel card is of its carousel -- so selecting an event is one
Navigator.goto like any other move, and costs nothing when it is already the
one on screen. Platinum is the one exception: it has a screen of its own,
platinum_capsules, with its own title.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .data import LEGEND, UBER, Banner, Dataset
from .paths import STATE

if TYPE_CHECKING:
    import numpy as np

    from .uigraph import UIGraph

# The dataset names an event by its newest unit ("Mighty Morta-Loncha
# added!"); the game's tab art names the series. The series that matter here,
# by the pool's series id.
SERIES = {3: "Galaxy Gals", 24: "Iron Legion", 34: "Fate/stay night [HF]"}

PLATINUM_SCREEN = "platinum_capsules"
# Rates are out of 10000, and the Platinum Capsules give an Uber every time.
PLATINUM_UBER = 10000
# The subtitle under the banner artwork on the capsule screen, as a fraction
# of the landscape frame measured on a 2532x1170 iPhone.
SUBTITLE_BOX = (0.16, 0.545, 0.84, 0.610)
# A normal event is only one that started within this many days. Older runs of
# a pool still listed as live are superseded re-listings, and legend-ticket
# capsules hide among them.
RECENT_DAYS = 45
# What the last look at the capsule screen found: which events it shows. The
# schedule lists some the game does not.
SCREEN_FILE = STATE / "capsule_screen.json"
# A look older than this, in hours, no longer says what the screen shows.
SCREEN_FRESH = 12
SECONDS_PER_HOUR = 3600
# The phone's clock need not be the computer's -- a time zone moved on puts an
# event on screen a day early, or keeps one a day late -- so a tab is matched
# against every event scheduled this many days either side of today.
CLOCK_SLACK = 3


@dataclass(frozen=True)
class Event:
    """One live gacha event, as the capsule screen offers it."""

    key: str                    # the dataset's banner key, e.g. "2026-09-21_979"
    gacha_id: int
    name: str                   # the subtitle the capsule screen shows
    label: str                  # what a person calls it: "Iron Legion"
    start: str
    end: str
    platinum: bool
    legends: tuple[int, ...]
    ubers: tuple[int, ...]
    banner: Banner = field(compare=False, repr=False)

    @property
    def screen(self) -> str:
        """The UI-map screen that is this event, selected."""
        return PLATINUM_SCREEN if self.platinum else f"event:{self.gacha_id}"

    def to_json(self, dataset: Dataset | None = None, owned: set[int] | None = None) -> dict:
        """The event as plain JSON, its cats named and marked owned when given."""
        def cats(ids):
            return [dict(id=c, name=dataset.cat_name(c) if dataset else str(c),
                         owned=None if owned is None else c in owned) for c in ids]

        return dict(key=self.key, gacha_id=self.gacha_id, name=self.name, label=self.label,
                    start=self.start, end=self.end, platinum=self.platinum, screen=self.screen,
                    rates=dict(rare=self.banner.rare, supa=self.banner.supa,
                               uber=self.banner.uber, legend=self.banner.legend),
                    legends=cats(self.legends),
                    ubers=cats(self.ubers) if not self.platinum else len(self.ubers))


def _event(banner: Banner, platinum: bool) -> Event:
    label = "Platinum" if platinum else SERIES.get(banner.series_id) or banner.name.split("!")[0][:40]
    return Event(
        key=banner.key, gacha_id=banner.gacha_id, name=banner.name, label=label,
        start=banner.start_on.isoformat(), end=banner.end_on.isoformat(), platinum=platinum,
        legends=tuple(banner.slots.get(LEGEND) or ()) if banner.legend > 0 else (),
        ubers=tuple(banner.slots.get(UBER) or ()), banner=banner,
    )


def live_events(dataset: Dataset, when: dt.date | None = None) -> list[Event]:
    """Every event selectable on the capsule screen today, Platinum last.

    The schedule re-lists a pool under several keys as a run is extended; they
    are the same tab on screen, so only the latest of each is kept. The Platinum
    pool grows as ubers are released and every past snapshot of it still looks
    live, so only the newest counts -- an old one predicts different cats.
    """
    when = when or dt.date.today()
    live = dataset.live_banners(when)
    unique: dict[tuple, Banner] = {}
    for b in sorted(live, key=lambda b: b.start_on):
        if b.uber >= PLATINUM_UBER or b.start_on < when - dt.timedelta(days=RECENT_DAYS):
            continue
        unique[(b.gacha_id, b.rare, b.supa, b.uber, b.guaranteed, b.step_up)] = b
    events = [_event(b, False) for b in unique.values()]
    platinum = [b for b in live if b.uber >= PLATINUM_UBER]
    if platinum:
        newest = max(platinum, key=lambda b: (b.start_on, len(b.slots.get(UBER) or [])))
        events.append(_event(newest, True))
    return events


def candidates(dataset: Dataset, when: dt.date | None = None, slack: int = CLOCK_SLACK) -> list[Banner]:
    """Every normal banner a tab on the capsule screen could be, whatever the
    phone's clock says: scheduled within `slack` days of `when`. A pool listed
    twice with the same rates is one tab; of two listings, the one running on
    `when` is kept, else the later."""
    when = when or dt.date.today()
    lo, hi = when - dt.timedelta(days=slack), when + dt.timedelta(days=slack)
    near = [b for b in dataset.banners.values()
            if b.uber < PLATINUM_UBER and b.start_on <= hi and b.end_on >= lo
            and b.start_on >= when - dt.timedelta(days=RECENT_DAYS)]
    unique: dict[tuple, Banner] = {}
    for b in sorted(near, key=lambda b: (b.is_live(when), b.start_on)):
        unique[(b.gacha_id, b.rare, b.supa, b.uber, b.guaranteed, b.step_up)] = b
    return list(unique.values())


def platinum_event(dataset: Dataset, when: dt.date | None = None) -> Event | None:
    """The live Platinum Capsules event, if there is one."""
    return next((e for e in live_events(dataset, when) if e.platinum), None)


def current(dataset: Dataset) -> list[Event]:
    """The events to plan over: those the capsule screen's tabs showed at the
    last fresh look -- which may lie outside their scheduled dates -- else the
    schedule's own list for today. Platinum last."""
    raw = _screen()
    shown = raw.get("shown") if raw else None
    if not shown:
        return live_events(dataset)
    events = [_event(dataset.banners[k], False) for k in shown if k in dataset.banners]
    platinum = platinum_event(dataset)
    return events + ([platinum] if platinum else [])


def by_key(events: list[Event], key: str) -> Event | None:
    """The event with the dataset key `key`, if among `events`."""
    return next((e for e in events if e.key == key), None)


def find(events: list[Event], query: str) -> Event | None:
    """The event a person means: its key, pool id, label or a word of its name."""
    q = str(query).strip().lower()
    for test in (lambda e: e.key.lower() == q, lambda e: str(e.gacha_id) == q,
                 lambda e: e.label.lower() == q, lambda e: q in e.label.lower(),
                 lambda e: q in e.name.lower()):
        hits = [e for e in events if test(e)]
        if len(hits) == 1:
            return hits[0]
    return None


def extend(graph: UIGraph, events: list[Event]) -> None:
    """Add each live event to the map as a screen, and the moves between them.

    Moving onto an event is a routine (tap its tab, read the subtitle back),
    so every edge carries the action "event:<key>". The fixed banner edges the
    map shipped with are dropped: they named events that come and go.
    """
    from .uigraph import Screen, Transition

    graph.events = events
    graph.transitions = [t for t in graph.transitions
                         if not (t.action or "").startswith(("banner:", "event:"))]
    normal = [e for e in events if not e.platinum]
    capsule = graph.screens.get("rare_capsules")
    for e in normal:
        graph.screens[e.screen] = Screen(
            name=e.screen, title=e.name, title_box=SUBTITLE_BOX, parent="rare_capsules",
            marks=capsule.marks if capsule else (), absent_marks=capsule.absent_marks if capsule else (),
            note=f"{e.label}: {e.start} to {e.end}, key {e.key}",
        )
    sources = ["rare_capsules", PLATINUM_SCREEN] + [e.screen for e in normal]
    for e in events:
        for src in sources:
            if src != e.screen and src in graph.screens:
                graph.transitions.append(Transition(
                    src, e.screen, label=f"select {e.label}", settle=1.5, action=f"event:{e.key}"))


def selected(frame: np.ndarray, graph: UIGraph, events: list[Event]) -> Event | None:
    """The event the capsule screen in `frame` shows, if it is one."""
    here = graph.identify(frame)
    return next((e for e in events if e.screen == here), None)


def _screen() -> dict | None:
    try:
        raw = json.loads(SCREEN_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return raw if time.time() - raw.get("checked_at", 0) <= SCREEN_FRESH * SECONDS_PER_HOUR else None


def save_screen(seen: dict, shown: list[str] | None = None, tabs: list | None = None) -> None:
    """Keep what a look at the capsule screen found: {event key: shown}, the
    normal events its tabs showed in order, and what each tab read."""
    SCREEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCREEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(checked_at=time.time(), seen=seen, shown=shown, tabs=tabs or []),
                              indent=1), encoding="utf-8")
    os.replace(tmp, SCREEN_FILE)


def last_screen() -> tuple[dict, str | None]:
    """{event key: shown on the phone} from the last look, if fresh, and when."""
    raw = _screen()
    if raw is None:
        return {}, None
    return raw.get("seen", {}), time.strftime("%H:%M", time.localtime(raw["checked_at"]))


def last_tabs() -> list:
    """What each tab read at the last fresh look: [{key, label, read}, ...]."""
    raw = _screen()
    return raw.get("tabs", []) if raw else []


def shown(events: list[Event]) -> list[Event]:
    """The events, less those the last fresh look found the game not showing."""
    seen, _ = last_screen()
    return [e for e in events if seen.get(e.key) is not False]
