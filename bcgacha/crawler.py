"""Discover screens and transitions by pressing the controls on each screen.

The game draws its controls to one consistent gold style, so they can be found
rather than measured, and a screen can be explored by pressing each in turn and
noting where it lands.

Some controls must never be pressed. A few spend real money, and several spend
in-game currency with no confirmation at all -- the Rare Capsule's single-draw
button takes a ticket the instant it is touched. Those are listed per screen as
keep-out rectangles, and anything inside one is recorded but never pressed, so
the map still shows the control exists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import safety
from .layout import landscape_to_hid
from .uigraph import Button, Navigator, Screen, Transition, UIGraph, find_buttons

# Rectangles (x0, y0, x1, y1) that must not be pressed, by screen.
KEEP_OUT: dict[str, list[tuple[float, float, float, float]]] = {
    # Real money.
    "*": [(0.52, 0.86, 0.72, 0.96)],                 # Store, on every base screen
    # Spends a Rare Ticket with no confirmation, and the 11-draw costs Cat Food.
    "rare_capsules": [(0.55, 0.66, 1.00, 0.90)],
    "cat_capsule": [(0.55, 0.66, 1.00, 0.90)],
    # Irreversible. Tapping a unit in the grid opens its own menu, and that
    # menu can exchange the unit for XP or NP -- the cat is gone. Nothing on
    # this screen may be pressed by exploration at all.
    "storage": [(0.00, 0.00, 1.00, 1.00)],
    # Starts a battle and spends energy.
    "cat_base": [(0.07, 0.23, 0.34, 0.33)],
    # Anything that leaves the game or changes the account.
    "title": [(0.41, 0.66, 0.59, 0.76)],             # Settings
    # A real-money offer. Everything on it except the back arrow is off limits.
    "purchase_offer": [(0.15, 0.00, 1.00, 0.90)],
}

# Screens whose controls must never be enumerated and pressed at all.
NEVER_CRAWL = {"purchase_offer", "settings", "title", "storage"}


def blocked(screen: str, button: Button) -> bool:
    for key in ("*", screen):
        for x0, y0, x1, y1 in KEEP_OUT.get(key, []):
            if x0 <= button.x <= x1 and y0 <= button.y <= y1:
                return True
    return False


@dataclass
class CrawlReport:
    visited: list[str] = field(default_factory=list)
    discovered: list[str] = field(default_factory=list)
    transitions: int = 0
    skipped: list[str] = field(default_factory=list)


class Crawler:
    def __init__(self, session, graph: UIGraph, home: str = "cat_base"):
        self.session = session
        self.graph = graph
        self.home = home
        self.nav = Navigator(session, graph)

    def _known_transition(self, src: str, x: float, y: float) -> bool:
        return any(
            t.src == src and abs(t.x - x) < 0.04 and abs(t.y - y) < 0.04
            for t in self.graph.transitions
        )

    def explore(self, screen: str, log=print) -> CrawlReport:
        """Press each unpressed control on `screen` and record where it goes."""
        report = CrawlReport(visited=[screen])
        if screen in NEVER_CRAWL:
            log(f"  refusing to crawl {screen}: it carries irreversible controls")
            report.skipped.append(screen)
            return report
        if not self.nav.goto(screen):
            log(f"  cannot reach {screen}")
            return report
        frame = self.session.screenshot()
        buttons = find_buttons(frame)
        log(f"  {screen}: {len(buttons)} controls")

        for i, button in enumerate(buttons):
            if blocked(screen, button):
                report.skipped.append(f"{screen}#{i}@({button.x:.2f},{button.y:.2f})")
                continue
            if self._known_transition(screen, button.x, button.y):
                continue
            if not self.nav.goto(screen):
                break
            self.session.tap(*landscape_to_hid(button.x, button.y))
            time.sleep(2.4)
            after = self.session.screenshot()
            if safety.inspect_dialog(after).present:
                # Never confirm anything found by poking around.
                self.nav._clear_obstruction(after)
                continue
            landed = self.graph.identify(after)
            if landed is None or landed == screen:
                continue
            self.graph.transitions.append(Transition(
                src=screen, dst=landed, x=round(button.x, 4), y=round(button.y, 4),
                label=f"button {i}",
            ))
            report.transitions += 1
            log(f"    control {i} at ({button.x:.3f}, {button.y:.3f}) -> {landed}")
        self.nav.goto(self.home)
        return report
