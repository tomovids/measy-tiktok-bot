"""Writes the day's hook, optional second line, caption intro and cover scene.

The OpenAI writer is shown the owner's past hooks as style examples. Every answer is checked:
claims about money or time must be true for the five recipes on the cards, the number of dinners
must be 5, only emoji that draw cleanly are allowed, and recent hooks are not repeated.
If the writer fails three times (or OpenAI is down) a saved hook is used instead.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from pathlib import Path

from . import config
from .catalogue import Recipe
from .openai_api import OpenAI, OpenAIError

THEMES = [
    "better than a takeaway / fakeaway", "skint until payday", "too tired or lazy to cook",
    "the weekly Aldi shop", "feeding the whole family", "Friday or Saturday night in",
    "cosy comfort food", "send this to a friend who can't cook", "meals you'll make on repeat",
    "no idea what to cook this week", "cheap but doesn't taste cheap", "beating a meal deal",
]
FALLBACK_INTROS = [
    "Saving these for this week 👇",
    "Which one are you making first? 👀",
    "Cheap, easy and actually tasty 🤤",
    "Your weekly shop just got easier 🛒",
    "Proof that budget dinners don't have to be boring 🔥",
]


@dataclass
class Words:
    hook: str
    subline: str
    intro: str
    scene: str
    source: str  # "ai" or "fallback"


@dataclass
class Facts:
    total_gbp: float | None       # all five dishes together, if every card shows a price
    max_serving_gbp: float | None  # dearest portion, if every card shows a price
    max_time: int | None           # slowest dish in minutes, if every card shows a time


def facts_for(recipes: list[Recipe]) -> Facts:
    totals = [r.total_gbp for r in recipes]
    servings = [r.per_serving_gbp for r in recipes]
    times = [r.time_mins for r in recipes]
    return Facts(
        total_gbp=round(sum(totals), 2) if all(t is not None for t in totals) else None,
        max_serving_gbp=max(servings) if all(s is not None for s in servings) else None,
        max_time=max(times) if all(t is not None for t in times) else None,
    )


# ---- checks -----------------------------------------------------------------------------------

def is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or 0x2300 <= cp <= 0x23FF
            or 0x2B00 <= cp <= 0x2BFF or cp in (0x200D, 0xFE0F, 0x20E3))


MONEY = re.compile(r"£\s?(\d+(?:\.\d{1,2})?)(.{0,14})", re.I)
PENCE = re.compile(r"\b\d+\s?p\b(?!\w)", re.I)
MINUTES = re.compile(r"\b(\d+)\s*-?\s*(?:min|mins|minutes)\b", re.I)
COUNT = re.compile(
    r"(?<![£\d.])\b(\d+)\b(?=(?:\s+[A-Za-z'’]+){0,3}?\s+(?:dinners?|meals?|recipes?|dishes|teas?)\b)",
    re.I)
PER_PORTION = re.compile(r"\b(per|each|a portion|a serving|a head|a plate|pp)\b", re.I)


def claim_problems(text: str, facts: Facts) -> list[str]:
    out = []
    for m in MONEY.finditer(text):
        amount = float(m.group(1))
        if PER_PORTION.search(m.group(2)):
            if facts.max_serving_gbp is None or facts.max_serving_gbp > amount:
                out.append(f"'£{m.group(1)}' per portion isn't backed up by the cards")
        elif facts.total_gbp is None or facts.total_gbp > amount:
            out.append(f"'£{m.group(1)}' isn't backed up by the cards"
                       + (f" (they add up to £{facts.total_gbp:.2f})" if facts.total_gbp else
                          " (not every card shows a price)"))
    if PENCE.search(text):
        out.append("don't use prices in pence")
    for m in MINUTES.finditer(text):
        n = int(m.group(1))
        if facts.max_time is None or facts.max_time > n:
            out.append(f"'{m.group(0)}' isn't true for every dish"
                       + (f" (the slowest takes {facts.max_time} min)" if facts.max_time else
                          " (not every card shows a time)"))
    for m in COUNT.finditer(text):
        if int(m.group(1)) != 5:
            out.append(f"the post has 5 dinners, not {m.group(1)}")
    return out


def normalise(hook: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", hook.lower())


def problems(w: Words, facts: Facts, recent: list[str], cfg: dict) -> list[str]:
    wc = cfg["words"]
    allowed = set(wc["emoji"])
    out = []
    hook, sub = w.hook.strip(), w.subline.strip()
    if not hook:
        return ["the hook is empty"]
    if len(hook) > wc["max_hook_chars"]:
        out.append(f"the hook is {len(hook)} characters; keep it to {wc['max_hook_chars']}")
    if "aldi" not in hook.lower():
        out.append("the hook must mention Aldi")
    if not is_emoji(hook[-1]):
        out.append("the hook must end with an emoji")
    if len(sub) > wc["max_subline_chars"]:
        out.append(f"the second line is {len(sub)} characters; keep it to {wc['max_subline_chars']}")
    if len(w.intro) > 150:
        out.append("the intro is too long (150 characters max)")
    for part in (hook, sub, w.intro):
        bad = sorted({c for c in part if is_emoji(c) and c not in allowed})
        if bad:
            out.append("use only these emoji: " + wc["emoji"] + " (not " + "".join(bad) + ")")
            break
    for part in (hook, sub, w.intro):
        out += claim_problems(part, facts)
    if normalise(hook) in {normalise(h) for h in recent}:
        out.append("that hook was used recently")
    return out


# ---- writing ----------------------------------------------------------------------------------

def load_examples(path: Path | None = None) -> list[tuple[int, str, str]]:
    path = path or config.DATA / "hook_examples.txt"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        views = int(parts[0]) if parts[0].isdigit() else 0
        out.append((views, parts[1], parts[2] if len(parts) > 2 else ""))
    return sorted(out, key=lambda e: -e[0])


def load_fallbacks(path: Path | None = None) -> list[tuple[str, str]]:
    path = path or config.DATA / "hooks_fallback.txt"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        hook, _, sub = line.partition("|")
        out.append((hook.strip(), sub.strip()))
    return out


def _rules(facts: Facts, cfg: dict) -> str:
    wc = cfg["words"]
    if facts.total_gbp is not None:
        money = (f"You may mention a £ amount only if it's at least £{math.ceil(facts.total_gbp)} "
                 f"for all five dinners together (the cards add up to £{facts.total_gbp:.2f})")
        if facts.max_serving_gbp is not None:
            money += (f", or at least £{facts.max_serving_gbp:.2f} a portion (say 'a portion' "
                      f"right after the amount)")
        money += ". No pence."
    else:
        money = "Do NOT mention any prices or £ amounts (not every card shows one)."
    if facts.max_time is not None:
        time = (f"You may say 'ready in N minutes or less' only if N is at least {facts.max_time} "
                f"(the slowest dish takes {facts.max_time} minutes).")
    else:
        time = "Do NOT mention cooking times or minutes."
    return f"""Rules:
- "hook": the main cover text, at most {wc['max_hook_chars']} characters, must mention Aldi, must end with 1 or 2 emoji.
  If it states a number of dinners/meals it must be 5. Capitals for emphasis are fine (LAZY, NO, ONE).
- "subline": an optional short second line, at most {wc['max_subline_chars']} characters, ending with one emoji, or "" for none.
  Use one on roughly 4 in 10 posts.
- "intro": the first line of the TikTok caption (at most 150 characters, 1-2 emoji, don't list the dishes).
- "scene": one sentence describing the photo conditions for a picture of an Aldi store front: time of day,
  weather, season, camera angle, lighting. No people, no text. Make it different from a plain sunny day sometimes.
- Use ONLY these emoji: {wc['emoji']}
- {money}
- {time}
- These rules apply to the hook, the subline and the intro.
- British English. Playful, relatable and a bit dramatic, like the examples. No hashtags."""


def _prompt(recipes: list[Recipe], facts: Facts, examples, recent: list[str], theme: str,
            cfg: dict) -> tuple[str, str]:
    system = ("You write the cover text for daily TikTok photo slideshows by Measy, a UK meal-planning "
              "app with budget recipes made from an Aldi shop. Every slideshow shows 5 Aldi dinners. "
              "Answer with a JSON object only.")
    ex = "\n".join(f"- {h}" + (f"  /  second line: {s}" if s else "") +
                   (f"  ({v:,} views)" if v else "") for v, h, s in examples)
    dishes = "\n".join(
        f"- {r.dish}" + (f" (card price £{r.total_gbp:.2f})" if r.total_gbp is not None else "")
        + (f" ({r.time_mins} min)" if r.time_mins else "") for r in recipes)
    rec = "\n".join(f"- {h}" for h in recent) or "- (none yet)"
    user = f"""Past hooks from this account, best performers first:
{ex}

Today's five dinners:
{dishes}

Angle to try today (optional, only if it fits): {theme}

Don't repeat or closely copy these recent hooks:
{rec}

{_rules(facts, cfg)}

Return: {{"hook": "...", "subline": "...", "intro": "...", "scene": "..."}}"""
    return system, user


def _clean_scene(scene: str) -> str:
    scene = re.sub(r"\s+", " ", str(scene or "")).strip().strip('"').strip()
    return scene.rstrip(".")[:220]


def write(recipes: list[Recipe], recent: list[str], cfg: dict, client: OpenAI | None,
          rng: random.Random, log=print) -> Words:
    facts = facts_for(recipes)
    if client is not None:
        examples = load_examples()
        theme = rng.choice(THEMES)
        system, user = _prompt(recipes, facts, examples, recent, theme, cfg)
        feedback = ""
        for attempt in range(3):
            try:
                data = client.chat_json(cfg["openai"]["text_model"], system, user + feedback)
            except OpenAIError as e:
                log(f"Writer unavailable, using a saved hook: {e}")
                break
            w = Words(hook=str(data.get("hook", "")).strip(), subline=str(data.get("subline", "") or "").strip(),
                      intro=str(data.get("intro", "")).strip(), scene=_clean_scene(data.get("scene", "")),
                      source="ai")
            found = problems(w, facts, recent, cfg)
            if not found:
                if not w.scene:
                    w.scene = rng.choice(cfg["cover"]["fallback_scenes"])
                return w
            log(f"Writer attempt {attempt + 1} rejected: {'; '.join(found)}")
            feedback = ("\n\nYour last answer was " + str(data) + "\nIt had these problems: "
                        + "; ".join(found) + ". Write a new answer that fixes them.")
    return fallback(facts, recent, cfg, rng)


def fallback(facts: Facts, recent: list[str], cfg: dict, rng: random.Random) -> Words:
    options = load_fallbacks()
    rng.shuffle(options)
    intro = rng.choice(FALLBACK_INTROS)
    scene = rng.choice(cfg["cover"]["fallback_scenes"])
    for ignore_recent in (False, True):
        for hook, sub in options:
            w = Words(hook, sub, intro, scene, "fallback")
            if not problems(w, facts, [] if ignore_recent else recent, cfg):
                return w
    return Words("5 Aldi Dinners I'd Make on Repeat 😋", "", intro, scene, "fallback")


def dish_name(r: Recipe) -> str:
    name = re.sub(r"\s+", " ", r.dish).strip()
    if len(name) > 60 and " with " in name.lower():
        name = name[:name.lower().index(" with ")]
    return name.rstrip(" .,!")


def caption(w: Words, recipes: list[Recipe], cfg: dict) -> str:
    c = cfg["caption"]
    lines = [w.intro, ""]
    lines += [f"{i}. {dish_name(r)}" for i, r in enumerate(recipes, 1)]
    lines += ["", c["cta"], "", " ".join(c["hashtags"])]
    return "\n".join(lines).strip()
