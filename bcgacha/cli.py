"""bcgacha: draw Battle Cats capsules for the units you want, on a USB iPhone.

Run it with nothing after it and it asks what you want, step by step. Or say
it all at once:

  bcgacha                                   guided: what is known, then what to do
  bcgacha status                            what is saved: seed, owned cats, tickets, events
  bcgacha search kasli                      find a unit: tier, owned, which event rolls it
  bcgacha plan -t "Dark Kasli"              the route to it and the run on paper (spends nothing)
  bcgacha run -t "Dark Kasli" -t Gunduros --roll
                                            draw towards them, most wanted first
  bcgacha run --capsules cat --play-legends open Cat Capsules, then play Uncanny Legends
  bcgacha ui                                the live page: do all of the above from a browser

Every run on the phone serves the live page too (http://127.0.0.1:8765), which
shows everything the bot sees, thinks and does, and can stop it. The page can
start any run the command line can, and says the command for it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from . import jobs
from .console import Console, table

HOST, PORT = "127.0.0.1", 8765
MACHINES = ("cat", "lucky", "lucky_g")


# -- the options a run takes -----------------------------------------------------------

def _capsules(value: str) -> tuple[str, int]:
    machine, _, count = value.partition(":")
    machine = machine.strip().lower().replace("-", "_")
    if machine not in MACHINES:
        raise argparse.ArgumentTypeError(f"{machine!r}: one of {', '.join(MACHINES)}")
    try:
        return machine, int(count) if count else 0
    except ValueError:
        raise argparse.ArgumentTypeError(f"{count!r} is not a number of capsules") from None


def _count_or_all(value: str):
    if value.lower() == "all":
        return None
    try:
        return max(0, int(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r}: a number, or 'all'") from None


def _want_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("what to go for")
    g.add_argument("-t", "--target", action="append", default=[], metavar="UNIT",
                   help="a unit you want, by any name, nickname or #id; repeat it for more, "
                        "most wanted first (find names with: bcgacha search)")
    g.add_argument("-e", "--event", action="append", default=[], metavar="EVENT",
                   help="also want every unowned Uber of this live event; repeat for more. "
                        "With no target and no event, every live event's Ubers are wanted")
    g.add_argument("--legend-rares", action="store_true",
                   help="want those events' Legend Rares too")
    g.add_argument("--prefer", metavar="EVENT", help="the event whose Legend Rare comes first")
    g.add_argument("--update", action="store_true",
                   help="download the newest events and tier list first (bcgacha tools update)")
    g.add_argument("--platinum", type=_count_or_all, default=None, metavar="N|all",
                   help="Platinum tickets it may spend (default: all it holds, as read off "
                        "the screen), on targets first, then the best unowned Ubers by tier")


def _do_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("what to do on the phone")
    g.add_argument("--roll", action="store_true",
                   help="draw rare tickets towards what you want (asks first)")
    g.add_argument("--rare", type=_count_or_all, default=None, metavar="N|all",
                   help="rare tickets it may spend (default: all it holds)")
    g.add_argument("--capsules", action="append", type=_capsules, default=[], metavar="MACHINE[:N]",
                   help="open a normal machine with its own tickets: cat, lucky or lucky_g; "
                        ":N for N capsules, else until its tickets run out")
    g.add_argument("--play-legends", action="store_true",
                   help="play the Uncanny Legends with the Cat CPU, stage after stage")
    g.add_argument("--empty-storage", action="store_true", help="press Use all on Cat Storage first")
    g.add_argument("--rescan-owned", action="store_true", help="read the Cat Guide again")
    g.add_argument("--rescan-map", action="store_true", help="read the save's sagas and chapters again")
    h = p.add_argument_group("how")
    h.add_argument("-y", "--yes", action="store_true", help="spend without asking first")
    h.add_argument("--speed", type=float, default=1.0, help="delay multiplier: 0.8 is quicker (default 1)")
    h.add_argument("--no-page", action="store_true", help="do not serve the live page")
    h.add_argument("--open", action="store_true", help="open the live page in a browser")
    h.add_argument("--stay", action="store_true", help="keep the live page up after the run")
    h.add_argument("-q", "--quiet", action="store_true", help="hide the step-by-step navigation")
    h.add_argument("--port", type=int, default=PORT)
    h.add_argument("--serial", help="the iPhone to use, if more than one is attached")


def request_from_args(args) -> jobs.Request:
    return jobs.Request(
        targets=list(args.target), events=list(args.event), legend_rares=args.legend_rares,
        prefer=args.prefer, roll=getattr(args, "roll", False), rare=getattr(args, "rare", None),
        platinum=args.platinum, capsules=dict(getattr(args, "capsules", []) or []),
        uncanny=getattr(args, "play_legends", False), storage=getattr(args, "empty_storage", False),
        rescan_owned=getattr(args, "rescan_owned", False), rescan_map=getattr(args, "rescan_map", False),
        update=getattr(args, "update", False),
    )


# -- the phone -----------------------------------------------------------------------------

def _open_session(con: Console, serial=None):
    """The device session, or None with the reason said plainly."""
    from . import device
    from .session import DeviceSession

    if not device.attached():
        con.say(con.bad("No iPhone is plugged in."))
        con.say("  Plug it in by USB, unlock it, and tap Trust if it asks. Then run this again.")
        con.say("  (bcgacha tools probe says what the phone supports once it is attached)")
        return None
    con.say(con.dim("connecting to the iPhone..."))
    try:
        session = DeviceSession(serial)
        session.__enter__()
        return session
    except Exception as exc:
        con.say(con.bad(f"The iPhone is attached but would not connect: {exc}"))
        con.say("  Developer Mode must be on, and the developer disk image mounted:")
        con.say("    .venv/bin/pymobiledevice3 mounter auto-mount")
        return None


def _page_taken(port: int) -> bool:
    import socket

    with socket.socket() as s:
        return s.connect_ex((HOST, port)) == 0


def _run_on_phone(con: Console, request: jobs.Request, args) -> int:
    """Carry a request out on the phone, the live page up beside it."""
    from . import liveview

    if _page_taken(args.port):
        con.say(con.bad(f"The live page is already running at http://{HOST}:{args.port}"))
        con.say("  Only one thing may drive the phone. Start this run from that page, or stop it first.")
        con.say(con.dim(f"  (the page's Run panel takes the same choices: {request.command()})"))
        return 1
    session = _open_session(con, args.serial)
    if session is None:
        return 1
    try:
        view = liveview.LiveView(session, False, 0.3, echo=con, speed=args.speed)
        if not args.no_page:
            liveview.serve(view, HOST, args.port)
            con.say(f"Watch it live, and stop it, at {con.note(f'http://{HOST}:{args.port}')}")
            if args.open:
                import webbrowser

                webbrowser.open(f"http://{HOST}:{args.port}")
        ok, message = view.submit(request)
        if not ok:
            con.say(con.bad(message))
            return 1
        _wait(con, view)
        result = view.job
        _finish(con, view, result)
        if args.stay and not args.no_page:
            con.say(f"The page stays up at http://{HOST}:{args.port}; Ctrl+C to quit.")
            _block(view)
        return 0 if result["ok"] else 1
    finally:
        session.__exit__(None, None, None)


def _wait(con: Console, view) -> None:
    """Until the job ends. Ctrl+C asks it to stop between taps; twice quits."""
    stopping = False
    while not view.done.is_set():
        try:
            view.done.wait(0.5)
        except KeyboardInterrupt:
            if stopping:
                con.say(con.bad("quitting now"))
                raise SystemExit(130)
            stopping = True
            con.say(con.bad("stopping before the next tap (Ctrl+C again to quit at once)"))
            view.stop()


def _block(view) -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        view.stop()


def _finish(con: Console, view, job) -> None:
    took = round((job["ended"] or time.time()) - (job["started"] or time.time()))
    con.say()
    if job["ok"]:
        con.say(con.good(f"✓ Finished in {took // 60}m {took % 60}s."))
    else:
        con.say(con.bad(f"✗ Ended after {took // 60}m {took % 60}s: {job['result']}"))
    state = view.pipeline_state()
    rolls = state["rolls"]
    if rolls:
        new = [r for r in rolls if r["new"]]
        con.say(f"  {len(rolls)} draw{'s' if len(rolls) != 1 else ''}, {len(new)} new unit{'s' if len(new) != 1 else ''}"
                + (": " + ", ".join(r["expected"] for r in new if r.get("rarity", 0) >= 4) if new else ""))
    run = state["sections"].get("run")
    if run and run.get("remaining") is not None:
        con.say(f"  still wanted: {run['remaining']}")


# -- commands --------------------------------------------------------------------------------

def cmd_status(args) -> int:
    con = Console()
    from . import device

    s = jobs.status()
    phone = device.attached()
    ok, no = con.good("✓"), con.bad("✗")
    con.say(con.bold("What the bot knows"))
    con.say(f"  {ok if phone else no} iPhone      {'plugged in' if phone else 'not plugged in'}")
    if not s["data"]["ok"]:
        con.say(f"  {no} cat data    missing")
    else:
        con.say(f"  {ok} cat data    updated {s['data']['updated']}")
        t = s["tiers"]
        con.say(f"  {ok if t['ok'] else no} tier list   " + (f"{t['cats']} cats ranked, {t['updated']}" if t["ok"] else "missing"))
        m = s["map"]
        con.say(f"  {ok if m['ok'] else no} save's map  " + (f"{m['sagas']} sagas" if m["ok"] else "not read yet (the first run reads it)"))
        o = s["owned"]
        con.say(f"  {ok if o['ok'] else no} owned cats  " + (f"{o['owned']}, read {o['scanned_at']}" if o["ok"] else "not read yet (the first run reads the Cat Guide)"))
        a = s["account"]
        if a["ok"]:
            con.say(f"  {ok} seed        {a['seed']} at {a['position']}"
                    f"{', confirmed by a draw' if a['confirmed'] else ', not yet confirmed by a draw'}")
            con.say(f"    tickets     {a['rare'] if a['rare'] is not None else '?'} rare, "
                    f"{a['platinum'] if a['platinum'] is not None else '?'} Platinum "
                    "(as last read off the screen; a draw run reads them again)")
            con.say(f"    storage     {a['storage']}")
        else:
            con.say(f"  {no} seed        unknown ({s['captures']} saved result screens to find it from)")
        con.say()
        checked = (f"  (the phone's capsule screen checked at {s['screen_checked']})" if s.get("screen_checked")
                   else "  (as scheduled; a draw run checks which the phone shows)")
        con.say(con.bold("Live events") + con.dim(checked))
        shown = {True: "shown", False: "NOT shown", None: "?"}
        rows = [[e["label"][:40], shown[e.get("on_phone")], e["end"], f"{e['ubers_missing']}/{e['ubers']}",
                 f"{e['legend_rares_missing']}/{e['legend_rares']}" if e["legend_rares"] else "-",
                 e["best_missing"]] for e in s["events"]]
        con.say("  " + table(rows, ["event", "on phone", "ends", "Ubers missing", "Legend Rares", "best missing"])
                .replace("\n", "\n  "))
    if s["next"]:
        con.say()
        con.say(con.bold("Next"))
        for line in s["next"]:
            con.say(f"  • {line}")
    return 0


def cmd_search(args) -> int:
    from . import units

    con = Console()
    catalogue = units.load()
    query = " ".join(args.name)
    hits = catalogue.search(query, limit=args.limit)
    if not hits:
        con.say(f"No unit is called anything like {query!r}.")
        return 1
    rows = [[f"#{u.id}", u.name, u.rarity_name, u.tier,
             {True: "owned", False: "not owned", None: "?"}[u.owned], u.where(2)] for u in hits]
    con.say(table(rows, ["id", "unit", "rarity", "tier", "you", "rolls on"]))
    first = hits[0]
    other = [f for f in first.forms if f != first.name]
    if other:
        con.say(con.dim(f"\n{first.name} is also called: {', '.join(other)}"))
    con.say(con.dim(f"\nWant one? bcgacha run -t \"{first.name}\" --roll   (or -t #{first.id})"))
    return 0


def _run_offline(con: Console, request: jobs.Request) -> bool:
    """A run needing no phone: a plan, an update."""
    from . import pipeline as P
    from .data import load
    from .uigraph import UIGraph

    graph = UIGraph.load()

    class LazyOCR:                   # only finding the seed from captures reads text
        def __call__(self, *a, **k):
            return graph.ocr(*a, **k)

    try:
        dataset = load()
    except FileNotFoundError:
        dataset = None               # an update fetches it
    ctx = P.Context(session=None, graph=graph, ocr=LazyOCR(), dataset=dataset,
                    log=con.log, publish=con.publish)
    return jobs.run(ctx, request)[0]


def cmd_update(args) -> int:
    """The newest events and tier list, downloaded; no phone needed."""
    con = Console()
    ok = _run_offline(con, jobs.Request(only=["update"]))
    if ok:
        con.say()
        con.say(con.good("✓ Up to date.") + " See what is live: " + con.note("bcgacha status"))
        con.say(con.dim("  (a draw run checks which of the events the phone shows; "
                        "bcgacha tools upkeep tickets does it on its own)"))
    return 0 if ok else 1


def cmd_plan(args) -> int:
    """A run with nothing spent: from what is saved, no phone needed."""
    con = Console(quiet=args.quiet)
    request = request_from_args(args)
    ok = _run_offline(con, request)
    con.say()
    if ok:
        con.say(con.good("✓ Planned; nothing was spent.") + " To draw it: "
                + con.note(request.command().replace(" --update", "").replace("bcgacha run", "bcgacha run --roll", 1)))
        con.say(con.dim("  (the plan is from the schedule: a run checks which events the phone shows first)"))
    return 0 if ok else 1


def cmd_run(args) -> int:
    con = Console(quiet=args.quiet)
    request = request_from_args(args)
    if not request.spends and not (request.rescan_map or request.rescan_owned or request.storage):
        con.say("Nothing to do on the phone was asked for: this is a plan.")
        con.say(con.dim("  Add --roll to draw, --capsules cat to open Cat Capsules, --play-legends to battle."))
        return cmd_plan(args)
    con.say(con.bold("This run will:"))
    for line in request.summary():
        con.say(f"  • {line}")
    con.announced = True
    if request.spends and not args.yes:
        if not sys.stdin.isatty():
            con.say(con.bad("It spends tickets: add --yes to go ahead without being asked."))
            return 1
        if input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
            con.say("Nothing done.")
            return 1
    return _run_on_phone(con, request, args)


def cmd_ui(args) -> int:
    """The live page on its own: every run started from the browser."""
    from . import liveview

    con = Console()
    if _page_taken(args.port):
        con.say(f"The live page is already running: http://{HOST}:{args.port}")
        return 1
    if args.replay:
        view = liveview.replay_view(args.replay, args.interval, args.profiles)
        session = None
    else:
        session = _open_session(con, args.serial)
        if session is None:
            con.say(con.dim("  (bcgacha ui --replay captures/ shows the page on saved frames instead)"))
            return 1
        view = liveview.LiveView(session, False, args.interval, args.profiles, speed=args.speed)
    try:
        liveview.serve(view, HOST, args.port)
        if not args.replay:
            view.catch_up()
        url = f"http://{HOST}:{args.port}"
        con.say(f"The live page is up at {con.note(url)} -- Ctrl+C here to close it.")
        con.say(con.dim("  Everything is done from the page: plan, draw, capsules, Uncanny Legends."))
        if not args.no_browser:
            import webbrowser

            webbrowser.open(url)
        _block(view)
    finally:
        if session is not None:
            session.__exit__(None, None, None)
    return 0


def cmd_guided(args) -> int:
    """Ask what the person wants, show the plan, then do it."""
    from . import units

    con = Console()
    con.say(con.bold("Battle Cats capsule bot") + con.dim("  (bcgacha --help lists every command)"))
    con.say()
    cmd_status(args)
    con.say()
    try:
        return _guided(con, units, args)
    except (EOFError, KeyboardInterrupt):
        con.say("\nNothing done.")
        return 1


def _ask(prompt: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    answer = input(f"{prompt}{shown}: ").strip()
    return answer or default


def _guided(con: Console, units, args) -> int:
    con.say(con.bold("What would you like to do?") + con.dim("  (numbers, comma separated)"))
    choices = [
        ("roll", "Draw rare tickets for units I want"),
        ("plan", "Just show me the plan -- spend nothing"),
        ("capsules", "Open Cat Capsules or Lucky Capsules"),
        ("legends", "Play the Uncanny Legends with the Cat CPU"),
        ("page", "Open the live page and decide there"),
    ]
    for n, (_, text) in enumerate(choices, 1):
        con.say(f"  {n}  {text}")
    picked = set()
    for part in _ask("Choose", "2").replace(" ", ",").split(","):
        if part.strip().isdigit() and 1 <= int(part) <= len(choices):
            picked.add(choices[int(part) - 1][0])
    if "page" in picked:
        return cmd_ui(argparse.Namespace(port=PORT, replay=None, serial=None, interval=0.3, profiles=None,
                                         speed=1.0, no_browser=False))
    req = jobs.Request()
    if picked & {"roll", "plan"}:
        catalogue = units.load()
        con.say()
        con.say(con.bold("Which units do you want?") + con.dim("  Type part of a name; Enter on its own when done."))
        ids = []
        while True:
            query = _ask(f"  unit {len(ids) + 1}")
            if not query:
                break
            hits = catalogue.search(query, limit=8)
            if not hits:
                con.say("    nothing is called that; try another spelling")
                continue
            for n, u in enumerate(hits, 1):
                con.say(f"    {n}) {u.line()}")
            pick = _ask("    which one (Enter to skip)", "1" if len(hits) == 1 else "")
            if pick.isdigit() and 1 <= int(pick) <= len(hits):
                u = hits[int(pick) - 1]
                if not u.obtainable:
                    con.say(con.bad(f"    {u.name} is not in any live event: it cannot be drawn today"))
                    continue
                ids.append(u)
                con.say(con.good(f"    + {u.name}") + (" (already owned)" if u.owned else ""))
        req.targets = [catalogue.query_for(u) for u in ids]
        events = [e for e in jobs.status()["events"] if not e["platinum"] and e.get("on_phone") is not False]
        default = "none" if ids else "all"
        con.say()
        con.say(con.bold("Also want every unowned Uber of some events?"))
        for n, e in enumerate(events, 1):
            con.say(f"    {n}) {e['label'][:40]}  ({e['ubers_missing']} of {e['ubers']} Ubers missing)")
        answer = _ask("  numbers, 'all' or 'none'", default).lower()
        if answer == "all":
            req.events = [e["label"] for e in events] if ids else []
        elif answer != "none":
            req.events = [events[int(p) - 1]["key"] for p in answer.replace(" ", ",").split(",")
                          if p.isdigit() and 1 <= int(p) <= len(events)]
        req.platinum = _count_or_all(_ask("How many Platinum tickets may it spend? (a number or 'all';"
                                          " the count held is read off the screen)", "all"))
        if "roll" in picked:
            req.roll = True
            req.rare = _count_or_all(_ask("How many rare tickets may it spend? (a number or 'all')", "all"))
    if "capsules" in picked:
        con.say()
        con.say(con.bold("Which machines?") + con.dim("  cat, lucky, lucky_g -- with :N for N capsules"))
        for part in _ask("  machines", "cat").replace(" ", ",").split(","):
            if part.strip():
                try:
                    machine, n = _capsules(part)
                    req.capsules[machine] = n
                except argparse.ArgumentTypeError as exc:
                    con.say(f"    skipped: {exc}")
    if "legends" in picked:
        req.uncanny = True
    con.say()
    con.say(con.bold("This run will:"))
    for line in req.summary():
        con.say(f"  • {line}")
    con.say(con.dim(f"  next time, straight from the command line: {req.command()}"))
    con.announced = True
    run_args = argparse.Namespace(port=PORT, serial=None, speed=1.0, no_page=False, open=False,
                                  stay=False, quiet=False, yes=True)
    if not req.spends:
        ns = argparse.Namespace(**vars(run_args), target=req.targets, event=req.events,
                                legend_rares=False, prefer=None, platinum=req.platinum)
        return cmd_plan(ns)
    if _ask("Go ahead? (y/n)", "n").lower() not in ("y", "yes"):
        con.say("Nothing done.")
        return 1
    return _run_on_phone(con, req, run_args)


# -- tools: single steps, for looking closer ---------------------------------------------------

def cmd_probe(args) -> int:
    from . import device

    caps = device.capabilities()
    print(f"device          {caps.product_type}  iOS {caps.ios_version}")
    print(f"developer mode  {'on' if caps.developer_mode else 'OFF'}")
    print(f"DDI mounted     {'yes' if caps.ddi_mounted else 'NO'}")
    print(f"native size     {caps.native_size}")
    print(f"screen capture  {'WORKS' if caps.can_screenshot else 'unavailable'}")
    print(f"synthetic taps  {'WORKS' if caps.can_tap else 'UNAVAILABLE'}")
    if caps.tap_blocked_reason:
        print(f"                {caps.tap_blocked_reason}")
    return 0 if caps.can_screenshot else 1


def cmd_screenshot(args) -> int:
    from . import device

    dest = Path(args.output)
    start = time.time()
    device.screenshot(dest)
    print(f"{dest} ({dest.stat().st_size:,} bytes, {time.time() - start:.2f}s)")
    return 0


def cmd_banners(args) -> int:
    from .data import load

    ds = load(args.lang)
    when = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    rows = ds.live_banners(when)
    if args.recent:
        rows = [b for b in rows if b.start_on >= when - dt.timedelta(days=args.recent)]
    for b in rows:
        pools = "/".join(str(len(b.slots.get(r) or [])) for r in (2, 3, 4, 5))
        flag = "G11" if b.guaranteed else ("S15" if b.step_up else "   ")
        print(f"{b.key:20} {flag} uber={b.uber:<5} R/S/U/L={pools:<12} {b.name[:48]}")
    print(f"\n{len(rows)} banner(s) live on {when}", file=sys.stderr)
    return 0


def cmd_predict(args) -> int:
    from .data import RARITY_NAMES, load
    from .gacha import TRACK_A, TRACK_B, Gacha

    ds = load(args.lang)
    banner = ds.find_banner(args.event)
    track = TRACK_B if args.track.upper() == "B" else TRACK_A
    rolls = Gacha(banner, args.seed, ds).walk(args.count, index=args.start, track=track)
    print(f"{banner.key}  {banner.name[:60]}")
    print(f"seed {args.seed}  starting {args.start}{args.track.upper()}\n")
    for n, roll in enumerate(rolls, 1):
        mark = f"  (dupe {ds.cat_name(roll.duped_from)} rerolled, +{roll.reroll_steps})" if roll.was_rerolled else ""
        guaranteed = f"   [G: {ds.cat_name(roll.guaranteed_cat_id)}]" if roll.guaranteed_cat_id is not None else ""
        print(f"{n:>4}. {roll.sequence:>4}{roll.track_name}  "
              f"{RARITY_NAMES[roll.rarity]:<12} {ds.cat_name(roll.cat_id):<26}{guaranteed}{mark}")
    return 0


def cmd_ubers(args) -> int:
    from .data import load
    from .planner import uber_positions

    ds = load(args.lang)
    banner = ds.find_banner(args.event)
    hits = uber_positions(args.seed, banner, args.count, ds)
    print(f"{banner.key}  uber weight {banner.uber}/10000")
    for pos, _cat_id, name in hits:
        print(f"  {pos:>5}A  {name}")
    print(f"\n{len(hits)} uber/legend in {args.count} rolls", file=sys.stderr)
    return 0


def cmd_find_seed(args) -> int:
    from .data import load
    from .seedfind import resolve_names, search

    ds = load(args.lang)
    banner = ds.find_banner(args.event)
    names = [n.strip() for n in args.cats.split(",") if n.strip()]
    observed = resolve_names(names, banner, ds)
    print(f"searching 2^32 seeds for {len(observed)} rolls on {banner.key}", file=sys.stderr)
    started = time.time()

    def progress(done, found):
        sys.stderr.write(f"\r  {100 * done / (1 << 32):5.1f}%  survivors={found:<9} {time.time() - started:6.1f}s")
        sys.stderr.flush()

    results = search(banner, observed, ds, progress=progress)
    sys.stderr.write("\n")
    if not results:
        print("no seed matches -- check the cat names and their order", file=sys.stderr)
        return 1
    for cand in results:
        print(f"seed {cand.seed}")
        print(f"  replay: {' -> '.join(cand.rolls)}")
    if len(results) > 1:
        print(f"\n{len(results)} seeds fit; roll once more and re-run", file=sys.stderr)
    return 0


def cmd_resync(args) -> int:
    """Recover the saved position after draws made outside the bot."""
    from . import events as live
    from . import units
    from .data import load
    from .state import Account, resync

    ds = load(args.lang)
    account = Account.load()
    unit, hits = units.load(ds).resolve(args.cat)
    if unit is None:
        print(f"{args.cat!r} could be: {', '.join(h.name for h in hits[:5]) or 'nothing'}", file=sys.stderr)
        return 1
    normal = [e.banner for e in live.live_events(ds) if not e.platinum]
    was = account.position
    if resync(account, unit.id, normal, ds, window=args.window) is None:
        print(f"{unit.name!r} appears at more than one position within "
              f"{args.window} rolls -- roll once more and try again", file=sys.stderr)
        return 1
    account.save()
    print(f"{unit.name}: {was} -> {account.position}")
    return 0


def cmd_tiers(args) -> int:
    from . import tiers as T
    from .data import load

    entries = T.parse(T.fetch_text())
    tier_list = T.match(entries, load(args.lang))
    tier_list.save()
    print(f"{len(entries)} entries, {len(tier_list.by_cat)} cats matched, {len(tier_list.unmatched)} unmatched")
    for miss in tier_list.unmatched[:10]:
        print("  unmatched:", miss)
    return 0


def cmd_map(args) -> int:
    from . import mapdraw

    sys.argv = ["mapdraw"] + (["--out", args.out] if args.out else [])
    return mapdraw.main()


def cmd_upkeep(args) -> int:
    """One task alone, read afresh: the map, the owned list, or Use all."""
    con = Console(quiet=args.quiet)
    tasks = ["capsule" if t == "tickets" else t for t in args.tasks]
    request = jobs.Request(only=tasks, rescan_map="map" in tasks, rescan_owned="owned" in tasks,
                           storage="storage" in tasks)
    return _run_on_phone(con, request, args)


# -- the parser -------------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bcgacha", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default="en", choices=["en", "jp", "kr", "tw"], help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("status", help="what is saved: phone, seed, owned cats, tickets, live events") \
        .set_defaults(func=cmd_status)

    p = sub.add_parser("search", help="find a unit by any of its names")
    p.add_argument("name", nargs="+")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("plan", help="the route and the run on paper; spends nothing, needs no phone",
                       description="Plan a run from what is saved: nothing is spent and no phone is needed.")
    _want_options(p)
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="do it on the phone: draw, open capsules, play Uncanny Legends",
                       description="Carry out a run on the phone, watched live at "
                                   f"http://{HOST}:{PORT}. Set up (map, owned cats, seed) happens "
                                   "first, only as needed.")
    _want_options(p)
    _do_options(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ui", help="the live page alone: start and watch runs from a browser")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--serial", help="the iPhone to use, if more than one is attached")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser")
    p.add_argument("--speed", type=float, default=1.0, help="delay multiplier for runs")
    p.add_argument("--interval", type=float, default=0.3, help="seconds between frames while idle")
    p.add_argument("--replay", nargs="+", type=Path, metavar="PATH",
                   help="saved frames, or folders of them, in place of the phone (plans only)")
    p.add_argument("--profiles", type=Path, metavar="DIR",
                   help="learn device profiles here instead of state/devices")
    p.set_defaults(func=cmd_ui)

    tools = sub.add_parser("tools", help="single steps for a closer look: probe, predict, resync, ...")
    ts = tools.add_subparsers(dest="tool", metavar="TOOL", required=True)
    ts.add_parser("probe", help="what the attached iPhone supports").set_defaults(func=cmd_probe)
    p = ts.add_parser("screenshot", help="save the phone's screen as a PNG")
    p.add_argument("output")
    p.set_defaults(func=cmd_screenshot)
    p = ts.add_parser("upkeep", help="read one thing afresh on the phone: map, owned, storage, tickets")
    p.add_argument("tasks", nargs="+", choices=["map", "owned", "storage", "tickets"],
                   help="tickets: which events the capsule screen shows, and the rare and Platinum counters")
    for flag, kw in (("--port", dict(type=int, default=PORT)), ("--serial", {}),
                     ("--speed", dict(type=float, default=1.0))):
        p.add_argument(flag, **kw)
    for flag in ("--no-page", "--open", "--stay", "--quiet"):
        p.add_argument(flag, action="store_true")
    p.set_defaults(func=cmd_upkeep)
    ts.add_parser("update", help="download the newest events and tier list (no phone needed)") \
        .set_defaults(func=cmd_update)
    ts.add_parser("tiers", help="fetch the community tier list again").set_defaults(func=cmd_tiers)
    p = ts.add_parser("resync", help="fix the position after draws made by hand")
    p.add_argument("--cat", required=True, help="the cat the last draw actually gave")
    p.add_argument("--window", type=int, default=40)
    p.set_defaults(func=cmd_resync)
    p = ts.add_parser("banners", help="every banner the schedule lists on a date")
    p.add_argument("--date")
    p.add_argument("--recent", type=int, metavar="DAYS")
    p.set_defaults(func=cmd_banners)
    p = ts.add_parser("predict", help="the cats a seed gives on one banner")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--track", default="A", choices=["A", "B", "a", "b"])
    p.set_defaults(func=cmd_predict)
    p = ts.add_parser("ubers", help="which positions give an Uber on one banner")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--count", type=int, default=200)
    p.set_defaults(func=cmd_ubers)
    p = ts.add_parser("find-seed", help="the seed from draws you made and wrote down")
    p.add_argument("--event", required=True)
    p.add_argument("--cats", required=True, help="comma separated, in draw order")
    p.set_defaults(func=cmd_find_seed)
    p = ts.add_parser("map", help="draw the screen map to an HTML page")
    p.add_argument("--out")
    p.set_defaults(func=cmd_map)
    return ap


def _interrupt(*_args) -> None:
    raise KeyboardInterrupt


def main(argv=None) -> int:
    import signal

    # A kill stops a run as Ctrl+C does: between taps, the device let go.
    signal.signal(signal.SIGTERM, _interrupt)
    if signal.getsignal(signal.SIGINT) is signal.SIG_IGN:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    args = parser().parse_args(argv)
    if not getattr(args, "func", None):
        if not sys.stdin.isatty():
            parser().print_help()
            return 0
        return cmd_guided(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
