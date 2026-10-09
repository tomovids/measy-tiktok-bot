"""Which supermarket a post is about (config.toml [[stores]]).

The recipe cards stay the same for every store; the hook, the cover's store front and the
hashtags change. Stores without `price_claims` get no £ claims in their hooks (the card prices
are Aldi prices). The stores take turns: the one posted about longest ago goes next.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .history import History


@dataclass
class Store:
    id: str
    name: str
    sign: str
    words: list[str]
    hashtags: list[str] = field(default_factory=list)
    price_claims: bool = False
    weight: float = 1.0

    def mentioned_in(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in self.words)


def load(cfg: dict) -> list[Store]:
    out = []
    for s in cfg.get("stores", []):
        out.append(Store(id=s["id"], name=s["name"], sign=s["sign"],
                         words=[w.lower() for w in s.get("words", [s["name"]])],
                         hashtags=list(s.get("hashtags", [])), price_claims=s.get("price_claims", False),
                         weight=float(s.get("weight", 1))))
    return out or [default()]


def default() -> Store:
    return Store("aldi", "Aldi", "the blue Aldi logo sign with its yellow, orange and red border",
                 ["aldi"], ["#aldi", "#aldiuk", "#aldidinners"], True, 1.0)


def by_id(cfg: dict, store_id: str) -> Store:
    return next((s for s in load(cfg) if s.id == store_id), default())


def choose(hist: History, cfg: dict, rng: random.Random, index: int = 0) -> Store:
    """The store for the day's post number `index` (0-based) from [store_rotation] plan.

    A fixed id gives that store; "rotate" (or no plan) gives the next store in turn: the one whose
    last post is oldest, never-used first, from the stores the plan doesn't fix.
    """
    stores = load(cfg)
    plan = cfg.get("store_rotation", {}).get("plan") or []
    entry = plan[index % len(plan)] if plan else "rotate"
    if entry != "rotate":
        return by_id(cfg, entry)
    fixed = {e for e in plan if e != "rotate"}
    stores = [s for s in stores if s.id not in fixed] or stores
    posts = sorted(hist.accepted(), key=lambda p: (p["date"], p.get("sent_at", "")))
    last = {}
    for i, p in enumerate(posts):
        last[p.get("store", "aldi")] = i
    oldest = min(last.get(s.id, -1) for s in stores)
    cands = [s for s in stores if last.get(s.id, -1) == oldest]
    return rng.choice(cands)


def all_words(cfg: dict) -> set[str]:
    return {w for s in load(cfg) for w in s.words}
