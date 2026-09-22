"""Community tier rankings for Uber and Legend cats.

battlecatstierlist.com publishes its ranking as images, but it also carries a
"Text Version" block underneath them, which is what this parses. Entries look
like ``S+: Cat Clan Heroes (UF), Baby Cats (UF), Thundia (UF), ...``.

Two wrinkles:

  * ``(UF)`` and ``(UT)`` mark Ultra Form and Ultra Talent placements. Those are
    investment states of a cat you already own, not separate units, and they can
    sit tiers apart -- Cat Clan Heroes is D- at base and S+ in Ultra Form. The
    base placement is what matters when deciding whether to chase a cat, so both
    are kept and the base one is preferred.
  * The list uses community nicknames. "Dark Lunos" is the game's "Lone Moon
    Lunos" / "Lunos the Eclipsed". Matching is therefore fuzzy, against every
    evolution form's name, with an override table for the ones that do not
    resolve on their own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

from .data import LEGEND, UBER, Dataset

TIER_URL = "https://www.battlecatstierlist.com/current-tier-list"
TIER_FILE = Path(__file__).resolve().parent.parent / "data" / "tiers.json"
OVERRIDE_FILE = Path(__file__).resolve().parent.parent / "data" / "tier_aliases.json"

# Best to worst. Index doubles as the score, so lower is better.
TIER_ORDER = [
    "SSS", "SS", "S+", "S", "S-",
    "A+", "A", "A-",
    "B+", "B", "B-",
    "C+", "C", "C-",
    "D+", "D", "D-",
    "E+", "E", "E-",
    "F+", "F", "F-",
]
TIER_RANK = {name: i for i, name in enumerate(TIER_ORDER)}
UNRANKED = len(TIER_ORDER)

LINE_RE = re.compile(r"^(SSS|SS|[SA-F][+-]?)\s*:\s*(.+)$")


@dataclass
class TierEntry:
    nickname: str
    tier: str
    ultra_form: bool = False
    ultra_talent: bool = False

    @property
    def rank(self) -> int:
        return TIER_RANK.get(self.tier, UNRANKED)


@dataclass
class TierList:
    entries: list[TierEntry] = field(default_factory=list)
    # cat id -> best (lowest) rank at base investment
    by_cat: dict[int, str] = field(default_factory=dict)
    # cat id -> best rank counting Ultra Form / Talent placements
    potential: dict[int, str] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)

    def rank_of(self, cat_id: int, use_potential: bool = False) -> int:
        table = self.potential if use_potential else self.by_cat
        return TIER_RANK.get(table.get(cat_id, ""), UNRANKED)

    def tier_of(self, cat_id: int, use_potential: bool = False) -> str:
        table = self.potential if use_potential else self.by_cat
        return table.get(cat_id, "?")

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or TIER_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "entries": [vars(e) for e in self.entries],
            "by_cat": {str(k): v for k, v in self.by_cat.items()},
            "potential": {str(k): v for k, v in self.potential.items()},
            "unmatched": self.unmatched,
        }, indent=1))
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "TierList":
        path = Path(path or TIER_FILE)
        raw = json.loads(path.read_text())
        return cls(
            entries=[TierEntry(**e) for e in raw["entries"]],
            by_cat={int(k): v for k, v in raw["by_cat"].items()},
            potential={int(k): v for k, v in raw["potential"].items()},
            unmatched=raw.get("unmatched", []),
        )


def parse(text: str) -> list[TierEntry]:
    """Pull entries out of the page's Text Version block."""
    out: list[TierEntry] = []
    start = text.find("Text Version")
    if start >= 0:
        text = text[start:]
    for line in text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        tier, rest = m.group(1), m.group(2)
        if tier not in TIER_RANK:
            continue
        for chunk in rest.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            uf = "(UF)" in chunk
            ut = "(UT)" in chunk
            nickname = re.sub(r"\((UF|UT)\)", "", chunk).strip()
            if nickname:
                out.append(TierEntry(nickname, tier, uf, ut))
    return out


def _candidate_names(dataset: Dataset) -> dict[str, int]:
    """Every form name of every Uber/Legend, mapped back to its cat id."""
    names: dict[str, int] = {}
    for cat_id, entry in dataset.cats.items():
        if entry.get("rarity") not in (UBER, LEGEND):
            continue
        for form in entry.get("name") or []:
            key = (form or "").strip()
            if key:
                names.setdefault(key, cat_id)
    return names


def _load_overrides() -> dict[str, str]:
    if OVERRIDE_FILE.exists():
        return json.loads(OVERRIDE_FILE.read_text())
    return {}


def match(entries: list[TierEntry], dataset: Dataset, cutoff: int = 82) -> TierList:
    """Resolve nicknames to cat ids, keeping the best tier seen for each."""
    names = _candidate_names(dataset)
    overrides = _load_overrides()
    choices = list(names)
    result = TierList(entries=entries)

    for entry in entries:
        cat_id = None
        if entry.nickname in overrides:
            target = overrides[entry.nickname]
            cat_id = names.get(target)
        if cat_id is None:
            hit = process.extractOne(
                entry.nickname, choices, scorer=fuzz.token_set_ratio, score_cutoff=cutoff
            )
            if hit:
                cat_id = names[hit[0]]
        if cat_id is None:
            result.unmatched.append(f"{entry.nickname} [{entry.tier}]")
            continue

        # Potential counts every placement; the base table ignores UF/UT ones.
        prev = result.potential.get(cat_id)
        if prev is None or entry.rank < TIER_RANK.get(prev, UNRANKED):
            result.potential[cat_id] = entry.tier
        if not (entry.ultra_form or entry.ultra_talent):
            prev = result.by_cat.get(cat_id)
            if prev is None or entry.rank < TIER_RANK.get(prev, UNRANKED):
                result.by_cat[cat_id] = entry.tier

    # A cat only ever listed in Ultra Form still deserves a base figure.
    for cat_id, tier in result.potential.items():
        result.by_cat.setdefault(cat_id, tier)
    return result


def fetch_text(url: str = TIER_URL) -> str:
    import httpx
    from bs4 import BeautifulSoup

    r = httpx.get(url, timeout=60, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    })
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml").get_text("\n")
