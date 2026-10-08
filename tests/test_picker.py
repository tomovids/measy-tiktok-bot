import random
from collections import Counter, defaultdict
from datetime import date, timedelta

from measybot.catalogue import Recipe, load_recipes
from measybot.history import SENT, History
from measybot.picker import pick, similar, usable


def simulate(cfg, days, start=date(2026, 10, 9)):
    recipes = load_recipes()
    hist = History()
    posts = []
    for i in range(days):
        day = start + timedelta(days=i)
        picks = pick(recipes, hist, day, cfg)
        hist.add({"date": day.isoformat(), "files": [r.file for r in picks],
                  "groups": [r.group for r in picks], "status": SENT})
        posts.append((day, picks))
    return recipes, posts


def test_five_different_dishes_every_day(cfg):
    _, posts = simulate(cfg, 60)
    for _, picks in posts:
        assert len(picks) == 5
        assert len({r.group for r in picks}) == 5


def test_no_dish_inside_the_cooldown(cfg):
    _, posts = simulate(cfg, 90)
    last = {}
    for day, picks in posts:
        for r in picks:
            if r.group in last:
                assert (day - last[r.group]).days >= cfg["picker"]["dish_cooldown_days"]
            last[r.group] = day


def test_every_dish_comes_round_evenly(cfg):
    recipes, posts = simulate(cfg, 60)
    groups = {r.group for r in usable(recipes, cfg)}
    cycle = -(-len(groups) // 5)  # days needed to show every dish once
    first_seen = {}
    for i, (_, picks) in enumerate(posts):
        for r in picks:
            first_seen.setdefault(r.group, i)
    assert set(first_seen) == groups
    # all dishes shown within one cycle; the variety rules can push the last few by a day or two
    assert max(first_seen.values()) <= cycle + 1
    uses = Counter(r.group for _, picks in posts for r in picks)
    assert max(uses.values()) - min(uses.values()) <= 2


def test_variety_caps_hold(cfg):
    _, posts = simulate(cfg, 60)
    for _, picks in posts:
        assert max(Counter(r.protein for r in picks).values()) <= cfg["picker"]["max_same_protein"]
        assert max(Counter(r.base for r in picks).values()) <= cfg["picker"]["max_same_base"]


def test_dollar_cards_skipped(cfg):
    _, posts = simulate(cfg, 30)
    assert all(r.currency != "USD" for _, picks in posts for r in picks)


def test_images_rotate_within_a_dish(cfg):
    _, posts = simulate(cfg, 90)
    shown = defaultdict(list)
    for _, picks in posts:
        for r in picks:
            shown[r.group].append(r.file)
    for group, files in shown.items():
        distinct = len(set(files))
        # each new appearance uses an image not shown since the dish's images were all used
        for i in range(1, len(files)):
            if i < distinct:
                assert files[i] not in files[:i], group


def test_same_day_same_picks(cfg):
    recipes = load_recipes()
    a = pick(recipes, History(), date(2026, 11, 1), cfg)
    b = pick(recipes, History(), date(2026, 11, 1), cfg)
    assert [r.file for r in a] == [r.file for r in b]


def test_similar_names():
    assert similar("sticky-bbq-chicken-rice-bowls", "sticky-bbq-beef-rice-bowls")
    assert similar("creamy-garlic-chicken-pasta", "creamy-garlic-chicken-orzo")
    assert not similar("creamy-tuscan-chicken-pasta", "chilli-beef-noodles")


def test_relaxes_rather_than_failing(cfg):
    # only five dishes, all used yesterday: the cooldown has to give way
    recipes = [Recipe(f"{i}.webp", f"Dish {i}", f"dish-{i}", "chicken", "rice", "GBP",
                      5.0, None, 4, 20, "card") for i in range(5)]
    hist = History([{"date": "2026-10-08", "files": [r.file for r in recipes],
                     "groups": [r.group for r in recipes], "status": SENT}])
    picks = pick(recipes, hist, date(2026, 10, 9), cfg, random.Random(1))
    assert {r.group for r in picks} == {r.group for r in recipes}


def test_only_recipe_cards(cfg):
    _, posts = simulate(cfg, 30)
    assert all(r.layout == "card" for _, picks in posts for r in picks)
