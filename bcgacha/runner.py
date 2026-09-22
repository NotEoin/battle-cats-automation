"""Run the capsule loop: plan, roll, keep state, drain storage, stop sensibly.

The bot knows every result before it rolls, so this layer is not about reading
outcomes -- it is about staying on the rails. It keeps the seed position in step
with reality, refuses to roll when the draw button might be spending Cat Food,
and empties Cat Storage when it fills rather than stalling against the cap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import cv2

from . import vision
from .data import LEGEND, UBER, Dataset
from .gacha import next_position
from .layout import CAPSULE_SCREEN, RESULT_SCREEN, SENT_TO_STORAGE_SCREEN, STORAGE_SCREEN
from .planner import PLATINUM_TICKET, Plan, Planner
from .roller import RollAborted
from .safety import SafeTapper, UnsafeTap
from .state import Account


class Mode(str, Enum):
    UNTIL_TARGET = "until-target"      # stop once the next wanted unit lands
    MAX_TICKETS = "max-tickets"        # stop after a ticket budget
    UNTIL_STORAGE_FULL = "until-storage-full"
    ALL = "all"                        # run dry, emptying storage as needed


@dataclass
class RunReport:
    rolled: int = 0
    tickets_spent: int = 0
    new_units: list[str] = field(default_factory=list)
    storage_emptied: int = 0
    stopped_because: str = ""
    frames: list[Path] = field(default_factory=list)


class Runner:
    def __init__(
        self,
        tapper: SafeTapper,
        dataset: Dataset,
        account: Account,
        planner: Planner,
        capture_dir: Path | None = None,
    ):
        self.tapper = tapper
        self.dataset = dataset
        self.account = account
        self.planner = planner
        self.capture_dir = Path(capture_dir) if capture_dir else None

    # -- screen helpers -----------------------------------------------------

    def to_capsule(self, timeout: float = 30.0):
        """Return to the capsule screen from wherever the game has ended up."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.tapper.capture()
            screen = vision.classify(frame)
            if screen is vision.Screen.CAPSULE:
                return frame
            if screen is vision.Screen.SENT_TO_STORAGE:
                self.tapper.tap(
                    SENT_TO_STORAGE_SCREEN["ok"],
                    expect=vision.Screen.SENT_TO_STORAGE,
                    require_anchor="sent_to_storage",
                )
                continue
            if screen is vision.Screen.RESULT:
                self.tapper.tap(
                    RESULT_SCREEN["ok"],
                    expect=vision.Screen.RESULT,
                    require_anchor="result_actions",
                )
                continue
            if screen is vision.Screen.STORAGE:
                self.tapper.tap(
                    STORAGE_SCREEN["back"],
                    expect=vision.Screen.STORAGE,
                    require_anchor="storage_title",
                )
                continue
            if self.tapper.dismiss_dialog(frame):
                continue
            self.tapper.human.sleep(0.4)
        raise RollAborted("could not get back to the capsule screen")

    def storage_state(self) -> tuple[int, int] | None:
        """Open storage, read N/M, come back."""
        self.to_capsule()
        self.tapper.tap(
            CAPSULE_SCREEN["storage"], expect=vision.Screen.CAPSULE,
            require_anchor="storage_button",
        )
        frame = self.tapper.wait_for(vision.Screen.STORAGE, timeout=15)
        if frame is None:
            return None
        reading = vision.read_storage(frame, vision.StorageAtlas())
        self.tapper.tap(
            STORAGE_SCREEN["back"], expect=vision.Screen.STORAGE,
            require_anchor="storage_title",
        )
        self.to_capsule()
        return reading

    def empty_storage(self) -> bool:
        """Redeem everything with Use all, confirming the dialog it raises."""
        self.to_capsule()
        self.tapper.tap(
            CAPSULE_SCREEN["storage"], expect=vision.Screen.CAPSULE,
            require_anchor="storage_button",
        )
        frame = self.tapper.wait_for(vision.Screen.STORAGE, timeout=15)
        if frame is None:
            return False
        self.tapper.tap(
            STORAGE_SCREEN["use_all"], expect=vision.Screen.STORAGE,
            require_anchor="storage_title",
        )
        # "Use all" raises a confirmation; it spends nothing, so Yes is correct.
        self.tapper.human.sleep(1.0)
        self.tapper.confirm_dialog()
        self.tapper.human.sleep(1.2)
        self.to_capsule()
        return True

    # -- the loop -----------------------------------------------------------

    def advance_state(self, step) -> None:
        """Keep the account's seed position in step with what was rolled."""
        delta, track = next_position(self.account.track, 0)
        self.account.index += delta
        self.account.track = track
        self.account.rolls_made += 1
        self.account.last_cat_id = step.cat_id

    def run(
        self,
        mode: Mode = Mode.UNTIL_TARGET,
        max_tickets: int = 50,
        horizon: int = 60,
        log=print,
    ) -> RunReport:
        report = RunReport()
        from .roller import Roller

        roller = Roller(self.tapper, self.capture_dir or Path("captures"))

        while True:
            plan = self.planner.plan(
                self.account.seed, rolls=min(horizon, 40),
                index=self.account.index, track=self.account.track,
                previous_cat=self.account.last_cat_id,
            )
            if not plan.steps:
                report.stopped_because = "planner produced nothing"
                break
            step = plan.steps[0]

            if step.currency == PLATINUM_TICKET:
                report.stopped_because = (
                    f"next best roll wants a Platinum Ticket on {step.banner_name[:40]} "
                    f"for {self.dataset.cat_name(step.cat_id)} -- switch by hand"
                )
                break

            if mode is Mode.MAX_TICKETS and report.tickets_spent >= max_tickets:
                report.stopped_because = f"ticket budget of {max_tickets} reached"
                break

            frame = self.to_capsule()
            tickets = vision.read_counter(frame, "tickets", vision.DigitAtlas())
            if tickets is not None and tickets < 1:
                report.stopped_because = "out of rare tickets"
                break

            storage = self.storage_state()
            if storage:
                used, cap = storage
                self.account.storage_used, self.account.storage_capacity = used, cap
                if used >= cap - 1:
                    if mode in (Mode.ALL,):
                        log(f"storage {used}/{cap}, emptying")
                        if self.empty_storage():
                            report.storage_emptied += 1
                    else:
                        report.stopped_because = f"storage full at {used}/{cap}"
                        break

            try:
                result = roller.roll_once(report.rolled + 1)
            except (RollAborted, UnsafeTap) as exc:
                report.stopped_because = f"aborted: {exc}"
                break

            report.rolled += 1
            report.tickets_spent += 1
            report.frames.append(result.frame_path)
            self.advance_state(step)
            self.account.save()

            got = self.dataset.cat_name(step.cat_id)
            if step.is_new:
                report.new_units.append(got)
                self.planner.scorer.owned.add(step.cat_id)
                log(f"  #{report.rolled:>3} {step.position:>6} NEW {got}")
                if mode is Mode.UNTIL_TARGET and step.rarity in (UBER, LEGEND):
                    report.stopped_because = f"got {got}"
                    break
            else:
                log(f"  #{report.rolled:>3} {step.position:>6}     {got}")

        return report
