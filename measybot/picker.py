"""Chooses the day's five recipes.

Dishes are used least-recently-used first (never-used dishes before anything else), so every dish
appears once before any dish repeats. A small random spread (`jitter_days`) stops the same five
dishes from always travelling together. Within a dish, the image used longest ago is shown.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import date

from .catalogue import Recipe
from .history import History

NEVER_USED = 10_000  # "days since last used" for a dish that has never been posted


class PickError(Exception):
    pass


def pick(recipes: list[Recipe], history: History, today: date, cfg: dict,
         rng: random.Random | None = None, allowed: set[str] | None = None,
         caps_off: set[str] | frozenset = frozenset(), lead: dict[str, int] | None = None,
         avoid: set[str] | dict[str, int] | None = None) -> list[Recipe]:
    """Five dishes. `allowed` limits them to a theme's dishes; `caps_off` lifts the "protein" or
    "base" variety limit (a chicken theme can be all chicken); `lead` scores put the most
    crave-worthy dish first; `avoid` = dishes other accounts posted recently, {dish: days ago}
    (a set means today): they count as used by this account then. A dish is never posted twice on
    the same day; if the other accounts leave too few dishes, their posts are ignored."""
    avoid = avoid if isinstance(avoid, dict) else dict.fromkeys(avoid or (), 0)
    p = cfg["picker"]
    n = p["recipes_per_post"]
    rng = rng or random.Random(f"{today.isoformat()}/picker")

    pool = [r for r in usable(recipes, cfg) if allowed is None or r.group in allowed]
    by_group: dict[str, list[Recipe]] = defaultdict(list)
    for r in pool:
        by_group[r.group].append(r)
    if len(by_group) < n:
        raise PickError(f"Only {len(by_group)} dishes available; need {n}.")

    last_group = history.last_used("groups")
    last_file = history.last_used("files")

    def age(g: str) -> int:
        d = last_group.get(g)
        own = NEVER_USED if d is None else (today - d).days
        return min(own, avoid.get(g, NEVER_USED))

    groups = sorted(by_group)  # stable order before the seeded shuffle of scores
    score = {g: age(g) + rng.uniform(0, p.get("jitter_days", 0)) for g in groups}
    order = sorted(groups, key=lambda g: -score[g])

    big = n if "protein" in caps_off else 0
    bigb = n if "base" in caps_off else 0
    chosen: list[str] = []
    for cooldown in range(p["dish_cooldown_days"], 0, -1):
        for extra in (0, 1, n):
            chosen = _greedy(order, by_group, age, cooldown, p["max_same_protein"] + extra + big,
                             p["max_same_base"] + extra + bigb, n, avoid_similar=extra == 0)
            if len(chosen) == n:
                break
        if len(chosen) == n:
            break
    else:
        if avoid:
            return pick(recipes, history, today, cfg, rng, allowed, caps_off, lead)
        raise PickError("Could not find five different dishes.")

    picks = [_least_used_image(by_group[g], last_file, rng) for g in chosen]
    rng.shuffle(picks)
    if lead:
        best = max(picks, key=lambda r: lead.get(r.group, 0))
        picks.remove(best)
        picks.insert(0, best)
    return picks


STOPWORDS = {"and", "with", "the", "a", "on", "in", "of"}


def similar(a: str, b: str) -> bool:
    """Dish names that mostly share words (e.g. sticky BBQ chicken / beef rice bowls)."""
    wa = set(a.split("-")) - STOPWORDS
    wb = set(b.split("-")) - STOPWORDS
    return len(wa & wb) / max(1, len(wa | wb)) >= 0.5


def usable(recipes: list[Recipe], cfg: dict) -> list[Recipe]:
    """The recipe images allowed in posts (no dollar cards, only the chosen layouts)."""
    p = cfg["picker"]
    layouts = set(p.get("layouts") or [])
    return [r for r in recipes
            if not (p.get("skip_dollar_cards") and r.currency == "USD")
            and (not layouts or r.layout in layouts)]


def _greedy(order, by_group, age, cooldown, max_protein, max_base, n,
            avoid_similar: bool = True) -> list[str]:
    chosen: list[str] = []
    proteins: Counter = Counter()
    bases: Counter = Counter()
    for g in order:
        if age(g) < cooldown:
            continue
        if avoid_similar and any(similar(g, c) for c in chosen):
            continue
        r = by_group[g][0]
        if r.protein and proteins[r.protein] >= max_protein:
            continue
        if r.base and bases[r.base] >= max_base:
            continue
        chosen.append(g)
        proteins[r.protein] += 1
        bases[r.base] += 1
        if len(chosen) == n:
            break
    return chosen


def _least_used_image(images: list[Recipe], last_file: dict[str, date], rng: random.Random) -> Recipe:
    keyed = [(last_file.get(r.file, date.min), rng.random(), r) for r in images]
    keyed.sort(key=lambda k: (k[0], k[1]))
    return keyed[0][2]
