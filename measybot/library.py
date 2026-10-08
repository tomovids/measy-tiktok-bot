"""The recipe library (data/recipe_library.json): one clean, card-ready recipe per dish.

Built once from the transcribed recipe cards (data/cards_transcribed.json): the AI keeps what the card
printed, converts dollar prices to Aldi UK pounds, writes anything missing (methods, whole recipes
for photo-only dishes) and shortens the method to fit the card. Everything it adds or changes is
listed in the entry's "ai_filled" so a person can check it.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config
from .card import CardRecipe, fit_line, render
from .openai_api import OpenAI, OpenAIError

LIBRARY = config.DATA / "recipe_library.json"

SYSTEM = """You prepare recipes for Measy, a UK budget meal-planning app whose recipes are made from an
Aldi UK shop. You turn a transcribed recipe card into a clean, card-ready recipe. British English.
Answer with a JSON object only."""

RULES = """Rules:
- Keep the card's title (fix obvious typos only). "subtitle": keep the card's line under the title if it
  describes the dish or its appeal; otherwise write a short mouth-watering one (max 40 characters,
  no emoji, no prices, no numbers).
- "serves", "prep_mins", "cook_mins", "calories" (per serving): keep the card's numbers. If missing, work
  calories out from this recipe's ingredients and servings (dishes differ; don't default to a round number). If the card only shows
  one total time, split it sensibly into prep and cook.
- "ingredients": 6-12 items, each {"item", "qty", "price"}.
  "item": the ingredient name only, lower case except brand-style names (e.g. "red pepper",
  "beef mince (5% fat)", "hoisin sauce"), with no preparation words like sliced or chopped.
  "qty": the amount only (e.g. "500g", "2", "1 tbsp", "1 bunch") or null for pantry staples.
  "price": what that amount costs at Aldi UK in 2025-26, in pounds (a number, e.g. 0.85). Keep the card's
  £ item prices unless one is clearly unrealistic for Aldi UK (far too cheap or too dear): then correct
  it and add "prices" to ai_filled. If the card is in dollars, has no item prices or only a total,
  price every item realistically. Never bend prices to match a printed total: the total is worked out
  from the items. Pantry staples like salt, pepper or oil cost 0.05-0.15.
- "method": 4 or 5 steps, each {"title": 2-4 words, "text": at most 130 characters}. Keep the card's
  method but shorten it; if the card has no method, write one that matches the ingredients.
- "tip": one Measy tip, at most 110 characters (keep the card's tip if it has one, shortened if needed).
- "ai_filled": a list of the fields you added or changed beyond shortening and tidying, e.g. ["prices",
  "method", "calories", "subtitle"]. Use [] if you only copied, shortened and tidied.
Return {"title", "subtitle", "serves", "prep_mins", "cook_mins", "calories", "ingredients", "method",
"tip", "ai_filled"}."""


def load_transcriptions(path: Path | None = None) -> dict[str, dict]:
    path = path or config.DATA / "cards_transcribed.json"
    return {r["group"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def prompt_for(group: str, raw: dict | None, catalogue_rows: list[dict]) -> str:
    if raw:
        source = "Transcribed card:\n" + json.dumps(raw, ensure_ascii=False, indent=1)
    else:
        r = catalogue_rows[0]
        facts = {k: r.get(k) for k in ("dish", "serves", "time_mins", "cost_total", "cost_per_serving")}
        source = ("There is no recipe card for this dish, only a photo poster with these facts:\n"
                  + json.dumps(facts, ensure_ascii=False) + "\nWrite the whole recipe for it.")
    return f"Dish id: {group}\n\n{source}\n\n{RULES}"


def check(entry: dict) -> list[str]:
    problems = []
    for key in ("title", "serves", "prep_mins", "cook_mins", "ingredients", "method"):
        if not entry.get(key):
            problems.append(f"missing {key}")
    for i in entry.get("ingredients", []):
        if not isinstance(i.get("price"), (int, float)):
            problems.append(f"no price for {i.get('item')}")
    if not 4 <= len(entry.get("method", [])) <= 5:
        problems.append("method must have 4 or 5 steps")
    sub = entry.get("subtitle") or ""
    if sub and fit_line(sub, 1080 - 88)[0] != sub.strip():
        problems.append("the subtitle is too long for one line: keep it under 45 characters")
    if not problems:
        try:
            from PIL import Image
            render(CardRecipe.from_dict(entry), Image.new("RGB", (1536, 1024), (200, 160, 120)))
        except ValueError:
            problems.append("too long to fit on the card: shorten the method and ingredient names")
    return problems


def build_entry(client: OpenAI, model: str, group: str, raw: dict | None, rows: list[dict],
                log=print) -> dict:
    user = prompt_for(group, raw, rows)
    feedback = ""
    for attempt in range(3):
        entry = client.chat_json(model, SYSTEM, user + feedback)
        problems = check(entry)
        if not problems:
            entry["group"] = group
            entry["source_card"] = raw["file"] if raw else None
            return entry
        log(f"  {group}: attempt {attempt + 1} needs fixing: {'; '.join(problems)}")
        feedback = ("\n\nYour last answer:\n" + json.dumps(entry, ensure_ascii=False)
                    + "\nProblems: " + "; ".join(problems) + ". Fix them.")
    raise OpenAIError(f"Couldn't make a card-ready recipe for {group}.")


def build(client: OpenAI, cfg: dict, only: list[str] | None = None, log=print, workers: int = 6) -> dict:
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    catalogue = [r for r in json.loads((config.DATA / "recipes.json").read_text(encoding="utf-8"))
                 if r["kind"] == "recipe"]
    groups: dict[str, list[dict]] = {}
    for r in catalogue:
        groups.setdefault(r["group"], []).append(r)
    raw = load_transcriptions()
    library = json.loads(LIBRARY.read_text(encoding="utf-8")) if LIBRARY.exists() else {}
    todo = [g for g in sorted(groups) if (g in only if only else g not in library)]
    lock = threading.Lock()

    def save():
        text = json.dumps(dict(sorted(library.items())), ensure_ascii=False, indent=1)
        LIBRARY.write_text(text + "\n", encoding="utf-8")

    with ThreadPoolExecutor(workers) as pool:
        jobs = {pool.submit(build_entry, client, cfg["openai"]["text_model"], g, raw.get(g), groups[g], log): g
                for g in todo}
        for job in as_completed(jobs):
            g = jobs[job]
            try:
                entry = job.result()
            except OpenAIError as e:
                log(f"FAILED {g}: {e}")
                continue
            with lock:
                library[g] = entry
                save()
            log(f"done {g} ({len(library)} in the library)")
    return library


def load() -> dict:
    return json.loads(LIBRARY.read_text(encoding="utf-8")) if LIBRARY.exists() else {}
