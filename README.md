# Battle Cats capsule automation

Rolls the Rare Cat Capsule on a USB-attached iPhone, and knows in advance what
every roll will produce.

The gacha is not random to an observer who knows the account's seed. One 32-bit
xorshift state drives every rare capsule draw, the seed is shared across all
banners, and nothing but a rare roll advances it. So the bot does not read roll
results off the screen — it computes them, and reads the screen only to confirm
it is on the screen it expects.

## Status

| Capability | State |
|---|---|
| Roll prediction from a seed | working, 1194 cells checked against bc.godfat.org |
| Guaranteed-uber prediction | working, 179/179 against bc.godfat.org |
| Seed recovery from observed rolls | working, unique hit in ~220s |
| Device screen capture | working, ~0.35s per frame |
| Synthetic taps | working, absolute coordinates |
| Screen recognition | ~1ms from remembered titles; OCR only for a screen never seen |
| Rare draw loop | ~13-14s a draw, humanised, reveals skipped |
| Normal capsules | Cat and Lucky Capsules: 3.3s a capsule in tens, 14s singly |
| Counter and capacity reading | tickets, Cat Food, XP, storage N/M |
| Single-draw roll loop | working, ten consecutive draws verified |
| Banner targeting | planner wired to the loop, switches by tapping tabs |
| Collection index | reads the Cat Guide, ~1.6s per entry |
| Tier rankings | 267 entries scraped, 185 cats matched |
| Desync detection | each result checked against the prediction |
| End to end | verified: plan, switch, roll, verify, advance |

### Requirements

Synthetic touch comes from Apple's CoreDevice remote-control feature, which
refuses below **iOS 27** with error 9021 — iOS 26 is not enough. Screen capture
works from iOS 17. Both need Developer Mode on and the Developer Disk Image
mounted, neither needs root, and no Apple developer account or jailbreak is
involved.

### Four things that will waste a day if nobody says them

HID coordinates are normalised against the device's **native portrait** frame,
not the orientation the app draws in. This game is landscape only, so every
coordinate must be rotated — see `layout.landscape_to_hid`. Sending landscape
fractions straight through puts taps somewhere else entirely.

The result screen's Ok button **pulses a pink outline**, so template matching
against it is unstable. Anchor on the static Use now / Exchange pair instead.

The Cat Guide's arrow and back buttons **do not respond to synthetic taps at
all** — not at 50ms, not at 350ms. Only a flick across the artwork moves it, and
the only dependable way to rewind the Guide is to leave to the Cat Base and come
back in through Menu.

Opening a Cat Guide entry that still carries a NEW! badge raises a Cat Food
reward popup **over** the description panel, so "is the panel visible" is not a
sufficient test for being on the detail view. Look for the popup's own button.

## Any iPhone, and no captured images shipped

Navigation ships no pictures of the game. `data/ui_graph.json` says what each
screen reads and what each transition presses -- "Rare Capsule", the back
arrow, the X -- and the bot learns where those are on whichever phone is
attached.

The first time a screen is met it is read in full: OCR of the whole frame, and
the game's gold pills and X discs found by shape (`perception`). What that
finds is kept per resolution under `state/devices/WxH/` (`profile`): the box
screen names are printed in, and a small template of each control the map
uses. Once a title has named its screen, a grey picture of it is kept too,
so after that a screen is recognised from templates alone, with no OCR: about
a millisecond against most of a second. A title read cut short -- "Lucky
Capsules" for "Lucky Capsules G", "Cat Base" for "Cat Base Select" -- is left
to a full look rather than trusted. Only what the map names is learned, never
timers or counters, so going over the same screens again leaves the profile
untouched.

The navigator does not sleep after a tap: it watches until two still frames
name the next screen, with a jittered pause before each tap standing in for a
person finding the button. Store, Attack!, Draw for Free!, Trade for Ticket
and Change to XP are refused whatever a map says.

Each chapter's Cat Base stands in front of its own door, and the door names
the chapter (`bases`). Doors are learned per device as well: on a phone that
has not seen them, the bot steps into each chapter once. The save's sagas and
chapters are scanned into `state/carousels.json` once per save.

Delete `state/devices/WxH/` to make a phone learn from scratch.

## Running the whole pipeline

    .venv/bin/python scripts/debug_ui.py

The debug page (http://127.0.0.1:8765) is the one process that drives the
phone, and shows every stage live. On a fresh start it scans the save's sagas
and chapters and learns the device; **Run setup** then reads the Cat Guide
(owned cats), checks each live event on the device, finds the seed and
position, and plans and simulates the run. **Start goal run** rolls: every
unowned Uber of the events named under Goal events (all live ones if blank;
their Legends too if ticked, the one named under Prefer first), and the best
unowned Platinum Ubers by tier with the Platinum Tickets, slotted into the same
route, until the goal is met or the rare tickets run out.

- Each live event is a screen of the map: `goto("event:979")` selects Iron
  Legion from anywhere, in one call.
- The seed is found from the saved result screens in `captures/`, with no
  tickets spent. Keep that folder: without it, finding the seed costs draws.
- Every draw is refused unless the button shows a ticket and a cost of 1, and
  the position is saved the moment a draw is tapped.
- Stop takes effect between draws; a run resumes from `state/account.json`.
- A run spends no Platinum Ticket until one of its own draws has matched: a
  draw made by hand since the last run moves the position unseen. A draw that
  disagrees is placed on the banner it was drawn on, near the saved position.
- Once a capsule has opened, a tap on the top bar skips its reveal.

The normal machines are opened by `capsules.CapsuleRun(ctx, "cat" | "lucky" |
"lucky_g")`: Try 10 times! while its face shows the 10, else Try once!, each
face checked against how it looked when it first drew, and the run stopped if
the Cat Food counter ever falls.

**Play Uncanny Legends** beats the Uncanny Legends one stage after another
with the in-game Cat CPU (`legends.LegendRun(ctx).run()`): it opens the
topmost green chapter of the Legend Stages list that is not greyed out, picks
its rightmost stage, keeps the Cat CPU item on CPU (a second tap turns it to
skip-battle, which refuses a stage not yet cleared) and presses Attack!. Energy
is refilled with Leadership; the offer to continue a lost battle for Cat Food
is always refused. It stops when that topmost chapter is CLEAR, or when one
stage is lost three times running, which needs a person. Each battle's end is
kept under `logs/legends`.

The older `cli run` and `cli goal` loops still check screens against captured
templates, which no longer ship; the debug page's pipeline replaces them.

## What banner switching can and cannot do

Rarity is decided by the seed, not by the banner: the rarity draw is
`rarity_seed % 10000` compared against the banner's weights. Every standard
banner uses the same 7000/2500/500 split, so an Uber position is an Uber
position on all of them.

So switching banners chooses **which** uber lands, not **whether** one lands.
Rarity only moves when the weights move:

| Banner | Uber weight | Ubers in 400 rolls (seed 123456789) |
|---|---|---|
| standard | 500 | 19 |
| Queen's/King fest | 700 | 27 |
| Uberfest / Superfest | 900 | 36 |
| Epicfest | 1000 | 39 |
| Platinum | 10000 | 400 |

`bcgacha ubers` lists the positions that pay out, so rolls can be spent getting
to them and the right banner selected when they arrive.

## Setup

    sudo apt install -y python3-dev usbmuxd
    python3 -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/python scripts/fetch_data.py --lang en

On the phone, once: Settings > Privacy & Security > Developer Mode, on, and
restart. Then mount the developer disk image:

    .venv/bin/pymobiledevice3 mounter auto-mount

## Use

    python -m bcgacha.cli probe                 # what the device supports
    python -m bcgacha.cli find-seed --event <banner> --cats "A,B,C,..." --progress
    python -m bcgacha.cli tiers                 # refresh community rankings
    python -m bcgacha.cli index                 # scan the Cat Guide
    python -m bcgacha.cli owned                 # what the scan found
    python -m bcgacha.cli plan --count 20       # what it would roll, and why
    python -m bcgacha.cli run --mode until-target

`find-seed` wants 7–10 rolls. Fewer than about 7 usually leaves several seeds
fitting; the command says so and asks for one more roll.

### Run modes

| Mode | Stops when |
|---|---|
| `until-target` (default) | the next new Uber or Legend lands |
| `max-tickets` | `--max-tickets N` tickets have been spent |
| `until-storage-full` | Cat Storage reaches its cap |
| `all` | tickets run out; empties storage with Use all as needed |

`--speed 0.6` scales every delay down; `--no-humanise` removes the jitter
entirely. Delays are drawn from a distribution by default, with the occasional
longer pause, so the cadence is not machine-exact.

## How rolls are chosen

Scoring is ownership first, quality second. A first copy of a unit dominates
everything; a duplicate is not worthless, because extra copies raise a unit's
level cap through the +N system, but it scores at a small fraction. Uber and
Legend values are then scaled by community tier ranking, so a strong unit
outranks a weak one of the same rarity.

Platinum Tickets are only ever spent on an unowned Uber ranked A- or better.
They read the same seed as every other banner, so a Platinum draw can be slotted
into the route at a chosen position -- but they are scarce, so the planner
refuses to waste one on a duplicate or a weak unit.

## Things that will bite a naive bot

- **Cat Storage holds 64, or 128 after Cats of the Cosmos Ch.3.** Not 200. A
  full storage blocks rolling outright rather than warning.
- **Rare Cat Tickets only ever do single draws.** There is no 11-draw with
  tickets.
- **The single-draw button silently changes currency.** With tickets in hand it
  spends a ticket; the instant the stack empties, the same button at the same
  position spends 150 Cat Food. Read the button, not its position.
- Uber and Legend reveals play a longer animation, so fixed sleeps desync. Poll
  for the action row instead.
- The capsule screen is online-only; a clock or network error blocks rolling.

## Terms of service

PONOS's terms prohibit "external tools which falsely manipulate the Service such
as BOT and/or cheat tools". This project is one. Running it risks the account.

## Data

Cat pools and rarity weights come from godfat's `battle-cats-rolls` dataset,
refreshed by `scripts/fetch_data.py`. The tests diff this engine against live
bc.godfat.org output saved under `tests/fixtures`.


## Modules

| Module | Does |
|---|---|
| `prng` | xorshift32 forward and inverse |
| `data` | godfat's dataset: cat pools, rarity weights, schedule |
| `gacha` | positions, tracks, dupe rerolls, guaranteed ubers |
| `seedfind` | brute-force seed recovery from observed rolls |
| `tiers` | community rankings, with nickname aliases |
| `catindex` | reads the Cat Guide to learn what is owned |
| `scoring` | what an outcome is worth: new, tier, duplicate |
| `planner` | which banner at each position, and when to spend Platinum |
| `session` | one persistent tunnel for taps and frames |
| `vision` | screen classification, counters, storage capacity |
| `safety` | verify-before-tap, dialog handling |
| `layout` | tap targets, and the portrait/landscape rotation |
| `timing` | jittered, human-looking delays |
| `roller` | a single draw, bracketed by checks |
| `runner` | the loop: plan, roll, drain storage, stop |
| `uigraph` | the screen map, recognition, and the navigator |
| `perception` | reading a screen with no templates: OCR and gold shapes |
| `profile` | what one device has learned: title box, controls, Cat Base doors |
| `bases` | which chapter a Cat Base belongs to, from its door |
| `carousel` | the save's sagas and chapters, scanned into the map |
| `events` | the live gacha events, each a screen of the map |
| `seedpos` | seed and position from saved result screens |
| `results` | the cat on a result screen, or "unsure" |
| `draw` | whether the draw button spends a ticket or Cat Food |
| `pipeline` | the stages and the goal run, reported live |
| `capsules` | the normal machines: Cat Capsules and both Lucky Capsules |
| `legends` | the Uncanny Legends, battle after battle, with the Cat CPU |

## When the position drifts

The saved position is the one thing that must stay true. Any roll made by hand
leaves it behind, and every later prediction is then wrong. The run loop reads
the cat off each result screen and stops the moment one disagrees with the plan.

Recovering does not need the seed finding again -- the seed has not changed,
only the position. Give `resync` the cat that actually came out:

    python -m bcgacha.cli resync --cat "Figure Skating Cats"

It searches forward for the position that would have produced it and corrects
the state, refusing when the answer is not unique.

## Known limitations

The Cat Guide walk reads a name per entry with OCR, which mangles the odd
letter on a stylised font. Matching is fuzzy and requires a clear winner, so a
missed entry is recorded as unowned rather than guessed at -- the failure mode
is chasing a cat you already have, never skipping one you do not.

Storage contents are not part of the index: a cat sitting in Cat Storage has
not joined the roster yet and does not appear in the Guide as unlocked.

The seed position is the one piece of state that must stay correct. It lives in
`state/account.json`, which is deliberately not committed. Losing it costs
another ten tickets to rediscover.
