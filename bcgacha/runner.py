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
from .layout import (
    CAPSULE_SCREEN,
    RESULT_SCREEN,
    SENT_TO_STORAGE_SCREEN,
    STORAGE_SCREEN,
    landscape_to_hid,
)
from .bannerpick import BannerPicker
from .catindex import CAT_BASE, MENU_DIALOG, OwnedIndex
from .planner import PLATINUM_TICKET, Plan, Planner
from .roller import RollAborted
from .safety import SafeTapper, UnsafeTap
from .state import Account


# Re-read the real storage count every this many rolls, and always once within
# this many slots of the cap.
STORAGE_RECHECK = 15
STORAGE_MARGIN = 4

# The cat name on the result screen, used to confirm the roll matched the plan.
# Generous around the plate, and upscaled: the name is small white text on a
# dark panel and the recogniser misses it entirely at native size.
RESULT_NAME_BOX = (0.320, 0.772, 0.690, 0.858)
RESULT_NAME_SCALE = 3


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
        picker: BannerPicker | None = None,
        pin_banner: bool = False,
    ):
        self.tapper = tapper
        self.dataset = dataset
        self.account = account
        self.planner = planner
        self.capture_dir = Path(capture_dir) if capture_dir else None
        self.picker = picker
        self._ocr = None
        # Kept in step as units are pulled, so a later run does not plan to
        # chase something this one already unlocked. A unit sitting in Cat
        # Storage counts as owned here: it cannot be rolled usefully again
        # even though the roster has not picked it up yet.
        self.owned_index = OwnedIndex.load()
        # When the carousel cannot be driven, stay put and roll where we are
        # rather than silently rolling on the wrong banner.
        self.pin_banner = pin_banner

    # -- screen helpers -----------------------------------------------------

    def to_capsule(self, timeout: float = 40.0):
        """Return to the capsule screen from wherever the game has ended up.

        Every branch hands its own frame to the tap, because re-capturing
        inside the tap opens a race: the screen cross-fades, and a tap chosen
        against one frame gets refused when checked against a later one.
        A refusal here means the game moved mid-decision, so it retries.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                frame = self.tapper.capture()
                screen = vision.classify(frame)

                if screen is vision.Screen.CAPSULE:
                    return frame
                if screen is vision.Screen.SENT_TO_STORAGE:
                    self.tapper.tap(
                        SENT_TO_STORAGE_SCREEN["ok"],
                        expect=vision.Screen.SENT_TO_STORAGE,
                        require_anchor="sent_to_storage",
                        frame=frame,
                    )
                    continue
                if screen is vision.Screen.RESULT:
                    self.tapper.tap(
                        RESULT_SCREEN["ok"],
                        expect=vision.Screen.RESULT,
                        require_anchor="result_actions",
                        frame=frame,
                    )
                    continue
                if screen is vision.Screen.STORAGE:
                    self.tapper.tap(
                        STORAGE_SCREEN["back"],
                        expect=vision.Screen.STORAGE,
                        require_anchor="storage_title",
                        frame=frame,
                    )
                    continue
                # An unattended run can end up anywhere: a stray tap, a popup
                # that navigated, or the game restarting on the base.
                if screen is vision.Screen.CAT_BASE:
                    self._blind_tap(CAT_BASE["rare_capsule"], 1.6)
                    continue
                if screen is vision.Screen.MENU:
                    self._blind_tap(MENU_DIALOG["close"], 1.2)
                    continue
                if screen is vision.Screen.CAT_GUIDE:
                    self._blind_tap((0.089, 0.872), 1.4)
                    continue
                if self.tapper.dismiss_dialog(frame):
                    continue
            except UnsafeTap:
                pass          # the screen moved mid-decision; look again
            self.tapper.human.sleep(0.4)
        raise RollAborted("could not get back to the capsule screen")

    def _blind_tap(self, point, settle: float) -> None:
        """Tap a fixed point without a screen check, for recovery steps."""
        self.tapper.session.tap(
            *self.tapper.human.jitter_point(*landscape_to_hid(*point))
        )
        self.tapper.human.sleep(settle)

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

    def verify_result(self, frame_path: Path, expected_cat: int) -> tuple[bool, str]:
        """Check the cat that actually came out against the one predicted.

        The whole system rests on the saved seed position matching the game. If
        a tap is swallowed or a roll is missed, the position drifts and every
        later prediction is quietly wrong, so a mismatch has to stop the run
        rather than be papered over.
        """
        import cv2

        from .catindex import clean_name, match_name

        frame = cv2.imread(str(frame_path))
        if frame is None:
            return True, "no frame to check"
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = RESULT_NAME_BOX
        crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
        crop = cv2.resize(
            crop, None, fx=RESULT_NAME_SCALE, fy=RESULT_NAME_SCALE,
            interpolation=cv2.INTER_CUBIC,
        )
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        result, _ = self._ocr(crop)
        if not result:
            return True, "could not read the name"
        raw = clean_name(" ".join(r[1] for r in result))
        forms = self.dataset.cats.get(expected_cat, {}).get("name") or []
        forms = [f for f in forms if f]
        if not forms:
            return True, "no name on record"
        hit = match_name(raw, forms)
        if hit:
            return True, hit
        return False, raw

    def advance_state(self, step) -> None:
        """Keep the account's seed position in step with what was rolled.

        A dupe reroll costs extra seed advances and an odd number of them flips
        the track, so the step's own reroll cost has to be applied. Assuming a
        clean one-row step would desync the position from the game and quietly
        invalidate every later prediction.
        """
        delta, track = next_position(self.account.track, step.reroll_steps)
        self.account.index += delta
        self.account.track = track
        self.account.rolls_made += 1
        self.account.last_cat_id = step.cat_id

    def run(
        self,
        mode: Mode = Mode.UNTIL_TARGET,
        max_tickets: int = 50,
        horizon: int = 60,
        verify: bool = True,
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

            if self.picker is not None and not self.pin_banner:
                wanted = next(
                    (b for b in self.planner.banners if b.key == step.banner_key), None
                )
                if wanted is not None:
                    current = self.picker.identify(frame, self.planner.banners)
                    if current is None or current.key != wanted.key:
                        if not self.picker.select(wanted, self.planner.banners):
                            report.stopped_because = (
                                f"could not switch to {wanted.name[:45]}"
                            )
                            break
                        frame = self.to_capsule()

            tickets = vision.read_counter(frame, "tickets", vision.DigitAtlas())
            if tickets is not None and tickets < 1:
                report.stopped_because = "out of rare tickets"
                break

            # Storage only moves by one per roll, so it is tracked locally and
            # only read off the device when it might actually matter. Opening
            # the storage screen costs four taps, which is far too expensive to
            # pay every roll just to learn a number we already know.
            predicted = self.account.storage_used
            near_cap = predicted >= self.account.storage_capacity - STORAGE_MARGIN
            if near_cap or report.rolled % STORAGE_RECHECK == 0:
                storage = self.storage_state()
                if storage:
                    used, cap = storage
                    self.account.storage_used, self.account.storage_capacity = used, cap
                    predicted = used
            if predicted >= self.account.storage_capacity - 1:
                if mode is Mode.ALL:
                    log(f"storage {predicted}/{self.account.storage_capacity}, emptying")
                    if self.empty_storage():
                        report.storage_emptied += 1
                        self.account.storage_used = 0
                    else:
                        report.stopped_because = "could not empty storage"
                        break
                else:
                    report.stopped_because = (
                        f"storage full at {predicted}/{self.account.storage_capacity}"
                    )
                    break

            try:
                result = roller.roll_once(report.rolled + 1)
            except (RollAborted, UnsafeTap) as exc:
                report.stopped_because = f"aborted: {exc}"
                break

            if verify:
                matched, seen = self.verify_result(result.frame_path, step.cat_id)
                if not matched:
                    report.stopped_because = (
                        f"prediction desync: expected "
                        f"{self.dataset.cat_name(step.cat_id)!r}, screen read {seen!r}. "
                        "The saved seed position no longer matches the game -- "
                        "re-run find-seed before continuing."
                    )
                    break

            report.rolled += 1
            report.tickets_spent += 1
            self.account.storage_used += 1
            report.frames.append(result.frame_path)
            self.advance_state(step)
            self.account.save()

            got = self.dataset.cat_name(step.cat_id)
            if step.is_new:
                report.new_units.append(got)
                self.planner.scorer.owned.add(step.cat_id)
                self.owned_index.owned.add(step.cat_id)
                self.owned_index.save()
                log(f"  #{report.rolled:>3} {step.position:>6} NEW {got}")
                if mode is Mode.UNTIL_TARGET and step.rarity in (UBER, LEGEND):
                    report.stopped_because = f"got {got}"
                    break
            else:
                log(f"  #{report.rolled:>3} {step.position:>6}     {got}")

        self.settle_on_exit(log=log)
        return report

    def settle_on_exit(self, log=print) -> None:
        """Leave the game on the capsule screen, whatever stopped the run.

        A run that ends on the "Sent to Cat Storage" notice leaves the account
        mid-flow: the next run has to clear it before it can do anything, and a
        human picking the phone up finds a modal in the way. Walking back is
        cheap and makes the stopping point somewhere sensible to resume from.
        """
        try:
            self.to_capsule()
        except Exception as exc:          # never let tidying up fail a run
            log(f"  could not return to the capsule screen: {exc}")
