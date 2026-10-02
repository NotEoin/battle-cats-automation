"""What is on the Storage screen: a capsule's panel, or the field itself."""

from bcgacha import perception, storage


def _t(text, x, y):
    return perception.Text(text, (x - 0.05, y - 0.02, x + 0.05, y + 0.02), 0.9)


def test_a_panel_is_known_by_its_buttons_even_without_a_count():
    """Bounty Up's panel never says how many there are."""
    texts = [_t("Bounty Up", 0.5, 0.53), _t("Use", 0.31, 0.78), _t("Exchange for XP", 0.5, 0.78),
             _t("Trade-in", 0.65, 0.77)]
    assert storage.is_panel(texts)


def test_the_storage_field_is_not_a_panel():
    """Its own Use all and Exchange all sit lower, along the bottom bar."""
    texts = [_t("Storage", 0.1, 0.04), _t("Use all", 0.47, 0.91), _t("Exchange all for NP/XP", 0.64, 0.91)]
    assert not storage.is_panel(texts)


def test_the_cat_food_counter_is_not_part_of_a_question():
    texts = [_t("All units in Storage will be exchanged for NP.", 0.5, 0.45), _t("Are you sure? (3880→3956)", 0.5, 0.52),
             _t("Yes", 0.39, 0.67), _t("No", 0.61, 0.67), _t("Cat Food", 0.78, 0.93)]
    assert "catfood" not in storage._dialog(texts)
    assert "areyousure" in storage._dialog(texts)


# -- clearing Storage: trade only what the game says Use all cannot use -------------

import pytest  # noqa: E402

from bcgacha import pipeline  # noqa: E402


class _Ctx:
    def __init__(self, exchange="np"):
        self.exchange, self.logged = exchange, []

    def log(self, line):
        self.logged.append(line)


def _clearing(monkeypatch, drained, left, said, after_trade=(0, 128)):
    """clear_storage over a Use all that is `drained`, leaves `left` of 128
    and says `said`; returns the context and what was traded for."""
    traded = []

    def drain(ctx):
        ctx.use_all = dict(before=(left, 128), after=(left, 128), said=said,
                           unusable=any(pipeline.UNUSABLE.search(s) for s in said))
        ctx.storage_left, ctx.storage_capacity = left, 128
        return drained

    monkeypatch.setattr(pipeline, "drain_storage", drain)
    monkeypatch.setattr(storage, "clear_unusable", lambda ctx, currency: traded.append(currency))
    monkeypatch.setattr(storage.Storage, "__init__", lambda self, ctx: None)
    monkeypatch.setattr(storage.Storage, "count", lambda self: after_trade)
    return traded


ACTIVATE = "allcapsulespresentinstoragewillbeactivated.doyouwishtocontinue?"
# What the game said on the phone, as OCR read it, after a Use all of 104 left 6.
LEFT_OVER = "storage xp all of thepossiblecat capsules havebeenused. there has been some left over. 6/128"


def test_nothing_is_traded_when_use_all_is_not_seen_through(monkeypatch):
    traded = _clearing(monkeypatch, False, 116, [])
    assert not pipeline.clear_storage(_Ctx())
    assert traded == []


def test_nothing_is_traded_on_a_use_all_that_said_nothing_against_it(monkeypatch):
    """Cats left behind with no word from the game may still be usable: a
    missed tap looks just the same. Trading one would mark a cat owned that
    is not."""
    traded = _clearing(monkeypatch, True, 125, [ACTIVATE])
    assert not pipeline.clear_storage(_Ctx()), "no room, and none made"
    assert traded == []
    traded = _clearing(monkeypatch, True, 60, [ACTIVATE])
    assert pipeline.clear_storage(_Ctx()), "room enough without trading"
    assert traded == []


def test_what_the_game_says_cannot_be_used_is_traded_then_exchanged(monkeypatch):
    traded = _clearing(monkeypatch, True, 116, [ACTIVATE, LEFT_OVER])
    assert pipeline.clear_storage(_Ctx("xp"))
    assert traded == ["xp"]


def test_an_emptied_storage_trades_nothing(monkeypatch):
    traded = _clearing(monkeypatch, True, 0, [ACTIVATE])
    assert pipeline.clear_storage(_Ctx())
    assert traded == []


@pytest.mark.parametrize("said, unusable", [
    (LEFT_OVER, True),
    ("there has been someleftover.", True),
    ("all of the possible cat capsules have been used.", False),
    (ACTIVATE, False),
])
def test_the_word_that_capsules_cannot_be_used(said, unusable):
    assert bool(pipeline.UNUSABLE.search(said)) == unusable



def test_an_unread_yes_beside_trade_for_ticket_is_left_of_the_no():
    """Use all's question as on the phone: OCR read No and Trade for Ticket,
    not Yes. No is in the middle -- its own mirror -- so Yes is found across
    from Trade for Ticket, and neither of the others is ever the answer."""
    no, trade = _t("No", 0.5, 0.58), _t("Trade for Ticket", 0.6875, 0.58)
    x, y = pipeline.unread_yes([_t("Do you wish to continue?", 0.5, 0.42), no, trade], no)
    assert abs(x - 0.3125) < 0.01 and y == 0.58


def test_an_unread_yes_in_a_two_button_dialog_mirrors_the_no():
    no = _t("No", 0.61, 0.67)
    assert pipeline.unread_yes([no], no) == (pytest.approx(0.39), 0.67)


def test_a_centred_no_alone_gives_no_yes():
    no = _t("No", 0.5, 0.58)
    assert pipeline.unread_yes([no], no) is None
