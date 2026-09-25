"""One run of the bot: everything a person asked for, task after task.

The command line and the live page both describe a run as a Request and hand
it to run(); neither has a way of its own to do anything. So whatever one can
do the other can, and both report the same way: every task is published as it
starts and ends (the "tasks" section), with what each found along the way.

The tasks, in the order they run, each only when needed:

  update    the newest event schedule and tier list, downloaded  (if asked)
  map       this save's sagas and chapters, and this phone's Cat Base doors
  storage   empty Cat Storage with Use all                      (if asked)
  owned     read the Cat Guide for the cats this account has    (once, or if asked)
  capsule   each live event on the phone, and the rare tickets held (before rolling)
  seed      the seed and position, from saved result screens
  goal      what is wanted, the route to it, and the run played out on paper
  roll      draw rare (and Platinum) tickets towards the goal   (if asked)
  capsules  open Cat or Lucky Capsules                          (if asked)
  legends   play the Uncanny Legends with the Cat CPU           (if asked)
"""

from __future__ import annotations

import shlex
import time
import traceback
from dataclasses import asdict, dataclass, field

from . import pipeline as P

# Held tickets assumed for the paper run when the count is unknown.
SIM_ASSUMED = 50
MACHINE_NAMES = {"cat": "Cat Capsules", "lucky": "Lucky Capsules", "lucky_g": "Lucky Capsules G"}
TITLES = {
    "update": "Events and tier list",
    "map": "Map of this save",
    "storage": "Empty Cat Storage",
    "owned": "Owned cats",
    "capsule": "Events and tickets",
    "seed": "Seed and position",
    "goal": "Goal and plan",
    "roll": "Rare draws",
    "capsules": "Normal capsules",
    "legends": "Uncanny Legends",
}
DOES = {
    "update": "downloading the newest event schedule and the community tier list",
    "map": "the save's sagas and chapters, and this phone's Cat Base doors",
    "storage": "Use all on Cat Storage, so everything drawn joins the roster",
    "owned": "reading every Cat Guide entry for what this account owns",
    "capsule": "visiting each live event's tab, and reading the rare ticket counter",
    "seed": "the account seed and position, from saved result screens",
    "goal": "what is wanted, the best route to it, and the run on paper",
    "roll": "drawing tickets along the planned route, each result checked",
    "capsules": "opening the normal machines with their own tickets",
    "legends": "beating Uncanny Legends stages with the Cat CPU",
}


class Refused(RuntimeError):
    """A run that cannot go ahead as asked, with what to do about it."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass
class Request:
    targets: list[str] = field(default_factory=list)    # units wanted, most wanted first
    events: list[str] = field(default_factory=list)     # events whose Ubers are wanted
    legend_rares: bool = False                          # those events' Legend Rares too
    prefer: str | None = None                           # event whose Legend Rare comes first
    roll: bool = False                                  # draw towards the goal
    rare: int | None = None                             # rare tickets to spend; None: all
    platinum: int | None = None                         # Platinum tickets to spend; None: all
    capsules: dict = field(default_factory=dict)        # machine -> capsules to open, 0: all
    uncanny: bool = False                               # play the Uncanny Legends
    storage: bool = False                               # empty Cat Storage first
    rescan_owned: bool = False
    rescan_map: bool = False
    update: bool = False                                # download events and tiers first
    only: list | None = None                            # just these tasks: upkeep from the page

    @classmethod
    def from_json(cls, raw: dict) -> "Request":
        known = {k: v for k, v in (raw or {}).items() if k in cls.__dataclass_fields__}
        req = cls(**known)
        req.targets = [str(t).strip() for t in req.targets if str(t).strip()]
        req.events = [str(e).strip() for e in req.events if str(e).strip()]
        req.rare = None if req.rare in (None, "", "all") else max(0, int(req.rare))
        req.platinum = None if req.platinum in (None, "", "all") else max(0, int(req.platinum))
        req.capsules = {m: max(0, int(n or 0)) for m, n in (req.capsules or {}).items() if m in MACHINE_NAMES}
        return req

    def to_json(self) -> dict:
        return asdict(self)

    @property
    def spends(self) -> bool:
        return self.roll or bool(self.capsules) or self.uncanny

    def tasks(self) -> list[str]:
        if self.only:
            return [t for t in TITLES if t in self.only]
        out = (["update"] if self.update else []) + ["map"]
        if self.storage:
            out.append("storage")
        if self.roll or self.targets or self.events or not self.spends:
            out += ["owned"] + (["capsule"] if self.roll else []) + ["seed", "goal"]
        if self.roll:
            out.append("roll")
        if self.capsules:
            out.append("capsules")
        if self.uncanny:
            out.append("legends")
        return out

    def command(self) -> str:
        """The command line that asks for this same run."""
        words = ["bcgacha", "run"]
        for t in self.targets:
            words += ["--target", t]
        for e in self.events:
            words += ["--event", e]
        if self.legend_rares:
            words.append("--legend-rares")
        if self.prefer:
            words += ["--prefer", self.prefer]
        if self.roll:
            words += ["--roll"] + (["--rare", str(self.rare)] if self.rare is not None else [])
        if self.platinum is not None:
            words += ["--platinum", str(self.platinum)]
        for machine, n in self.capsules.items():
            words += ["--capsules", f"{machine}:{n}" if n else machine]
        if self.uncanny:
            words.append("--play-legends")
        if self.storage:
            words.append("--empty-storage")
        if self.rescan_owned:
            words.append("--rescan-owned")
        if self.rescan_map:
            words.append("--rescan-map")
        if self.update:
            words.append("--update")
        if self.only == ["update"]:
            words = ["bcgacha", "tools", "update"]
        elif self.only:
            words = ["bcgacha", "tools", "upkeep", *("tickets" if t == "capsule" else t for t in self.only)]
        return " ".join(shlex.quote(w) for w in words)

    def summary(self) -> list[str]:
        """What this run will do, in words a person checks before it starts."""
        if self.only:
            return ["only: " + ", ".join(TITLES[t].lower() for t in self.tasks())
                    + (" (read afresh)" if self.rescan_map or self.rescan_owned else "")]
        lines = ["first download the newest events and tier list"] if self.update else []
        if self.targets:
            lines.append("want, most first: " + ", ".join(self.targets))
        if self.events:
            lines.append(f"want the Ubers of: {', '.join(self.events)}"
                         + (" (and their Legend Rares)" if self.legend_rares else ""))
        elif not self.targets:
            lines.append("want every unowned Uber of every live event"
                         + (" and their Legend Rares" if self.legend_rares else ""))
        if self.roll:
            lines.append(f"draw with {'every rare ticket held' if self.rare is None else f'up to {self.rare} rare tickets'}"
                         + (" and every Platinum ticket held" if self.platinum is None else
                            f" and up to {self.platinum} Platinum" if self.platinum else ", no Platinum")
                         + "; it stops once everything wanted is unlocked")
        else:
            lines.append("plan only: no rare ticket is spent")
        for machine, n in self.capsules.items():
            lines.append(f"open {MACHINE_NAMES[machine]}: "
                         + (f"{n} capsule{'s' if n != 1 else ''}" if n else "until its tickets run out"))
        if self.uncanny:
            lines.append("play the Uncanny Legends with the Cat CPU until one stage is lost 3 times")
        return lines


# -- the run -------------------------------------------------------------------------

class Job:
    """One Request carried out on a Context, published task by task."""

    def __init__(self, ctx: P.Context, request: Request, reload=None):
        self.ctx, self.req, self.reload = ctx, request, reload
        self.tasks = [dict(name=n, title=TITLES[n], does=DOES[n], state="waiting", detail="",
                           started=None, seconds=None) for n in request.tasks()]
        self.owned = self.account = self.events = None
        self.planner = self.goal = self.tiers = None
        self.rare_held: int | None = None
        self.rare_source = ""
        self.plat_held: int | None = None
        self.plat_source = ""

    # -- reporting --

    def _put_tasks(self) -> None:
        self.ctx.put("tasks", [dict(t) for t in self.tasks])

    def _task(self, name):
        return next(t for t in self.tasks if t["name"] == name)

    def _set(self, name, state, detail=None) -> None:
        t = self._task(name)
        t["state"] = state
        if detail is not None:
            t["detail"] = detail
        if state == "running":
            t["started"] = time.time()
        elif t["started"]:
            t["seconds"] = round(time.time() - t["started"], 1)
        self._put_tasks()
        if state == "running":
            self.ctx.put("stage", dict(name=name, state="running"))

    def _needs_device(self, what: str) -> None:
        if self.ctx.session is None:
            raise Refused(f"{what} needs the phone", "attach the iPhone and run again")

    # -- the whole of it --

    def run(self) -> tuple[bool, str]:
        ctx = self.ctx
        ctx.put("request", dict(self.req.to_json(), command=self.req.command(), summary=self.req.summary()))
        ctx.put("error", None)
        self._put_tasks()
        current = None
        try:
            for t in self.tasks:
                ctx.check()
                current = t["name"]
                self._set(current, "running")
                ctx.log(f"== {t['title']}: {t['does']}")
                detail = getattr(self, f"_do_{current}")()
                self._set(current, "done" if detail is None or not detail.startswith("skipped") else "skipped",
                          detail or "")
            last = self.tasks[-1]
            return True, f"{last['title'].lower()}: {last['detail']}" if last["detail"] else "done"
        except P.Stopped:
            self._fail(current, "stopped", "stopped by request")
            return False, "stopped"
        except Exception as exc:
            hint = getattr(exc, "hint", "")
            self._fail(current, "failed", str(exc), hint)
            if not isinstance(exc, Refused):
                ctx.log(traceback.format_exc(limit=6).rstrip())
            return False, f"{current} failed: {exc}"

    def _fail(self, name, state, message, hint="") -> None:
        if name:
            self._set(name, state, message)
        for t in self.tasks:
            if t["state"] == "waiting":
                t["state"] = "not run"
        self._put_tasks()
        if state == "failed":
            self.ctx.put("error", dict(task=name, title=TITLES.get(name, name), message=message, hint=hint))
            self.ctx.log(f"!! {TITLES.get(name, name)} failed: {message}" + (f" -- {hint}" if hint else ""))

    # -- the tasks --

    def _do_update(self):
        """The newest schedule and tier list. Needs no phone; the map is built
        again after, so a new event is a screen at once."""
        from . import data
        from . import events as live
        from . import tiers as T
        from .uigraph import UIGraph

        ctx = self.ctx

        def live_now():
            try:
                return {e.key: e for e in live.live_events(data.load())}
            except FileNotFoundError:
                return {}

        before = live_now()
        ctx.log("  downloading the event schedule (godfat's dataset)")
        try:
            path = data.fetch()
        except Exception as exc:
            raise Refused(f"the event schedule did not download: {exc}",
                          "check the internet connection; the schedule kept is unchanged") from None
        ctx.dataset = data.load()
        after = live_now()
        new = [e for k, e in after.items() if k not in before]
        ended = [e for k, e in before.items() if k not in after]
        ctx.log(f"  {path.name}: {path.stat().st_size:,} bytes, {len(after)} events live today")
        for e in new:
            ctx.log(f"  new: {e.label} ({e.start} to {e.end})")
        for e in ended:
            ctx.log(f"  gone: {e.label}")
        ctx.log("  downloading the tier list")
        try:
            tier_list = T.match(T.parse(T.fetch_text()), ctx.dataset)
            tier_list.save()
            tiers = f"{len(tier_list.by_cat)} cats ranked"
        except Exception as exc:
            tiers = f"tier list kept as it was ({type(exc).__name__}: {exc})"
            ctx.log(f"  {tiers}")
        ctx.graph = self.reload() if self.reload else UIGraph.load()
        self.events = None
        from .catindex import OwnedIndex

        index = OwnedIndex.load()
        seen, _ = live.last_screen()
        ctx.put("events", [dict(e.to_json(ctx.dataset, index.owned if index.complete else None), seen=seen.get(e.key))
                           for e in after.values()])
        ctx.put("update", dict(at=time.strftime("%Y-%m-%d %H:%M"), events=[e.label for e in after.values()],
                               new=[dict(label=e.label, start=e.start, end=e.end) for e in new],
                               ended=[e.label for e in ended], tiers=tiers))
        changes = (f"; new: {', '.join(e.label for e in new)}" if new else "") + \
                  (f"; ended: {', '.join(e.label for e in ended)}" if ended else "")
        return f"{len(after)} events live{changes or ', none new'}; {tiers}"

    def _do_map(self):
        from . import carousel

        if self.req.rescan_map or carousel.load_catalogue() is None:
            self._needs_device("Reading the save's sagas and chapters")
        if self.ctx.session is None:
            catalogue = carousel.load_catalogue()
            return f"{len(catalogue['sagas'])} sagas saved (not checked: no phone)"
        catalogue = carousel.ensure(self.ctx.session, rescan=self.req.rescan_map, log=self.ctx.log,
                                    graph=self.ctx.graph, progress=getattr(self.ctx, "map_progress", None))
        if self.reload:
            self.ctx.graph = self.reload()
        self.ctx.put("graph", dict(sagas=[s["name"] for s in catalogue["sagas"]],
                                   screens=len(self.ctx.graph.screens),
                                   transitions=len(self.ctx.graph.transitions)))
        return f"{len(catalogue['sagas'])} sagas, {len(self.ctx.graph.screens)} screens"

    def _do_storage(self):
        from .state import STATE_PATH, Account

        self._needs_device("Emptying Cat Storage")
        if not P.drain_storage(self.ctx):
            raise Refused("Cat Storage was not emptied", "look at the phone: a question may be waiting")
        if STATE_PATH.exists():
            account = Account.load()
            account.storage_used = getattr(self.ctx, "storage_left", 0)
            account.storage_capacity = getattr(self.ctx, "storage_capacity", account.storage_capacity)
            account.save()
        return f"{getattr(self.ctx, 'storage_left', 0)} left in storage"

    def _do_owned(self):
        from .catindex import OwnedIndex

        index = OwnedIndex.load()
        if not index.complete or self.req.rescan_owned:
            self._needs_device("Reading the Cat Guide")
        if self.ctx.session is None:
            self.ctx.put("owned", index.to_json(self.ctx.dataset))
            self.owned = index
            return f"{len(index.owned)} cats, as read {index.scanned_at}"
        self.owned = P.stage_owned(self.ctx, force=self.req.rescan_owned)
        return f"{len(self.owned.owned)} cats owned, read {self.owned.scanned_at}"

    def _do_capsule(self):
        """Every live event checked on the phone by going to its tab -- the
        schedule lists some the game does not show, and a route through one
        of those could never be drawn -- then the rare tickets held, read off
        the counter; else the count the last run left behind."""
        from . import events as live
        from .catindex import OwnedIndex
        from .state import STATE_PATH, Account

        self._needs_device("Checking the capsule screen")
        ctx = self.ctx
        nav = ctx.navigator()
        events = ctx.graph.events
        self.owned = self.owned or OwnedIndex.load()
        seen = {}
        for e in events:
            ctx.check()
            seen[e.key] = nav.goto(e.screen, log=ctx.log)
            ctx.log(f"  {e.label}: {'on the capsule screen' if seen[e.key] else 'NOT on the capsule screen'}")
        ctx.put("events", [dict(e.to_json(ctx.dataset, self.owned.owned if self.owned else None),
                                seen=seen.get(e.key)) for e in events])
        missing = [e for e in events if not seen.get(e.key)]
        if len(missing) == len(events):
            raise Refused("no live event could be put on screen", "look at the phone: something is in the way")
        # The route is planned over the events the phone shows, and no other.
        ctx.graph.events = [e for e in events if seen.get(e.key)]
        live.save_screen(seen)

        # The counters, each read twice on fresh frames and trusted only when
        # both reads agree. Cat Food and XP are read too: every number read
        # teaches the digit reader the glyphs a lone Platinum count needs.
        rare = self._counter(nav, "rare_capsules", P.TICKETS_BOX, also=(P.CAT_FOOD_BOX,))
        plat = self._counter(nav, "platinum_capsules", P.TICKETS_BOX)
        account = Account.load() if STATE_PATH.exists() else None
        self.rare_held, self.rare_source = self._held(rare, account.tickets if account else None,
                                                      "drawing until the button asks for Cat Food")
        self.plat_held, self.plat_source = self._held(plat, account.platinum_tickets if account else None,
                                                      "no Platinum ticket is spent")
        if account is not None and (rare is not None or plat is not None):
            account.tickets = rare if rare is not None else account.tickets
            account.platinum_tickets = plat if plat is not None else account.platinum_tickets
            account.save()
        ctx.put("tickets", dict(held=self.rare_held, source=self.rare_source, rare=self._rare_budget(),
                                platinum_held=self.plat_held, platinum_source=self.plat_source,
                                platinum=self._platinum_budget()))
        gone = f"; not shown: {', '.join(e.label for e in missing)}" if missing else ""
        return (f"{len(events) - len(missing)} events on screen{gone}; "
                f"{self.rare_held if self.rare_held is not None else '?'} rare held ({self.rare_source}), "
                f"{self.plat_held if self.plat_held is not None else '?'} Platinum held ({self.plat_source})")

    def _counter(self, nav, screen: str, box, also=()) -> int | None:
        """The ticket counter on `screen`, when two fresh reads agree. A read
        both frames agree on teaches the digit reader its glyphs -- the
        ticket counter's, and those of the counters `also` names."""
        from . import digits

        ctx = self.ctx
        if not nav.goto(screen, log=ctx.log):
            ctx.log(f"  could not reach {screen} to read its counter")
            return None
        atlas = digits.Atlas()
        frames = (nav.arrival[1], ctx.session.screenshot())
        for extra in also:
            reads = [digits.read(f, extra, ctx.ocr, atlas)[0] for f in frames]
            if reads[0] is not None and reads[0] == reads[1]:
                digits.teach(frames[0], extra, reads[0], atlas)
        first, how = digits.read(frames[0], box, ctx.ocr, atlas)
        # The same pixels read the same: a second read is only worth making
        # when the counter's picture has changed between the two frames.
        same = (digits.ink(frames[0], box) == digits.ink(frames[1], box)).all()
        again = first if same else digits.read(frames[1], box, ctx.ocr, atlas)[0]
        name = ctx.graph.screens[screen].title or screen
        if first is None or first != again:
            ctx.log(f"  {name}: ticket counter not read ({how if first is None else f'{first} then {again}'})")
            return None
        if how == "read":
            digits.teach(frames[0], box, first, atlas)
        ctx.log(f"  {name}: {first} ticket{'s' if first != 1 else ''} ({how})")
        return first

    @staticmethod
    def _held(read, saved, unknown: str) -> tuple[int | None, str]:
        if read is not None:
            return read, "read off the screen"
        if saved is not None:
            return saved, "as the last run left them: the counter did not read"
        return None, f"unknown: {unknown}"

    def _platinum_budget(self) -> int:
        """Platinum tickets this run may spend: as many as asked, never more
        than are held, and none when the count is not known."""
        held = self.plat_held
        if held is None:
            return 0
        return held if self.req.platinum is None else min(self.req.platinum, held)

    def _rare_budget(self) -> int | None:
        if self.req.rare is None:
            return self.rare_held
        return self.req.rare if self.rare_held is None else min(self.req.rare, self.rare_held)

    def _do_seed(self):
        # Finding it from captures/ needs no phone, only the saved screens.
        self.account = P.stage_seed(self.ctx)
        a = self.account
        return f"seed {a.seed} at {a.position} ({a.source or 'saved'}{', confirmed' if a.confirmed else ''})"

    def resolve_targets(self) -> list[int]:
        """The units the request names, or Refused naming the candidates."""
        from . import units

        catalogue = units.Catalogue(self.ctx.dataset, self.tiers, self.owned.owned, self.events)
        ids, rows = [], []
        for query in self.req.targets:
            unit, hits = catalogue.resolve(query)
            if unit is None:
                if not hits:
                    raise Refused(f"no unit is called {query!r}", "check the spelling, or search for it")
                raise Refused(f"{query!r} could be " + ", ".join(h.name for h in hits[:5]),
                              "give the full name, or pick one by its #id")
            ids.append(unit.id)
            rows.append(dict(unit.to_json(), query=query, rank=len(ids)))
        self.ctx.put("targets", rows)
        return ids

    def _do_goal(self):
        from . import events as live
        from .catindex import OwnedIndex
        from .tiers import TierList

        ctx = self.ctx
        self.owned = self.owned or OwnedIndex.load()
        if not self.owned.complete:
            raise Refused("there is no complete list of owned cats",
                          "run with the phone attached: the Cat Guide is read first")
        self.account = self.account or P.stage_seed(ctx)
        try:
            self.tiers = TierList.load()
        except FileNotFoundError:
            self.tiers = None
            ctx.log("no tier list saved: every Uber is ranked as middling (bcgacha tools tiers)")
        self.events = ctx.graph.events
        if "capsule" not in self.req.tasks():
            # No look at the phone this run: the last one, if fresh, says which
            # events the game shows; the schedule alone lists some it does not.
            seen, when = live.last_screen()
            ctx.put("events", [dict(e.to_json(ctx.dataset, self.owned.owned), seen=seen.get(e.key),
                                    checked=when) for e in self.events])
            gone = [e for e in self.events if seen.get(e.key) is False]
            if gone:
                ctx.log(f"left out, as the capsule screen did not show them at {when}: "
                        + ", ".join(e.label for e in gone))
                self.events = ctx.graph.events = [e for e in self.events if e not in gone]
        wanted_events = []
        for name in self.req.events:
            e = live.find(self.events, name)
            if e is None:
                raise Refused(f"no live event is called {name!r}",
                              "live now: " + ", ".join(e.label for e in self.events if not e.platinum))
            wanted_events.append(e)
        prefer = live.find(self.events, self.req.prefer) if self.req.prefer else None
        targets = self.resolve_targets()
        event_units = not targets or bool(wanted_events)
        if "capsule" not in self.req.tasks():
            # No look at the counter this run: what the last one read.
            self.plat_held, self.plat_source = self._held(None, self.account.platinum_tickets,
                                                          "no Platinum ticket is planned")
        platinum = self._platinum_budget()
        rare = self._rare_budget()
        source = ("as asked" if self.req.rare is not None and rare == self.req.rare
                  else self.rare_source or "")
        if rare is None and not self.req.roll:
            rare, source = self.account.tickets, "as the last run left them"
        assumed = rare is None
        if assumed:
            source = "assumed: the count is not known"
        sim_rare = SIM_ASSUMED if assumed else rare
        owned = self.owned.owned
        opts = dict(goal_events=wanted_events or None, legends=self.req.legend_rares,
                    targets=targets, event_units=event_units)
        self.planner, self.goal, self.tiers = P.build_plan(ctx, self.account, owned, self.events, platinum,
                                                           prefer, **opts)
        ctx.put("goal", P.goal_json(self.goal, ctx.dataset, self.tiers, owned, self.events))
        sim = P.simulate(ctx, self.account, owned, self.events, sim_rare, platinum, prefer, **opts)
        sim["assumed"] = assumed
        sim["rare_given"] = sim_rare
        sim["rare_source"] = source
        sim["platinum_given"] = platinum
        sim["platinum_source"] = self.plat_source
        ctx.put("simulation", sim)
        plan = self.planner.plan(self.account.seed, rolls=P.PLAN_ROLLS, index=self.account.index,
                                 track=self.account.track, previous_cat=self.account.last_cat_id)
        ctx.put("plan", P.plan_json(plan, ctx.dataset, self.events, self.goal, self.tiers))
        left = len(self.goal.remaining(owned))
        got = len(sim["unlocked"])
        return (f"{left} unit{'s' if left != 1 else ''} wanted; "
                f"{sim['rare_used']} rare{' (assumed)' if assumed else ''} would unlock {got}"
                f"{', ' + str(len(sim['left'])) + ' left after' if sim['left'] else ', every one'}")

    def _do_roll(self):
        self._needs_device("Drawing")
        if self.goal.complete(self.owned.owned):
            return "skipped: nothing wanted is left to draw for -- name a unit, or give Platinum tickets"
        rare = self._rare_budget()
        platinum = self._platinum_budget()
        if rare == 0 and not platinum:
            return "skipped: no rare tickets to spend"
        run = P.GoalRun(self.ctx, self.account, self.planner, self.goal, self.owned, self.events, self.tiers,
                        rare, platinum)
        self.ctx.put("stage", dict(name="roll", state="rolling"))
        reason = run.run()
        s = run.state
        detail = f"{s.rolled} drawn, {len(s.unlocked)} new Uber{'s' if len(s.unlocked) != 1 else ''}: {reason}"
        if reason not in ("every wanted cat is unlocked", "out of rare and platinum tickets") and \
                not reason.startswith("rare tickets depleted"):
            raise Refused(detail, "the position is saved after every draw: fix what stopped it, then run again")
        return detail

    def _do_capsules(self):
        from .capsules import CapsuleRun

        self._needs_device("Opening capsules")
        done = []
        for machine, n in self.req.capsules.items():
            self.ctx.check()
            self.ctx.log(f"-- {MACHINE_NAMES[machine]}: {n or 'until out of tickets'}")
            run = CapsuleRun(self.ctx, machine, limit=n or None)
            reason = run.run()
            done.append(f"{MACHINE_NAMES[machine]} {run.state.capsules} ({reason})")
            self.ctx.put("capsule_runs", done)
            if "fell" in reason or "could not" in reason:
                raise Refused("; ".join(done), "look at the phone before running the machines again")
        return "; ".join(done)

    def _do_legends(self):
        from .legends import LegendRun

        self._needs_device("Playing the Uncanny Legends")
        run = LegendRun(self.ctx)
        reason = run.run()
        s = run.state
        return f"{s.wins} won, {s.losses} lost: {reason}"


def run(ctx: P.Context, request: Request, reload=None) -> tuple[bool, str]:
    return Job(ctx, request, reload).run()


# -- what is known without touching the phone --------------------------------------------

def status(dataset=None) -> dict:
    """Everything saved about this account and today, and what to do next."""
    import datetime as dt

    from . import carousel
    from . import data as D
    from . import events as live
    from .catindex import OwnedIndex
    from .state import STATE_PATH, Account
    from .tiers import TIER_FILE, TIER_RANK, TierList

    out: dict = dict(next=[])
    try:
        dataset = dataset or D.load()
        source = D.DATA_DIR / "bc-en.yaml"
        out["data"] = dict(ok=True, updated=dt.date.fromtimestamp(source.stat().st_mtime).isoformat())
    except FileNotFoundError:
        out["data"] = dict(ok=False)
        out["next"].append("fetch the cat data: .venv/bin/python scripts/fetch_data.py --lang en")
        return out
    try:
        tiers = TierList.load()
        out["tiers"] = dict(ok=True, cats=len(tiers.by_cat),
                            updated=dt.date.fromtimestamp(TIER_FILE.stat().st_mtime).isoformat())
    except FileNotFoundError:
        tiers = None
        out["tiers"] = dict(ok=False)
        out["next"].append("fetch the tier list: bcgacha tools tiers")
    catalogue = carousel.load_catalogue()
    out["map"] = dict(ok=catalogue is not None, sagas=len(catalogue["sagas"]) if catalogue else 0)
    index = OwnedIndex.load()
    out["owned"] = dict(ok=index.complete, owned=len(index.owned), scanned_at=index.scanned_at)
    if not index.complete:
        out["next"].append("read the Cat Guide: any run with the phone attached does it first")
    if STATE_PATH.exists():
        a = Account.load()
        out["account"] = dict(ok=True, seed=a.seed, position=a.position, source=a.source,
                              confirmed=a.confirmed, rare=a.tickets, platinum=a.platinum_tickets,
                              storage=f"{a.storage_used}/{a.storage_capacity}",
                              saved=dt.datetime.fromtimestamp(STATE_PATH.stat().st_mtime).isoformat(timespec="minutes"))
    else:
        out["account"] = dict(ok=False)
        out["next"].append("find the seed: any run finds it from captures/, spending nothing")
    captures = list(P.CAPTURES.glob("roll_*.png")) if P.CAPTURES.exists() else []
    out["captures"] = len(captures)
    events = live.live_events(dataset)
    owned = index.owned if index.complete else set()
    seen, out["screen_checked"] = live.last_screen()
    out["events"] = []
    for e in events:
        ubers = list(e.ubers)
        out["events"].append(dict(label=e.label, key=e.key, end=e.end, platinum=e.platinum,
                                  on_phone=seen.get(e.key),
                                  ubers=len(ubers), ubers_missing=sum(c not in owned for c in ubers),
                                  legend_rares=len(e.legends),
                                  legend_rares_missing=sum(c not in owned for c in e.legends),
                                  best_missing=min((tiers.tier_of(c) for c in ubers if c not in owned),
                                                   key=lambda t: TIER_RANK.get(t, 99), default="-")
                                  if tiers else "?"))
    out["ready"] = out["data"]["ok"] and out["owned"]["ok"] and out["account"]["ok"]
    if out["ready"]:
        out["next"].append("plan: bcgacha plan   |   roll: bcgacha run --roll   |   guided: bcgacha")
    return out
