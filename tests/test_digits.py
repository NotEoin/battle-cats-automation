"""Counters read off the screen, down to a lone Platinum ticket digit.

The counters are drawn here in a blocky 5x7 font like the game's, in its
yellow, and OCR is a stand-in that reads what a test says it reads: what is
under test is which reads are trusted, and what is learned from them.
"""

import cv2
import numpy as np

from bcgacha import digits

FONT = {
    "2": ["11110", "00001", "00001", "01110", "10000", "10000", "11111"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
}
BOX = (0.0, 0.0, 1.0, 1.0)
YELLOW = (0, 215, 255)         # BGR


def counter(text: str, cell: int = 8) -> np.ndarray:
    """`text` in the blocky font, yellow on the dark bar, with an icon beside it."""
    h = 7 * cell
    frame = np.full((h * 2, 40 + len(text) * 6 * cell + 20, 3), (40, 30, 20), np.uint8)
    cv2.rectangle(frame, (4, 10), (30, h + 30), (255, 255, 255), 2)       # a thin icon outline
    for n, ch in enumerate(text):
        x0 = 40 + n * 6 * cell
        for r, row in enumerate(FONT[ch]):
            for c, bit in enumerate(row):
                if bit == "1":
                    # Bold, as the game's digits are: each block spills a
                    # little into its neighbours.
                    grow = cell // 3
                    cv2.rectangle(frame, (x0 + c * cell - grow, h // 2 + r * cell - grow),
                                  (x0 + (c + 1) * cell - 1 + grow, h // 2 + (r + 1) * cell - 1 + grow), YELLOW, -1)
    return frame


def _font_glyph(ch: str) -> np.ndarray:
    return digits.glyphs(digits.ink(counter(ch), BOX))[0]


class FontOCR:
    """Reads this test's font perfectly -- every dark blob on the page named by
    the digit it is drawn from -- except a lone glyph, which, like the real
    detector, it does not see at all."""

    def __init__(self):
        self.font = {ch: digits.cell(_font_glyph(ch)) for ch in FONT}

    def __call__(self, page):
        grey = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
        mask = (grey < 128).astype(np.uint8) * 255
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        # Solid, upright blobs: the digits, not the icon's outline.
        blobs = sorted((int(stats[i][0]), i) for i in range(1, count)
                       if stats[i][4] > 30 and stats[i][4] >= 0.45 * stats[i][2] * stats[i][3]
                       and stats[i][2] <= 0.85 * stats[i][3])
        if len(blobs) < 2:
            return None, None
        text = ""
        for _x, i in blobs:
            x, y, w, h = (int(v) for v in stats[i][:4])
            c = digits.cell((labels[y:y + h, x:x + w] == i).astype(np.uint8) * 255)
            text += min(self.font, key=lambda ch: float(np.abs(c - self.font[ch]).mean()))
        return [[None, text, 0.9]], None


class Scripted:
    """Reads nothing for the counter's page, then the scripted answers."""

    def __init__(self, answers):
        self.answers, self.first = iter(answers), True

    def __call__(self, page):
        if self.first:
            self.first = False
            return None, None
        text = next(self.answers, None)
        return ([[None, text, 0.9]] if text else None), None


def atlas_in(tmp_path, *learnt):
    atlas = digits.Atlas(tmp_path / "digits.json")
    for text in learnt:
        atlas.learn(digits.glyphs(digits.ink(counter(text), BOX)), int(text))
    return atlas


def test_the_icon_beside_a_counter_is_not_a_digit():
    assert len(digits.glyphs(digits.ink(counter("922"), BOX))) == 3


def test_a_number_read_for_certain_teaches_its_glyphs(tmp_path):
    atlas = atlas_in(tmp_path)
    assert digits.read(counter("2893"), BOX, FontOCR(), atlas) == (2893, "read")
    assert atlas.known() == "", "reading alone teaches nothing"
    assert digits.teach(counter("2893"), BOX, 2893, atlas)
    assert digits.Atlas(tmp_path / "digits.json").known() == "2389", "kept for the next run"


def test_a_misread_does_not_teach(tmp_path):
    """Glyphs already known as 2 and 9 are not taught as an 8 and a 2."""
    atlas = atlas_in(tmp_path, "29")
    assert not digits.teach(counter("29"), BOX, 82, atlas)
    assert atlas.known() == "29"


def test_a_lone_digit_is_read_every_way_that_can(tmp_path):
    value, how = digits.read(counter("9"), BOX, FontOCR(), atlas_in(tmp_path, "298"))
    assert value == 9
    assert "remembered" in how and "in company" in how and "repeated" in how


def test_a_digit_never_seen_is_not_taken_for_its_neighbour(tmp_path):
    """An 8 and a 9 differ by one stroke: with only an 8 remembered, a 9 is
    not named an 8 -- read among the 8s, it is a 9."""
    value, how = digits.read(counter("9"), BOX, FontOCR(), atlas_in(tmp_path, "28"))
    assert value == 9 and "remembered" not in how


def test_a_lone_digit_nothing_reads_is_none(tmp_path):
    value, _ = digits.read(counter("9"), BOX, Scripted([]), atlas_in(tmp_path, "8"))
    assert value is None


def test_runs_that_disagree_are_not_trusted(tmp_path):
    value, _ = digits.read(counter("9"), BOX, Scripted(["999", "8888", "999", "99999"]), atlas_in(tmp_path))
    assert value is None


def test_a_run_that_reads_letters_is_not_trusted(tmp_path):
    """A 7 in the game's font reads as a run of L: nothing, not a guess."""
    value, _ = digits.read(counter("9"), BOX, Scripted(["LLL", "LLLL", "LLL", "LLLLL"]), atlas_in(tmp_path))
    assert value is None


def test_the_ways_must_agree(tmp_path, monkeypatch):
    monkeypatch.setattr(digits, "read_in_company", lambda g, a, o: None)
    monkeypatch.setattr(digits, "read_runs", lambda g, o: "8")
    value, how = digits.read(counter("9"), BOX, Scripted([]), atlas_in(tmp_path, "9"))
    assert value is None and "disagree" in how
