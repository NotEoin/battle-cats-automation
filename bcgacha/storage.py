"""What Use all leaves in Cat Storage: capsules that can no longer be used.

A Cat Capsule item or unit already at its maximum stays in Storage after Use
all, and the game says so: "There has been some left over." Then, in order:
Use all again, answered Trade for Ticket -- the maxed base upgrades, traded
for Rare Tickets in one press; it trades nothing that can be used -- and
"Exchange all for NP/XP" for the rest, answered NP unless XP is asked.

Every press here is made only once the question it answers has been read
and says what is expected: Use all's must be its own "will be activated"
question, a question after Trade for Ticket must be about tickets, and
Exchange all's must be its own "Everything will be exchanged ... NP or XP?".
Anything else is answered No, or closed.

Positions are fractions of the landscape frame, measured on a 2532x1170
iPhone; other screen shapes are untested.
"""

from __future__ import annotations

import re
import time
from typing import Any

# A notice with no button goes at a tap on it.
NOTICE_TAP = (0.5, 0.44)
# Words that make a question one about spending: never answered Yes.
SPENDING = re.compile(r"catfood|purchase|buy")
# A stored capsule's panel keeps its buttons in this band, top to bottom.
PANEL_BUTTONS_Y = (0.7, 0.84)
# A dialog's own words sit inside this box, clear of the bars along the edges.
DIALOG_X = (0.15, 0.85)
DIALOG_Y = (0.1, 0.72)
# Trade for Ticket shares a row with No when its centre is this close in height.
SAME_ROW = 0.05


def is_panel(texts: list[Any]) -> bool:
    """A stored capsule's panel is up: known by its buttons along the bottom.
    Not every panel says how many of it there are."""
    return any(PANEL_BUTTONS_Y[0] < t.centre[1] < PANEL_BUTTONS_Y[1] and ("exchangefor" in t.text.lower().replace(" ", "")
                                              or "trade" in t.text.lower()) for t in texts)


def _flat(texts) -> str:
    return " ".join(t.text for t in texts).lower().replace(" ", "")


def _dialog(texts) -> str:
    """Only a dialog's own words: the Cat Food counter along the bottom bar
    must not make every question look like one about spending."""
    return _flat([t for t in texts if DIALOG_Y[0] < t.centre[1] < DIALOG_Y[1] and DIALOG_X[0] < t.centre[0] < DIALOG_X[1]])


def _find(texts, *words):
    return next((t for t in texts if all(w in t.text.lower().replace(" ", "") for w in words)), None)


class Storage:
    """Cat Storage's leftovers, traded and exchanged through a run's context."""

    def __init__(self, ctx: Any):
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

    def settle(self) -> None:
        """Close any capsule panel or notice left up, so the Storage screen
        itself is showing."""
        for _ in range(4):
            frame, texts = self._look(0.4)
            if is_panel(texts):
                self._close(frame)
            elif any(w in _flat(texts) for w in ("traded", "ticket!", "exchanged")):
                self._tap(NOTICE_TAP)
            else:
                return

    def count(self) -> tuple[int, int] | None:
        """Storage's N/M as read off the screen, or None when it does not read."""
        from .pipeline import storage_count

        return storage_count(self._look(0.3)[1])

    # -- trading -----------------------------------------------------------------

    def trade_for_tickets(self) -> str:
        """Use all, answered Trade for Ticket: the maxed base upgrades traded
        for Rare Tickets in one press. Only ever after a Use all answered Yes
        has run, so nothing usable is left to trade. Returns what happened."""
        from .perception import reward_ok

        ctx = self.ctx
        self.settle()
        if not self.nav.goto("storage", log=ctx.log):
            return "could not reach Cat Storage"
        frame, texts = self._look(0.3)
        use_all = _find(texts, "useall")
        if use_all is None:
            return "no Use all on the Storage screen: nothing to trade"
        self._tap(use_all.centre)
        for _ in range(10):                     # the question can take a moment
            frame, texts = self._look(0.8)
            if "willbeactivated" in _dialog(texts):
                break
        else:
            return "Use all's question did not come up: nothing traded"
        no = next((t for t in texts if t.text.strip().lower() == "no"), None)
        trade = _find(texts, "trade", "ticket")
        if trade is None or no is None or abs(trade.centre[1] - no.centre[1]) > SAME_ROW \
                or trade.centre[0] <= no.centre[0]:
            self._tap(no.centre) if no is not None else self._close(frame)
            return "no Trade for Ticket beside Use all's No: nothing traded"
        ctx.log("  Use all's question: Trade for Ticket")
        self._tap(trade.centre)
        said = []
        for _ in range(8):
            frame, texts = self._look(1.4)
            asked = _dialog(texts)
            if not asked:
                break                           # back on Storage
            no = next((t for t in texts if t.text.strip().lower() == "no"), None)
            yes = next((t for t in texts if t.text.strip().lower().rstrip("!") == "yes"), None)
            if "willbeactivated" in asked:
                self._tap(no.centre) if no is not None else self._close(frame)
                return "Trade for Ticket did not take: Use all's question still up, answered No"
            said.append(asked)
            if "?" in asked:
                if SPENDING.search(asked) or not re.search(r"ticket|trade", asked):
                    self._tap(no.centre) if no is not None else self._close(frame)
                    return f"a question after Trade for Ticket not as expected, answered No: {asked[:90]!r}"
                ctx.log(f"  confirming: {asked[:90]!r}")
                if yes is not None:
                    self._tap(yes.centre)
                elif no is not None:
                    from .pipeline import unread_yes

                    point = unread_yes(texts, no)
                    if point is None:
                        self._tap(no.centre)
                        return "no Yes on the question after Trade for Ticket, answered No"
                    self._tap(point)
                else:
                    self._close(frame)
                    return "no Yes or No on the question after Trade for Ticket"
                continue
            ctx.log(f"  the game says: {asked[:90]!r}")
            ok = reward_ok(frame, ctx.ocr) or next(
                (t.centre for t in texts if t.text.strip().lower() in ("ok", "0k")), None)
            if ok is None:
                break                           # never a blind tap: Storage's cats lie under it
            self._tap(ok)
        self.settle()
        return "traded for Rare Tickets" + (f": {said[-1][:80]!r}" if said else "")

    def exchange_rest(self, currency: str = "np") -> str:
        """Exchange all that is left for NP or XP. Returns what happened."""
        ctx, name = self.ctx, currency.upper()
        self.settle()
        if not self.nav.goto("storage", log=ctx.log):
            return "could not reach Cat Storage"
        frame, texts = self._look(0.3)
        from .pipeline import storage_count

        held = storage_count(texts)
        if held is not None and held[0] == 0:
            return "Storage is empty: nothing to exchange"
        button = _find(texts, "exchangeall")
        if button is None:
            return "no Exchange all on the Storage screen: nothing left"
        self._tap(button.centre)
        frame, texts = self._look(1.6)
        said = _flat(texts)
        button = _find(texts, "exchangefor" + currency)
        if "everythingwillbeexchanged" not in said or button is None:
            self._close(frame)
            return f"Exchange all's question did not read as expected, closed: {said[:90]!r}"
        self._tap(button.centre)
        for _ in range(8):
            frame, texts = self._look(1.2)
            said = _flat(texts)
            # "Are you sure? (3880->3946)": the NP or XP before and after. OCR does
            # not read its Yes; the dialog is centred, so Yes mirrors the No.
            no = next((t for t in texts if t.text.strip().lower() == "no"), None)
            yes = next((t for t in texts if t.text.strip().lower().rstrip("!") in ("yes", "ok")), None)
            asked = _dialog(texts)
            if "areyousure" in said and re.search(r"\d+\D{1,3}\d+", said) and (yes or no):
                if SPENDING.search(asked):
                    self._tap(no.centre if no else NOTICE_TAP)
                    return f"refused a question that mentions spending: {said[:90]!r}"
                ctx.log(f"  confirming the exchange: {said[:90]!r}")
                self._tap(yes.centre if yes else (1.0 - no.centre[0], no.centre[1]))
                continue
            if yes is not None and not SPENDING.search(asked):
                self._tap(yes.centre)
                continue
            if is_panel(texts) or any(w in said for w in ("exchanged", "received", "npgot", "got")):
                self._tap(NOTICE_TAP)
                continue
            break
        self.settle()
        left = self.count()
        return f"exchanged for {name}; Storage now {left[0]}/{left[1]}" if left else f"exchanged for {name}"


def clear_unusable(ctx: Any, currency: str = "np") -> dict:
    """After Use all, and only once the game has said some were left over:
    Trade for Ticket for the maxed base upgrades, then the rest for NP or XP."""
    store = Storage(ctx)
    traded = store.trade_for_tickets()
    ctx.log(f"  {traded}")
    exchanged = store.exchange_rest(currency)
    ctx.log(f"  {exchanged}")
    result = dict(traded=traded, exchange=exchanged)
    ctx.put("trade_in", result)
    return result
