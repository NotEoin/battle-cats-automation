"""The Uncanny Legends player's eyes: the list's pills, the CPU item, the stage tabs."""

import cv2
import numpy as np

from bcgacha import legends

W, H = 2532, 1170
GREEN = (42, 202, 210)
GREEN_LOCKED = (42, 202, 105)
YELLOW = (24, 200, 240)
ORANGE = (12, 200, 235)
PAPER = (18, 30, 250)


def _hsv_frame(fill=PAPER) -> np.ndarray:
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:] = fill
    return frame


def _bgr(frame):
    return cv2.cvtColor(frame, cv2.COLOR_HSV2BGR)


def _pill(frame, y0, y1, colour, badge=False):
    frame[int(y0 * H): int(y1 * H), int(0.07 * W): int(0.33 * W)] = colour
    if badge:
        mid = int((y0 + y1) / 2 * H)
        frame[mid: int(y1 * H), int(0.075 * W): int(0.11 * W)] = (10, 220, 60)


def test_pills_are_told_apart_by_colour_and_brightness():
    frame = _hsv_frame()
    _pill(frame, 0.10, 0.19, ORANGE)
    _pill(frame, 0.26, 0.35, GREEN_LOCKED)
    _pill(frame, 0.40, 0.49, GREEN)
    _pill(frame, 0.54, 0.63, GREEN, badge=True)
    _pill(frame, 0.70, 0.79, YELLOW)
    frame = _bgr(frame)
    found = legends.pills(frame)
    assert [(p.kind, p.bright) for p in found] == [
        ("other", True), ("green", False), ("green", True), ("green", True), ("yellow", True)]
    assert abs(found[2].y - 0.445) < 0.01
    assert not legends.cleared(frame, found[2])
    assert legends.cleared(frame, found[3])


def _icon(body, screen):
    frame = _hsv_frame((75, 40, 80))
    x0, y0, x1, y1 = legends.CPU_ICON
    frame[int(y0 * H): int(y1 * H), int(x0 * W): int(x1 * W)] = body
    mx0, mx1 = int((x0 + 0.012) * W), int((x1 - 0.012) * W)
    my0, my1 = int((y0 + 0.02) * H), int((y1 - 0.03) * H)
    for i, x in enumerate(range(mx0, mx1, 8)):
        frame[my0:my1, x:x + 8] = screen(i)
    return _bgr(frame)


def test_the_cpu_item_state_is_read_from_its_colours():
    rainbow = lambda i: ((i * 23) % 180, 220, 230)      # noqa: E731
    grey = lambda i: (0, 0, 90)                         # noqa: E731
    assert legends.cpu_state(_icon((0, 5, 245), rainbow)) == "cpu"
    assert legends.cpu_state(_icon((22, 200, 240), rainbow)) == "skip"
    assert legends.cpu_state(_icon((0, 5, 245), grey)) == "off"


def test_the_selected_tab_and_those_right_of_it():
    frame = _hsv_frame((16, 120, 70))
    row = slice(int(0.11 * H), int(0.18 * H))
    frame[row, int(0.12 * W): int(0.24 * W)] = (14, 23, 170)
    frame[row, int(0.42 * W): int(0.58 * W)] = (0, 0, 253)
    frame[row, int(0.61 * W): int(0.74 * W)] = (14, 23, 170)
    selected, others = legends.tabs(_bgr(frame))
    assert selected and abs(selected[0] - 0.42) < 0.005 and abs(selected[1] - 0.58) < 0.005
    later = [t for t in others if t[0] >= selected[1]]
    assert len(later) == 1 and abs(later[0][0] - 0.61) < 0.005
