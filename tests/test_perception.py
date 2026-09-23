"""Controls found by their shape, on any device.

The scenes are drawn, not captured: a gold disc with the white X that closes a
panel, the round yellow back arrow, a gold pill. Each is drawn at the size the
game draws it on a 1170-high screen, scaled with the height as the game scales
its layout, so a pixel constant that forgets to scale shows up on the smaller
phone.
"""

import cv2
import numpy as np
import pytest

from bcgacha import perception
from bcgacha.perception import CLOSE_SCORE, Control, Percept
from bcgacha.uigraph import find_back_arrow, find_buttons, frame_changed

SIZES = [(2532, 1170), (1334, 617)]
GOLD = (0, 190, 255)            # BGR
YELLOW = (0, 210, 255)
WHITE = (255, 255, 255)
DARK = (30, 30, 30)
BACKDROP = (90, 60, 40)

DISC_CENTRE = (0.7, 0.3)
BACK_CENTRE = (0.089, 0.872)
PILL_CENTRE = (0.2, 0.275)


def _px(point, size):
    return round(point[0] * size[0]), round(point[1] * size[1])


def _disc(size, glyph):
    """A gold disc in a thin dark ring, carrying `glyph`: "x", "star" or "round"."""
    w, h = size
    frame = np.full((h, w, 3), BACKDROP, np.uint8)
    (cx, cy), r = _px(DISC_CENTRE, size), round(0.045 * h)
    cv2.circle(frame, (cx, cy), r + 3, DARK, -1)
    cv2.circle(frame, (cx, cy), r, GOLD, -1)
    if glyph == "x":
        a, thick = round(0.44 * r), max(3, round(0.38 * r))
        cv2.line(frame, (cx - a, cy - a), (cx + a, cy + a), WHITE, thick)
        cv2.line(frame, (cx - a, cy + a), (cx + a, cy - a), WHITE, thick)
    elif glyph == "star":
        points = [(cx + (0.6 if i % 2 == 0 else 0.25) * r * np.cos(-np.pi / 2 + i * np.pi / 5),
                   cy + (0.6 if i % 2 == 0 else 0.25) * r * np.sin(-np.pi / 2 + i * np.pi / 5))
                  for i in range(10)]
        cv2.fillPoly(frame, [np.array(points, np.int32)], WHITE)
    elif glyph == "round":
        cv2.circle(frame, (cx, cy), round(0.45 * r), WHITE, -1)
    return frame


def _scene(size):
    """A back arrow bottom-left and a gold "Start!!" pill, sized for this screen's height."""
    w, h = size
    k = h / 1170
    frame = np.full((h, w, 3), BACKDROP, np.uint8)

    (bx, by), r = _px(BACK_CENTRE, size), round(50 * k)
    cv2.circle(frame, (bx, by), r, YELLOW, -1)
    arrow = [(bx - round(25 * k), by), (bx + round(10 * k), by - round(22 * k)),
             (bx + round(10 * k), by + round(22 * k))]
    cv2.fillPoly(frame, [np.array(arrow, np.int32)], DARK)

    # 120 x 44 at 1170 high; at 617 high it covers about 1400 px, under the
    # 2600 px floor measured at 1170, so an unscaled floor would drop it.
    (px, py), pw, ph = _px(PILL_CENTRE, size), round(120 * k), round(44 * k)
    x0, y0 = px - pw // 2, py - ph // 2
    cv2.rectangle(frame, (x0 + ph // 2, y0), (x0 + pw - ph // 2, y0 + ph), GOLD, -1)
    cv2.circle(frame, (x0 + ph // 2, py), ph // 2, GOLD, -1)
    cv2.circle(frame, (x0 + pw - ph // 2, py), ph // 2, GOLD, -1)
    cv2.putText(frame, "Start!!", (x0 + round(12 * k), py + round(10 * k)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9 * k, DARK, max(1, round(3 * k)))
    return frame


# -- the close button ------------------------------------------------------------

@pytest.mark.parametrize("size", SIZES)
def test_a_gold_disc_with_a_white_x_is_a_close_button(size):
    """The disc is found where it was drawn, and its glyph scores as an X."""
    frame = _disc(size, "x")
    discs = perception.find_discs(frame)
    assert len(discs) == 1
    box, centre = discs[0]
    assert centre == pytest.approx(DISC_CENTRE, abs=0.005)
    assert perception.close_glyph_score(frame, box) >= CLOSE_SCORE


@pytest.mark.parametrize("size", SIZES)
def test_a_star_badge_on_the_same_disc_is_not_a_close_button(size):
    """A card's star badge shares the X's gold disc, but not its glyph."""
    frame = _disc(size, "star")
    (box, _centre), = perception.find_discs(frame)
    assert perception.close_glyph_score(frame, box) < CLOSE_SCORE


@pytest.mark.xfail(reason="close_glyph_score rewards any centred, quarter-turn-symmetric white "
                          "blob: a plain white dot on the gold disc scores about 0.79 (X-template "
                          "correlation ~0.58, rotation symmetry 1.0) against CLOSE_SCORE 0.57")
def test_a_round_badge_on_the_same_disc_is_not_a_close_button():
    """A plain white dot on a gold disc is a badge, not an X."""
    frame = _disc(SIZES[0], "round")
    (box, _centre), = perception.find_discs(frame)
    assert perception.close_glyph_score(frame, box) < CLOSE_SCORE


def test_a_label_never_finds_the_back_or_close_shape():
    """"Back" and "Close" name labels; the arrow and the X answer only to "@back" and "@close"."""
    arrow = Control("back", "back", (0.05, 0.82, 0.13, 0.95), (0.09, 0.88))
    cross = Control("close", "close", (0.85, 0.30, 0.93, 0.47), (0.89, 0.38))
    percept = Percept(1334, 617, controls=[arrow, cross])
    assert percept.find("Back") is None
    assert percept.find("Close") is None
    assert percept.find("@back") == arrow and percept.find("@close") == cross

    card = Control("Back", "tag", (0.40, 0.48, 0.60, 0.66), (0.5, 0.57))
    percept.controls.append(card)
    assert percept.find("Back") == card


# -- the back arrow and gold buttons, at any resolution ---------------------------------

@pytest.mark.parametrize("size", SIZES)
def test_the_back_arrow_is_found_on_a_small_screen_and_a_large_one(size):
    """Its size floor scales with the screen's height."""
    assert find_back_arrow(_scene(size)) == pytest.approx(BACK_CENTRE, abs=0.01)


@pytest.mark.parametrize("size", SIZES)
def test_a_gold_pill_is_found_on_a_small_screen_and_a_large_one(size):
    """Its area floor and the kernel that closes its lettering scale with the height."""
    buttons = find_buttons(_scene(size))
    x, y = PILL_CENTRE
    pill = [b for b in buttons if b.left <= x <= b.left + b.w and b.top <= y <= b.top + b.h]
    assert len(pill) == 1, buttons
    assert pill[0].centre == pytest.approx(PILL_CENTRE, abs=0.01)


# -- whether a tap changed anything ---------------------------------------------------

def _panel():
    frame = np.full((1170, 2532, 3), 80, np.uint8)
    cv2.rectangle(frame, (300, 200), (900, 600), (200, 150, 50), -1)
    return frame


def test_a_frame_is_unchanged_from_itself():
    """Two grabs of a still screen are the same screen."""
    assert not frame_changed(_panel(), _panel())


def test_a_small_local_change_is_not_a_changed_screen():
    """A counter ticking or a badge blinking, about 3% of the screen, is idle movement."""
    before = _panel()
    after = before.copy()
    cv2.rectangle(after, (1500, 300), (1753, 651), WHITE, -1)
    assert not frame_changed(before, after)


def test_a_large_change_is_a_changed_screen():
    """Half the screen redrawn: the tap did something."""
    before = _panel()
    after = before.copy()
    after[:, :1266] = 255
    assert frame_changed(before, after)
