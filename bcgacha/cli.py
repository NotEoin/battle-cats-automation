"""Command line entry points for the capsule automation."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from . import device
from .data import RARITY_NAMES, load
from .gacha import Gacha, TRACK_A, TRACK_B
from .seedfind import resolve_names, search


def cmd_probe(args) -> int:
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
    dest = Path(args.output)
    start = time.time()
    device.screenshot(dest)
    print(f"{dest} ({dest.stat().st_size:,} bytes, {time.time() - start:.2f}s)")
    return 0


def cmd_banners(args) -> int:
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
    ds = load(args.lang)
    banner = ds.find_banner(args.event)
    track = TRACK_B if args.track.upper() == "B" else TRACK_A
    gacha = Gacha(banner, args.seed, ds)
    rolls = gacha.walk(args.count, index=args.start, track=track)
    print(f"{banner.key}  {banner.name[:60]}")
    print(f"seed {args.seed}  starting {args.start}{args.track.upper()}\n")
    for n, roll in enumerate(rolls, 1):
        mark = ""
        if roll.was_rerolled:
            mark = f"  (dupe {ds.cat_name(roll.duped_from)} rerolled, +{roll.reroll_steps})"
        guaranteed = ""
        if roll.guaranteed_cat_id is not None:
            guaranteed = f"   [G: {ds.cat_name(roll.guaranteed_cat_id)}]"
        print(
            f"{n:>4}. {roll.sequence:>4}{roll.track_name}  "
            f"{RARITY_NAMES[roll.rarity]:<12} {ds.cat_name(roll.cat_id):<26}"
            f"{guaranteed}{mark}"
        )
    return 0


def cmd_find_seed(args) -> int:
    ds = load(args.lang)
    banner = ds.find_banner(args.event)
    names = [n.strip() for n in args.cats.split(",") if n.strip()]
    observed = resolve_names(names, banner, ds)
    print(f"searching 2^32 seeds for {len(observed)} rolls on {banner.key}", file=sys.stderr)
    started = time.time()

    def progress(done, found):
        pct = 100 * done / (1 << 32)
        sys.stderr.write(
            f"\r  {pct:5.1f}%  survivors={found:<9} {time.time() - started:6.1f}s"
        )
        sys.stderr.flush()

    results = search(banner, observed, ds, progress=progress if args.progress else None)
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


def cmd_ubers(args) -> int:
    from .planner import uber_positions

    ds = load(args.lang)
    banner = ds.find_banner(args.event)
    hits = uber_positions(args.seed, banner, args.count, ds)
    print(f"{banner.key}  uber weight {banner.uber}/10000")
    for pos, _cat_id, name in hits:
        print(f"  {pos:>5}A  {name}")
    print(f"\n{len(hits)} uber/legend in {args.count} rolls", file=sys.stderr)
    return 0


def _live_banners(ds, when=None):
    """The banners actually selectable on the capsule screen right now.

    The schedule re-lists the same pool under several dates as a run is
    extended, so the raw list contains duplicates that share a name, a pool and
    their rates. Those are indistinguishable on screen and switching between
    them achieves nothing, so only the latest of each is kept.
    """
    import datetime as dt

    when = when or dt.date.today()
    live = ds.live_banners(when)
    recent = [
        b for b in live
        if b.uber < 10000 and b.start_on >= when - dt.timedelta(days=45)
    ]
    unique: dict[tuple, object] = {}
    for banner in sorted(recent, key=lambda b: b.start_on):
        key = (banner.gacha_id, banner.rare, banner.supa, banner.uber,
               banner.guaranteed, banner.step_up)
        unique[key] = banner          # later run of the same pool wins
    # The Platinum pool GROWS as new ubers are released, and the schedule keeps
    # every past snapshot of it -- 70 cats in 2018 against 134 now. They all
    # look "live" by date, so taking the first match silently uses an eight
    # year old pool, and since the unit is slot_seed % pool_size that predicts
    # an entirely different cat. Always take the most recent snapshot.
    platinum_runs = [b for b in live if b.uber == 10000]
    platinum = max(platinum_runs, key=lambda b: (b.start_on, len(b.slots.get(4) or []))) \
        if platinum_runs else None
    return list(unique.values()), platinum


def _build_planner(ds, args):
    from .catindex import OwnedIndex
    from .planner import Planner
    from .scoring import Scorer
    from .tiers import TierList

    owned = OwnedIndex.load().owned
    try:
        tier_list = TierList.load()
    except FileNotFoundError:
        tier_list = None
        print("no tier data -- run 'bcgacha tiers' to fetch it", file=sys.stderr)
    normal, platinum = _live_banners(ds)
    scorer = Scorer(owned=owned, tiers=tier_list)
    tickets = getattr(args, "platinum", 0)
    planner = Planner(
        ds, normal, scorer,
        platinum_banner=platinum,
        platinum_tickets=tickets,
    )
    if tickets:
        print(f"{tickets} platinum ticket(s) reserved for:", file=sys.stderr)
        for cat in sorted(planner.platinum_wanted, key=lambda c: (tier_list.rank_of(c) if tier_list else 0)):
            tier = tier_list.tier_of(cat) if tier_list else "?"
            print(f"    {tier:<4} {ds.cat_name(cat)}", file=sys.stderr)
    return planner, owned, tier_list


def cmd_tiers(args) -> int:
    from . import tiers as T

    ds = load(args.lang)
    entries = T.parse(T.fetch_text())
    tier_list = T.match(entries, ds)
    tier_list.save()
    print(f"{len(entries)} entries, {len(tier_list.by_cat)} cats matched, "
          f"{len(tier_list.unmatched)} unmatched")
    for miss in tier_list.unmatched[:10]:
        print("  unmatched:", miss)
    return 0


def cmd_index(args) -> int:
    from .catindex import CatIndexer
    from .data import BASIC, EX, LEGEND, RARE, SUPER_RARE, UBER
    from .session import DeviceSession

    ds = load(args.lang)
    rarities = {BASIC, EX, RARE, SUPER_RARE, UBER, LEGEND}
    with DeviceSession() as session:
        indexer = CatIndexer(session, ds)
        if not args.no_reset:
            if not indexer.open_guide():
                return 1
            indexer.clear_filter()
            indexer.tap((0.285, 0.258), settle=1.8)
            indexer.dismiss_popup()
        result = indexer.walk(rarities, limit=args.limit)
    result.save()
    print(f"owned={len(result.owned)} locked={result.locked_seen} "
          f"walked={result.entries_walked} unresolved={len(result.unresolved)}")
    return 0


def cmd_owned(args) -> int:
    from collections import Counter

    from .catindex import OwnedIndex
    from .data import RARITY_NAMES

    ds = load(args.lang)
    index = OwnedIndex.load()
    counts = Counter(ds.rarity_of(c) for c in index.owned)
    print(f"{len(index.owned)} cats indexed ({index.locked_seen} seen locked)")
    for rarity, n in sorted(counts.items()):
        print(f"  {RARITY_NAMES.get(rarity, rarity):<12} {n}")
    return 0


def cmd_plan(args) -> int:
    from .state import Account

    ds = load(args.lang)
    account = Account.load()
    planner, owned, _ = _build_planner(ds, args)
    plan = planner.plan(
        account.seed, rolls=args.count,
        index=account.index, track=account.track,
        previous_cat=account.last_cat_id,
    )
    print(f"seed {account.seed} at {account.position}, {len(owned)} cats owned\n")
    print(plan.summary(ds))
    print(f"\n{len(plan.new_units)} new unit(s), {plan.banner_switches()} banner switches, "
          f"{plan.platinum_spent} platinum")
    return 0


def cmd_resync(args) -> int:
    """Recover the saved position after rolls were made outside the bot."""
    from .catindex import match_name
    from .state import Account, resync

    ds = load(args.lang)
    account = Account.load()
    normal, _platinum = _live_banners(ds)
    names = [n for e in ds.cats.values() for n in (e.get("name") or []) if n]
    hit = match_name(args.cat, names)
    if not hit:
        print(f"no cat matching {args.cat!r}", file=sys.stderr)
        return 1
    cat_id = next(
        cid for cid, e in ds.cats.items()
        if any(n == hit for n in (e.get("name") or []) if n)
    )
    was = account.position
    if resync(account, cat_id, normal, ds, window=args.window) is None:
        print(f"{hit!r} appears at more than one position within "
              f"{args.window} rolls -- roll once more and try again", file=sys.stderr)
        return 1
    account.save()
    print(f"{hit}: {was} -> {account.position}")
    return 0


def _goal_setup(ds, args):
    """Planner and goal for a goal-driven run."""
    from . import goals
    from .catindex import OwnedIndex
    from .planner import Planner
    from .scoring import Scorer
    from .tiers import TierList

    owned = OwnedIndex.load().owned
    try:
        tier_list = TierList.load()
    except FileNotFoundError:
        tier_list = None
    normal, platinum = _live_banners(ds)
    goal = goals.build(
        ds, tier_list, owned, normal, platinum,
        platinum_tickets=args.platinum, preferred_banner=args.prefer,
    )
    scorer = Scorer(owned=set(owned), tiers=tier_list, priority=goal.priority)
    planner = Planner(
        ds, normal, scorer, platinum_banner=platinum,
        platinum_tickets=args.platinum, platinum_wanted=goal.platinum,
    )
    return planner, goal, tier_list, owned


def cmd_goal(args) -> int:
    """Roll towards a set of wanted units until they are all unlocked."""
    from pathlib import Path

    from .bannerpick import BannerPicker
    from .runner import Mode, Runner
    from .safety import SafeTapper
    from .session import DeviceSession
    from .state import Account
    from .timing import Humaniser

    ds = load(args.lang)
    account = Account.load()
    planner, goal, tier_list, owned = _goal_setup(ds, args)
    print(goal.describe(ds, tier_list, owned))
    print(f"\nseed {account.seed} at {account.position}\n")
    if args.simulate:
        from . import goals as G
        from .data import LEGEND

        unlocked = G.simulate(
            planner, goal, account.seed, account.index, account.track,
            account.last_cat_id, args.simulate, args.platinum,
        )
        print(f"{'roll':>5} {'pos':>6} {'kind':<7} {'tier':<5} unit")
        for u in unlocked:
            kind = "LEGEND" if u["rarity"] == LEGEND else "uber"
            tier = tier_list.tier_of(u["cat_id"]) if tier_list else "?"
            mark = " [PLATINUM]" if u["platinum"] else ""
            print(f"{u['roll']:>5} {u['position']:>6} {kind:<7} {tier:<5} "
                  f"{ds.cat_name(u['cat_id'])}{mark}")
        left = len(goal.remaining(planner.scorer.owned))
        print(f"\n{len(unlocked)} new unit(s) over {args.simulate} tickets; "
              f"{left} still wanted afterwards")
        return 0
    if args.dry_run:
        plan = planner.plan(
            account.seed, rolls=args.count, index=account.index,
            track=account.track, previous_cat=account.last_cat_id,
        )
        print(plan.summary(ds))
        return 0

    human = Humaniser(scale=args.speed, enabled=not args.no_humanise)
    with DeviceSession() as session:
        tapper = SafeTapper(session, capture_dir=Path(args.captures), humaniser=human)
        runner = Runner(
            tapper, ds, account, planner, capture_dir=Path(args.captures),
            picker=BannerPicker(session, ds), goal=goal,
        )
        report = runner.run(mode=Mode.GOAL, max_tickets=args.max_tickets)
    account.save()
    print(f"\nrolled {report.rolled}, tickets spent {report.tickets_spent}, "
          f"storage emptied {report.storage_emptied}x")
    if report.new_units:
        print("new units:", ", ".join(report.new_units))
    print("stopped:", report.stopped_because)
    return 0


def cmd_run(args) -> int:
    from pathlib import Path

    from .bannerpick import BannerPicker
    from .runner import Mode, Runner
    from .safety import SafeTapper
    from .session import DeviceSession
    from .state import Account
    from .timing import Humaniser

    ds = load(args.lang)
    account = Account.load()
    planner, _owned, _tiers = _build_planner(ds, args)
    human = Humaniser(scale=args.speed, enabled=not args.no_humanise)
    with DeviceSession() as session:
        tapper = SafeTapper(session, capture_dir=Path(args.captures), humaniser=human)
        picker = None if args.pin_banner else BannerPicker(session, ds)
        runner = Runner(
            tapper, ds, account, planner,
            capture_dir=Path(args.captures),
            picker=picker, pin_banner=args.pin_banner,
        )
        report = runner.run(
            mode=Mode(args.mode), max_tickets=args.max_tickets,
            verify=not args.no_verify,
        )
    account.save()
    print(f"\nrolled {report.rolled}, tickets spent {report.tickets_spent}, "
          f"storage emptied {report.storage_emptied}x")
    if report.new_units:
        print("new units:", ", ".join(report.new_units))
    print("stopped:", report.stopped_because)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bcgacha", description=__doc__)
    ap.add_argument("--lang", default="en", choices=["en", "jp", "kr", "tw"])
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="report what the attached iPhone supports").set_defaults(
        func=cmd_probe
    )

    p = sub.add_parser("screenshot", help="save the device screen as a PNG")
    p.add_argument("output")
    p.set_defaults(func=cmd_screenshot)

    p = sub.add_parser("banners", help="list banners live on a date")
    p.add_argument("--date")
    p.add_argument("--recent", type=int, metavar="DAYS", help="only ones started recently")
    p.set_defaults(func=cmd_banners)

    p = sub.add_parser("predict", help="show the cats a seed will produce")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--track", default="A", choices=["A", "B", "a", "b"])
    p.set_defaults(func=cmd_predict)

    sub.add_parser("tiers", help="refresh community tier rankings").set_defaults(func=cmd_tiers)

    p = sub.add_parser("index", help="scan the Cat Guide for owned cats")
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--no-reset", action="store_true", help="start from the current entry")
    p.set_defaults(func=cmd_index)

    sub.add_parser("owned", help="summarise the indexed collection").set_defaults(func=cmd_owned)

    p = sub.add_parser("plan", help="show the planned rolls")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--platinum", type=int, default=0, help="platinum tickets available")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="roll capsules according to a plan")
    p.add_argument("--mode", default="until-target",
                   choices=["until-target", "max-tickets", "until-storage-full", "all"])
    p.add_argument("--max-tickets", type=int, default=50)
    p.add_argument("--platinum", type=int, default=0)
    p.add_argument("--speed", type=float, default=1.0, help="delay multiplier")
    p.add_argument("--no-humanise", action="store_true")
    p.add_argument("--captures", default="captures")
    p.add_argument("--no-verify", action="store_true",
                   help="skip checking each result against the prediction")
    p.add_argument("--pin-banner", action="store_true",
                   help="never switch banners; roll on whatever is selected")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("goal", help="roll until a set of wanted units is unlocked")
    p.add_argument("--platinum", type=int, default=0, help="platinum tickets held")
    p.add_argument("--prefer", help="banner key whose legendary to chase first")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--no-humanise", action="store_true")
    p.add_argument("--captures", default="captures")
    p.add_argument("--max-tickets", type=int, default=10_000)
    p.add_argument("--dry-run", action="store_true", help="show the plan, roll nothing")
    p.add_argument("--simulate", type=int, metavar="TICKETS",
                   help="play the goal out on paper over this many rare tickets")
    p.add_argument("--count", type=int, default=25, help="rolls to show with --dry-run")
    p.set_defaults(func=cmd_goal)

    p = sub.add_parser("resync", help="fix the position after untracked rolls")
    p.add_argument("--cat", required=True, help="the last cat actually rolled")
    p.add_argument("--window", type=int, default=40)
    p.set_defaults(func=cmd_resync)

    p = sub.add_parser("ubers", help="which upcoming positions yield an uber")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--count", type=int, default=200)
    p.set_defaults(func=cmd_ubers)

    p = sub.add_parser("find-seed", help="recover a seed from rolls you already made")
    p.add_argument("--event", required=True)
    p.add_argument("--cats", required=True, help="comma separated, in roll order")
    p.add_argument("--progress", action="store_true")
    p.set_defaults(func=cmd_find_seed)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
