"""What Use all leaves in Cat Storage: capsules that can no longer be used.

A Cat Capsule item or unit already at its maximum stays in Storage after Use
all. Each item of those has a Trade-in button: one trade puts one capsule
toward a Rare Ticket, five make a ticket. What cannot be traded -- the basic
cats -- goes with "Exchange all for NP/XP", answered NP.

Every press here is made only once the question it answers has been read
and says what is expected: the trade question must name trading capsules you
can no longer use for a Rare Ticket, and Exchange all's must be its own
"Everything will be exchanged ... NP or XP?". Anything else is closed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# Where the stored capsules float, clear of the filters above and the
# buttons below.
FIELD_XS = (0.16, 0.26, 0.36, 0.46, 0.56, 0.66, 0.76, 0.86)
FIELD_YS = (0.26, 0.38, 0.50, 0.62, 0.72)
# A notice with no button goes at a tap on it.
NOTICE_TAP = (0.5, 0.44)
# Taps in a row that trade nothing before the trading is called done: every
# point of the field tried once.
MISSES = len(FIELD_XS) * len(FIELD_YS)


@dataclass
class Traded:
    traded: int = 0
    tickets: int = 0
    skipped: set = field(default_factory=set)       # what a tap found untradeable
    reason: str = ""

    def to_json(self) -> dict:
        return dict(traded=self.traded, tickets=self.tickets, skipped=sorted(self.skipped), reason=self.reason)


def _flat(texts) -> str:
    return " ".join(t.text for t in texts).lower().replace(" ", "")


def _find(texts, *words):
    return next((t for t in texts if all(w in t.text.lower().replace(" ", "") for w in words)), None)


class Storage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.nav = ctx.navigator()

    def _look(self, wait: float = 1.4):
        from .perception import read_texts

        time.sleep(wait)
        frame = self.ctx.session.screenshot()
        return frame, read_texts(frame, self.ctx.ocr)

    def _tap(self, point, wait: float = 0.0) -> None:
        self.nav._tap(*point, wait)

    def _close(self, frame) -> None:
        """Close whatever panel is up by its X."""
        from .perception import CLOSE_SCORE, close_glyph_score, find_discs

        scored = [(close_glyph_score(frame, box), centre) for box, centre in find_discs(frame)]
        best = max(scored, default=None)
        if best and best[0] >= CLOSE_SCORE:
            self._tap(best[1])
        time.sleep(1.0)

    def count(self):
        from .pipeline import storage_count

        return storage_count(self._look(0.3)[1])

    # -- trading -----------------------------------------------------------------

    def trade_in(self, progress=None, limit: int | None = None) -> Traded:
        """Trade every capsule that has a Trade-in, one press at a time."""
        ctx, out = self.ctx, Traded()
        if not self.nav.goto("storage", log=ctx.log):
            out.reason = "could not reach Cat Storage"
            return out
        points = [(x, y) for y in FIELD_YS for x in FIELD_XS]
        misses, n = 0, 0
        while misses < MISSES and (limit is None or out.traded < limit):
            ctx.check()
            point = points[n % len(points)]
            n += 1
            self._tap(point)
            frame, texts = self._look()
            if "youhave" not in _flat(texts):
                misses += 1                     # open water, or a notice to clear
                if any(w in _flat(texts) for w in ("traded", "ticket!")):
                    self._tap(NOTICE_TAP)
                continue
            name = next((t.text for t in texts if 0.47 < t.centre[1] < 0.56), "?")
            trade = _find(texts, "trade")
            if trade is None or trade.centre[1] < 0.7:
                out.skipped.add(name)
                misses += 1
                self._close(frame)
                continue
            self._tap(trade.centre)
            frame, texts = self._look(1.6)
            said = _flat(texts)
            if not ("tradingin" in said and "rareticket" in said and "?" in said):
                ctx.log(f"  a Trade-in question not as expected, closed: {said[:90]!r}")
                no = _find(texts, "no")
                self._tap(no.centre) if no is not None and no.text.strip().lower() == "no" else self._close(frame)
                out.reason = "the Trade-in question did not read as expected"
                break
            yes = next((t for t in texts if t.text.strip().lower().rstrip("!") == "yes"), None)
            no = next((t for t in texts if t.text.strip().lower() == "no"), None)
            point_yes = yes.centre if yes else (1.0 - no.centre[0], no.centre[1]) if no else None
            if point_yes is None:
                self._close(frame)
                out.reason = "no Yes on the Trade-in question"
                break
            self._tap(point_yes)
            frame, texts = self._look(1.4)
            said = _flat(texts)
            out.traded += 1
            misses = 0
            if "traded" in said and "more" not in said or re.search(r"(got|received).*rareticket", said):
                out.tickets += 1
            ctx.log(f"  traded 1 {name} toward a Rare Ticket ({out.traded} traded, {out.tickets} tickets)")
            if progress:
                progress(out)
            self._tap(NOTICE_TAP)
        out.reason = out.reason or ("as many as asked" if limit and out.traded >= limit else "nothing left with a Trade-in")
        return out

    def exchange_rest_for_np(self) -> str:
        """Exchange all that is left for NP. Returns what happened."""
        ctx = self.ctx
        if not self.nav.goto("storage", log=ctx.log):
            return "could not reach Cat Storage"
        frame, texts = self._look(0.3)
        button = _find(texts, "exchangeall")
        if button is None:
            return "no Exchange all on the Storage screen: nothing left"
        self._tap(button.centre)
        frame, texts = self._look(1.6)
        said = _flat(texts)
        np_button = _find(texts, "exchangefornp")
        if "everythingwillbeexchanged" not in said or np_button is None:
            self._close(frame)
            return f"Exchange all's question did not read as expected, closed: {said[:90]!r}"
        self._tap(np_button.centre)
        for _ in range(8):
            frame, texts = self._look(1.2)
            said = _flat(texts)
            ok = next((t for t in texts if t.text.strip().lower().rstrip("!") in ("ok", "yes")), None)
            if ok is not None and not re.search(r"cat ?food|purchase|buy", said):
                ctx.log(f"  confirming: {said[:90]!r}")
                self._tap(ok.centre)
                continue
            if "youhave" in said or "exchanged" in said:
                self._tap(NOTICE_TAP)
                continue
            break
        left = self.count()
        return f"exchanged for NP; Storage now {left[0]}/{left[1]}" if left else "exchanged for NP"


def clear_unusable(ctx) -> dict:
    """After Use all: trade what can be traded for Rare Tickets, then the rest
    for NP."""
    store = Storage(ctx)
    traded = store.trade_in(progress=lambda t: ctx.put("trade_in", t.to_json()))
    ctx.log(f"  trade-in: {traded.traded} traded, {traded.tickets} Rare Ticket(s); {traded.reason}")
    np = store.exchange_rest_for_np()
    ctx.log(f"  {np}")
    result = dict(traded.to_json(), exchange=np)
    ctx.put("trade_in", result)
    return result
