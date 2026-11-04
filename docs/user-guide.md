# User guide

How to use bcgacha once it is installed and the device is prepared. To get
that far, start at the [README](../README.md).

## Two ways to drive it

Type `bcgacha` with nothing after it and it says what it knows, asks what you
want, and does it. Or say it all at once on the command line. Every run on the
phone also serves the live page at <http://127.0.0.1:8765>, which shows what
the bot sees and works out, and can stop it. Either one can do anything the
other can:

| You want to | Command line | Live page (`bcgacha ui`) |
|---|---|---|
| see what is known | `bcgacha status` | Overview tab |
| get new events | automatic: every command downloads them first (or `bcgacha tools update`) | automatic before every run (or Update events & tiers) |
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

The page shows the command for whatever is ticked, so a run set up there can
be repeated from a terminal. Setting up (the save's map, the owned cats)
happens on the first run by itself, and only again when asked. The seed is
the exception: see [Find your seed](howto/find-your-seed.md).

`bcgacha run --help` lists every option.

## What a run does

A run is a list of tasks, each done only when needed, each reported on the
terminal and the page as it starts and ends:

| Task | Does |
|---|---|
| map | this save's sagas and chapters, and this device's Cat Base doors: once per save and device |
| storage | Use all on Cat Storage, when asked |
| owned | reads every Cat Guide entry for what the account owns: once, or when asked |
| capsule | before drawing: puts each live event on screen (the schedule lists some the game does not show) and reads the rare and Platinum ticket counters |
| seed | the seed and position, as saved, or found from the saved result screens, spending nothing |
| goal | what is wanted and why, the route to it, and the whole run played out on paper |
| roll | draws along the route, every result read and checked against the plan |
| capsules | the normal machines, with their own tickets |
| legends | the Uncanny Legends, stage after stage, with the Cat CPU |
| outbreaks | each saga chapter's Zombie Outbreak, with the zombie deck and the Cat CPU |

- What is wanted: the units named with `-t`, in that order, outrank
  everything; then each event named with `-e`. With neither, every unowned
  Uber of every live event. Platinum tickets go on named units first, then the
  best unowned Platinum Ubers by tier. Twice as many are earmarked as tickets
  held, so one that never comes up on the route does not strand a ticket.
- Nothing the screen shows is typed in: the rare and Platinum ticket counts,
  Cat Food and Cat Storage's size are all read off it.
- An event the tab strip does not show is noted after one sweep of the tabs
  and left out of every plan that day.
- Every draw is refused unless the button shows a ticket and a cost of 1, and
  the position is saved the moment a draw is tapped.
- Stop takes effect between draws; a run resumes from where it left off.
- A run spends no Platinum Ticket until one of its own draws has matched: a
  draw made by hand since the last run moves the position unseen.
- Once a capsule has opened, a tap on the top bar skips its reveal. Log-in
  bonus and reward notices in the way are pressed through with their Ok.
- Store, Attack!, Draw for Free!, Trade for Ticket and Change to XP are never
  pressed by the navigator, whatever the screen map says. The battle players
  press Attack! themselves, on the stage they chose.

The normal machines press Try 10 times! while its face shows the 10, else Try
once!, each face checked against how it looked when it first drew, and stop
if the Cat Food counter ever falls.

The Uncanny Legends player opens the topmost green chapter of the Legend
Stages list that is not greyed out, picks its rightmost stage, keeps the Cat
CPU item on CPU (a second tap turns it to skip-battle, which refuses a stage
not yet cleared) and presses Attack!. Energy is refilled with Leadership; the
offer to continue a lost battle for Cat Food is always refused. It stops when
that topmost chapter is CLEAR, or when one stage is lost three times running,
which needs a person.

The Zombie Outbreak player goes through every saga chapter in turn. On each
chapter's Stage Select, a purple OUTBREAK button on the left means an
outbreak is up. If the Equip button beside Attack! does not name the zombie
deck, it steps through the decks in Organize Cats until one named "zombie"
comes up. So name one of your decks with "zombie" in it before using this.
A stage is fought until it is cleared or lost three times running; then on to
the next chapter.

Only one thing may drive the device. A second `bcgacha run` while the page is
up refuses, and says to start the run from the page.

## How draws are chosen

Scoring is ownership first, quality second. A first copy of a unit dominates
everything; a duplicate is not worthless, because extra copies raise a unit's
level cap through the +N system, but it scores at a small fraction. Uber and
Legend values are then scaled by the community tier ranking, so a strong unit
outranks a weak one of the same rarity.

Platinum Tickets are only ever spent on an unowned Uber ranked A- or better.
They read the same seed as every other banner, so a Platinum draw can be
slotted into the route at a chosen position. They are scarce, so the planner
refuses to waste one on a duplicate or a weak unit.

## What banner switching can and cannot do

Rarity is decided by the seed, not by the banner: the rarity draw is
`rarity_seed % 10000` compared against the banner's weights. Every standard
banner uses the same 7000/2500/500 split, so an Uber position is an Uber
position on all of them.

So switching banners chooses which Uber lands, not whether one lands. Rarity
only moves when the weights move:

| Banner | Uber weight | Ubers in 400 rolls (seed 123456789) |
|---|---|---|
| standard | 500 | 19 |
| Queen's/King fest | 700 | 27 |
| Uberfest / Superfest | 900 | 36 |
| Epicfest | 1000 | 39 |
| Platinum | 10000 | 400 |

`bcgacha tools ubers --seed S --event KEY` lists the positions that pay out.

## Where bcgacha keeps its files

Everything bcgacha downloads, learns and captures lives in one folder:

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\bcgacha` |
| macOS | `~/Library/Application Support/bcgacha` |
| Linux | `~/.local/share/bcgacha` |

Set the `BCGACHA_HOME` environment variable to use another folder.
`bcgacha status` prints the one in use. Inside it:

| Folder | Holds |
|---|---|
| `state/account.json` | the seed and position: the one file that must stay right |
| `state/owned.json` | the cats the Cat Guide says you own |
| `state/devices/WxH/` | what was learned about one screen size; delete it to make a device learn again |
| `captures/` | the result screen of every draw bcgacha made |
| `logs/` | battle ends from the players, and the drawn screen map |
| `data/` | the downloaded event schedule and tier list |

## Tools

Single steps, for a closer look (`bcgacha tools --help`):

```
bcgacha tools probe                 # what the attached device supports
bcgacha tools upkeep owned          # read the Cat Guide again (also: map, storage)
bcgacha tools resync --cat NAME     # fix the position after draws made by hand
bcgacha tools set-seed S --cat NAME # save a seed found elsewhere
bcgacha tools update                # the newest events and tier list
bcgacha tools tiers                 # the tier list alone
bcgacha tools banners               # today's banners and their keys
bcgacha tools predict --seed S --event KEY
bcgacha tools ubers --seed S --event KEY
bcgacha tools find-seed --event KEY --cats "A,B,C,..."
bcgacha tools map                   # draw the screen map to an HTML page
```

`bcgacha ui --replay FOLDER` serves the page over saved frames, with no
device: plans work, nothing else.

## Things that will bite a careless run

- Cat Storage holds 64, or 128 after Cats of the Cosmos Ch.3. A full storage
  blocks drawing outright rather than warning. Add `--empty-storage`.
- Rare Cat Tickets only ever do single draws.
- The single-draw button silently changes currency. With tickets in hand it
  spends a ticket; the instant the stack runs out, the same button spends 150
  Cat Food. bcgacha reads the button before every draw for this reason.
- The capsule screen is online only; a clock or network error blocks drawing.
- Draws made by hand move the position without bcgacha seeing. Use
  `bcgacha tools resync` after any.

## Known limitations

The Cat Guide walk reads a name per entry with OCR, which mangles the odd
letter on a stylised font. Matching is fuzzy and needs a clear winner, so a
missed entry is recorded as unowned rather than guessed at. The failure mode
is chasing a cat you already have, never skipping one you do not.

A cat sitting in Cat Storage has not joined the roster yet and does not
appear in the Guide as unlocked.

Only the English version of the game is supported: screens are recognised by
their English text.
