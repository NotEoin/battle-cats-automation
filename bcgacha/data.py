"""Load godfat's Battle Cats dataset into the shapes the roll engine needs.

The YAML carries three top-level maps:

  cats    id -> {name: [forms], rarity: int, ...}
  gacha   id -> {cats: [cat ids], name, series_id, ...}
  events  key -> {id, start_on, end_on, rare, supa, uber, guaranteed, step_up}

`events` is the schedule: each entry points at a `gacha` pool by id and carries
the rarity weights that were live for that run of the banner.  The same pool can
appear many times with different rates, which is why rates belong to the event
and not to the pool.
"""

from __future__ import annotations

import datetime as dt
import functools
import pathlib
import pickle
from dataclasses import dataclass, field

import yaml

from .paths import DATA as DATA_DIR

# godfat's dataset, one YAML per game language, rebuilt as events are announced.
SOURCE = "https://gitlab.com/godfat/battle-cats-rolls/-/raw/master/build/bc-{lang}.yaml"
# Seconds to wait for it: the file is several megabytes.
FETCH_TIMEOUT = 120

# Rarity codes as the dataset stores them.
BASIC, EX, RARE, SUPER_RARE, UBER, LEGEND = range(6)
# The rarities a rare capsule draws.
CAPSULE_RARITIES = (RARE, SUPER_RARE, UBER, LEGEND)

RARITY_NAMES = {
    BASIC: "Basic",
    EX: "EX",
    RARE: "Rare",
    SUPER_RARE: "Super Rare",
    UBER: "Uber Rare",
    LEGEND: "Legend Rare",
}

# Rarity weights are out of this.
BASE = 10000

# Seed positions a guaranteed banner consumes before its Uber lands: an
# 11-draw, and a step-up's run of draws.
GUARANTEED_DRAW = 11
STEP_UP_DRAWS = 15

# The YAML is downloaded, so it is only ever read with a safe loader; the C one
# when PyYAML was built with it, as it is several times quicker.
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@dataclass(frozen=True)
class Banner:
    """One scheduled run of a gacha pool, with the rates that were live for it."""

    key: str
    gacha_id: int
    name: str
    start_on: dt.date
    end_on: dt.date
    rare: int
    supa: int
    uber: int
    guaranteed: bool = False
    step_up: bool = False
    # The pool's series: stable across re-runs, and what the game's tab art
    # names ("Iron Legion") where the event name only names the newest unit.
    series_id: int | None = None
    # cat ids by rarity, in the order the banner lists them -- slot order matters
    slots: dict[int, list[int]] = field(default_factory=dict, compare=False)

    @property
    def legend(self) -> int:
        """The Legend Rare weight: whatever the other rarities leave of `BASE`."""
        return BASE - self.rare - self.supa - self.uber

    @property
    def guaranteed_rolls(self) -> int:
        """Seed positions consumed before the guaranteed uber lands, or 0."""
        if self.guaranteed:
            return GUARANTEED_DRAW
        if self.step_up:
            return STEP_UP_DRAWS
        return 0

    def is_live(self, when: dt.date) -> bool:
        """True when the banner runs on `when`, both end days included."""
        return self.start_on <= when <= self.end_on


@dataclass
class Dataset:
    """Every cat and every scheduled banner, as the roll engine reads them."""

    cats: dict[int, dict]
    banners: dict[str, Banner]

    def cat_name(self, cat_id: int) -> str:
        """The cat's first-form name; "N/A" for no cat, "#id" for one unknown."""
        if cat_id < 0:
            return "N/A"
        entry = self.cats.get(cat_id)
        if not entry:
            return f"#{cat_id}"
        names = entry.get("name") or []
        return names[0] if names else f"#{cat_id}"

    def rarity_of(self, cat_id: int) -> int:
        """The cat's rarity code; `BASIC` for a cat the dataset does not know."""
        return self.cats.get(cat_id, {}).get("rarity", BASIC)

    def live_banners(self, when: dt.date | None = None) -> list[Banner]:
        """Banners running on `when` (default today), in key order."""
        when = when or dt.date.today()
        return sorted(
            (b for b in self.banners.values() if b.is_live(when)),
            key=lambda b: b.key,
        )

    def find_banner(self, key: str) -> Banner:
        """The banner with this key, or the one key suffix or name part it fits.

        Raises KeyError when nothing fits or more than one does.
        """
        if key in self.banners:
            return self.banners[key]
        matches = [b for b in self.banners.values() if b.key.endswith(key) or key in b.name]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise KeyError(f"no banner matching {key!r}")
        raise KeyError(f"{key!r} is ambiguous: {[m.key for m in matches[:5]]}")


def _build(raw: dict) -> Dataset:
    cats = raw["cats"]
    pools = raw["gacha"]
    banners: dict[str, Banner] = {}

    for key, ev in raw["events"].items():
        pool = pools.get(ev["id"])
        if pool is None:
            continue
        slots: dict[int, list[int]] = {r: [] for r in range(6)}
        for cat_id in pool["cats"]:
            slots[cats.get(cat_id, {}).get("rarity", BASIC)].append(cat_id)
        banners[key] = Banner(
            key=key,
            gacha_id=ev["id"],
            name=ev.get("name") or pool.get("name") or key,
            start_on=_as_date(ev["start_on"]),
            end_on=_as_date(ev["end_on"]),
            rare=ev.get("rare", 0),
            supa=ev.get("supa", 0),
            uber=ev.get("uber", 0),
            guaranteed=bool(ev.get("guaranteed")),
            step_up=bool(ev.get("step_up")),
            series_id=pool.get("series_id"),
            slots=slots,
        )
    return Dataset(cats=cats, banners=banners)


def _as_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


# Versioned: a pickle of an older Banner would silently lack new fields.
CACHE_VERSION = "v2"


@functools.lru_cache(maxsize=4)
def load(lang: str = "en") -> Dataset:
    """Load the dataset, caching a pickle because parsing 2 MB of YAML is slow."""
    source = DATA_DIR / f"bc-{lang}.yaml"
    if not source.exists():
        raise FileNotFoundError(
            f"{source} missing -- run: bcgacha tools update"
            if lang == "en" else f"{source} missing -- run: python scripts/fetch_data.py --lang {lang}"
        )
    # The pickle is one bcgacha wrote itself, into its own folder, from the
    # YAML beside it: never one downloaded.
    cache = DATA_DIR / f"bc-{lang}.{CACHE_VERSION}.pickle"
    if cache.exists() and cache.stat().st_mtime >= source.stat().st_mtime:
        with open(cache, "rb") as fh:
            return pickle.load(fh)

    with open(source, encoding="utf-8") as fh:
        raw = yaml.load(fh, Loader=SAFE_LOADER)
    ds = _build(raw)
    with open(cache, "wb") as fh:
        pickle.dump(ds, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return ds


def fetch(lang: str = "en") -> pathlib.Path:
    """Download the newest dataset -- the event schedule with it -- in place of
    the one kept. Written aside and swapped in, so a dropped connection leaves
    the old file whole; load() rebuilds its cache from the new one. An
    unchanged download leaves the file and its cache alone."""
    import os

    import httpx

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"bc-{lang}.yaml"
    r = httpx.get(SOURCE.format(lang=lang), follow_redirects=True, timeout=FETCH_TIMEOUT)
    r.raise_for_status()
    if out.exists() and out.read_bytes() == r.content:
        return out
    yaml.load(r.text, Loader=SAFE_LOADER)["events"]   # whole, or raises
    tmp = out.with_suffix(".yaml.part")
    tmp.write_bytes(r.content)
    os.replace(tmp, out)
    load.cache_clear()
    return out
