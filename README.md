# Battle Cats capsule automation

Rolls the Rare Cat Capsule on a USB-attached iPhone, and knows in advance what
every roll will produce.

The gacha is not random to an observer who knows the account's seed. One 32-bit
xorshift state drives every rare capsule draw, the seed is shared across all
banners, and nothing but a rare roll advances it. So the bot does not read roll
results off the screen — it computes them, and reads the screen only to confirm
it is on the screen it expects.

## Quick start

    bcgacha                 # guided: says what it knows, asks what you want, does it

That is all that is needed. Every run on the phone also serves the live page at
http://127.0.0.1:8765, which shows everything the bot sees and works out, and
can stop it. Either one can do anything the other can:

| You want to | Command line | Live page (`bcgacha ui`) |
|---|---|---|
| see what is known | `bcgacha status` | Overview tab |
| get new events | `bcgacha tools update` (or `--update` on any run) | Update events & tiers |
| find a unit | `bcgacha search dark kasli` | search box under Start a run |
| see the plan, spending nothing | `bcgacha plan -t "Dark Kasli"` | Plan |
| draw for units, most wanted first | `bcgacha run -t "Dark Kasli" -t Gunduros --roll` | tick Draw, Start |
| limit Platinum spending | `--platinum 2` (default: every one held, read off the screen) | Platinum: at most |
| want every Uber of an event | `-e "Iron Legion"` (`--legend-rares` for its Legend Rares) | tick the event |
| open Cat or Lucky Capsules | `--capsules cat:30` (`lucky`, `lucky_g`; no count: until out) | Normal capsules |
| play the Uncanny Legends | `--play-legends` | Battles |
| beat the Zombie Outbreaks | `--play-outbreaks` | Battles |
| all of it in one go | `bcgacha run -t Gunduros --roll --capsules cat --play-legends` | tick them all |
| stop | Ctrl+C (between taps) | Stop |

The page shows the command for whatever is ticked, so a run set up there can be
repeated from a terminal. Setting up -- the save's map, the owned cats, the seed
-- happens on the first run by itself, and only again when asked.

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

## What a run does

A run is a list of tasks, each done only when needed, each reported on the
terminal and the page as it starts and ends (`jobs.py`):

| Task | Does |
|---|---|
| map | this save's sagas and chapters, and this phone's Cat Base doors: once per save and phone |
| storage | Use all on Cat Storage, when asked |
| owned | reads every Cat Guide entry for what the account owns: once, or when asked |
| capsule | before drawing: puts each live event on screen -- the schedule lists some the game does not show -- and reads the rare and Platinum ticket counters |
| seed | the seed and position, found from the saved result screens in `captures/`, spending nothing |
| goal | what is wanted and why, the route to it, and the whole run played out on paper |
| roll | draws along the route, every result read and checked against the plan |
| capsules | the normal machines, with their own tickets |
| legends | the Uncanny Legends, stage after stage, with the Cat CPU |
| outbreaks | each saga chapter's Zombie Outbreak, with the zombie deck and the Cat CPU |

- What is wanted: the units named with `-t`, in that order, outrank everything;
  then each event named with `-e`. With neither, every unowned Uber of every
  live event. Platinum tickets go on named units first, then the best unowned
  Platinum Ubers by tier -- twice as many are earmarked as tickets held, so
  one that never comes up on the route does not strand a ticket.
- Nothing the screen shows is typed in: the rare and Platinum ticket counts,
  Cat Food and Cat Storage's size are all read off it. OCR cannot see a lone
  digit -- the Platinum count, usually -- so `digits.py` reads one three ways
  and trusts it only when they agree: by the glyphs of numbers it has read for
  certain, set among those digits as a number, and drawn as a run of itself.
- Each live event is a screen of the map: `goto("event:979")` selects Iron
  Legion from anywhere, in one call. An event the tab strip does not show is
  noted after one sweep of the tabs and left out of every plan that day.
- Every draw is refused unless the button shows a ticket and a cost of 1, and
  the position is saved the moment a draw is tapped.
- Stop takes effect between draws; a run resumes from `state/account.json`.
- A run spends no Platinum Ticket until one of its own draws has matched: a
  draw made by hand since the last run moves the position unseen. A draw that
  disagrees is placed on the banner it was drawn on, near the saved position.
- Once a capsule has opened, a tap on the top bar skips its reveal. Log-in
  bonus and reward notices in the way are pressed through with their Ok.

The normal machines press Try 10 times! while its face shows the 10, else Try
once!, each face checked against how it looked when it first drew, and stop if
the Cat Food counter ever falls.

The Uncanny Legends player opens the topmost green chapter of the Legend Stages
list that is not greyed out, picks its rightmost stage, keeps the Cat CPU item
on CPU (a second tap turns it to skip-battle, which refuses a stage not yet
cleared) and presses Attack!. Energy is refilled with Leadership; the offer to
continue a lost battle for Cat Food is always refused. It stops when that
topmost chapter is CLEAR, or when one stage is lost three times running, which
needs a person. Each battle's end is kept under `logs/legends`.

The Zombie Outbreak player goes through every saga chapter in turn. On each
chapter's Stage Select, a purple OUTBREAK button on the left means an outbreak
is up: pressing it selects the stage. If the Equip button beside Attack! does
not name the zombie deck, Equip opens Organize Cats, whose arrows step through
the decks until one named zombie comes up, and Back returns to the stage. Then
the Cat CPU, Attack!, and the same battle handling as the Legends. A stage is
fought until it is cleared or lost three times running; then on to the next
chapter.

Only one thing may drive the phone. A second `bcgacha run` while the page is up
refuses, and says to start the run from the page.

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

`bcgacha tools ubers` lists the positions that pay out, so rolls can be spent getting
to them and the right banner selected when they arrive.

## Setup

    sudo apt install -y python3-dev usbmuxd
    python3 -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/bcgacha tools update      # the event schedule and the tier list

`bcgacha` is then `.venv/bin/bcgacha` (or `python -m bcgacha`). To call it by
name from anywhere without activating the venv, link it onto your PATH:

    ln -s "$PWD/.venv/bin/bcgacha" ~/.local/bin/bcgacha

On the phone, once: Settings > Privacy & Security > Developer Mode, on, and
restart. The developer disk image comes off whenever the phone restarts;
`bcgacha run` and `bcgacha ui` mount it again before connecting. By hand:

    .venv/bin/pymobiledevice3 mounter auto-mount

## Tools

Single steps, for a closer look (`bcgacha tools --help`):

    bcgacha tools probe                 # what the attached iPhone supports
    bcgacha tools upkeep owned          # read the Cat Guide again (also: map, storage)
    bcgacha tools resync --cat NAME     # fix the position after draws made by hand
    bcgacha tools update                # the newest events and tier list (no phone)
    bcgacha tools tiers                 # the tier list alone
    bcgacha tools predict --seed S --event KEY
    bcgacha tools ubers --seed S --event KEY
    bcgacha tools find-seed --event KEY --cats "A,B,C,..."
    bcgacha tools map                   # draw the screen map to logs/ui_graph.html

`find-seed` wants 7–10 draws written down by hand; a run finds the seed from
`captures/` by itself.

`bcgacha ui --replay captures/` serves the page over saved frames, with no
phone: plans work, nothing else.

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
refreshed by `bcgacha tools update`. The tests diff this engine against live
bc.godfat.org output saved under `tests/fixtures`.


## Modules

| Module | Does |
|---|---|
| `cli` | the `bcgacha` command: guided mode, status, search, plan, run, ui, tools |
| `jobs` | a run as a list of tasks, the one thing both the CLI and the page start |
| `console` | what a run says on the terminal |
| `liveview` | the live page: the screen, what is recognised, and every section of a run |
| `units` | find a unit by any name, nickname or id |
| `goals` | what a run wants, in what order, and why |
| `planner` | which banner at each position, and when to spend Platinum |
| `scoring` | what an outcome is worth: new, tier, duplicate |
| `pipeline` | the rare draw loop and its checks, storage, owned list, seed |
| `capsules` | the normal machines: Cat Capsules and both Lucky Capsules |
| `legends` | the Uncanny Legends, battle after battle, with the Cat CPU |
| `prng` | xorshift32 forward and inverse |
| `data` | godfat's dataset: cat pools, rarity weights, schedule |
| `gacha` | positions, tracks, dupe rerolls, guaranteed ubers |
| `seedfind` | brute-force seed recovery from observed rolls |
| `seedpos` | seed and position from saved result screens |
| `tiers` | community rankings, with nickname aliases |
| `catindex` | reads the Cat Guide to learn what is owned |
| `events` | the live gacha events, each a screen of the map, and which the phone shows |
| `results` | the cat on a result screen, or "unsure" |
| `digits` | counters off the screen, down to a lone Platinum digit |
| `draw` | whether the draw button spends a ticket or Cat Food |
| `session` | one persistent tunnel for taps and frames |
| `device` | what the phone supports, and whether one is plugged in |
| `uigraph` | the screen map, recognition, and the navigator |
| `perception` | reading a screen with no templates: OCR and gold shapes |
| `profile` | what one device has learned: title box, controls, Cat Base doors |
| `bases` | which chapter a Cat Base belongs to, from its door |
| `carousel` | the save's sagas and chapters, scanned into the map |
| `bannerpick` | the capsule screen's event tabs |
| `mapdraw` | draws the screen map, for the page and as its own page |
| `layout` | the portrait/landscape rotation taps need |
| `timing` | jittered, human-looking delays |

## When the position drifts

The saved position is the one thing that must stay true. Any roll made by hand
leaves it behind, and every later prediction is then wrong. The run loop reads
the cat off each result screen and stops the moment one disagrees with the plan.

Recovering does not need the seed finding again -- the seed has not changed,
only the position. Give `resync` the cat that actually came out:

    bcgacha tools resync --cat "Figure Skating Cats"

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
