"""Writes each post's hook, second line, caption intro and comment question.

Hook tournament: the writer (OpenAI) gets the brand guide (data/brand.md), the account's best past
hooks with their views, the post's theme, the five dishes and the facts on their cards, and writes
`candidates` different hooks. Each is checked: claims about money or time must be true for the
five cards, the number of dinners must be 5, only emoji that draw cleanly, no words the brand
avoids, never a hook used before and nothing too close to a recent one. A second call scores the
survivors like a TikTok strategist (scroll-stopping, relatable, specific, shareable, on-brand) and
the best one wins. If OpenAI is down a saved hook is used instead.
"""
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import config, stores
from .catalogue import Recipe
from .openai_api import OpenAI, OpenAIError
from .stores import Store

FALLBACK_INTROS = [
    "Saving these for this week 👇",
    "Cheap, easy and actually tasty 🤤",
    "Your weekly shop just got easier 🛒",
    "Proof that budget dinners don't have to be boring 🔥",
]
FALLBACK_QUESTIONS = [
    "Which one are you making first? 👇",
    "Rate these out of 10 👀",
    "Which one would you add to your shop this week? 🛒",
    "What would you add to number 3? 👇",
]
US_FALLBACK_INTROS = [
    "Saving these for this week 👇",
    "Cheap, easy and actually tasty 🤤",
    "Your next grocery run just got easier 🛒",
    "Proof that budget dinners don't have to be boring 🔥",
]
US_FALLBACK_QUESTIONS = [
    "Which one are you making first? 👇",
    "Rate these out of 10 👀",
    "Which one is going on your grocery list this week? 🛒",
    "What would you add to number 3? 👇",
]


def _us(cfg: dict) -> bool:
    return cfg.get("region", {}).get("id") == "us"


def _cur(cfg: dict) -> str:
    return cfg.get("region", {}).get("currency", "£")


def intros(cfg: dict) -> list[str]:
    return US_FALLBACK_INTROS if _us(cfg) else FALLBACK_INTROS


def questions(cfg: dict) -> list[str]:
    return US_FALLBACK_QUESTIONS if _us(cfg) else FALLBACK_QUESTIONS


@dataclass
class Words:
    hook: str
    subline: str
    intro: str
    scene: str = ""      # filled in by the pipeline (cover.pick_scene)
    source: str = "ai"   # "ai" or "fallback"
    question: str = ""
    score: float | None = None
    candidates: list = field(default_factory=list)


@dataclass
class Facts:
    # in the account's currency (£, or $ for a US account), from the cards it shows
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


MONEY = re.compile(r"([£$€])\s?(\d+(?:\.\d{1,2})?)(.{0,14})", re.I)
PENCE = re.compile(r"\b\d+\s?(?:p|cents?)\b(?!\w)|\d\s?¢", re.I)
MINUTES = re.compile(r"\b(\d+)\s*-?\s*(?:min|mins|minutes)\b", re.I)
COUNT = re.compile(
    r"(?<![£\d.])\b(\d+)\b(?=(?:\s+[A-Za-z'’]+){0,3}?\s+(?:dinners?|meals?|recipes?|dishes|teas?)\b)",
    re.I)
PER_PORTION = re.compile(r"\b(per|each|a portion|a serving|a head|a plate|pp)\b", re.I)


def claim_problems(text: str, facts: Facts, cur: str = "£") -> list[str]:
    out = []
    for m in MONEY.finditer(text):
        sym, amount = m.group(1), float(m.group(2))
        if sym != cur:
            out.append(f"prices on this account are in {cur}, not {sym}")
            continue
        if PER_PORTION.search(m.group(3)):
            if facts.max_serving_gbp is None or facts.max_serving_gbp > amount:
                out.append(f"'{cur}{m.group(2)}' per portion isn't backed up by the cards")
        elif facts.total_gbp is None or facts.total_gbp > amount:
            out.append(f"'{cur}{m.group(2)}' isn't backed up by the cards"
                       + (f" (they add up to {cur}{facts.total_gbp:.2f})" if facts.total_gbp else
                          " (not every card shows a price)"))
    if PENCE.search(text):
        out.append("don't use prices in cents" if cur == "$" else "don't use prices in pence")
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


def line_problems(text: str, max_len: int, facts: Facts, cfg: dict, store: Store | None = None) -> list[str]:
    """Checks for a caption line (intro or question): length, emoji, brand words, claims."""
    out = []
    if not text:
        return ["empty"]
    if len(text) > max_len:
        out.append(f"longer than {max_len} characters")
    allowed = set(cfg["words"]["emoji"])
    if any(is_emoji(c) and c not in allowed for c in text):
        out.append("unsupported emoji")
    if any(a in text.lower() for a in avoided(cfg, store)):
        out.append("a word the brand avoids")
    return out + claim_problems(text, facts, _cur(cfg))


def normalise(hook: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", hook.lower())


STORE_WORDS = {"aldi", "tesco", "lidl", "asda", "sainsbury's", "sainsburys", "morrisons", "waitrose",
               "walmart", "trader", "joe's", "joes"}


def _words(text: str) -> set[str]:
    return (set(re.findall(r"[a-z0-9£$']+", text.lower()))
            - {"5", "dinners", "for", "the", "a", "to", "of", "and", "you", "your", "i'd"} - STORE_WORDS)


def avoided(cfg: dict, store: Store | None = None) -> list[str]:
    """Brand-avoided words, minus the post's own supermarket."""
    own = set((store or stores.default()).words)
    return [a.lower() for a in cfg.get("brand", {}).get("avoid", []) if not any(o in a.lower() for o in own)]


def too_similar(hook: str, recent: list[str], threshold: float) -> str | None:
    w = _words(hook)
    for r in recent:
        rw = _words(r)
        if w and rw and len(w & rw) / len(w | rw) >= threshold:
            return r
    return None


def problems(w: Words, facts: Facts, recent: list[str], cfg: dict,
             used: set[str] | None = None, store: Store | None = None) -> list[str]:
    store = store or stores.default()
    wc = cfg["words"]
    allowed = set(wc["emoji"])
    out = []
    hook, sub = w.hook.strip(), w.subline.strip()
    if not hook:
        return ["the hook is empty"]
    if len(hook) > wc["max_hook_chars"]:
        out.append(f"the hook is {len(hook)} characters; keep it to {wc['max_hook_chars']}")
    if not store.mentioned_in(hook):
        out.append(f"the hook must mention {store.name}")
    if not is_emoji(hook[-1]):
        out.append("the hook must end with an emoji")
    if len(sub) > wc["max_subline_chars"]:
        out.append(f"the second line is {len(sub)} characters; keep it to {wc['max_subline_chars']}")
    hw, sw = _words(hook), _words(sub)
    if sw and len(hw & sw) / len(sw) >= 0.5:
        out.append("the second line repeats the hook; it must add something new")
    if len(w.intro) > 150:
        out.append("the intro is too long (150 characters max)")
    if w.question and len(w.question) > 100:
        out.append("the question is too long (100 characters max)")
    for part in (hook, sub, w.intro, w.question):
        bad = sorted({c for c in part if is_emoji(c) and c not in allowed})
        if bad:
            out.append("use only these emoji: " + wc["emoji"] + " (not " + "".join(bad) + ")")
            break
    text = " ".join((hook, sub, w.intro, w.question)).lower()
    avoid = [a for a in avoided(cfg, store) if a in text]
    if avoid:
        out.append("don't mention " + ", ".join(avoid))
    for part in (hook, sub, w.intro, w.question):
        out += claim_problems(part, facts, _cur(cfg))
    if normalise(hook) in {normalise(h) for h in (used or set())}:
        out.append("that exact hook has been used before")
    elif normalise(hook) in {normalise(h) for h in recent}:
        out.append("that hook was used recently")
    else:
        twin = too_similar(hook, recent, wc.get("similar_threshold", 0.6))
        if twin:
            out.append(f"too close to a recent hook ('{twin}'); find a different idea")
    return out


# ---- prompts ----------------------------------------------------------------------------------

def load_examples(path: Path | None = None) -> list[tuple[int, str, str]]:
    path = path or config.DATA / "hook_examples.txt"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        views = int(parts[0]) if parts[0].isdigit() else 0
        out.append((views, parts[1], parts[2] if len(parts) > 2 else ""))
    # the bot's own best posts (from the TikTok stats) join the examples
    from .tuning import load as load_tuning
    seen = {normalise(h) for _, h, _ in out}
    for t in load_tuning().get("top_hooks", []):
        if normalise(t["hook"]) not in seen:
            out.append((int(t.get("views", 0)), t["hook"], t.get("subline", "")))
            seen.add(normalise(t["hook"]))
    return sorted(out, key=lambda e: -e[0])


def load_fallbacks(path: Path | None = None, region: str = "uk") -> list[tuple[str, str]]:
    path = path or config.DATA / ("hooks_fallback.txt" if region == "uk" else f"hooks_fallback_{region}.txt")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        hook, _, sub = line.partition("|")
        out.append((hook.strip(), sub.strip()))
    return out


def brand_guide() -> str:
    path = config.DATA / "brand.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _rules(facts: Facts, cfg: dict, store: Store | None = None) -> str:
    store = store or stores.default()
    wc = cfg["words"]
    c = _cur(cfg)
    per = "a serving" if _us(cfg) else "a portion"
    if not store.price_claims:
        money = (f"Do NOT mention any prices or {c} amounts (the card prices aren't {store.name} prices).")
    elif facts.total_gbp is not None:
        money = (f"You may mention a {c} amount only if it's at least {c}{math.ceil(facts.total_gbp)} "
                 f"for all five dinners together (the cards add up to {c}{facts.total_gbp:.2f})")
        if facts.max_serving_gbp is not None:
            money += (f", or at least {c}{facts.max_serving_gbp:.2f} {per} (say '{per}' "
                      f"right after the amount)")
        money += ". No cents." if c == "$" else ". No pence."
    else:
        money = f"Do NOT mention any prices or {c} amounts (not every card shows one)."
    if facts.max_time is not None:
        time = (f"You may say 'ready in N minutes or less' only if N is at least {facts.max_time} "
                f"(the slowest dish takes {facts.max_time} minutes).")
    else:
        time = "Do NOT mention cooking times or minutes."
    return f"""Rules for every hook:
- At most {wc['max_hook_chars']} characters, mentions {store.name}, ends with 1 or 2 emoji. Never names any
  other supermarket. If it states a number
  of dinners/meals it must be 5. Capitals for emphasis on one word at most.
- "subline": an optional second line, at most {wc['max_subline_chars']} characters, ending with one emoji,
  or "" (about 4 in 10 posts have one).
- Use ONLY these emoji: {wc['emoji']}
- {money}
- {time}
- The same rules apply to the subline, the intro and the question."""


def _when(day: date | None, slot: str | None) -> str:
    if day is None:
        return ""
    part = {"morning": "morning", "midday": "lunchtime", "afternoon": "late afternoon"}.get(slot or "", "morning")
    return (f"The post goes out on {day:%A} {part}. Only mention a day of the week if it's "
            f"{day:%A} or the coming weekend.")


def _prompt(recipes, facts, examples, recent, theme, cfg, day, slot, store=None) -> tuple[str, str]:
    store = store or stores.default()
    n = cfg["words"].get("candidates", 6)
    us = _us(cfg)
    system = ("You write viral TikTok photo-slideshow covers for Measy, a " + ("" if us else "UK ")
              + "meal-planning app with "
              f"budget recipes. This post is about {store.name}: it shows 5 {store.name} dinners. Follow "
              "the brand guide. Answer with a JSON object only.\n\n" + brand_guide())
    if us:
        system += "\n\n" + cfg["region"].get("voice", "")
        system += (f"\n\nThe past hooks below are from Measy's UK account (Aldi UK posts). Copy their energy "
                   f"and structures, not their British words; this post is about {store.name} in the US.")
    elif store.id != "aldi":
        system += (f"\n\nThe past hooks below are from Aldi posts; this post is about {store.name}, so use "
                   f"{store.name} where they say Aldi.")
    ex = "\n".join(f"- {h}" + (f"  /  second line: {s}" if s else "") +
                   (f"  ({v:,} views)" if v else "") for v, h, s in examples)
    dishes = "\n".join(
        f"- {r.dish}" + (f" ({_cur(cfg)}{r.per_serving_gbp:.2f} a portion)"
                         if r.per_serving_gbp and store.price_claims else "")
        + (f" ({r.time_mins} min)" if r.time_mins else "") for r in recipes)
    rec = "\n".join(f"- {h}" for h in recent) or "- (none yet)"
    theme_txt = (f"Today's theme: 5 {store.name} {theme.label}. "
                 f"Angle: {theme.angle_text.replace('{store}', store.name)}.\n"
                 f"The hook must make the theme obvious.") if theme else ""
    if theme and us:
        theme_txt += ("\n(The theme and angle are written in British English: say the same thing the way "
                      "an American would, e.g. fakeaway -> takeout copycat, payday -> payday / end of the month, "
                      "the big shop -> grocery run, mince -> ground beef.)")
    user = f"""Past hooks from this account, best performers first:
{ex}

{theme_txt}
{_when(day, slot)}

The five dinners on the cards:
{dishes}

Don't repeat or closely copy these recent hooks:
{rec}

{_rules(facts, cfg, store)}

Write {n} genuinely different hook candidates (different structures and emotional triggers: a pain
point, a money detail, a "send this to" line, a takeaway comparison, a bold claim...). Then one caption
"intro" line (max 150 characters, 1-2 emoji, don't list the dishes) and one "question" that gets people
commenting (max 100 characters, ends with an emoji).
Return: {{"candidates": [{{"hook": "...", "subline": "..."}}, ...], "intro": "...", "question": "..."}}"""
    return system, user


JUDGE_SYSTEM = """You are a TikTok growth strategist for UK food content. You rank cover hooks for a
photo slideshow by how likely they are to stop the scroll and get saves, shares and comments from UK
viewers on a budget. Answer with a JSON object only."""
JUDGE_SYSTEM_US = """You are a TikTok growth strategist for US food content. You rank cover hooks for a
photo slideshow by how likely they are to stop the scroll and get saves, shares and comments from
American viewers on a budget. Mark down anything that sounds British. Answer with a JSON object only."""


def _judge(client: OpenAI, cfg: dict, cands: list[Words], examples, theme,
           store: Store | None = None) -> tuple[int, list[float]]:
    store = store or stores.default()
    top = "\n".join(f"- {h} ({v:,} views)" for v, h, _ in examples[:6] if v)
    listing = "\n".join(f"{i}. {w.hook}" + (f"  /  {w.subline}" if w.subline else "")
                        for i, w in enumerate(cands))
    angle = theme.angle_text.replace("{store}", store.name) if theme else ""
    source = "Measy's UK account (Aldi UK posts)" if _us(cfg) else "Aldi posts"
    user = f"""This account's best performers ({source}), for reference:
{top}

This post is about {store.name}. {"Theme: 5 " + theme.label + ", angle: " + angle if theme else ""}

Candidates:
{listing}

Be a harsh judge: most hooks deserve 4-7, only a genuinely great one gets 9+. Score each 1-10 on:
stops the scroll in the first second; relatable feeling (money, tiredness, indecision); specific and
believable; makes people want to send it to someone or save it; reads naturally out loud like a real
person, not an ad; fits the theme. Mark down hard: clumsy or confusing wording, a second line that
repeats the hook, claims that sound odd ("for one"), more than one idea crammed in.
Then give an overall score.
Return {{"scores": [{{"i": 0, "overall": 7.5, "why": "..."}}, ...], "best": <index>}}"""
    data = client.chat_json(cfg["openai"]["text_model"], JUDGE_SYSTEM_US if _us(cfg) else JUDGE_SYSTEM, user)
    scores = [0.0] * len(cands)
    for s in data.get("scores", []):
        try:
            scores[int(s["i"])] = float(s["overall"])
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    best = data.get("best")
    if not isinstance(best, int) or not 0 <= best < len(cands):
        best = max(range(len(cands)), key=lambda i: scores[i])
    return best, scores


# ---- writing ----------------------------------------------------------------------------------

def write(recipes: list[Recipe], recent: list[str], cfg: dict, client: OpenAI | None,
          rng: random.Random, log=print, day: date | None = None, theme=None,
          used: set[str] | None = None, slot: str | None = None, store: Store | None = None) -> Words:
    store = store or stores.default()
    facts = facts_for(recipes)
    if not store.price_claims:  # card prices are Aldi prices: no £ claims for other stores
        facts = Facts(None, None, facts.max_time)
    if client is not None:
        examples = load_examples()
        system, user = _prompt(recipes, facts, examples, recent, theme, cfg, day, slot, store)
        feedback = ""
        for attempt in range(3):
            try:
                data = client.chat_json(cfg["openai"]["text_model"], system, user + feedback)
            except OpenAIError as e:
                log(f"Writer unavailable, using a saved hook: {e}")
                break
            intro = str(data.get("intro", "")).strip()
            question = str(data.get("question", "")).strip()
            if line_problems(intro, 150, facts, cfg, store):
                log(f"  intro swapped for a saved one ({'; '.join(line_problems(intro, 150, facts, cfg, store))})")
                intro = rng.choice(intros(cfg))
            if line_problems(question, 100, facts, cfg, store):
                question = rng.choice(questions(cfg))
            cands, rejected = [], []
            for c in data.get("candidates", []) or []:
                w = Words(hook=str(c.get("hook", "")).strip(), subline=str(c.get("subline", "") or "").strip(),
                          intro=intro, question=question, source="ai")
                found = problems(w, facts, recent, cfg, used, store)
                (rejected.append((w.hook, found)) if found else cands.append(w))
            for hook, found in rejected:
                log(f"  rejected: {hook}  ({'; '.join(found)})")
            if cands:
                best, scores = 0, [None] * len(cands)
                if len(cands) > 1:
                    try:
                        best, scores = _judge(client, cfg, cands, examples, theme, store)
                    except OpenAIError as e:
                        log(f"Judge unavailable, taking the first good hook: {e}")
                w = cands[best]
                w.score = scores[best]
                w.candidates = [{"hook": c.hook, "subline": c.subline, "score": s}
                                for c, s in zip(cands, scores)]
                if not w.question:
                    w.question = rng.choice(questions(cfg))
                return w
            log(f"Writer attempt {attempt + 1}: no usable candidates")
            feedback = ("\n\nYour last answer was " + json.dumps(data, ensure_ascii=False)
                        + "\nEvery candidate broke a rule:\n"
                        + "\n".join(f"- {h}: {'; '.join(f)}" for h, f in rejected)
                        + "\nWrite new candidates that follow every rule.")
    return fallback(facts, recent, cfg, rng, used, store)


def fallback(facts: Facts, recent: list[str], cfg: dict, rng: random.Random,
             used: set[str] | None = None, store: Store | None = None) -> Words:
    store = store or stores.default()
    region = cfg.get("region", {}).get("id", "uk")
    options = [(h.replace("Aldi", store.name), s.replace("Aldi", store.name))
               for h, s in load_fallbacks(region=region)]
    rng.shuffle(options)
    intro = rng.choice(intros(cfg))
    question = rng.choice(questions(cfg))
    for strict in (True, False):
        for hook, sub in options:
            w = Words(hook, sub, intro, source="fallback", question=question)
            if not problems(w, facts, recent if strict else [], cfg, used if strict else None, store):
                return w
    return Words(f"5 {store.name} Dinners I'd Make on Repeat 😋", "", intro, source="fallback",
                 question=question)


def dish_name(r: Recipe) -> str:
    name = re.sub(r"\s+", " ", r.dish).strip()
    if len(name) > 60 and " with " in name.lower():
        name = name[:name.lower().index(" with ")]
    return name.rstrip(" .,!")


def caption(w: Words, recipes: list[Recipe], cfg: dict, theme=None, rng: random.Random | None = None,
            store: Store | None = None) -> str:
    store = store or stores.default()
    c = cfg["caption"]
    rng = rng or random.Random(w.hook)
    lines = [w.intro, ""]
    lines += [f"{i}. {dish_name(r)}" for i, r in enumerate(recipes, 1)]
    lines += [""]
    if w.question:
        lines.append(w.question)
    saves = c.get("save_lines") or []
    if saves:
        lines.append(rng.choice(saves).replace("{store}", store.name))
    lines += [c["cta"], ""]
    swap = cfg.get("region", {}).get("hashtag_swap", {})
    theme_tags = [swap.get(t, t) for t in (theme.hashtags if theme else [])]
    tags = list(dict.fromkeys(store.hashtags + c["hashtags"] + theme_tags))
    tags = tags[: c.get("max_hashtags", 10)]
    lines.append(" ".join(tags))
    return "\n".join(lines).strip()
