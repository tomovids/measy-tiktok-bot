import random

from measybot import stores, writer
from measybot.catalogue import Recipe
from measybot.history import SENT, History
from measybot.writer import Words, facts_for, problems

FIVE = [Recipe(f"{i}.webp", f"Dish {i}", f"dish-{i}", "chicken", "rice", "GBP", 2.5, None, 4, 20 + i)
        for i in range(5)]


def test_plan_two_aldi_one_tester(cfg):
    h = History()
    assert stores.choose(h, cfg, random.Random(1), 0).id == "aldi"
    assert stores.choose(h, cfg, random.Random(1), 2).id == "aldi"
    assert stores.choose(h, cfg, random.Random(1), 1).id in {"tesco", "sainsburys", "asda", "lidl"}


def test_tester_stores_take_turns(cfg):
    h = History()
    seen = []
    for i in range(8):
        s = stores.choose(h, cfg, random.Random(i), 1)
        seen.append(s.id)
        h.add({"date": f"2026-10-{10 + i}", "store": s.id, "status": SENT, "files": [], "groups": []})
    assert sorted(seen[:4]) == ["asda", "lidl", "sainsburys", "tesco"]
    assert sorted(seen[4:]) == ["asda", "lidl", "sainsburys", "tesco"]


def test_tesco_post_rules(cfg):
    tesco = stores.by_id(cfg, "tesco")
    f = facts_for(FIVE)
    ok = Words("5 Tesco Dinners Better Than a Takeaway 🍔", "", "intro", source="ai")
    assert problems(ok, f, [], cfg, store=tesco) == []
    aldi_hook = Words("5 Aldi Dinners Better Than a Takeaway 🍔", "", "intro", source="ai")
    assert any("mention Tesco" in p for p in problems(aldi_hook, f, [], cfg, store=tesco))
    knock = Words("5 Tesco Dinners Cheaper Than Aldi 😏", "", "intro", source="ai")
    assert any("aldi" in p for p in problems(knock, f, [], cfg, store=tesco))
    # an Aldi post may of course say Aldi, and still can't name Tesco
    assert problems(aldi_hook, f, [], cfg) == []
    assert any("tesco" in p for p in problems(Words("5 Aldi Dinners Cheaper Than Tesco 😏", "", "i", source="ai"),
                                              f, [], cfg))


def test_no_price_claims_off_aldi(cfg):
    class Stub:
        def __init__(self):
            self.prompts = []

        def chat_json(self, model, system, user):
            self.prompts.append(user)
            return {"candidates": [{"hook": "5 Tesco Dinners Under £13 😳", "subline": ""},
                                   {"hook": "5 Tesco Dinners Ready in 25 Minutes ⏰", "subline": ""}],
                    "intro": "Go on 👀", "question": "Which one first? 👇"}
    tesco = stores.by_id(cfg, "tesco")
    client = Stub()
    w = writer.write(FIVE, [], cfg, client, random.Random(1), log=lambda m: None, store=tesco)
    assert w.hook == "5 Tesco Dinners Ready in 25 Minutes ⏰"
    assert "Do NOT mention any prices" in client.prompts[0]


def test_caption_uses_store_hashtags_and_save_line(cfg):
    lidl = stores.by_id(cfg, "lidl")
    w = Words("5 Lidl Dinners 😋", "", "intro 👇", source="ai", question="Which one? 👇")
    text = writer.caption(w, FIVE, cfg, store=lidl, rng=random.Random(0))
    assert "#lidl" in text and "#aldi" not in text and "#measy" in text
    assert "Aldi" not in text
