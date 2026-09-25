#!/usr/bin/env python3
"""Download godfat's Battle Cats dataset for one game language.

`bcgacha tools update` does this for English, together with the tier list;
this is for the other languages. Run it with bcgacha installed.
"""

import argparse
import sys

from bcgacha.data import fetch

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", default="en", choices=["en", "jp", "kr", "tw"])
    path = fetch(ap.parse_args().lang)
    print(f"{path} ({path.stat().st_size:,} bytes)", file=sys.stderr)
