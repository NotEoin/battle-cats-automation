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
import time
from dataclasses import dataclass, field
from pathlib import Path

from .data import LEGEND, UBER, Banner, Dataset

# The dataset names an event by its newest unit ("Mighty Morta-Loncha
# added!"); the game's tab art names the series. The series that matter here,
# by the pool's series id.
SERIES = {3: "Galaxy Gals", 24: "Iron Legion", 34: "Fate/stay night [HF]"}

PLATINUM_SCREEN = "platinum_capsules"
# The subtitle under the banner artwork on the capsule screen.
SUBTITLE_BOX = (0.16, 0.545, 0.84, 0.610)
# A normal event is only one that started within this many days. Older runs of
# a pool still listed as live are superseded re-listings, and legend-ticket
# capsules hide among them.
RECENT_DAYS = 45
# What the last look at the capsule screen found: which events it shows. The
# schedule lists some the game does not.
SCREEN_FILE = Path(__file__).resolve().parent.parent / "state" / "capsule_screen.json"
# A look older than this, in hours, no longer says what the screen shows.
SCREEN_FRESH = 12


@dataclass(frozen=True)
class Event:
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
        if b.uber >= 10000 or b.start_on < when - dt.timedelta(days=RECENT_DAYS):
            continue
        unique[(b.gacha_id, b.rare, b.supa, b.uber, b.guaranteed, b.step_up)] = b
    events = [_event(b, False) for b in unique.values()]
    platinum = [b for b in live if b.uber >= 10000]
    if platinum:
        newest = max(platinum, key=lambda b: (b.start_on, len(b.slots.get(UBER) or [])))
        events.append(_event(newest, True))
    return events


def by_key(events: list[Event], key: str) -> Event | None:
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


def extend(graph, events: list[Event]) -> None:
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
    platinum = next((e for e in events if e.platinum), None)
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


def selected(frame, graph, events: list[Event]) -> Event | None:
    """The event the capsule screen in `frame` shows, if it is one."""
    here = graph.identify(frame)
    return next((e for e in events if e.screen == here), None)


def save_screen(seen: dict) -> None:
    """Keep what a look at the capsule screen found: {event key: shown}."""
    SCREEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCREEN_FILE.write_text(json.dumps(dict(checked_at=time.time(), seen=seen), indent=1))


def last_screen() -> tuple[dict, str | None]:
    """{event key: shown on the phone} from the last look, if fresh, and when."""
    try:
        raw = json.loads(SCREEN_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}, None
    if time.time() - raw.get("checked_at", 0) > SCREEN_FRESH * 3600:
        return {}, None
    return raw.get("seen", {}), time.strftime("%H:%M", time.localtime(raw["checked_at"]))


def shown(events: list[Event]) -> list[Event]:
    """The events, less those the last fresh look found the game not showing."""
    seen, _ = last_screen()
    return [e for e in events if seen.get(e.key) is not False]
