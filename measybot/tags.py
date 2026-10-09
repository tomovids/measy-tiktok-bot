"""Tags for every dish (cheesy, sticky, fakeaway, chicken, noodles, quick, under-150...).

Worked out from the recipe library and the catalogue, so a new dish is tagged automatically.
Fix a dish by hand in data/dish_tags_extra.toml ([add] / [remove] tables keyed by dish id).
"""
from __future__ import annotations

import json
import tomllib
from functools import lru_cache

from . import config

CHEESES = ("cheese", "cheddar", "mozzarella", "parmesan", "halloumi", "feta", "mascarpone")
CREAMS = ("single cream", "double cream", "cream cheese", "creme fraiche", "crème fraîche", "soft cheese")

TITLE_WORDS = {
    "cheesy": ("cheesy",),
    "creamy": ("creamy",),
    "sticky": ("sticky", "honey", "hoisin", "teriyaki", "glazed"),
    "spicy": ("cajun", "peri", "buffalo", "hot honey", "harissa", "korean", "chilli beef", "taco"),
    "bbq": ("bbq",),
    "garlic": ("garlic",),
    "loaded": ("loaded", "nachos"),
    "mexican": ("taco", "quesadilla", "burrito", "nachos", "fajita"),
    "asian": ("noodle", "hoisin", "teriyaki", "korean", "soy", "sweet chilli", "honey chilli"),
    "italian": ("pasta", "gnocchi", "orzo", "pesto", "tuscan", "parmesan", "pizza"),
    "onepan": ("one-pan", "one pan", "skillet", "traybake", "bake"),
    "fakeaway": ("loaded", "nachos", "quesadilla", "burrito", "pizza", "burger", "fries", "korean",
                 "teriyaki", "hoisin", "sweet chilli", "honey chilli", "peri", "buffalo", "wrap",
                 "flatbread", "taco", "noodle"),
}
BASES = {
    "pasta": ("pasta", "gnocchi", "orzo"),
    "noodles": ("noodles",),
    "rice": ("rice",),
    "potato": ("potato", "fries"),
    "handheld": ("wrap", "flatbread", "quesadilla", "burger", "bread", "pizza", "nachos"),
    "couscous": ("couscous",),
}


@lru_cache(maxsize=1)
def _catalogue_meta() -> dict:
    rows = json.loads((config.DATA / "recipes.json").read_text(encoding="utf-8"))
    meta = {}
    for r in rows:
        if r.get("kind") == "recipe":
            meta.setdefault(r["group"], r)
    return meta


def _extra() -> dict:
    path = config.DATA / "dish_tags_extra.toml"
    if not path.exists():
        return {"add": {}, "remove": {}}
    with open(path, "rb") as f:
        d = tomllib.load(f)
    return {"add": d.get("add", {}), "remove": d.get("remove", {})}


def tags_for(group: str, entry: dict) -> set[str]:
    title = (entry["title"] + " " + (entry.get("subtitle") or "")).lower()
    items = " ".join(i["item"].lower() for i in entry.get("ingredients", []))
    meta = _catalogue_meta().get(group, {})
    t: set[str] = set()
    for tag, words in TITLE_WORDS.items():
        if any(w in title for w in words):
            t.add(tag)
    if any(c in items for c in CHEESES):
        t.add("cheesy")
    if any(c in items for c in CREAMS):
        t.add("creamy")
    protein = meta.get("protein") or ""
    if protein in ("halloumi", "beans", "cheese", "veg"):
        t.add("veggie")
    elif protein in ("pork",):
        t.add("sausage")
    elif protein:
        t.add(protein)
    base = (meta.get("base") or "") + " " + title
    for tag, words in BASES.items():
        if any(w in base for w in words):
            t.add(tag)
    mins = (entry.get("prep_mins") or 0) + (entry.get("cook_mins") or 0)
    if 0 < mins <= 20:
        t.add("quick")
    prices = [i.get("price") or 0 for i in entry.get("ingredients", [])]
    if entry.get("serves"):
        pp = sum(prices) / entry["serves"]
        if pp <= 1.5:
            t.add("under-150")
        if pp <= 2.0:
            t.add("under-2")
    if (entry.get("serves") or 0) >= 4:
        t.add("family")
    if t & {"creamy", "cheesy", "loaded", "onepan", "potato"}:
        t.add("comfort")
    extra = _extra()
    t |= set(extra["add"].get(group, []))
    t -= set(extra["remove"].get(group, []))
    return t


def crave_score(tags: set[str]) -> int:
    """Rough 'stop scrolling' appeal of a dish photo: leads the post."""
    weights = {"loaded": 3, "cheesy": 2, "sticky": 2, "fakeaway": 2, "bbq": 1, "creamy": 1, "spicy": 1}
    return sum(weights.get(t, 0) for t in tags)


def all_tags() -> dict[str, set[str]]:
    from . import library
    return {g: tags_for(g, e) for g, e in library.load("uk").items()}   # tags come from the UK words and prices
