"""The Zombie Outbreak player's eyes and its place in a run."""

import shlex

import cv2
import numpy as np

from bcgacha import jobs, outbreaks

W, H = 2532, 1170
PAPER = (18, 30, 250)
PURPLE = (140, 150, 170)


def _frame(*boxes) -> np.ndarray:
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:] = PAPER
    for x0, y0, x1, y1 in boxes:
        frame[int(y0 * H): int(y1 * H), int(x0 * W): int(x1 * W)] = PURPLE
    return cv2.cvtColor(frame, cv2.COLOR_HSV2BGR)


def test_the_outbreak_button_is_purple_on_the_left():
    button = (0.11, 0.44, 0.19, 0.53)
    assert outbreaks.outbreak_shown(_frame(button))
    assert not outbreaks.outbreak_shown(_frame())


def test_the_outbreak_stage_is_selected_when_the_middle_tab_is_purple():
    assert outbreaks.outbreak_selected(_frame((0.42, 0.10, 0.58, 0.21)))
    assert not outbreaks.outbreak_selected(_frame((0.11, 0.44, 0.19, 0.53)))


def test_the_zombie_deck_is_known_whatever_its_case():
    assert outbreaks.is_deck("Zombie")
    assert outbreaks.is_deck("zom bie")
    assert not outbreaks.is_deck("Red")
    assert not outbreaks.is_deck("")


def test_outbreaks_come_last_in_a_run():
    req = jobs.Request(capsules={"cat": 0}, uncanny=True, outbreaks=True)
    assert req.tasks() == ["map", "capsules", "legends", "outbreaks"]
    assert jobs.Request(outbreaks=True).spends


def test_the_command_line_asks_for_outbreaks_too():
    from bcgacha import cli

    req = jobs.Request(outbreaks=True)
    assert "--play-outbreaks" in req.command()
    assert cli.request_from_args(cli.parser().parse_args(shlex.split(req.command())[1:])) == req
