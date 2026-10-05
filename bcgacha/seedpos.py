"""Find the account's seed and position without spending a ticket.

The seed never changes; only the position along it moves, a draw at a time.
Every draw the bot makes is kept as a result screen in captures/, so the
archive already holds the evidence. A run of draws on one event pins the seed
down (a brute-force search over all 2^32 seeds, a few minutes), and the newest
draws, placed along that seed, say where the account is now. Only with no
archive to go on does finding the seed cost draws of its own.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from .data import CAPSULE_RARITIES, RARE, Dataset
from .gacha import Gacha, next_position

# Draws further apart than this belong to different runs.
RUN_GAP = 300
# A run must hold this many readable draws in a row to search the seed from;
# fewer usually leaves several seeds fitting.
SEARCH_ROLLS = 10
# How far along the seed the newest draws are looked for.
PLACE_WINDOW = 600


@dataclass
class Observation:
    """One saved result screen and the cat read off it, if any."""

    file: str
    time: float
    raw: str
    cat_id: int | None
    platinum: bool | None

    def to_json(self, dataset: Dataset | None = None) -> dict:
        """The observation for the live page, the cat named when `dataset` is given."""
        return dict(file=Path(self.file).name, time=dt.datetime.fromtimestamp(self.time).isoformat(timespec="seconds"),
                    raw=self.raw, cat_id=self.cat_id,
                    name=dataset.cat_name(self.cat_id) if dataset and self.cat_id is not None else None,
                    platinum=self.platinum)


@dataclass
class Identified:
    """The seed and position the saved screens point to, and how they were found."""

    seed: int | None = None
    index: int | None = None
    track: int | None = None
    last_cat_id: int | None = None
    source: str = ""
    detail: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)

    @property
    def found(self) -> bool:
        """True when both the seed and the position are known."""
        return self.seed is not None and self.index is not None

    def to_json(self, dataset: Dataset | None = None) -> dict:
        """The finding for the live page and `bcgacha status`."""
        return dict(seed=self.seed, position=f"{self.index}{'AB'[self.track]}" if self.found else None,
                    last_cat=dataset.cat_name(self.last_cat_id) if dataset and self.last_cat_id is not None else None,
                    source=self.source, detail=self.detail, alternatives=self.alternatives,
                    observations=[o.to_json(dataset) for o in self.observations])


def _pool(events) -> set[int]:
    return {c for e in events for r in CAPSULE_RARITIES for c in e.banner.slots.get(r) or []}


def read_captures(captures_dir: Path, ocr, dataset, events_on, log=print, should_stop=None) -> list[Observation]:
    """Every saved result screen, oldest first, with the cat read off it.

    `events_on(date)` gives the events live that day: a draw can only have come
    from one of them, so names are matched against their pools alone.
    """
    from .results import read_result

    files = sorted(Path(captures_dir).glob("roll_*.png"), key=os.path.getmtime)
    out = []
    for f in files:
        if should_stop and should_stop():
            break
        frame = cv2.imread(str(f))
        if frame is None:
            continue
        when = os.path.getmtime(f)
        pool = _pool(events_on(dt.date.fromtimestamp(when)))
        read = read_result(frame, ocr, dataset, pool)
        out.append(Observation(str(f), when, read.raw, read.cat_id, read.platinum))
        log(f"  {f.name}: {read.raw!r} -> "
            f"{dataset.cat_name(read.cat_id) if read.cat_id is not None else 'unsure'}")
    return out


def runs(observations: list[Observation]) -> list[list[Observation]]:
    """Split draws into runs where the gap between them is long."""
    out: list[list[Observation]] = []
    for o in observations:
        if out and o.time - out[-1][-1].time <= RUN_GAP:
            out[-1].append(o)
        else:
            out.append([o])
    return out


def _step(states: dict, obs: Observation | None, gachas: dict, events) -> dict:
    """Advance every candidate (index, track, previous cat) by one draw that
    could have produced `obs` on some live event. obs None: any draw at all."""
    out = {}
    for (index, track, prev), path in states.items():
        for e in events:
            if obs is not None and obs.platinum is not None and obs.platinum != e.platinum:
                continue
            roll = gachas[e.key].cell(index, track)
            if roll.rarity == RARE and prev is not None and roll.cat_id == prev:
                gachas[e.key]._reroll(roll)
            if obs is not None and obs.cat_id is not None and roll.cat_id != obs.cat_id:
                continue
            delta, nxt = next_position(track, roll.reroll_steps)
            key = (index + delta, nxt, roll.cat_id)
            out.setdefault(key, path + [f"{index}{'AB'[track]} {e.label}"])
    return out


def place(dataset, events, seed: int, sequence: list[Observation], lo: int = 1,
          hi: int = PLACE_WINDOW) -> dict:
    """Every end state (index, track, last cat) the draws in `sequence` could
    have left, starting anywhere from row `lo` to `hi` along `seed`."""
    gachas = {e.key: Gacha(e.banner, seed, dataset) for e in events}
    ends: dict = {}
    for index in range(lo, hi):
        for track in (0, 1):
            states = {(index, track, None): []}
            for obs in sequence:
                states = _step(states, obs, gachas, events)
                if not states:
                    break
            for key, path in states.items():
                ends.setdefault(key, path)
    return ends


def search_seed(dataset, events, run: list[Observation], progress=None, log=print) -> int | None:
    """Brute-force the seed from one run of draws on a single event."""
    from .seedfind import search

    for start in range(0, max(1, len(run) - SEARCH_ROLLS + 1)):
        window = run[start:start + SEARCH_ROLLS]
        if len(window) < SEARCH_ROLLS or any(o.cat_id is None or o.platinum for o in window):
            continue
        cats = [o.cat_id for o in window]
        banners = [e for e in events if not e.platinum and set(cats) <= _pool([e])]
        for e in banners:
            log(f"  searching every seed for {len(cats)} draws on {e.label}")
            found = search(e.banner, cats, dataset, progress=progress)
            if len(found) == 1:
                return found[0].seed
            log(f"    {len(found)} seeds fit")
        # A dupe reroll among the first two draws hides the seed from the
        # prefilter: try the window one draw later before giving up.
    return None


def identify(captures_dir, dataset, events_on, ocr, log=print, progress=None,
             should_stop=None) -> Identified:
    """The seed and the position now, from the archive of result screens."""
    out = Identified()
    obs = read_captures(captures_dir, ocr, dataset, events_on, log=log, should_stop=should_stop)
    out.observations = obs
    groups = runs(obs)
    if not groups:
        out.detail.append("no saved result screens: the seed needs fresh draws")
        return out
    out.detail.append(f"{len(obs)} saved draws in {len(groups)} runs")
    seed_run = max(groups, key=lambda g: sum(o.cat_id is not None and not o.platinum for o in g))
    when = dt.date.fromtimestamp(seed_run[0].time)
    seed = search_seed(dataset, events_on(when), seed_run, progress=progress, log=log)
    if seed is None:
        out.detail.append("no run pinned the seed down: fresh draws on one event are needed")
        return out
    out.seed, out.source = seed, "captures"
    out.detail.append(f"seed {seed} from the run of {len(seed_run)} draws at "
                      f"{dt.datetime.fromtimestamp(seed_run[0].time):%H:%M}")
    latest = groups[-1]
    ends = place(dataset, events_on(dt.date.fromtimestamp(latest[0].time)), seed, latest)
    if not ends:
        out.detail.append("the newest draws fit nowhere along that seed")
        return out
    positions = sorted({(i, t) for i, t, _ in ends})
    if len(positions) > 1:
        out.alternatives = [f"{i}{'AB'[t]}" for i, t in positions]
        out.detail.append(f"the newest draws fit {len(positions)} places: {out.alternatives}")
        return out
    (index, track, last), path = next(iter(ends.items()))
    out.index, out.track, out.last_cat_id = index, track, last
    out.detail.append(f"newest run of {len(latest)} draws ends at {index}{'AB'[track]}: "
                      + " | ".join(path))
    return out
