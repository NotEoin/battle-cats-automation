"""The command line's own work: saving a seed found by hand."""

import pytest

from bcgacha import cli, state
from bcgacha.data import load
from bcgacha.gacha import TRACK_A, Gacha

SEED = 123456789
EVENT = "2026-09-21_1081"


@pytest.fixture
def account_file(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    monkeypatch.setattr(state, "STATE_PATH", path)
    return path


def _set_seed(*extra):
    args = cli.parser().parse_args(["tools", "set-seed", str(SEED), "--event", EVENT, *extra])
    return args.func(args)


def test_set_seed_saves_the_position_after_the_cat_named(account_file):
    ds = load()
    banner = ds.find_banner(EVENT)
    gacha = Gacha(banner, SEED, ds)
    # The first cat along the seed that comes out only once, so the answer is unique.
    for index in range(1, 20):
        cat = gacha.cell(index, TRACK_A).cat_id
        expected = state.Account(seed=SEED)
        if state.resync(expected, cat, [banner], ds) is not None:
            break

    assert _set_seed("--cat", f"#{cat}") == 0
    saved = state.Account.load(account_file)
    assert (saved.seed, saved.position) == (SEED, expected.position)


def test_set_seed_never_overwrites_a_saved_position_unasked(account_file):
    state.Account(seed=1, index=50).save(account_file)
    assert _set_seed("--cat", "Cat") == 1
    assert state.Account.load(account_file).seed == 1


def test_resync_without_a_saved_seed_says_what_to_do(account_file, capsys):
    """Regression: resync with no seed saved ended in a traceback."""
    args = cli.parser().parse_args(["tools", "resync", "--cat", "Cat"])
    assert args.func(args) == 1
    assert "find-your-seed" in capsys.readouterr().err
