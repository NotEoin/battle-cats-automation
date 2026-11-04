# Developer guide

How bcgacha works and how to change it. For using it, see the
[user guide](user-guide.md).

## Setting up

```
git clone https://github.com/NotEoin/battle-cats-automation
cd battle-cats-automation
uv venv && uv pip install -e ".[test]"    # editable install with pytest and ruff
uv run pytest                             # about ten seconds; no device, no network
uv run ruff check .                       # lint, import order, non-ASCII text
```

The tests read a frozen, cut-down dataset and tier list from
`tests/fixtures/data`, and run in a scratch `BCGACHA_HOME` that
`tests/conftest.py` sets up, so they never touch your own bcgacha folder.
After `bcgacha tools update`, `python scripts/make_test_data.py` rebuilds the
fixtures when a test needs a newer event.

Two tests read a real result screen, `tests/fixtures/result_viking_cat.png`.
It is a game screenshot, so it is not in git; they skip without it.

CI (`.github/workflows/ci.yml`) runs the linter, then the tests on Linux,
macOS and Windows with Python 3.11 and 3.13.

## The idea

One 32-bit xorshift state drives every Rare Cat Capsule draw, the seed is
shared across all banners, and nothing but a rare draw advances it. So the bot
does not read draw results off the screen to learn them: it computes them, and
reads the screen only to confirm it is on the screen it expects and that the
result matched. `prng`, `gacha` and `data` reproduce bc.godfat.org's tables
exactly; `tests/test_gacha.py` diffs them against pages saved from that site.

## Any device, and no captured images shipped

Navigation ships no pictures of the game. `bcgacha/resources/ui_graph.json`
says what each screen reads and what each transition presses ("Rare Capsule",
the back arrow, the X), and the bot learns where those are on whichever
device is attached.

The first time a screen is met it is read in full: OCR of the whole frame,
and the game's gold pills and X discs found by shape (`perception`). What that
finds is kept per resolution under `state/devices/WxH/` (`profile`): the box
screen names are printed in, and a small template of each control the map
uses. Once a title has named its screen, a grey picture of it is kept too, so
after that a screen is recognised from templates alone, with no OCR: about a
millisecond against most of a second. A title read cut short ("Lucky
Capsules" for "Lucky Capsules G") is left to a full look rather than trusted.
Only what the map names is learned, never timers or counters.

The navigator does not sleep after a tap: it watches until two still frames
name the next screen, with a jittered pause before each tap standing in for a
person finding the button.

Each chapter's Cat Base stands in front of its own door, and the door names
the chapter (`bases`). Doors are learned per device as well.

Some positions are not learned: the battle players (`legends`, `outbreaks`),
the normal machines (`capsules`) and a few fixed boxes in `uigraph` use
screen fractions measured on a 2532x1170 iPhone. These are the first thing to
check on a device with another screen shape, and `bcgacha check` warns about
such a device.

## Four things that will waste a day if nobody says them

HID coordinates are normalised against the device's native portrait frame,
not the orientation the app draws in. This game is landscape only, so every
coordinate must be rotated: see `layout.landscape_to_hid`. Sending landscape
fractions straight through puts taps somewhere else entirely.

The result screen's Ok button pulses a pink outline, so template matching
against it is unstable. Anchor on the static Use now / Exchange pair instead.

The Cat Guide's arrow and back buttons do not respond to synthetic taps at
all, at 50 ms or at 350 ms. Only a flick across the artwork moves it, and the
only dependable way to rewind the Guide is to leave to the Cat Base and come
back in through Menu.

Opening a Cat Guide entry that still carries a NEW! badge raises a Cat Food
reward popup over the description panel, so "is the panel visible" is not a
sufficient test for being on the detail view. Look for the popup's own button.

## Talking to the device

Synthetic touch comes from Apple's CoreDevice remote-control feature, which
refuses below iOS 27 with error 9021. Screen capture works from iOS 17. Both
need Developer Mode on and the Developer Disk Image mounted; neither needs
root, an Apple developer account or a jailbreak. `session` holds one
userspace tunnel, one screenshot channel and one touch session open for a
whole run, because starting each afresh costs about two seconds.

## Measured performance

From runs on the tested iPhone 16e:

| What | Measured |
|---|---|
| roll prediction | 1194 cells checked against bc.godfat.org |
| guaranteed-Uber prediction | 179 of 179 against bc.godfat.org |
| seed recovery from observed draws | unique hit in about 220 s |
| screen capture | about 0.35 s a frame |
| screen recognition | about 1 ms from remembered titles |
| rare draw loop | 13 to 14 s a draw, reveals skipped |
| normal capsules | 3.3 s a capsule in tens, 14 s singly |
| Cat Guide walk | about 1.6 s an entry |

## Modules

| Module | Does |
|---|---|
| `cli` | the `bcgacha` command: guided mode, status, search, plan, run, ui, check, tools |
| `jobs` | a run as a list of tasks, the one thing both the CLI and the page start |
| `console` | what a run says on the terminal |
| `liveview` | the live page: the screen, what is recognised, and every section of a run |
| `paths` | where bcgacha keeps what it downloads, learns and captures |
| `units` | find a unit by any name, nickname or id |
| `goals` | what a run wants, in what order, and why |
| `planner` | which banner at each position, and when to spend Platinum |
| `scoring` | what an outcome is worth: new, tier, duplicate |
| `pipeline` | the rare draw loop and its checks, storage, owned list, seed |
| `capsules` | the normal machines: Cat Capsules and both Lucky Capsules |
| `storage` | clearing Cat Storage: Use all, then trade or exchange what is left |
| `legends` | the Uncanny Legends, battle after battle, with the Cat CPU |
| `outbreaks` | each chapter's Zombie Outbreak, with the zombie deck |
| `prng` | xorshift32 forward and inverse |
| `data` | godfat's dataset: cat pools, rarity weights, schedule |
| `gacha` | positions, tracks, dupe rerolls, guaranteed Ubers |
| `seedfind` | brute-force seed recovery from observed draws |
| `seedpos` | seed and position from saved result screens |
| `state` | the saved seed and position, and resync |
| `tiers` | community rankings, with nickname aliases |
| `catindex` | reads the Cat Guide to learn what is owned |
| `events` | the live gacha events, each a screen of the map, and which the device shows |
| `results` | the cat on a result screen, or "unsure" |
| `digits` | counters off the screen, down to a lone Platinum digit |
| `draw` | whether the draw button spends a ticket or Cat Food |
| `session` | one persistent tunnel for taps and frames |
| `device` | what the device supports, and whether one is plugged in |
| `uigraph` | the screen map, recognition, and the navigator |
| `perception` | reading a screen with no templates: OCR and gold shapes |
| `profile` | what one device has learned: title box, controls, Cat Base doors |
| `bases` | which chapter a Cat Base belongs to, from its door |
| `carousel` | the save's sagas and chapters, scanned into the map |
| `bannerpick` | the capsule screen's event tabs |
| `mapdraw` | draws the screen map, for the page and as its own page |
| `layout` | the portrait/landscape rotation taps need |
| `timing` | jittered, human-looking delays |
| `vision` | loading a saved screen |

## Changing the screen map

`bcgacha/resources/ui_graph.json` is edited by hand. `bcgacha tools map`
draws it to an HTML page with every route the navigator would take, which is
the quickest way to check an edit. `tests/test_uigraph.py` checks that every
screen can reach the Cat Base.

## Data

Cat pools and rarity weights come from godfat's `battle-cats-rolls` dataset,
downloaded into the bcgacha folder before every command (offline, the copy
saved is used). The tier list is scraped from battlecatstierlist.com, and
`bcgacha/resources/tier_aliases.json` maps its nicknames to dataset names
where fuzzy matching is not enough.
