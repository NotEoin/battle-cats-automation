#!/usr/bin/env python3
"""Cut the downloaded dataset and tier list down to the copies the tests use.

The tests must pass on a fresh clone with no network, so they read a frozen
copy under `tests/fixtures/data/` rather than whatever `bcgacha tools update`
last downloaded. The copy keeps what the roll engine reads: every cat's name
and rarity, and the events from `SINCE` on with the pools they draw from.
Descriptions and stats are dropped, which is most of the file.

The tier list keeps only the cat id -> tier maps, not the site's nicknames.

Run it, with bcgacha installed, after `bcgacha tools update` when a test
needs a newer event:

    python scripts/make_test_data.py
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml

from bcgacha.data import SAFE_LOADER
from bcgacha.paths import DATA

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "data"
# The oldest event any test names starts in July 2026.
SINCE = dt.date(2026, 6, 1)


def slim_dataset(raw: dict) -> dict:
    """The dataset with only what `bcgacha.data` reads, and recent events."""
    events = {k: e for k, e in raw["events"].items() if e["start_on"] >= SINCE}
    pools = {e["id"] for e in events.values()}
    return {
        "cats": {i: {"name": c["name"], "rarity": c["rarity"]} for i, c in raw["cats"].items()},
        "gacha": {i: g for i, g in raw["gacha"].items() if i in pools},
        "events": events,
    }


def main() -> None:
    """Write both fixtures from the copies in the bcgacha data folder."""
    OUT.mkdir(parents=True, exist_ok=True)
    raw = yaml.load((DATA / "bc-en.yaml").read_text(encoding="utf-8"), Loader=SAFE_LOADER)
    (OUT / "bc-en.yaml").write_text(
        yaml.dump(slim_dataset(raw), Dumper=getattr(yaml, "CSafeDumper", yaml.SafeDumper),
                  allow_unicode=False, width=1000),
        encoding="utf-8")
    tiers = json.loads((DATA / "tiers.json").read_text(encoding="utf-8"))
    (OUT / "tiers.json").write_text(json.dumps({
        "entries": [], "by_cat": tiers["by_cat"], "potential": tiers["potential"], "unmatched": [],
    }, indent=1) + "\n", encoding="utf-8")
    for f in sorted(OUT.iterdir()):
        print(f"{f.relative_to(ROOT)} ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
