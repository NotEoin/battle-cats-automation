"""Tests for scoring, tier parsing and the roll planner."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from bcgacha import tiers as T  # noqa: E402
from bcgacha.catindex import LOCKED_RE, clean_name  # noqa: E402
from bcgacha.data import LEGEND, RARE, SUPER_RARE, UBER, load  # noqa: E402
from bcgacha.planner import PLATINUM_TICKET, RARE_TICKET, Planner  # noqa: E402
from bcgacha.scoring import Scorer, tier_multiplier  # noqa: E402


def test_new_units_always_beat_duplicates():
    ds = load()
    tier_list = T.TierList.load()
    uber = next(c for c in tier_list.by_cat if ds.rarity_of(c) == UBER)
    fresh = Scorer(owned=set(), tiers=tier_list)
    dupe = Scorer(owned={uber}, tiers=tier_list)
    assert fresh.value(uber, UBER) > dupe.value(uber, UBER) * 5


def test_duplicate_uber_is_worth_more_than_nothing():
    """Extra copies raise the +N level cap, so they are not worthless."""
    ds = load()
    tier_list = T.TierList.load()
    uber = next(c for c in tier_list.by_cat if ds.rarity_of(c) == UBER)
    assert Scorer(owned={uber}, tiers=tier_list).value(uber, UBER) > 0


def test_tier_multiplier_orders_best_to_worst():
    ranks = [T.TIER_RANK[t] for t in ("SSS", "S", "A", "C", "F-")]
    values = [tier_multiplier(r) for r in ranks]
    assert values == sorted(values, reverse=True)
    assert tier_multiplier(T.UNRANKED) == 1.0


def test_a_good_new_uber_outscores_a_bad_new_uber():
    ds = load()
    tier_list = T.TierList.load()
    best = min(tier_list.by_cat, key=lambda c: tier_list.rank_of(c))
    worst = max(tier_list.by_cat, key=lambda c: tier_list.rank_of(c))
    scorer = Scorer(owned=set(), tiers=tier_list)
    assert scorer.value(best, ds.rarity_of(best)) > scorer.value(worst, ds.rarity_of(worst))


def test_tier_parse_reads_every_tier():
    sample = (
        "Text Version\n"
        "SSS: Dark Lunos, Lunos\n"
        "SS: Luna, Cosmo (UF), Balrog\n"
        "F-: Oda, Papaluga\n"
    )
    entries = T.parse(sample)
    assert [e.nickname for e in entries if e.tier == "SSS"] == ["Dark Lunos", "Lunos"]
    cosmo = next(e for e in entries if e.nickname == "Cosmo")
    assert cosmo.ultra_form and cosmo.tier == "SS"
    assert any(e.tier == "F-" for e in entries)


def test_tier_order_has_no_duplicates():
    assert len(T.TIER_ORDER) == len(set(T.TIER_ORDER))


def test_locked_entries_are_recognised():
    for text in ("???", "[???]", "?7?", "277", " ?? "):
        assert LOCKED_RE.search(text), text
    for text in ("Lesser Demon Cat", "Cat", "Bath Cat"):
        assert not LOCKED_RE.search(text), text


def test_a_real_name_containing_question_marks_is_not_locked():
    """"Rei Ayanami (???)" is a real unit, not an unlocked placeholder."""
    assert not LOCKED_RE.search("Rei Ayanami (???)")
    assert not LOCKED_RE.search("Rei Ayanami ???")


def test_name_matching_rejects_ambiguous_readings():
    from bcgacha.catindex import match_name

    choices = ["Cat", "Bird Cat", "Tank Cat", "Cow Cat"]
    assert match_name("cowCat", choices) == "Cow Cat"
    assert match_name("Tank Cat", choices) == "Tank Cat"
    # Nothing close enough to be worth guessing at.
    assert match_name("zzzzzzzz", choices) is None


def test_clean_name_strips_game_brackets():
    assert clean_name("【Shitakiri Sparrow】") == "Shitakiri Sparrow"
    assert clean_name("[Lesser Demon Cat]") == "Lesser Demon Cat"


def test_planner_prefers_the_banner_with_the_better_cat():
    """Same position, two banners: it must take the one worth more."""
    ds = load()
    tier_list = T.TierList.load()
    live = [b for b in ds.banners.values() if b.uber == 500 and b.slots.get(UBER)]
    banners = live[:4]
    scorer = Scorer(owned=set(), tiers=tier_list)
    planner = Planner(ds, banners, scorer)
    plan = planner.plan(3728687165, rolls=8)
    assert len(plan.steps) == 8
    for step in plan.steps:
        alternatives = [
            scorer.value(
                Planner(ds, [b], scorer)._evaluate(
                    Planner(ds, [b], scorer)._gacha(3728687165, b, {}),
                    step.index, step.track, None,
                ).cat_id,
                step.rarity,
            )
            for b in banners
        ]
        assert step.score >= max(alternatives) - 1e-6 or step.rarity == RARE


def test_platinum_is_refused_for_a_duplicate():
    ds = load()
    tier_list = T.TierList.load()
    platinum = next(b for b in ds.banners.values() if b.uber == 10000)
    normal = next(b for b in ds.banners.values() if b.uber == 500 and b.slots.get(UBER))
    everything = {c for ids in platinum.slots.values() for c in ids}
    scorer = Scorer(owned=everything, tiers=tier_list)
    planner = Planner(ds, [normal], scorer, platinum_banner=platinum, platinum_tickets=5)
    plan = planner.plan(3728687165, rolls=10)
    assert plan.platinum_spent == 0


def test_platinum_is_only_spent_on_a_reserved_unit():
    """Tickets are earmarked up front; nothing else may consume one."""
    ds = load()
    tier_list = T.TierList.load()
    platinum = next(b for b in ds.banners.values() if b.uber == 10000)
    normal = next(b for b in ds.banners.values() if b.uber == 500 and b.slots.get(UBER))
    planner = Planner(
        ds, [normal], Scorer(owned=set(), tiers=tier_list),
        platinum_banner=platinum, platinum_tickets=10,
    )
    plan = planner.plan(3728687165, rolls=40)
    for step in plan.steps:
        if step.currency == PLATINUM_TICKET:
            assert step.cat_id in planner.platinum_wanted
    assert plan.platinum_spent <= 10


def test_plan_steps_carry_their_reroll_cost():
    """A dupe reroll must be visible to whatever advances the saved position."""
    from bcgacha.gacha import next_position

    ds = load()
    banner = ds.find_banner("2026-09-21_979")
    planner = Planner(ds, [banner], Scorer(owned=set(), tiers=T.TierList.load()))
    plan = planner.plan(3728687165, rolls=60)

    # Replaying the plan's own positions must land where the plan says.
    index, track = 1, 0
    for step in plan.steps:
        assert (step.index, step.track) == (index, track)
        delta, track = next_position(track, step.reroll_steps)
        index += delta


def test_a_reroll_actually_occurs_somewhere_in_a_long_plan():
    """Guards the test above from passing trivially on a reroll-free seed."""
    ds = load()
    banner = ds.find_banner("2026-09-21_979")
    planner = Planner(ds, [banner], Scorer(owned=set(), tiers=T.TierList.load()))
    plan = planner.plan(3728687165, rolls=200)
    assert any(s.reroll_steps for s in plan.steps), "no reroll in 200 rolls"


def test_result_verification_accepts_the_predicted_cat():
    """A real result frame must verify against the cat that was predicted."""
    from bcgacha.runner import Runner

    ds = load()
    runner = Runner.__new__(Runner)
    runner.dataset, runner._ocr = ds, None
    frame = pathlib.Path(__file__).parent / "fixtures" / "result_viking_cat.png"
    matched, seen = runner.verify_result(frame, 48)   # 48 = Viking Cat
    assert matched, seen


def test_result_verification_catches_a_desync():
    """A wrong prediction must be rejected, not quietly accepted.

    If the saved seed position drifts, every later prediction is wrong, so
    this is the check that stops a bad run rather than letting it continue.
    """
    from bcgacha.runner import Runner

    ds = load()
    runner = Runner.__new__(Runner)
    runner.dataset, runner._ocr = ds, None
    frame = pathlib.Path(__file__).parent / "fixtures" / "result_viking_cat.png"
    matched, _seen = runner.verify_result(frame, 800)  # 800 = Morta-Loncha
    assert not matched


def test_platinum_reserves_the_best_unowned_units():
    """N tickets reserve exactly the N best unowned units, in rank order."""
    from bcgacha.planner import platinum_targets

    ds = load()
    tier_list = T.TierList.load()
    platinum = next(b for b in ds.banners.values() if b.uber == 10000)
    pool = {c for r in (UBER, LEGEND) for c in (platinum.slots.get(r) or [])}
    ranked = sorted(pool, key=lambda c: tier_list.rank_of(c))
    owned = set(ranked[:5])          # pretend the five best are already had

    picked = platinum_targets(tier_list, owned, ds, platinum, 4)
    assert len(picked) == 4
    assert not (picked & owned), "must never reserve a unit already owned"
    # Everything picked must outrank everything left behind.
    rest = [c for c in pool if c not in owned and c not in picked]
    assert max(tier_list.rank_of(c) for c in picked) <= min(
        tier_list.rank_of(c) for c in rest
    )


def test_platinum_reserves_nothing_without_tickets():
    from bcgacha.planner import platinum_targets

    ds = load()
    platinum = next(b for b in ds.banners.values() if b.uber == 10000)
    assert platinum_targets(T.TierList.load(), set(), ds, platinum, 0) == set()


def test_deeper_lookahead_keeps_the_uber_route():
    """Shallow lookahead trades an Uber away for a new Rare; deep does not.

    Switching banner can hand you a duplicate Rare, and the reroll that follows
    flips the track and diverts the path off an Uber several rolls out.
    """
    from bcgacha.gacha import next_position
    from bcgacha.planner import Planner as P

    ds = load()
    tier_list = T.TierList.load()
    banners = [ds.find_banner(k) for k in
               ("2026-09-21_1081", "2026-09-21_1021", "2026-09-21_979")]

    def run(depth):
        scorer = Scorer(owned=set(), tiers=tier_list)
        planner = P(ds, banners, scorer)
        index, track, previous = 38, 0, None
        for _ in range(12):
            step = planner.plan(
                3728687165, rolls=12, index=index, track=track,
                previous_cat=previous, lookahead=depth,
            ).steps[0]
            if step.rarity >= UBER:
                return step.position
            scorer.owned.add(step.cat_id)
            delta, track = next_position(track, step.reroll_steps)
            index += delta
            previous = step.cat_id
        return None

    assert run(6) == "46A"


def test_verification_tolerates_an_ocr_slip_but_not_a_wrong_cat():
    """The check must survive mangled text without waving through a desync.

    "Rich Cat III" comes back from OCR as 'Rich Cat "'. That must still verify,
    while a genuinely different unit must not.
    """
    from rapidfuzz import fuzz

    from bcgacha.runner import VERIFY_SCORE

    ds = load()

    def forms_of(name):
        for entry in ds.cats.values():
            names = [n for n in (entry.get("name") or []) if n]
            if name in names:
                return names
        raise AssertionError(name)

    def score(raw, target):
        return max(fuzz.ratio(raw.lower(), f.lower()) for f in forms_of(target))

    assert score('rich cat "', "Rich Cat III") >= VERIFY_SCORE
    assert score("Viking Cat", "Viking Cat") >= VERIFY_SCORE
    assert score('rich cat "', "Swordsman Cat") < VERIFY_SCORE
    assert score("Bath Cat", "Rich Cat III") < VERIFY_SCORE


def _goal_fixture():
    from bcgacha import goals
    from bcgacha.catindex import OwnedIndex

    ds = load()
    tier_list = T.TierList.load()
    owned = OwnedIndex.load().owned
    normal = [ds.find_banner(k) for k in
              ("2026-09-21_1081", "2026-09-21_1021", "2026-09-21_979")]
    platinum = next(b for b in ds.banners.values() if b.uber == 10000)
    goal = goals.build(ds, tier_list, owned, normal, platinum,
                       platinum_tickets=7, preferred_banner="2026-09-21_979")
    return ds, tier_list, owned, normal, platinum, goal


def test_goal_ranks_legendaries_above_every_uber():
    _ds, _t, _owned, _n, _p, goal = _goal_fixture()
    assert goal.legendaries and goal.ubers
    assert min(goal.priority[c] for c in goal.legendaries) > max(
        goal.priority[c] for c in goal.ubers
    )


def test_goal_prefers_the_named_banner_for_equal_legendaries():
    """The Iron Legion legend must outrank the other one."""
    ds, tier_list, owned, normal, platinum, goal = _goal_fixture()
    iron = ds.find_banner("2026-09-21_979")
    on_iron = [c for c in goal.legendaries if c in (iron.slots.get(LEGEND) or [])]
    elsewhere = [c for c in goal.legendaries if c not in on_iron]
    assert on_iron and elsewhere
    assert max(goal.priority[c] for c in on_iron) > max(
        goal.priority[c] for c in elsewhere
    )


def test_goal_completes_only_when_everything_is_owned():
    _ds, _t, owned, _n, _p, goal = _goal_fixture()
    assert not goal.complete(owned)
    assert goal.complete(owned | goal.wanted)
    assert goal.remaining(owned | goal.wanted) == set()


def test_goal_priority_never_applies_to_a_duplicate():
    from bcgacha.scoring import Scorer

    ds, tier_list, owned, _n, _p, goal = _goal_fixture()
    target = next(iter(goal.legendaries))
    fresh = Scorer(owned=set(owned), tiers=tier_list, priority=goal.priority)
    dupe = Scorer(owned=set(owned) | {target}, tiers=tier_list, priority=goal.priority)
    assert fresh.value(target, ds.rarity_of(target)) > 10_000
    assert dupe.value(target, ds.rarity_of(target)) < 1_000
