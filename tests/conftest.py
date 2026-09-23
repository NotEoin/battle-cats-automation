"""Two things no test may reach: the profiles learned on the real phone, and
the OCR model, which takes a second to load and more to run.

Tests give each graph a tmp_path profile_root and a stub OCR themselves; these
guards catch one that forgets, rather than letting it write into state/devices
or quietly slow the suite down.

Nor may a test read what the last download left behind: every run gets a fresh
`BCGACHA_HOME` holding the frozen dataset and tier list in `fixtures/data`, set
before `bcgacha` is first imported, so the suite passes on a fresh clone.
"""

import os
import shutil
import tempfile
from pathlib import Path

_HOME = Path(tempfile.mkdtemp(prefix="bcgacha-tests-"))
os.environ["BCGACHA_HOME"] = str(_HOME)
shutil.copytree(Path(__file__).parent / "fixtures" / "data", _HOME / "data")

import pytest  # noqa: E402 - BCGACHA_HOME must be set before bcgacha is imported

from bcgacha import profile  # noqa: E402
from bcgacha.uigraph import UIGraph  # noqa: E402


@pytest.fixture(autouse=True)
def _scratch_devices(tmp_path_factory, monkeypatch):
    """A graph left on the default profile_root learns into a scratch directory."""
    monkeypatch.setattr(profile, "DEVICES_DIR", tmp_path_factory.mktemp("devices"))


@pytest.fixture(autouse=True)
def _no_ocr_model(monkeypatch):
    """A graph with no stub OCR fails at once instead of loading the model."""

    def ocr(graph):
        if graph._ocr is None:
            raise AssertionError("set graph._ocr to a stub: the real OCR model is slow")
        return graph._ocr

    monkeypatch.setattr(UIGraph, "ocr", property(ocr))


def pytest_sessionfinish(session, exitstatus):
    """Remove the scratch home once the run is over."""
    shutil.rmtree(_HOME, ignore_errors=True)
