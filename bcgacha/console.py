"""What a run says on the terminal: each task as it starts and ends, what it
found, every draw, and any error with what to do about it.

It hears exactly what the live page hears -- the log lines and the published
sections of a run (jobs.py) -- and prints a readable account of them.
"""

from __future__ import annotations

import os
import sys
import time

from .data import RARITY_NAMES

MARKS = {"done": "✓", "skipped": "–", "failed": "✗", "stopped": "■", "not run": "·"}


class Console:
    def __init__(self, out=None, colour: bool | None = None, quiet: bool = False):
        self.out = out or sys.stdout
        tty = hasattr(self.out, "isatty") and self.out.isatty()
        self.colour = tty and not os.environ.get("NO_COLOR") if colour is None else colour
        self.quiet = quiet
        self._tasks: dict[str, str] = {}
        self._said: set[str] = set()
        self.announced = False              # the run's summary was said before it started

    # -- text --

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.colour else text

    def bold(self, t): return self.paint(t, "1")
    def dim(self, t): return self.paint(t, "2")
    def good(self, t): return self.paint(t, "32")
    def bad(self, t): return self.paint(t, "31;1")
    def note(self, t): return self.paint(t, "36")

    def say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    # -- what a run hears --

    def log(self, line: str) -> None:
        if line.startswith("== "):
            return                          # the task header says it
        if line.startswith(("!! ", "run finished", "run ended")):
            return                          # the error section and the summary say it
        if "Traceback" in line or line.startswith("  File "):
            self.say(self.dim(line))
            return
        indented = line.startswith("    ")
        if indented and self.quiet:
            return
        stamp = time.strftime("%H:%M:%S")
        text = f"  {self.dim(stamp)} {line}"
        self.say(self.dim(text) if indented else text)

    def publish(self, section: str, payload) -> None:
        show = getattr(self, f"_on_{section}", None)
        if show and payload is not None:
            show(payload)

    # -- sections --

    def _on_tasks(self, tasks) -> None:
        total = len(tasks)
        for n, t in enumerate(tasks, 1):
            was = self._tasks.get(t["name"])
            if was == t["state"]:
                continue
            self._tasks[t["name"]] = t["state"]
            if t["state"] == "running":
                self.say()
                self.say(self.bold(f"[{n}/{total}] {t['title']}") + self.dim(f" -- {t['does']}"))
            elif t["state"] in ("done", "skipped"):
                took = f" ({t['seconds']}s)" if t.get("seconds") else ""
                self.say(f"  {self.good(MARKS[t['state']])} {t['detail']}{self.dim(took)}")
            elif t["state"] == "stopped":
                self.say(f"  {self.bad(MARKS[t['state']])} {t['title']} {t['state']}: {t['detail']}")

    def _on_error(self, e) -> None:
        self.say()
        self.say(self.bad(f"✗ {e['title']} failed: {e['message']}"))
        if e.get("hint"):
            self.say(f"  what to do: {e['hint']}")

    def _on_request(self, r) -> None:
        if self.announced:
            return
        self.say(self.bold("This run will:"))
        for line in r["summary"]:
            self.say(f"  • {line}")
        self.say(self.dim(f"  (as a command: {r['command']})"))

    def _on_targets(self, rows) -> None:
        for u in rows:
            owned = "already owned" if u["owned"] else "not owned"
            self.say(f"  target #{u['rank']}: {self.bold(u['name'])} ({u['rarity_name']}, tier {u['tier']}, "
                     f"{owned}) -- rolls on {u['where']}")

    def _on_goal(self, g) -> None:
        rows = g["targets"] + g["legendaries"] + g["ubers"] + g["platinum"]
        wanted = [r for r in rows if not r["owned"]]
        self.say(f"  wanted: {g['remaining']} unit{'s' if g['remaining'] != 1 else ''}")
        if g.get("empty_why"):
            self.say(self.note(f"    nothing to go for: {g['empty_why']}"))
            self.say(self.dim("    name a unit with -t (bcgacha search finds it), or add --platinum N"))
        for r in wanted[:12]:
            plat = " [Platinum ticket reserved]" if r.get("platinum") else ""
            self.say(f"    {r['tier']:<4} {r['name']:<28} {self.dim(r['why'])}{plat}")
        if len(wanted) > 12:
            self.say(self.dim(f"    ... and {len(wanted) - 12} more (all on the live page)"))
        for r in g.get("unreachable", []):
            self.say(self.bad(f"    {r['name']}: no live event rolls it, so it is left out"))

    def _on_simulation(self, sim) -> None:
        got = sim["unlocked"]
        given = f"{sim['rare_given']} rare ticket{'s' if sim['rare_given'] != 1 else ''}"
        if sim.get("rare_source"):
            given += f" ({sim['rare_source']})"
        self.say(f"  on paper, {given} would unlock {len(got)}:")
        for u in got[:15]:
            plat = " with a Platinum ticket" if u["platinum"] else ""
            self.say(f"    draw {u['n']:>3} at {u['position']:>6} on {u['event']}: "
                     f"{self.good(u['cat'])}{plat}")
        if sim["left"]:
            names = ", ".join(x["name"] for x in sim["left"][:6])
            more = f" and {len(sim['left']) - 6} more" if len(sim["left"]) > 6 else ""
            self.say(self.dim(f"    still wanted after: {names}{more}"))

    def _on_plan(self, plan) -> None:
        if "plan" in self._said:
            return                          # a run republishes it every draw
        self._said.add("plan")
        self.say("  next draws:")
        for s in plan[:8]:
            mark = self.good(" NEW") if s["new"] else ""
            why = self.dim(f"  {s['why']}") if s.get("why") else ""
            self.say(f"    {s['position']:>6} {s['event'][:24]:<24} {'PLAT' if s['platinum'] else 'rare'} "
                     f"{RARITY_NAMES.get(s['rarity'], '?'):<11} {s['cat']}{mark}{why}")

    def _on_roll(self, r) -> None:
        pass                                # the run logs each draw as it goes

    def _on_seed_search(self, s) -> None:
        pct = int(100 * s["done"])
        if pct % 10 == 0 and f"seed{pct}" not in self._said:
            self._said.add(f"seed{pct}")
            self.say(self.dim(f"  seed search {pct}%: {s['survivors']} seeds still fit, {s['seconds']}s"))


def table(rows: list[list[str]], head: list[str] | None = None) -> str:
    """Plain columns, as wide as their widest cell."""
    rows = [head] + rows if head else rows
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    if head:
        lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)
