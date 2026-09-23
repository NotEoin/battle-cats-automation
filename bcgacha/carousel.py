"""The saga and chapter carousels, which differ from save to save.

The saga carousel (Empire of Cats, Into The Future, ...) and each saga's
chapter carousel only show what a save has unlocked, so they cannot live in the
fixed map. They are scanned from the device once, kept in state/carousels.json,
and turned into screens and transitions whenever the map is loaded:

    saga:<saga>           one card of the saga carousel
    chapter:<saga>:<n>    Chapter n of that saga's chapter carousel

Each is recognised by reading the centre card, the only live one. Neighbours
are one drag apart, a tap on the card enters it, and X goes back up a level.
Scan again with `python -m bcgacha.cli scan-carousels` once a save unlocks more.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

from rapidfuzz import fuzz

from .layout import landscape_to_hid
from .paths import STATE

CATALOGUE_FILE = STATE / "carousels.json"

# The centre card, as fractions of the frame. The name sits below the
# "Chapter n" label and above the treasure line; both carousels put it here.
# A tighter box catches the card edge and reads "Empire of C Cats".
CARD_NAME_BOX = (0.385, 0.46, 0.615, 0.67)
# OCR reads "Chapter" here but drops the lone digit in the game's font, so
# the label only says a card is a chapter; numbers come from carousel order.
CARD_LABEL_BOX = (0.38, 0.375, 0.50, 0.45)

# A drag of 0.20 of the width skipped saga cards; 0.15, held still before the
# finger lifts, moves both carousels exactly one card in either direction.
DRAG_SPAN = 0.15
DRAG_Y = 0.58
DRAG_SETTLE = 1.6

ENTER_SAGA = (0.5, 0.552)
ENTER_CHAPTER = (0.497, 0.585)
CAROUSEL_X = (0.906, 0.354)

MAX_CARDS = 40          # a runaway guard, far beyond any real carousel


class ScanError(RuntimeError):
    """The carousels did not read or move as a scan expects."""


def slug(name: str) -> str:
    """`name` as a screen-name fragment: lower case, words joined by `_`."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def clean(text: str) -> str:
    """OCR splits hyphenated words and spaces oddly; normalise both."""
    text = re.sub(r"\s*-\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def same(a: str, b: str) -> bool:
    """Whether two readings name the same card. OCR sometimes returns a
    two-line name's lines in the other order, so word order does not count."""
    a, b = a.lower(), b.lower()
    return bool(a) and bool(b) and max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b)) >= 85


# -- the device side ---------------------------------------------------------

def drag(session, direction: str, settle: float = DRAG_SETTLE) -> None:
    """Move a carousel one card. `left` moves the finger left: the next card."""
    lo, hi = 0.5 - DRAG_SPAN / 2, 0.5 + DRAG_SPAN / 2
    x0, x1 = (hi, lo) if direction == "left" else (lo, hi)
    session.drag(*landscape_to_hid(x0, DRAG_Y), *landscape_to_hid(x1, DRAG_Y))
    time.sleep(settle)


def tap(session, point: tuple[float, float], settle: float) -> None:
    """Tap a landscape screen fraction and give the screen `settle` seconds."""
    session.tap(*landscape_to_hid(*point))
    time.sleep(settle)


def read_card(graph, frame) -> tuple[str, str]:
    """(label, name) of the centre card: ("Chapter 2", "The Emperor of Darkness")."""
    return (clean(graph.read_title(frame, CARD_LABEL_BOX)),
            clean(graph.read_title(frame, CARD_NAME_BOX)))


def is_chapter(label: str) -> bool:
    """Whether a card's label says Chapter, allowing OCR to clip a letter."""
    words = label.strip().lower().split()
    return bool(words) and fuzz.ratio("chapter", words[0]) >= 80


def is_back_card(card: tuple[str, str]) -> bool:
    """True for the Back card that ends a chapter carousel."""
    return card[1].lower() == "back"


def same_card(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Whether a drag left the carousel where it was. The label region holds
    artwork on saga cards, so only whether it says "Chapter" is compared."""
    return same(a[1], b[1]) and is_chapter(a[0]) == is_chapter(b[0])


def seek_end(session, graph, end: str = "start") -> tuple[str, str]:
    """Drag to one end of the carousel on screen; stop when the card stops changing."""
    direction = "right" if end == "start" else "left"
    card = read_card(graph, session.screenshot())
    for _ in range(MAX_CARDS):
        drag(session, direction)
        nxt = read_card(graph, session.screenshot())
        if same_card(nxt, card):
            return nxt
        card = nxt
    raise ScanError(f"the carousel never stopped moving {direction}")


def _close_point(frame):
    """The X of a carousel, found by shape; None when there is none."""
    from .perception import CLOSE_SCORE, close_glyph_score, find_discs

    scored = [(close_glyph_score(frame, box), centre) for box, centre in find_discs(frame)]
    best = max(scored, default=None)
    return best[1] if best and best[0] >= CLOSE_SCORE else None


def _select_close(frame) -> bool:
    return _close_point(frame) is not None


def tap_close(session, settle: float = 2.2) -> None:
    """Tap the carousel's X wherever it is on this device."""
    tap(session, _close_point(session.screenshot()) or CAROUSEL_X, settle)


def _leave_notice(session, graph, here: str) -> None:
    """Press the way out of a notice that stepped in front, found by its target."""
    leave = next(t for t in graph.transitions if t.src == here and not t.action)
    frame = session.screenshot()
    point = None
    if leave.target:
        from .perception import perceive

        control = perceive(frame, graph.ocr).find(leave.target)
        point = control.tap if control else None
    tap(session, point or (leave.x, leave.y), leave.settle)


def _learn_base(session, graph, chapter: str, log, enter=ENTER_CHAPTER) -> bool:
    """Step into the centred card's Cat Base, learn its door, and come back out."""
    from . import bases
    from .uigraph import GENERIC_BACK, find_back_arrow

    tap(session, enter, 3.5)
    frame = session.screenshot()
    rec = graph.recognise(frame)
    if rec.here and graph.screens[rec.here].reactive:
        _leave_notice(session, graph, rec.here)
        frame = session.screenshot()
        rec = graph.recognise(frame)
    # The door is read off the very frame that was recognised as a Cat Base.
    learned = rec.here == "cat_base" and bases.learn(frame, graph, chapter, rec.percept)
    if learned:
        log(f"    learned the background of {chapter}")
    else:
        log(f"    could not learn the background of {chapter} (saw {rec.here})")
    tap(session, find_back_arrow(frame) or GENERIC_BACK, 2.6)
    return learned


def _back_on(session, graph, name: str, reads: int = 3) -> tuple[str, str]:
    """The centre card once it reads as `name`, allowing a read or two to come
    back mangled; the last reading if it never does."""
    card = read_card(graph, session.screenshot())
    for _ in range(reads - 1):
        if same(card[1], name):
            break
        time.sleep(0.6)
        card = read_card(graph, session.screenshot())
    return card


def _walk_chapters(session, graph, log, saga: dict, progress) -> list[dict]:
    """From anywhere on a chapter carousel, read every chapter left to right,
    stepping into each one's Cat Base to learn its background."""
    chapters = saga["chapters"]
    seek_end(session, graph, "start")
    card = read_card(graph, session.screenshot())
    for _ in range(MAX_CARDS):
        if is_chapter(card[0]) and card[1]:
            number = len(chapters) + 1
            chapters.append(dict(number=number, name=card[1]))
            log(f"    Chapter {number}: {card[1]}")
            progress()
            _learn_base(session, graph, chapter_screen(saga, number), log)
            back = _back_on(session, graph, card[1])
            if not same(back[1], card[1]):
                raise ScanError(f"expected to be back on {card[1]!r}, found {back[1]!r}")
        elif not is_back_card(card):
            log(f"    unreadable card {card!r}, skipped")
        drag(session, "left")
        nxt = read_card(graph, session.screenshot())
        if same_card(nxt, card):
            return chapters
        card = nxt
    raise ScanError("the chapter carousel never ended")


def _enter_saga(session, graph, entry: dict, log, progress) -> None:
    """Enter the centred saga, fill in `entry` with what it opens, come back out."""
    from .uigraph import GENERIC_BACK, find_back_arrow

    tap(session, ENTER_SAGA, 3.2)
    frame = session.screenshot()
    card = read_card(graph, frame)
    if _select_close(frame) and (is_chapter(card[0]) or is_back_card(card)):
        entry["enters"] = "chapters"
        entry["chapters"] = []
        progress()
        _walk_chapters(session, graph, log, entry, progress)
        tap_close(session)
        return

    rec = graph.recognise(frame)
    if rec.here and graph.screens[rec.here].reactive:
        # A notice in the way, such as Legend Stages' stage clear reward.
        entry["notice"] = rec.here
        _leave_notice(session, graph, rec.here)
        frame = session.screenshot()
        rec = graph.recognise(frame)
    here = rec.here
    if here:
        entry["enters"] = here
        if here == "cat_base":
            from . import bases

            if bases.learn(frame, graph, saga_screen(entry), rec.percept):
                log(f"    learned the background of {saga_screen(entry)}")
    else:
        # Not on the map, so recognition took a full look: its title is the
        # largest top-left text it read, wherever this device prints it.
        title = rec.percept.title.text if rec.percept and rec.percept.title else ""
        title = clean(title)
        entry["enters"] = "screen"
        entry["screen"] = dict(name=slug(title) or f"{slug(entry['name'])}_entry",
                               title=title or None)
        log(f"    opens a screen the map does not know: {title or 'untitled'!r}")
    progress()
    back = find_back_arrow(frame) or GENERIC_BACK
    tap(session, back, 2.4)


def scan(session, log=print, progress=None, graph=None) -> dict:
    """Read every saga, and every chapter of every saga, off the device.

    `progress`, when given, is called with the catalogue so far each time a
    saga or chapter is read, so a watcher can draw the map as it grows.
    """
    from .uigraph import Navigator, UIGraph

    graph = graph or UIGraph.load(carousels=False)
    if not Navigator(session, graph).goto("saga_select", log=log):
        raise ScanError("could not reach the saga carousel")
    card = read_card(graph, session.screenshot())
    if is_chapter(card[0]) or is_back_card(card):
        # Started on the chapter carousel: go up to the sagas.
        tap_close(session)
    seek_end(session, graph, "start")

    catalogue = dict(scanned=None, sagas=[])
    sagas = catalogue["sagas"]

    def report():
        if progress:
            progress(catalogue)

    for _ in range(MAX_CARDS):
        name = read_card(graph, session.screenshot())[1]
        if not name:
            raise ScanError("could not read the centre saga card")
        log(f"  saga {name}")
        entry = dict(name=name)
        sagas.append(entry)
        report()
        _enter_saga(session, graph, entry, log, report)
        back = _back_on(session, graph, name)[1]
        if not same(back, name):
            raise ScanError(f"expected to be back on {name!r}, found {back!r}")
        drag(session, "left")
        nxt = read_card(graph, session.screenshot())[1]
        if same(nxt, name):
            break
    catalogue["scanned"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report()
    return catalogue


def load_catalogue(path: Path | None = None) -> dict | None:
    """The save's scanned sagas and chapters, or None before the first scan."""
    path = Path(path or CATALOGUE_FILE)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_catalogue(catalogue: dict, path: Path | None = None) -> Path:
    """Keep the catalogue, written aside and swapped in whole."""
    path = Path(path or CATALOGUE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalogue, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def ensure(session, rescan: bool = False, log=print, progress=None, graph=None) -> dict:
    """This save's carousels, and this device's Cat Base backgrounds.

    The carousels belong to the save: scanned on first use, which learns the
    backgrounds on the way, and read from state/ after. The backgrounds belong
    to the device, so any this one has not learned -- a second phone, or a
    chapter unlocked since -- are learned by stepping into those chapters.
    """
    catalogue = None if rescan else load_catalogue()
    if catalogue is None:
        log("scanning the saga and chapter carousels")
        catalogue = scan(session, log=log, progress=progress, graph=graph)
        log(f"saved {save_catalogue(catalogue)}")
    learn_bases(session, catalogue, log=log, graph=graph)
    return catalogue


def base_screens(catalogue: dict) -> list[str]:
    """Every screen whose Cat Base has a background of its own: each chapter,
    and each saga that opens straight onto a Cat Base (Legend Stages)."""
    out = []
    for saga in catalogue.get("sagas", []):
        if saga.get("enters") == "chapters":
            out += [chapter_screen(saga, c["number"]) for c in saga.get("chapters", [])]
        elif saga.get("enters") == "cat_base":
            out.append(saga_screen(saga))
    return out


def missing_bases(graph, catalogue: dict, frame) -> list[str]:
    """The Cat Base backgrounds the device showing `frame` has yet to learn."""
    known = graph.profile_for(frame).bases()
    return [s for s in base_screens(catalogue) if s not in known]


def learn_bases(session, catalogue: dict, log=print, graph=None) -> int:
    """Learn each Cat Base background this device is missing, by walking the
    map to its card and stepping in. Returns how many were learned."""
    from .uigraph import Navigator, UIGraph

    full = UIGraph.load(carousels=False)
    extend(full, catalogue)
    if graph is not None:
        # Learn into the same profiles, with the same OCR, as the caller.
        full.profile_root, full._profiles, full._ocr = graph.profile_root, graph._profiles, graph._ocr
    missing = missing_bases(full, catalogue, session.screenshot())
    if not missing:
        return 0
    log(f"learning {len(missing)} Cat Base background(s) for this device")
    nav, learned = Navigator(session, full), 0
    for screen in missing:
        if not nav.goto(screen, log=log):
            log(f"    could not reach {screen}; its background stays unknown")
            continue
        enter = ENTER_CHAPTER if screen.startswith("chapter:") else ENTER_SAGA
        learned += _learn_base(session, full, screen, log, enter=enter)
    return learned


# -- the map side ------------------------------------------------------------

def saga_screen(saga: dict) -> str:
    """The map's name for a saga's card screen."""
    return f"saga:{slug(saga['name'])}"


def chapter_screen(saga: dict, number: int) -> str:
    """The map's name for a chapter's Cat Base screen."""
    return f"chapter:{slug(saga['name'])}:{number}"


def extend(graph, catalogue: dict) -> None:
    """Add one screen per card, and the drags, taps and X that join them."""
    from .uigraph import GENERIC_BACK, Screen, Transition

    if "saga_select" not in graph.screens or "base_select" not in graph.screens:
        return

    def tap_like(src, dst):
        """The generic carousel's own tap for this move, so coordinates live in one place."""
        return next((t for t in graph.transitions if t.src == src and t.dst == dst
                     and not t.action), None)

    saga_x = tap_like("saga_select", "title")
    enter = tap_like("saga_select", "base_select")
    chapter_enter = tap_like("base_select", "cat_base")
    chapter_x = next((t for t in graph.transitions if t.src == "base_select"
                      and t.dst == "saga_select" and t.label == "X"), None)
    add = graph.transitions.append

    sagas = catalogue.get("sagas", [])
    names = [saga_screen(s) for s in sagas]
    for i, saga in enumerate(sagas):
        me = names[i]
        graph.screens[me] = Screen(
            name=me, title=saga["name"], shapes=("close",),
            title_box=CARD_NAME_BOX, parent="saga_select",
            note=f"{saga['name']}, card {i + 1} of the saga carousel",
        )
        if i == 0:
            add(Transition("saga_select", me, label="drag to the first saga",
                           settle=1.0, action="seek:start"))
        if i + 1 < len(names):
            add(Transition(me, names[i + 1], label="next saga", settle=1.0, action="drag:left"))
            add(Transition(names[i + 1], me, label="previous saga", settle=1.0, action="drag:right"))
        if saga_x:
            add(Transition(me, "title", saga_x.x, saga_x.y, saga_x.label, saga_x.settle,
                           target="@close"))

        kind = saga.get("enters")
        ex, ey, es = (enter.x, enter.y, enter.settle) if enter else (*ENTER_SAGA, 3.2)
        if kind == "chapters":
            chapters = saga.get("chapters", [])
            cnames = [chapter_screen(saga, c["number"]) for c in chapters]
            for j, chapter in enumerate(chapters):
                cn = cnames[j]
                graph.screens[cn] = Screen(
                    name=cn, title=chapter["name"], shapes=("close",),
                    title_box=CARD_NAME_BOX, parent="base_select",
                    note=f"{saga['name']}, Chapter {chapter['number']}: {chapter['name']}",
                )
                if j == 0 and "chapter_back_card" in graph.screens:
                    add(Transition(cn, "chapter_back_card", label="previous chapter",
                                   settle=1.0, action="drag:right"))
                if j + 1 < len(cnames):
                    add(Transition(cn, cnames[j + 1], label="next chapter", settle=1.0,
                                   action="drag:left"))
                    add(Transition(cnames[j + 1], cn, label="previous chapter", settle=1.0,
                                   action="drag:right"))
                if chapter_enter:
                    add(Transition(cn, "cat_base", chapter_enter.x, chapter_enter.y,
                                   chapter_enter.label, chapter_enter.settle, target="@card"))
                if chapter_x:
                    add(Transition(cn, me, chapter_x.x, chapter_x.y, chapter_x.label,
                                   chapter_x.settle, target="@close"))
            if cnames:
                # Entering opens the chapter played last; the walk re-reads the
                # card and drags from wherever it lands.
                add(Transition(me, cnames[0], ex, ey, "enter selected saga", es, target="@card"))
        elif kind == "screen":
            # Named after the saga, so the name holds however its title reads.
            screen = saga.get("screen") or {}
            name = slug(saga["name"])
            if name not in graph.screens:
                graph.screens[name] = Screen(
                    name=name, title=screen.get("title") or saga["name"],
                    note=f"Opened by {saga['name']}; left by the back arrow. Found by the scan.",
                )
                add(Transition(name, me, *GENERIC_BACK, "Back", 2.4, target="@back"))
            add(Transition(me, name, ex, ey, "enter selected saga", es, target="@card"))
        elif kind in graph.screens:
            add(Transition(me, kind, ex, ey, "enter selected saga", es, target="@card"))
            if saga.get("notice") in graph.screens:
                add(Transition(me, saga["notice"], ex, ey, "enter selected saga", es,
                               target="@card"))
