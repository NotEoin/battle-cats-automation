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
| Roll prediction from a seed | working, 995 cells checked against bc.godfat.org |
| Guaranteed-uber prediction | working, 179/179 against bc.godfat.org |
| Seed recovery from observed rolls | working, unique hit in ~228s |
| Device screen capture | working on iOS 18.7.8 |
| Synthetic taps | **blocked — needs iOS 27** |
| Roll loop, banner targeting | not started, blocked on taps |

### The iOS 27 blocker

Taps come from Apple's CoreDevice remote-control feature, which refuses below
iOS 27 with error 9021. The attached iPhone 16e runs iOS 18.7.8, so it cannot
currently be tapped over USB. iOS 26 does not help; the requirement is 27.0.

Alternatives if the device stays on iOS 18: WebDriverAgent via go-ios (needs an
Apple certificate that a free account expires weekly), or an external USB-HID
board driving AssistiveTouch (cheap, but a documented iOS bug locks the
AssistiveTouch pointer to portrait mapping in landscape, and this game is
landscape-only).

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
