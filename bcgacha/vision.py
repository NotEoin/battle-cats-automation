"""Load a saved screen.

The Battle Cats renders through Cocos2d-x into a single GL surface, so the
device exposes no accessibility elements at all -- everything the bot knows of
the screen comes from its pixels: see perception.py and uigraph.py.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def load(path: str | Path) -> np.ndarray:
    """The saved screen at `path` as a BGR array; FileNotFoundError if unreadable."""
    frame = cv2.imread(str(path))
    if frame is None:
        raise FileNotFoundError(path)
    return frame
