"""The whole run, stage by stage, each one reported as it happens.

  graph    the UI map for this save and device: carousels, Cat Base doors
  storage  empty Cat Storage with Use all, so every cat shows in the Guide
  owned    read the Cat Guide: which cats this account has
  events   the gacha events live now, each a screen of the map
  seed     the seed and position, from the archive of result screens
  plan     the goal, the route to it, and the whole run played out on paper
  run      roll to the goal, or until the rare tickets run out

Every stage takes a Context and reports through ctx.publish(section, data),
with plain JSON-able data, so the debug view can show all of it live. Nothing
here opens a device session of its own: the caller owns the one there is.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .data import LEGEND, UBER
from .gacha import next_position

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "captures"
# Counters on the capsule screen's bottom bar, read only to watch them: the
# draw button's own face is what guards a draw (see draw.py).
TICKETS_BOX = (0.635, 0.865, 0.745, 0.950)
CAT_FOOD_BOX = (0.845, 0.865, 0.955, 0.950)
# A draw paid in Cat Food costs exactly this much.
CAT_FOOD_PER_DRAW = 150
# How long a reveal may take: Uber and Legend animations run long.
REVEAL_TIMEOUT = 45.0
PLAN_ROLLS = 40
# Empty storage this many draws before it would fill.
STORAGE_MARGIN = 3


class Stopped(RuntimeError):
    pass


@dataclass
class Context:
    session: object
    graph: object
    ocr: object
    dataset: object
    log: object = print
    publish: object = None                 # publish(section, payload)
    should_stop: object = None             # () -> bool, checked between steps
    human: object = None
    captures: Path = CAPTURES

    def put(self, section: str, payload) -> None:
        if self.publish:
            self.publish(section, payload)

    def check(self) -> None:
        if self.should_stop and self.should_stop():
            raise Stopped("stopped")

    def navigator(self):
        from .uigraph import Navigator

        return Navigator(self.session, self.graph, humaniser=self.human)


# -- reading numbers off the screen -------------------------------------------------

def read_number(frame: np.ndarray, box, ocr) -> int | None:
    """A counter in the game's yellow-and-white digits, or None if unsure."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    crop = frame[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    ink = cv2.inRange(hsv, (15, 80, 150), (40, 255, 255)) | cv2.inRange(hsv, (0, 0, 200), (180, 60, 255))
    page = cv2.copyMakeBorder(255 - ink, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    page = cv2.cvtColor(cv2.resize(page, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), cv2.COLOR_GRAY2BGR)
    result, _ = ocr(page)
    digits = [str(r[1]) for r in result or [] if str(r[1]).strip().isdigit()]
    return int(digits[0]) if len(digits) == 1 else None


# -- stages -----------------------------------------------------------------------

def stage_graph(ctx: Context, reload) -> None:
    """The saga and chapter carousels and this device's Cat Base doors."""
    from . import carousel

    ctx.put("stage", dict(name="graph", state="running"))
    catalogue = carousel.ensure(ctx.session, log=ctx.log, graph=ctx.graph)
    ctx.graph = reload()
    ctx.put("graph", dict(sagas=[s["name"] for s in catalogue["sagas"]],
                          screens=len(ctx.graph.screens), transitions=len(ctx.graph.transitions)))


def drain_storage(ctx: Context) -> bool:
    """Press Use all on Cat Storage -- the only control ever pressed there --
    and confirm its question only once it reads as that question."""
    from .perception import perceive

    nav = ctx.navigator()
    if not nav.goto("storage", log=ctx.log):
        ctx.log("  could not reach Cat Storage")
        return False
    frame = ctx.session.screenshot()
    percept = perceive(frame, ctx.ocr)
    use_all = percept.find("Use all")
    if use_all is None:
        ctx.log("  no Use all on the Storage screen: nothing to redeem")
        return True
    ctx.log("  Cat Storage: Use all")
    nav._tap(*use_all.tap, 1.5)
    for _ in range(4):
        frame = ctx.session.screenshot()
        percept = perceive(frame, ctx.ocr)
        text = " ".join(t.text for t in percept.readings()).lower()
        yes = percept.find("Yes") or percept.find("OK")
        if yes is None:
            break
        spends = any(w in text for w in ("cat food", "exchange", "np", "xp"))
        if spends:
            ctx.log(f"  refusing a Storage question that mentions spending: {text[:80]!r}")
            no = percept.find("No") or percept.find("Cancel")
            if no:
                nav._tap(*no.tap, 1.2)
            return False
        ctx.log(f"  confirming: {text[:80]!r}")
        nav._tap(*yes.tap, 2.0)
    ctx.put("storage", dict(drained_at=dt.datetime.now().isoformat(timespec="seconds")))
    return True


def stage_owned(ctx: Context, force: bool = False, limit: int | None = None):
    from .catindex import OwnedIndex, scan

    index = OwnedIndex.load()
    if index.complete and not force:
        ctx.log(f"owned: {len(index.owned)} cats, scanned {index.scanned_at}")
    else:
        ctx.put("stage", dict(name="storage", state="running"))
        drain_storage(ctx)
        ctx.put("stage", dict(name="owned", state="running"))
        index = scan(ctx.session, ctx.graph, ctx.dataset, ctx.ocr, log=ctx.log,
                     on_entry=lambda e: ctx.put("owned_entry", e), should_stop=ctx.should_stop,
                     human=ctx.human, limit=limit)
    ctx.put("owned", index.to_json(ctx.dataset))
    return index


def stage_events(ctx: Context, visit: bool = True):
    """The live events, each checked on the device by going to it."""
    events = ctx.graph.events
    seen = {}
    if visit:
        nav = ctx.navigator()
        for e in events:
            ctx.check()
            seen[e.key] = nav.goto(e.screen, log=ctx.log)
            ctx.log(f"  {e.label}: {'on screen' if seen[e.key] else 'NOT reached'}")
    ctx.put("events", [dict(e.to_json(ctx.dataset), seen=seen.get(e.key)) for e in events])
    return events


def stage_seed(ctx: Context):
    """Load the saved position, or work it out from the result screens."""
    from . import events as live
    from . import seedpos
    from .state import STATE_PATH, Account

    if STATE_PATH.exists():
        account = Account.load()
        ctx.log(f"position {account.position} ({account.source or 'saved'})")
    else:
        ctx.put("stage", dict(name="seed", state="searching"))
        started = time.time()

        def progress(done, survivors):
            ctx.put("seed_search", dict(done=done / (1 << 32), survivors=survivors,
                                        seconds=round(time.time() - started)))
            ctx.check()

        found = seedpos.identify(ctx.captures, ctx.dataset, lambda d: live.live_events(ctx.dataset, d),
                                 ctx.ocr, log=ctx.log, progress=progress, should_stop=ctx.should_stop)
        ctx.put("seed_found", found.to_json(ctx.dataset))
        if not found.found:
            raise RuntimeError("seed not identified: " + "; ".join(found.detail))
        account = Account(seed=found.seed, index=found.index, track=found.track,
                          last_cat_id=found.last_cat_id, source="captures", confirmed=False)
        account.save()
    ctx.put("account", account.to_json())
    return account


def build_plan(ctx: Context, account, owned: set[int], events, platinum_tickets: int, prefer):
    """The goal and a planner for it. Refuses an owned list that is not whole:
    everything missing from it would look like a target."""
    from . import goals
    from .planner import Planner
    from .scoring import Scorer
    from .tiers import TierList

    try:
        tiers = TierList.load()
    except FileNotFoundError:
        tiers = None
    normal = [e.banner for e in events if not e.platinum]
    platinum = next((e.banner for e in events if e.platinum), None)
    goal = goals.build(ctx.dataset, tiers, owned, normal, platinum,
                       platinum_tickets=platinum_tickets,
                       preferred_banner=prefer.key if prefer else None)
    scorer = Scorer(owned=set(owned), tiers=tiers, priority=goal.priority)
    planner = Planner(ctx.dataset, normal, scorer, platinum_banner=platinum,
                      platinum_tickets=platinum_tickets, platinum_wanted=set(goal.platinum))
    return planner, goal, tiers


def goal_json(goal, dataset, tiers, owned, events) -> dict:
    where = {}
    for e in events:
        for c in e.legends + e.ubers:
            where.setdefault(c, e.label)

    def row(c):
        return dict(id=c, name=dataset.cat_name(c), tier=tiers.tier_of(c) if tiers else "?",
                    event=where.get(c, "Platinum"), owned=c in owned,
                    priority=round(goal.priority.get(c, 0)))

    order = lambda s: sorted(s, key=lambda c: -goal.priority.get(c, 0))
    return dict(legendaries=[row(c) for c in order(goal.legendaries)],
                ubers=[row(c) for c in order(goal.ubers)],
                platinum=[row(c) for c in order(goal.platinum)],
                remaining=len(goal.remaining(owned)))


def plan_json(plan, dataset, events) -> list[dict]:
    from . import events as live
    from .planner import PLATINUM_TICKET

    out = []
    for n, s in enumerate(plan.steps, 1):
        e = live.by_key(events, s.banner_key)
        out.append(dict(n=n, position=s.position, event=e.label if e else s.banner_key,
                        platinum=s.currency == PLATINUM_TICKET, cat=dataset.cat_name(s.cat_id), cat_id=s.cat_id,
                        rarity=s.rarity, new=s.is_new, score=round(s.score, 1),
                        rerolled_from=dataset.cat_name(s.rerolled_from) if s.rerolled_from else None))
    return out


def simulate(ctx: Context, account, owned, events, rare: int, platinum: int, prefer) -> dict:
    """Play the run out on paper on a planner of its own, so nothing the real
    run relies on is touched. Platinum draws cost Platinum, not rare tickets."""
    from .planner import PLATINUM_TICKET

    planner, goal, tiers = build_plan(ctx, account, owned, events, platinum, prefer)
    have = set(owned)
    index, track, prev = account.index, account.track, account.last_cat_id
    rolls, unlocked = [], []
    left_rare, left_plat = rare, platinum
    while left_rare > 0 or left_plat > 0:
        if ctx.should_stop and ctx.should_stop():
            break
        planner.platinum_tickets = left_plat
        if left_rare <= 0:
            # No rare tickets left to steer with: a Platinum draw is made only
            # if it lands one of the tier-list picks; otherwise the tickets keep.
            roll = planner._evaluate(planner._gacha(account.seed, planner.platinum_banner, {}),
                                     index, track, prev)
            if roll.cat_id in have or roll.cat_id not in planner.platinum_wanted:
                break
            step_cat, rarity, currency, steps, key = roll.cat_id, roll.rarity, PLATINUM_TICKET, roll.reroll_steps, planner.platinum_banner.key
        else:
            s = planner.plan(account.seed, rolls=8, index=index, track=track, previous_cat=prev).steps[0]
            step_cat, rarity, currency, steps, key = s.cat_id, s.rarity, s.currency, s.reroll_steps, s.banner_key
        new = step_cat not in have
        rolls.append(dict(n=len(rolls) + 1, position=f"{index}{'AB'[track]}", cat=ctx.dataset.cat_name(step_cat),
                          cat_id=step_cat, rarity=rarity, new=new, platinum=currency == PLATINUM_TICKET,
                          event=next((e.label for e in events if e.key == key), key)))
        if new and rarity >= UBER:
            unlocked.append(rolls[-1])
        have.add(step_cat)
        planner.scorer.owned.add(step_cat)
        if currency == PLATINUM_TICKET:
            left_plat -= 1
            planner.platinum_wanted.discard(step_cat)
        else:
            left_rare -= 1
        delta, track = next_position(track, steps)
        index += delta
        prev = step_cat
        if goal.complete(have):
            break
    return dict(rolls=rolls, unlocked=unlocked, rare_used=rare - left_rare, platinum_used=platinum - left_plat,
                left=[dict(id=c, name=ctx.dataset.cat_name(c)) for c in goal.remaining(have)],
                goal=goal_json(goal, ctx.dataset, tiers, owned, events))


# -- the run ------------------------------------------------------------------------

@dataclass
class RunState:
    rolled: int = 0
    rare_left: int | None = None
    platinum_left: int = 0
    cat_food: int | None = None
    unverified_in_a_row: int = 0
    unlocked: list = field(default_factory=list)
    reason: str = ""


class GoalRun:
    """Roll towards the goal, one guarded draw at a time.

    Before a draw: the planned event is on screen (read afresh after getting
    there), and the draw button's face shows the ticket it will spend. After
    it: the cat is read and checked against the plan, and the position moves
    on and is saved whatever happens -- a spent draw that is not recorded
    would put every later prediction one step out.
    """

    def __init__(self, ctx: Context, account, planner, goal, owned_index, events, tiers,
                 rare_tickets: int, platinum_tickets: int):
        self.ctx, self.account, self.planner, self.goal = ctx, account, planner, goal
        self.owned_index, self.events, self.tiers = owned_index, events, tiers
        self.state = RunState(rare_left=rare_tickets, platinum_left=platinum_tickets)
        self.planner.platinum_tickets = platinum_tickets
        self.nav = ctx.navigator()
        ctx.captures.mkdir(parents=True, exist_ok=True)

    # -- helpers --

    def _event(self, key):
        from . import events as live

        return live.by_key(self.events, key)

    def _publish_state(self) -> None:
        s = self.state
        self.ctx.put("run", dict(rolled=s.rolled, rare_left=s.rare_left, platinum_left=s.platinum_left,
                                 cat_food=s.cat_food, unlocked=s.unlocked, reason=s.reason,
                                 remaining=len(self.goal.remaining(self.owned_index.owned))))
        self.ctx.put("account", self.account.to_json())

    def _draw_button(self, frame, screen):
        from .perception import perceive

        profile = self.ctx.graph.profile_for(frame)
        for name in (screen, self.ctx.graph.screens[screen].parent):
            if name:
                found = profile.find(frame, name, "Try once!")
                if found:
                    return found
        return perceive(frame, self.ctx.ocr).find("Try once!")

    def _await_result(self, before):
        """(frame, read, moved): the result screen once its name plate reads --
        or the last frame seen -- and whether the screen ever left `before`."""
        from .results import read_result
        from .uigraph import frame_changed

        deadline = time.time() + REVEAL_TIMEOUT
        pool = {c for e in self.events for r in (2, 3, 4, 5) for c in e.banner.slots.get(r) or []}
        moved, last = False, None
        while time.time() < deadline:
            time.sleep(1.2)
            frame = self.ctx.session.screenshot()
            moved = moved or frame_changed(before, frame)
            read = read_result(frame, self.ctx.ocr, self.ctx.dataset, pool)
            if read.cat_id is not None:
                return frame, read, True
            last = (frame, read, moved)
        return last

    def _advance(self, cat_id, steps) -> None:
        delta, track = next_position(self.account.track, steps)
        self.account.index += delta
        self.account.track = track
        self.account.rolls_made += 1
        self.account.last_cat_id = cat_id
        self.account.storage_used += 1

    def _recover(self, observed_cat) -> bool:
        """Place the cat just seen near the saved position; True if unique."""
        from .gacha import Gacha

        found = set()
        for index in range(max(1, self.account.index - 3), self.account.index + 25):
            for track in (0, 1):
                for e in self.events:
                    roll = Gacha(e.banner, self.account.seed, self.ctx.dataset).cell(index, track)
                    if roll.cat_id == observed_cat:
                        d, t = next_position(track, roll.reroll_steps)
                        found.add((index + d, t))
        if len(found) != 1:
            return False
        index, track = found.pop()
        self.ctx.log(f"  recovered: the cat seen puts the account at {index}{'AB'[track]}")
        self.account.index, self.account.track = index, track
        self.account.last_cat_id = observed_cat
        self.account.source = "resynced"
        return True

    # -- one draw --

    def roll_once(self, step) -> str | None:
        """Make one planned draw. Returns a reason to stop, or None to go on."""
        from . import draw
        from .planner import PLATINUM_TICKET

        ctx, s = self.ctx, self.state
        platinum = step.currency == PLATINUM_TICKET
        event = self._event(step.banner_key)
        if event is None:
            return f"{step.banner_key} is not a live event"
        if not self.nav.goto(event.screen, log=ctx.log):
            return f"could not put {event.label} on screen"
        frame = ctx.session.screenshot()
        here = ctx.graph.identify(frame)
        if here != event.screen:
            return f"expected {event.label} on screen, saw {here}"
        button = self._draw_button(frame, here)
        gate = draw.check(frame, button)
        ctx.put("gate", dict(gate.to_json(), event=event.label, platinum=platinum,
                             position=step.position, cat=ctx.dataset.cat_name(step.cat_id)))
        if not gate.ok:
            if gate.red and gate.red > draw.RED_LIMIT:
                return "rare tickets depleted: the draw button now spends Cat Food"
            return f"draw refused: {gate.reason}"
        food = read_number(frame, CAT_FOOD_BOX, ctx.ocr)
        if food is not None:
            if s.cat_food is None:
                # The first reading only counts once a second one agrees.
                again = read_number(ctx.session.screenshot(), CAT_FOOD_BOX, ctx.ocr)
                s.cat_food = food if again == food else None
            elif food < s.cat_food and len(str(food)) == len(str(s.cat_food)) \
                    and (s.cat_food - food) % CAT_FOOD_PER_DRAW == 0:
                # Cat Food only ever goes in 150s on a draw; a misread digit
                # rarely lands on one. A second fresh read must agree.
                again = read_number(ctx.session.screenshot(), CAT_FOOD_BOX, ctx.ocr)
                if again == food:
                    return f"Cat Food fell from {s.cat_food} to {food}"
            elif food > s.cat_food and len(str(food)) == len(str(s.cat_food)):
                s.cat_food = food           # rewards add Cat Food

        # From the tap on, the draw has happened: whatever goes wrong below,
        # the position is advanced and saved before anything else.
        self.nav._tap(*gate.tap, 0.4)
        s.rolled += 1
        if platinum:
            s.platinum_left -= 1
            self.planner.platinum_tickets = max(0, self.planner.platinum_tickets - 1)
            self.planner.platinum_wanted.discard(step.cat_id)
        else:
            s.rare_left = None if s.rare_left is None else s.rare_left - 1
        verdict, seen = "unverified", None
        try:
            got = self._await_result(frame)
            if got and not got[2]:
                # The screen never left the capsule screen: the tap was
                # swallowed and no draw happened. Nothing is spent or moved.
                verdict = "no draw"
                s.rolled -= 1
                if platinum:
                    s.platinum_left += 1
                    self.planner.platinum_tickets += 1
                    self.planner.platinum_wanted.add(step.cat_id)
                elif s.rare_left is not None:
                    s.rare_left += 1
            elif got:
                result_frame, read, _ = got
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                cv2.imwrite(str(ctx.captures / f"roll_{stamp}_{step.position}.png"), result_frame)
                seen = read.cat_id
                verdict = ("match" if seen == step.cat_id else
                           "unverified" if seen is None else "desync")
        finally:
            if verdict == "no draw":
                pass
            elif verdict == "desync" and self._recover(seen):
                verdict = "recovered"
            else:
                self._advance(step.cat_id if verdict != "desync" else seen, step.reroll_steps)
            if verdict == "match":
                self.account.confirmed = True
            if verdict != "no draw":
                self.account.save()
        if verdict == "no draw":
            return "the draw tap had no effect; nothing was spent or moved"
        new = step.cat_id not in self.owned_index.owned and verdict == "match"
        if new:
            self.owned_index.owned.add(step.cat_id)
            self.owned_index.save()
            self.planner.scorer.owned.add(step.cat_id)
            if step.rarity >= UBER:
                s.unlocked.append(dict(cat=ctx.dataset.cat_name(step.cat_id), rarity=step.rarity,
                                       position=step.position, event=event.label))
        ctx.put("roll", dict(n=s.rolled, position=step.position, event=event.label, platinum=platinum,
                             expected=ctx.dataset.cat_name(step.cat_id),
                             seen=ctx.dataset.cat_name(seen) if seen is not None else None,
                             verdict=verdict, new=new, rarity=step.rarity,
                             goal=step.cat_id in self.goal.wanted))
        ctx.log(f"  #{s.rolled:>3} {step.position:>6} {'PLAT' if platinum else '    '} "
                f"{ctx.dataset.cat_name(step.cat_id):<26} {verdict}{'  NEW' if new else ''}")
        if verdict == "unverified":
            s.unverified_in_a_row += 1
            if s.unverified_in_a_row >= 2:
                return "two draws in a row could not be read: stopping to check the position"
        else:
            s.unverified_in_a_row = 0
        if verdict == "desync":
            return f"desync: expected {ctx.dataset.cat_name(step.cat_id)}, saw {ctx.dataset.cat_name(seen)}"
        return None

    # -- the loop --

    def run(self) -> str:
        from .planner import PLATINUM_TICKET

        ctx, s = self.ctx, self.state
        try:
            while True:
                ctx.check()
                owned = self.owned_index.owned
                if self.goal.complete(owned):
                    s.reason = "every wanted cat is unlocked"
                    break
                if (s.rare_left is not None and s.rare_left <= 0) and s.platinum_left <= 0:
                    s.reason = "out of rare and platinum tickets"
                    break
                # Until a live draw has matched the saved position, only rare
                # tickets are spent: a platinum ticket on a wrong position is
                # an uber lost.
                spare = self.planner.platinum_tickets
                if not self.account.confirmed or s.unverified_in_a_row:
                    self.planner.platinum_tickets = 0
                if s.rare_left is not None and s.rare_left <= 0:
                    step = self._platinum_only_step()
                    if step is None:
                        s.reason = "rare tickets depleted; no tier-list pick is next on the platinum machine"
                        break
                else:
                    plan = self.planner.plan(self.account.seed, rolls=PLAN_ROLLS, index=self.account.index,
                                             track=self.account.track, previous_cat=self.account.last_cat_id)
                    ctx.put("plan", plan_json(plan, ctx.dataset, self.events))
                    step = plan.steps[0]
                self.planner.platinum_tickets = spare
                if step.currency == PLATINUM_TICKET and s.platinum_left <= 0:
                    s.reason = "planned a platinum draw with none left"
                    break
                if self.account.storage_used >= self.account.storage_capacity - STORAGE_MARGIN:
                    ctx.log("  Cat Storage nearly full: Use all")
                    if not drain_storage(ctx):
                        s.reason = "could not empty Cat Storage"
                        break
                    self.account.storage_used = 0
                reason = self.roll_once(step)
                self._publish_state()
                if reason:
                    s.reason = reason
                    break
        except Stopped:
            s.reason = "stopped by request"
        self._publish_state()
        ctx.log(f"run over: {s.reason}")
        return s.reason

    def _platinum_only_step(self):
        """With the rare tickets gone, a platinum draw here -- only if it lands
        one of the tier-list picks the tickets are reserved for."""
        from .planner import PLATINUM_TICKET, PlanStep

        banner = self.planner.platinum_banner
        if banner is None or self.state.platinum_left <= 0:
            return None
        roll = self.planner._evaluate(self.planner._gacha(self.account.seed, banner, {}),
                                      self.account.index, self.account.track, self.account.last_cat_id)
        if roll.cat_id in self.owned_index.owned or roll.cat_id not in self.planner.platinum_wanted:
            return None
        return PlanStep(index=self.account.index, track=self.account.track, banner_key=banner.key,
                        banner_name=banner.name, cat_id=roll.cat_id, rarity=roll.rarity,
                        currency=PLATINUM_TICKET, is_new=True, reroll_steps=roll.reroll_steps)
