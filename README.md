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
| Device screen capture | working, ~1.9s per frame |
| Synthetic taps | working, absolute coordinates |
| Screen classification | capsule / result / sent-to-storage / storage / dialog |
| Counter and capacity reading | tickets, Cat Food, XP, storage N/M |
| Single-draw roll loop | working, ten consecutive draws verified |
| Banner targeting | planner written, not yet wired to the roll loop |

### Requirements

Synthetic touch comes from Apple's CoreDevice remote-control feature, which
refuses below **iOS 27** with error 9021 — iOS 26 is not enough. Screen capture
works from iOS 17. Both need Developer Mode on and the Developer Disk Image
mounted, neither needs root, and no Apple developer account or jailbreak is
involved.

### Two things that will waste a day if nobody says them

HID coordinates are normalised against the device's **native portrait** frame,
not the orientation the app draws in. This game is landscape only, so every
coordinate must be rotated — see `layout.landscape_to_hid`. Sending landscape
fractions straight through puts taps somewhere else entirely.

The result screen's Ok button **pulses a pink outline**, so template matching
against it is unstable. Anchor on the static Use now / Exchange pair instead.

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

    python -m bcgacha.cli probe
    python -m bcgacha.cli banners --recent 30
    python -m bcgacha.cli predict --seed 123456789 --event 2026-08-21_1075 --count 12
    python -m bcgacha.cli find-seed --event 2026-09-21_1081 \
        --cats "Pogo Cat,Hip Hop Cat,Psychocat,Wushu Cat,Illya the Cat" --progress

`find-seed` wants 7–10 rolls. Fewer than about 7 usually leaves several seeds
fitting; the command says so and asks for one more roll.

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
