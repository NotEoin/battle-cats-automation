"""A run as a person asks for it: which tasks it takes, and the same run on
the command line."""

import shlex

from bcgacha import jobs


def test_a_plan_takes_no_drawing_task():
    req = jobs.Request()
    assert req.tasks() == ["map", "owned", "seed", "goal"]
    assert not req.spends


def test_rolling_checks_the_capsule_screen_first():
    req = jobs.Request(roll=True)
    assert req.tasks() == ["map", "owned", "capsule", "seed", "goal", "roll"]


def test_normal_capsules_alone_need_no_seed_or_goal():
    req = jobs.Request(capsules={"cat": 30})
    assert req.tasks() == ["map", "capsules"]


def test_everything_at_once_runs_in_one_order():
    req = jobs.Request(targets=["Kasli"], roll=True, capsules={"lucky": 0}, uncanny=True, storage=True)
    assert req.tasks() == ["map", "storage", "owned", "capsule", "seed", "goal", "roll", "capsules", "legends"]


def test_a_request_from_the_page_is_cleaned():
    req = jobs.Request.from_json(dict(targets=[" Dark Kasli ", ""], rare="all", platinum="2",
                                      capsules={"cat": "10", "nonsense": 3}, bogus=1))
    assert req.targets == ["Dark Kasli"]
    assert req.rare is None and req.platinum == 2
    assert req.capsules == {"cat": 10}


def test_the_command_line_asks_for_the_same_run():
    req = jobs.Request(targets=["Dark Kasli", "Shirou Emiya"], events=["Iron Legion"], roll=True,
                       rare=20, platinum=1, capsules={"cat": 0, "lucky": 10}, uncanny=True,
                       exchange="xp")
    from bcgacha import cli

    again = cli.request_from_args(cli.parser().parse_args(shlex.split(req.command())[1:]))
    assert again == req


def test_a_task_needing_the_phone_says_so_without_one():
    import types

    published = {}
    ctx = types.SimpleNamespace(session=None, put=lambda s, p: published.__setitem__(s, p),
                                log=lambda line: None, check=lambda: None)
    ok, why = jobs.Job(ctx, jobs.Request(rescan_map=True)).run()
    assert not ok and "needs the phone" in why
    assert published["error"]["hint"]
    assert [t["state"] for t in published["tasks"]] == ["failed", "not run", "not run", "not run"]


def test_a_draw_run_says_it_stops_at_the_goal():
    assert any("stops once everything wanted is unlocked" in line
               for line in jobs.Request(roll=True).summary())


def test_platinum_is_every_ticket_held_unless_limited():
    assert jobs.Request.from_json({}).platinum is None
    assert jobs.Request.from_json(dict(platinum="all")).platinum is None
    assert jobs.Request.from_json(dict(platinum="0")).platinum == 0
    assert "--platinum" not in jobs.Request(roll=True).command()
    assert any("every Platinum ticket held" in line for line in jobs.Request(roll=True).summary())


def test_an_update_comes_before_everything_else():
    assert jobs.Request(update=True, roll=True).tasks()[:2] == ["update", "map"]
    assert jobs.Request(only=["update"]).tasks() == ["update"]


def test_an_update_has_its_own_command():
    assert jobs.Request(only=["update"]).command() == "bcgacha tools update"
    assert "--update" not in jobs.Request(update=True, roll=True).command()
    assert jobs.Request(update=True).summary()[0].startswith("first download")


def test_a_run_from_the_page_updates_first():
    assert jobs.Request.from_json(dict(roll=True)).tasks()[:2] == ["update", "map"]
    assert jobs.Request.from_json(dict(only=["owned"])).tasks() == ["owned"]


def test_missing_cat_data_names_a_command_that_exists(monkeypatch):
    """Regression: the hint named .venv/bin/python scripts/fetch_data.py, absent from an install."""
    from bcgacha import data

    def missing(*_args, **_kw):
        raise FileNotFoundError("no dataset")

    monkeypatch.setattr(data, "load", missing)
    assert jobs.status()["next"] == ["download the cat data: bcgacha tools update"]



def test_a_new_install_is_told_to_find_its_seed_by_hand(tmp_path, monkeypatch):
    """With no seed and no saved result screens, no run can find the seed alone."""
    from bcgacha import state

    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "account.json")
    monkeypatch.setattr(jobs.P, "CAPTURES", tmp_path / "captures")
    assert any("tools find-seed" in step for step in jobs.status()["next"])
