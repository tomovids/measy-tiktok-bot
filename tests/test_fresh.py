import random
from datetime import date

from PIL import Image

from measybot import card, fresh, library, photos, stores, themes, writer
from measybot.history import SENT, History


def dish(title, price=1.2):
    return {"title": title, "subtitle": "Saucy and golden", "serves": 4, "prep_mins": 10, "cook_mins": 20,
            "calories": 540,
            "ingredients": [{"item": f"thing {i}", "qty": "200g", "price": price} for i in range(7)],
            "method": [{"title": f"Step {i}", "text": "Cook it until golden and bubbling."} for i in range(4)],
            "tip": "Swap in whatever veg you have."}


class Stub:
    def __init__(self, batches):
        self.batches, self.prompts = list(batches), []

    def chat_json(self, model, system, user):
        self.prompts.append(user)
        return {"dishes": self.batches.pop(0)}


def test_clash_spots_copies():
    assert fresh.clash("Sticky Korean BBQ Chicken Loaded Fries", ["Sticky Korean Chicken Loaded Fries"])
    assert fresh.clash("Lemon Pepper Chicken Couscous", ["Sticky Korean Chicken Loaded Fries"]) is None


def test_posted_dishes_covers_every_account_and_the_library():
    a = History([{"date": "2026-11-20", "status": SENT, "dishes": ["Old One"], "sent_at": "2026-11-20T08:00"}])
    b = History([{"date": "2026-11-21", "status": SENT, "dishes": ["Newer One"], "sent_at": "2026-11-21T08:00"}])
    got = fresh.posted_dishes([a, b])
    assert got[:2] == ["Newer One", "Old One"]
    assert set(e["title"] for e in library.load().values()) <= set(got)


def test_invent_rounds_numbers(cfg):
    d = dish("Lemon Pepper Chicken Couscous")
    d["calories"] = 469.1
    got = fresh.invent(Stub([[d] + [dish(t) for t in ("Butter Bean Orzo", "Halloumi Fajita Traybake",
                                                      "Smoky Chorizo Gnocchi Bake", "Honey Garlic Pork Noodles")]]),
                       cfg, "5 Aldi dinners", stores.by_id(cfg, "aldi"), [], log=lambda *_: None)
    assert got[0]["calories"] == 469


def test_invent_retries_copies_and_bad_recipes(cfg):
    aldi = stores.by_id(cfg, "aldi")
    first = [dish("Lemon Pepper Chicken Couscous"), dish("Sticky Korean Chicken Loaded Fries"),
             dish("Butter Bean Orzo"), dish("Halloumi Fajita Traybake"), {"title": "Broken"}]
    second = [dish("Smoky Chorizo Gnocchi Bake"), dish("Honey Garlic Pork Noodles")]
    stub = Stub([first, second])
    got = fresh.invent(stub, cfg, "5 Aldi cheesy dinners", aldi, ["Sticky Korean BBQ Chicken Loaded Fries"],
                       log=lambda *_: None)
    assert [g["title"] for g in got] == ["Lemon Pepper Chicken Couscous", "Butter Bean Orzo",
                                         "Halloumi Fajita Traybake", "Smoky Chorizo Gnocchi Bake",
                                         "Honey Garlic Pork Noodles"]
    assert "Rejected last time" in stub.prompts[1] and "too close" in stub.prompts[1]


def test_make_gives_new_photos_and_drawable_cards(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "FRESH_DIR", tmp_path)

    def fake_generate(client, entry, n, cfg, folder=None, angle=None):
        path = folder / f"{entry['group']}-{n}.jpg"
        Image.new("RGB", (1536, 1024), (180, 120, 60)).save(path)
        return path

    monkeypatch.setattr(photos, "generate", fake_generate)
    titles = ["Lemon Pepper Chicken Couscous", "Butter Bean Orzo", "Halloumi Fajita Traybake",
              "Smoky Chorizo Gnocchi Bake", "Honey Garlic Pork Noodles"]
    recipes = fresh.make(Stub([[dish(t) for t in titles]]), cfg, "5 Aldi dinners", stores.by_id(cfg, "aldi"),
                         [], "2026-11-24/morning", log=lambda *_: None)
    assert [r.dish for r in recipes] == titles
    assert all(r.group.startswith("new-") and r.total_gbp == 8.4 for r in recipes)
    assert card.render_for(recipes[0].file).size == (1080, 1920)
    shop = card.render_shop([card.load_card(r.file) for r in recipes], "Aldi")
    assert shop.size == (1080, 1920)
    assert card.render_shop([card.load_card(r.file) for r in recipes], "Trader Joe's").size == (1080, 1920)


def test_full_week_angle_only_where_prices_are_allowed(cfg):
    data = themes.load()
    tags = {f"d{i}": {"cheesy", "chicken"} for i in range(10)}
    picked = {themes.choose(date(2026, 11, 24), "morning", History(), tags, cfg, random.Random(i), data,
                            price_ok=False).angle for i in range(60)}
    assert "full-week" not in picked
    picked = {themes.choose(date(2026, 11, 24), "morning", History(), tags, cfg, random.Random(i), data).angle
              for i in range(60)}
    assert "full-week" in picked


def test_full_week_hook_rule(cfg):
    aldi = stores.by_id(cfg, "aldi")
    facts = writer.Facts(total_gbp=23.4, max_serving_gbp=1.6, max_time=30)
    theme = themes.Theme("cheesy", "cheesy dinners", "full-week", "a full week", [], set())
    rules = writer._rules(facts, cfg, aldi, theme)
    assert "A full week of" in rules and "least 24" in rules
    assert 'start with "5 Aldi"' in writer._rules(facts, cfg, aldi)
