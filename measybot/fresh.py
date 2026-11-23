"""Five brand-new dishes for every post, each with its own new AI food photo.

TikTok holds back slideshows that reuse pictures ("unoriginal content": not shown on the For You feed).
The library's 140 photos had each been posted 5-8 times across the accounts, so now every post gets
five dishes that haven't been posted on any account, made for the post's theme, and a new photo of
each. The photos aren't kept (they only live in that post's slides); the dish names go into the
history, so later posts avoid them. If anything fails, the post falls back to the recipe library.
"""
from __future__ import annotations

import hashlib
import random
import re
from concurrent.futures import ThreadPoolExecutor

from . import config, library, photos
from .catalogue import Recipe
from .openai_api import OpenAI, OpenAIError

SYSTEM_UK = """You create new budget dinner recipes for Measy, a UK meal-planning app whose recipes are made
from one {store} shop. You know what UK home cooks actually crave and what {store} sells. British English.
Answer with a JSON object only."""
SYSTEM_US = """You create new budget dinner recipes for Measy, a meal-planning app, for American home cooks
shopping at {store}. You know what Americans actually crave and what {store} sells. American English
(ground beef, cilantro, scallions, skillet, broil, oven in °F). Answer with a JSON object only."""

RULES = """Invent {n} different dinners for this post: {theme}.
- Dishes people really cook and crave on a budget, that look amazing in a photo. Every one must fit the
  theme.
- Every dish must be NEW: not the same as, or a close variant of, any dish on the "already posted" list
  (a different protein or base on the same idea still counts as a copy).
- Make the {n} varied: different proteins and bases where the theme allows, and no two titles starting
  with the same word.
- "title": at most 34 characters, no emoji. "subtitle": at most 40 characters, mouth-watering, no emoji,
  prices or numbers.
- "serves": 2-4. "prep_mins" + "cook_mins": the whole dish ready in 15-45 minutes. "calories": per
  serving, worked out from the ingredients (don't default to a round number).
- "ingredients": 6-10 items, each {{"item", "qty", "price"}}. "item": the ingredient name only, lower
  case, no preparation words. "qty": the amount bought or used ({units}) or null for pantry staples.
  "price": what that amount costs at {store} in 2025-26, in {money} (a number). Pantry staples like salt,
  pepper or oil cost {staples}. Price realistically; never bend prices to make a dish look cheap.
- "method": 4 steps, each {{"title": 2-4 words, "text": at most 120 characters}}.
- "tip": one Measy tip, at most 100 characters.
Return {{"dishes": [{{"title", "subtitle", "serves", "prep_mins", "cook_mins", "calories", "ingredients",
"method", "tip"}}, ...]}}"""

STOP = {"and", "with", "the", "a", "of", "in", "on", "&", "style"}


def _words(title: str) -> set[str]:
    return set(re.findall(r"[a-z]+", title.lower())) - STOP


def clash(title: str, others: list[str]) -> str | None:
    """The dish it copies, if it shares most of its words with one already posted."""
    w = _words(title)
    for o in others:
        ow = _words(o)
        if w and ow and len(w & ow) / len(w | ow) >= 0.6:
            return o
    return None


def posted_dishes(hists) -> list[str]:
    """Every dish posted on any account, newest first, plus the library's dishes."""
    seen, out = set(), []
    posts = sorted((p for h in hists for p in h.accepted()), key=lambda p: p.get("sent_at") or p["date"],
                   reverse=True)
    titles = [d for p in posts for d in p.get("dishes") or []]
    titles += [e["title"] for e in library.load().values()]
    for t in titles:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def invent(client: OpenAI, cfg: dict, theme: str, store, avoid: list[str], n: int = 5,
           log=print, loved: list[str] | None = None) -> list[dict]:
    """`loved`: dishes from the account's most-viewed recent posts: new dishes with the same appeal."""
    us = config.REGION == "us"
    system = (SYSTEM_US if us else SYSTEM_UK).format(store=store.name)
    rules = RULES.format(n=n, theme=theme, store=store.name,
                         money="US dollars" if us else "pounds",
                         units='"1 lb", "8 oz", "1 can (14 oz)", "2 tbsp", "2"' if us
                         else '"500g", "2", "1 tbsp", "400g tin"',
                         staples="0.05-0.20" if us else "0.05-0.15")
    hits = ""
    if loved:
        hits = ("Dishes from this account's most-viewed recent posts. Viewers loved these: make new dishes "
                "with the same kind of appeal (the same comfort, flavours and price feel), never copies:\n"
                + "\n".join(f"- {t}" for t in loved[:25]) + "\n\n")
    got: list[dict] = []
    feedback = ""
    for attempt in range(3):
        need = n - len(got)
        listing = "\n".join(f"- {t}" for t in (avoid[:250] + [g["title"] for g in got]))
        user = (hits + f"Already posted (don't repeat or closely copy):\n{listing}\n\n"
                + rules.replace(f"Invent {n} ", f"Invent {need} ") + feedback)
        data = client.chat_json(cfg["openai"]["text_model"], system, user)
        rejected = []
        for e in (data.get("dishes") or [])[:need]:
            if isinstance(e, dict):
                for k in ("serves", "prep_mins", "cook_mins", "calories"):
                    if isinstance(e.get(k), float):
                        e[k] = round(e[k])          # the cards print whole numbers
            try:
                problems = library.check(e) if isinstance(e, dict) else ["not a recipe"]
            except (KeyError, TypeError, AttributeError) as err:
                problems = [f"malformed recipe ({err})"]
            title = e.get("title", "") if isinstance(e, dict) else ""
            copy = clash(title, avoid + [g["title"] for g in got]) if title else None
            if copy:
                problems.append(f"too close to '{copy}'")
            if problems:
                rejected.append(f"{title or '?'}: {'; '.join(problems)}")
            else:
                got.append(e)
        if len(got) >= n:
            return got[:n]
        log(f"  New dishes: {len(got)} of {n} ok; retrying ({' | '.join(rejected)[:300]})")
        feedback = ("\n\nRejected last time: " + " | ".join(rejected)
                    + f". Write {n - len(got)} more that avoid those problems.")
    raise OpenAIError(f"Couldn't invent {n} new dishes for {theme}.")


def make(client: OpenAI, cfg: dict, theme: str, store, avoid: list[str], seed: str,
         log=print, loved: list[str] | None = None) -> list[Recipe]:
    """Five new dishes with a new photo each, ready to draw as cards."""
    entries = invent(client, cfg, theme, store, avoid + list(loved or []), log=log, loved=loved)
    rng = random.Random(f"{seed}/fresh")
    for e in entries:
        slug = "-".join(sorted(_words(e["title"]), key=e["title"].lower().find))[:40] or "dish"
        e["group"] = f"new-{slug}-{hashlib.md5((seed + e['title']).encode()).hexdigest()[:5]}"
        e["fresh"] = True
    angles = [rng.randrange(8) for _ in entries]
    with ThreadPoolExecutor(5) as pool:
        list(pool.map(lambda ea: photos.generate(client, ea[0], 1, cfg, folder=photos.FRESH_DIR,
                                                 angle=ea[1]), zip(entries, angles)))
    out = []
    for e in entries:
        library.add_fresh(e)
        prices = [i["price"] for i in e["ingredients"]]
        out.append(Recipe(
            file=f"card:{e['group']}-1", dish=e["title"], group=e["group"], protein=None, base=None,
            currency="USD" if config.REGION == "us" else "GBP", cost_total=round(sum(prices), 2),
            cost_per_serving=None, serves=e.get("serves"),
            time_mins=(e.get("prep_mins") or 0) + (e.get("cook_mins") or 0) or None, layout="card"))
    log("New dishes, each with a new photo: " + "; ".join(r.dish for r in out))
    return out
