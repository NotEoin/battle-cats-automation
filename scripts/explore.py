#!/usr/bin/env python3
"""Tap a point, then report what screen the game lands on.

Used to build data/ui_graph.json by hand-walking the interface. It never
confirms a dialog: anything that looks like a prompt is dismissed with No, so
exploring cannot spend currency.
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bcgacha import safety, vision                      # noqa: E402
from bcgacha.layout import landscape_to_hid             # noqa: E402
from bcgacha.session import DeviceSession               # noqa: E402
from bcgacha.uigraph import UIGraph                     # noqa: E402

OUT = Path(tempfile.gettempdir()) / "bcgacha-explore"


def report(graph, frame, tag):
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / f"{tag}.png"), frame)
    title = graph.read_title(frame)
    known = graph.identify(frame)
    dialog = safety.inspect_dialog(frame)
    print(f"  title={title!r}")
    print(f"  known={known}  legacy={vision.classify(frame).value}")
    if dialog.present:
        print(f"  DIALOG present (cat food: {dialog.spends_cat_food})")
    return title


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tap", nargs=2, type=float, metavar=("X", "Y"))
    ap.add_argument("--tag", default="probe")
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()

    graph = UIGraph.load()
    with DeviceSession() as session:
        if args.tap:
            print(f"tapping ({args.tap[0]}, {args.tap[1]})")
            session.tap(*landscape_to_hid(*args.tap))
            time.sleep(args.settle)
        report(graph, session.screenshot(), args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
