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

    p = sub.add_parser("find-seed", help="recover a seed from rolls you already made")
    p.add_argument("--event", required=True)
    p.add_argument("--cats", required=True, help="comma separated, in roll order")
    p.add_argument("--progress", action="store_true")
    p.set_defaults(func=cmd_find_seed)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
