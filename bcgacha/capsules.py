"""Open the normal-side machines: Cat Capsules, Lucky Capsules, Lucky Capsules G.

Nothing is predicted here: these machines are not the rare seed's, and what
they give is only read off the name plate for the log. What matters is that a
press spends tickets and nothing else, and that the run is quick.

A press is made only when its button looks exactly as it did when it was
learned with tickets on it -- a face that changes (a Cat Food can, another
count) is refused -- and the Cat Food counter is read around every press: if
it ever falls, the run stops. "Try 10 times!" is pressed while its face shows
the 10; otherwise, "Try once!".

Reveals are skipped: once a capsule has opened, a tap anywhere jumps to the
result, as a player mashing through would. The tap goes on the top bar, which
does nothing on any screen, so a tap landing late presses nothing.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

MACHINES = {"cat": "cat_capsules", "lucky": "lucky_capsules", "lucky_g": "lucky_capsules_g"}
SINGLE, MULTI = "Try once!", "Try 10 times!"
COST = {SINGLE: 1, MULTI: 10}
# The button must look this much as it did when learned. A pulse or glow
# costs a few hundredths; another icon or count costs far more.
FACE_MATCH = 0.93
# Where a skip tap goes, and how long after a press the capsule starts to
# take one: taps while it is still being lowered are ignored.
SKIP_POINT = (0.5, 0.035)
SKIP_AFTER = 3.0
SKIP_EVERY = 0.5
# After an Ok the next capsule of a batch opens straight away.
SKIP_AFTER_OK = 0.8
# A draw button's height, as a share of the frame; a learned box much shorter
# than this holds only the label.
FACE_HEIGHT = 0.117
# The Cat Food can sits in the lower part of the face, with the cost; the
# label above it prints the 10 of "Try 10 times!" in red.
FACE_LOWER = 0.45
# An Ok the screen has not answered in this long is pressed again.
OK_AGAIN = 2.5
# A press that has not changed the screen in this long did not draw.
NO_DRAW = 4.0
# Empty Storage when a press would leave fewer free slots than this.
STORAGE_MARGIN = 3


@dataclass
class CapsuleState:
    presses: int = 0
    capsules: int = 0
    names: list = field(default_factory=list)
    cat_food: int | None = None
    started: float = field(default_factory=time.time)
    reason: str = ""

    def to_json(self) -> dict:
        spent = time.time() - self.started
        return dict(presses=self.presses, capsules=self.capsules, cat_food=self.cat_food,
                    seconds=round(spent, 1), reason=self.reason,
                    per_capsule=round(spent / self.capsules, 1) if self.capsules else None,
                    last=self.names[-10:])


class CapsuleRun:
    """Press one machine's draw button until told to stop, `limit` capsules
    are open, or a check refuses."""

    def __init__(self, ctx, machine: str, limit: int | None = None, multi: bool = True):
        from .state import STATE_PATH, Account

        if machine not in MACHINES:
            raise ValueError(f"unknown machine {machine!r}: one of {', '.join(MACHINES)}")
        self.ctx, self.screen, self.limit, self.multi = ctx, MACHINES[machine], limit, multi
        self.nav = ctx.navigator()
        self.state = CapsuleState()
        self.account = Account.load() if STATE_PATH.exists() else None
        self.stored: int | None = self.account.storage_used if self.account else None
        self.capacity = self.account.storage_capacity if self.account else 128

    # -- reading ---------------------------------------------------------------

    def _ok_point(self, screen: str):
        step = next((t for t in self.ctx.graph.transitions if t.src == screen and t.target == "Ok"), None)
        return (step.x, step.y) if step else None

    def _cat_food(self, frame) -> int | None:
        """The Cat Food counter, only when two reads agree."""
        from .pipeline import CAT_FOOD_BOX, read_number

        first = read_number(frame, CAT_FOOD_BOX, self.ctx.ocr)
        if first is None:
            return None
        again = read_number(self.ctx.session.screenshot(), CAT_FOOD_BOX, self.ctx.ocr)
        return first if again == first else None

    def _learn_multi(self, frame) -> None:
        """"Try 10 times!" is not on the map; learn it by a full look, once."""
        from .perception import perceive

        profile = self.ctx.graph.profile_for(frame)
        if profile.key_for(self.screen, MULTI) is None:
            profile.learn(self.screen, frame, perceive(frame, self.ctx.ocr).controls, wanted={MULTI})

    def _button(self, frame, name: str):
        """The learned button `name`, if it is on screen looking as it did
        when learned and its face shows a cost of the right length. Else None
        and why."""
        from . import draw

        profile = self.ctx.graph.profile_for(frame)
        found = profile.find(frame, self.screen, name)
        if found is None:
            return None, f"no {name!r} on screen"
        if found["score"] < FACE_MATCH:
            return None, f"{name!r} does not look as it did when learned ({found['score']:.2f})"
        box = self._face_box(profile, name, found["box"])
        if box is None:
            return None, f"only the label of {name!r} is known, not the whole button"
        face = draw._crop(frame, box)
        # Its whole face -- label, ticket and cost -- as it looked the first
        # time it passed, must be what is there now.
        key = f"{self.screen}: {name}"
        known = profile.known_text(frame, box)
        if known is not None and known != key:
            return None, f"{name!r} looks like {known!r}"
        if known is None:
            if profile.data["texts"].get(profile._box_key(box), {}).get(key):
                return None, f"{name!r} does not look as it did when it last drew"
            digits = draw.cost_digits(face)
            if digits != len(str(COST[name])):
                return None, f"{name!r} shows a {digits}-digit cost, not {COST[name]}"
            # The Cat Tickets are silver: red by the cost is the Cat Food can.
            # Lucky Tickets are red themselves, so there only the look counts.
            lower = face[int(face.shape[0] * FACE_LOWER):]
            if self.screen == "cat_capsules" and draw.red_share(lower) > draw.RED_LIMIT:
                return None, f"red on {name!r}: the Cat Food can"
            profile.learn_text(frame, box, key)
        return dict(found, box=box), None

    def _face_box(self, profile, name: str, box):
        """The whole button. On a gold background the button's shape is lost
        and only its label is learned; the three machines are tabs of one
        screen with their buttons in one place, so take it from a tab where the
        whole button was found."""
        if box[3] - box[1] >= 0.8 * FACE_HEIGHT:
            return tuple(box)
        for screen in MACHINES.values():
            entry = profile.controls(screen).get(name)
            if entry and entry["box"][3] - entry["box"][1] >= 0.8 * FACE_HEIGHT:
                x0, y0, x1, y1 = entry["box"]
                # Only if the label sits inside that button.
                if x0 <= (box[0] + box[2]) / 2 <= x1 and y0 - 0.03 <= box[1] <= y1:
                    return tuple(entry["box"])
        return None

    # -- one press ---------------------------------------------------------------

    def _collect(self, before, cost: int) -> int | None:
        """Watch a press through: skip each reveal, press Ok on each result and
        on Sent to Cat Storage, until the machine is back. Returns how many
        results were seen, or None if the press did not draw."""
        from .results import NAME_BOX, NAME_SCALE, _read
        from .uigraph import RESULT_SCREENS, frame_changed, result_ok

        ctx, graph, human = self.ctx, self.ctx.graph, self.nav.human
        started = time.monotonic()
        deadline = started + 25 + 8 * cost
        next_skip = started + SKIP_AFTER
        seen, moved, last = 0, False, None
        # After an Ok, the next result counts only once the screen has left
        # the result screen: two cats on the same stage differ too little to
        # tell apart by the picture alone. An Ok not answered is pressed again.
        pressed_at, left = None, True
        while time.monotonic() < deadline:
            frame = ctx.session.screenshot()
            now = time.monotonic()
            moved = moved or frame_changed(before, frame)
            if not moved:
                if now - started > NO_DRAW:
                    return None
                continue
            name = graph.recognise(frame, slow=False, ocr=False).here
            still = last is not None and last[0] == name and not frame_changed(last[1], frame)
            last = (name, frame)
            left = left or (name not in RESULT_SCREENS and result_ok(graph, frame) is None)
            if name == self.screen and still:
                return seen
            if name is None and still and result_ok(graph, frame) is not None:
                name = "reward_result"       # an XP reward: only its Ok is known
            if name in RESULT_SCREENS + ("reward_result",) and still:
                if not left:
                    if now - pressed_at > OK_AGAIN:
                        self.nav._press(*(result_ok(graph, frame) or self._ok_point(name)))
                        pressed_at, last = time.monotonic(), None
                    continue
                seen += 1
                raw = _read(frame, NAME_BOX, ctx.ocr, NAME_SCALE)
                self.state.names.append(raw)
                ctx.put("capsule", dict(n=self.state.capsules + seen, name=raw, screen=name))
                self.nav._press(*(result_ok(graph, frame) or self._ok_point(name)))
                pressed_at, left, last = time.monotonic(), False, None
                next_skip = pressed_at + SKIP_AFTER_OK
                continue
            if name == "sent_to_storage" and still:
                self.nav._press(*self._ok_point("sent_to_storage"))
                last = None
                continue
            if name not in RESULT_SCREENS + ("reward_result", "sent_to_storage") and now >= next_skip:
                from .layout import landscape_to_hid

                ctx.session.tap(*human.jitter_point(*landscape_to_hid(*SKIP_POINT)))
                next_skip = now + SKIP_EVERY * random.uniform(0.7, 1.3)
        ctx.log("  a press did not come back to the machine in time")
        return seen or None

    def _drain(self) -> bool:
        from .pipeline import drain_storage

        self.ctx.log("  Cat Storage nearly full: Use all")
        if not drain_storage(self.ctx):
            return False
        self.stored = 0
        self._save_storage()
        return True

    def _save_storage(self) -> None:
        if self.account is not None and self.stored is not None:
            self.account.storage_used = self.stored
            self.account.save()

    def press_once(self) -> str | None:
        """One press of the best button. Returns a reason to stop, or None."""
        ctx, s = self.ctx, self.state
        left = None if self.limit is None else self.limit - s.capsules
        want = MULTI if self.multi and (left is None or left >= COST[MULTI]) else SINGLE
        if self.stored is None or self.stored + COST[want] > self.capacity - STORAGE_MARGIN:
            if not self._drain():
                return "could not empty Cat Storage"
        if not self.nav.goto(self.screen, log=ctx.log):
            return f"could not reach {self.screen}"
        here, frame = self.nav.arrival
        if here != self.screen:
            return f"expected {self.screen}, saw {here}"
        if want == MULTI:
            self._learn_multi(frame)
        button, why = self._button(frame, want)
        if button is None and want == MULTI:
            ctx.log(f"  {why}: one at a time")
            want = SINGLE
            button, why = self._button(frame, want)
        if button is None:
            return f"draw refused: {why}"
        food = self._cat_food(frame)
        if food is not None:
            if s.cat_food is not None and food < s.cat_food:
                return f"Cat Food fell from {s.cat_food} to {food}"
            s.cat_food = food

        self.nav._press(*button["tap"])
        seen = self._collect(frame, COST[want])
        if seen is None:
            return f"{want!r} did not draw: out of tickets, or a question in the way"
        s.presses += 1
        s.capsules += COST[want]
        if self.stored is not None:
            self.stored += COST[want]
            self._save_storage()
        ctx.put("capsules", s.to_json())
        ctx.log(f"  press {s.presses}: {want} -> {seen} result{'s' if seen != 1 else ''}, "
                f"{s.capsules} opened, {s.to_json()['per_capsule']}s each")
        return None

    def run(self) -> str:
        from .pipeline import Stopped

        s = self.state
        try:
            while True:
                self.ctx.check()
                if self.limit is not None and s.capsules >= self.limit:
                    s.reason = f"{s.capsules} capsules opened"
                    break
                reason = self.press_once()
                if reason:
                    s.reason = reason
                    break
        except Stopped:
            s.reason = "stopped by request"
        # The last check: a press may have spent Cat Food after all.
        if s.cat_food is not None and self.nav.goto(self.screen):
            food = self._cat_food(self.nav.arrival[1])
            if food is not None and food < s.cat_food:
                s.reason += f"; Cat Food fell from {s.cat_food} to {food}"
        self.ctx.put("capsules", s.to_json())
        self.ctx.log(f"capsules: {s.reason}")
        return s.reason
