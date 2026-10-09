"""Chooses each post's theme: a dish collection + an angle (data/themes.toml).

Rules: a collection needs at least 6 dishes that weren't posted today; a collection rests
`collection_gap_days`; an angle isn't repeated within the last 3 posts; a collection + angle
pair isn't reused within 30 days; day / slot / month limits on angles are respected.
Each rule relaxes only if nothing else is left.
"""
from __future__ import annotations

import random
import tomllib
from dataclasses import dataclass, field
from datetime import date

from . import config
from .history import History

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PROTEIN_TAGS = {"chicken", "beef", "sausage", "veggie"}
BASE_COLLECTIONS = {"pasta", "noodles", "rice", "handheld", "loaded", "mexican", "italian", "asian"}
MIN_DISHES = 6


@dataclass
class Theme:
    collection: str
    label: str
    angle: str
    angle_text: str
    hashtags: list[str]
    groups: set[str]
    caps_off: set[str] = field(default_factory=set)

    def record(self) -> dict:
        return {"collection": self.collection, "angle": self.angle, "label": self.label,
                "angle_text": self.angle_text}


def load(path=None) -> dict:
    with open(path or config.DATA / "themes.toml", "rb") as f:
        return tomllib.load(f)


def fits(tags: set[str], c: dict) -> bool:
    any_ = c.get("any") or []
    all_ = c.get("all") or []
    return (not any_ or bool(tags & set(any_))) and set(all_) <= tags


def angle_allowed(a: dict, day: date, slot: str) -> bool:
    if a.get("days") and WEEKDAYS[day.weekday()] not in a["days"]:
        return False
    if a.get("slots") and slot not in a["slots"]:
        return False
    if a.get("months") and day.month not in a["months"]:
        return False
    return True


def choose(day: date, slot: str, hist: History, dish_tags: dict[str, set[str]], cfg: dict,
           rng: random.Random, data: dict | None = None, boost: dict | None = None) -> Theme:
    """`boost`: performance multipliers {"collection": {id: x}, "angle": {id: x}} (tuning.py)."""
    data = data or load()
    boost = boost or {}
    cw = boost.get("collection", {})
    aw = boost.get("angle", {})
    posts = sorted(hist.accepted(), key=lambda p: (p["date"], p.get("sent_at", "")))
    last_group = hist.last_used("groups")

    def free(g: str) -> bool:
        d = last_group.get(g)
        return d is None or (day - d).days >= 1

    coll_last: dict[str, date] = {}
    pairs: dict[tuple[str, str], date] = {}
    for p in posts:
        t = p.get("theme") or {}
        if t.get("collection"):
            d = date.fromisoformat(p["date"])
            coll_last[t["collection"]] = d
            pairs[(t["collection"], t.get("angle"))] = d
    recent_angles = [(p.get("theme") or {}).get("angle") for p in posts[-3:]]

    groups_for = {c["id"]: {g for g, tg in dish_tags.items() if fits(tg, c)} for c in data["collections"]}
    gap = cfg["picker"].get("collection_gap_days", 4)
    chosen_c = None
    for g_days in (gap, 2, 1, 0):
        cands = [c for c in data["collections"]
                 if sum(1 for g in groups_for[c["id"]] if free(g)) >= MIN_DISHES
                 and (c["id"] not in coll_last or (day - coll_last[c["id"]]).days >= g_days)]
        if cands:
            chosen_c = rng.choices(cands, weights=[c.get("weight", 1) * cw.get(c["id"], 1.0) for c in cands])[0]
            break
    if chosen_c is None:
        chosen_c = next(c for c in data["collections"] if c["id"] == "anything")

    angles = [a for a in data["angles"] if angle_allowed(a, day, slot)]
    chosen_a = None
    for strict in (2, 1, 0):
        cands = []
        for a in angles:
            if strict >= 1 and a["id"] in recent_angles:
                continue
            last = pairs.get((chosen_c["id"], a["id"]))
            if strict >= 2 and last and (day - last).days < 30:
                continue
            cands.append(a)
        if cands:
            chosen_a = rng.choices(cands, weights=[a.get("weight", 1) * aw.get(a["id"], 1.0) for a in cands])[0]
            break
    chosen_a = chosen_a or rng.choice(angles or data["angles"])

    caps_off = set()
    if set(chosen_c.get("any") or []) & PROTEIN_TAGS:
        caps_off.add("protein")
    if chosen_c["id"] in BASE_COLLECTIONS:
        caps_off.add("base")
    return Theme(chosen_c["id"], chosen_c["label"], chosen_a["id"], chosen_a["text"],
                 list(chosen_c.get("hashtags", [])), groups_for[chosen_c["id"]], caps_off)
