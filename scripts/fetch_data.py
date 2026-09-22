#!/usr/bin/env python3
"""Fetch godfat's Battle Cats dataset, the source of truth for cat pools and rates.

The file is tracked in the battle-cats-rolls repository, so we pull the single
YAML we need rather than cloning the whole project.
"""
import argparse
import pathlib
import sys

import httpx

RAW = "https://gitlab.com/godfat/battle-cats-rolls/-/raw/master/build/bc-{lang}.yaml"
DEST = pathlib.Path(__file__).resolve().parent.parent / "data"


def fetch(lang: str) -> pathlib.Path:
    DEST.mkdir(exist_ok=True)
    out = DEST / f"bc-{lang}.yaml"
    url = RAW.format(lang=lang)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(out, "wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", default="en", choices=["en", "jp", "kr", "tw"])
    args = ap.parse_args()
    path = fetch(args.lang)
    print(f"{path} ({path.stat().st_size:,} bytes)", file=sys.stderr)
