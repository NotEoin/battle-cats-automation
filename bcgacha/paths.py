"""Where bcgacha keeps what it downloads, learns and captures.

Everything a run writes lives under one folder, so a person can find it, back
it up or delete it: `BCGACHA_HOME` when that is set, else the per-user data
folder of the platform (`~/.local/share/bcgacha` on Linux,
`~/Library/Application Support/bcgacha` on macOS, `%LOCALAPPDATA%\\bcgacha`
on Windows). Never inside the package: an installed package can sit somewhere
read-only, and an upgrade replaces it.

What ships with the package, the screen map and the tier aliases, is read from
`RESOURCES` and never written.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

APP = "bcgacha"


def home() -> Path:
    """The folder a run writes into: `BCGACHA_HOME`, else the user data folder."""
    override = os.environ.get("BCGACHA_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_data_dir(APP, appauthor=False))


HOME = home()
DATA = HOME / "data"            # the downloaded dataset and tier list
STATE = HOME / "state"          # the save's position, owned cats, learned devices
CAPTURES = HOME / "captures"    # result screens, from which the seed is found
LOGS = HOME / "logs"            # battle ends and the drawn screen map

RESOURCES = Path(__file__).resolve().parent / "resources"
