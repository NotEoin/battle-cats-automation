"""What a draw run saves about the account between draws."""

from bcgacha.pipeline import held_after_draw


def test_a_capped_run_leaves_the_rest_of_the_tickets_held():
    """Regression: a run asked to spend 1 of 7 tickets saved 0 held, its budget left."""
    assert held_after_draw(7) == 6


def test_an_unknown_ticket_count_stays_unknown():
    assert held_after_draw(None) is None


def test_the_held_count_never_goes_below_zero():
    assert held_after_draw(0) == 0
