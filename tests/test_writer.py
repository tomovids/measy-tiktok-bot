import random

from measybot import writer
from measybot.catalogue import Recipe
from measybot.openai_api import OpenAIError
from measybot.writer import Facts, Words, claim_problems, facts_for, problems


def recipe(i, total=None, per=None, serves=4, mins=None, currency="GBP"):
    return Recipe(f"{i:03d}_x.webp", f"Dish number {i}", f"dish-{i}", "chicken", "rice",
                  currency, total, per, serves, mins)


FIVE_PRICED = [recipe(i, total=2.5, mins=20 + i) for i in range(5)]  # £12.50, slowest 24 min


def test_facts():
    f = facts_for(FIVE_PRICED)
    assert f.total_gbp == 12.5 and f.max_time == 24 and f.max_serving_gbp == 0.62
    mixed = FIVE_PRICED[:4] + [recipe(9)]
    assert facts_for(mixed) == Facts(None, None, None)
    per = facts_for([recipe(i, per=1.5, serves=4) for i in range(5)])
    assert per.total_gbp == 30.0 and per.max_serving_gbp == 1.5


def test_money_claims():
    f = facts_for(FIVE_PRICED)
    assert claim_problems("5 Aldi Dinners for Under £15 😭", f) == []
    assert claim_problems("5 Aldi Meals I'd Make If I Had £13 Until Payday 😭", f) == []
    assert claim_problems("5 Aldi Dinners for Under £10 😭", f)
    assert claim_problems("Aldi dinners for under £1 a portion", f) == []
    assert claim_problems("Aldi dinners for under 50p", f)
    assert claim_problems("5 Aldi Dinners for Under £15 😭", Facts(None, None, None))


def test_time_and_count_claims():
    f = facts_for(FIVE_PRICED)
    assert claim_problems("5 LAZY Aldi dinners ready in 25 minutes or less ⏰", f) == []
    assert claim_problems("5 LAZY Aldi dinners ready in 20 minutes or less ⏰", f)
    assert claim_problems("3 Aldi Dinners to Make This Week 🛒", f)
    assert claim_problems("5 Meals. 1 Basket. Just £13 😳", f) == []


def test_problems(cfg):
    f = facts_for(FIVE_PRICED)
    ok = Words("5 Aldi Dinners I'd Make on Repeat 😋", "", "Saving these 👇", "sunny", "ai")
    assert problems(ok, f, [], cfg) == []
    assert problems(Words("5 Dinners I'd Make on Repeat 😋", "", "", "", "ai"), f, [], cfg)
    assert problems(Words("5 Aldi Dinners I'd Make on Repeat", "", "", "", "ai"), f, [], cfg)
    zwj = Words("5 Aldi Dinners That Feel Like Takeaway 😮‍💨", "", "", "", "ai")
    assert any("emoji" in p for p in problems(zwj, f, [], cfg))
    assert problems(ok, f, ["5 aldi dinners I'd make on repeat 😋"], cfg)
    long = Words("5 Aldi Dinners " + "really " * 12 + "😋", "", "", "", "ai")
    assert problems(long, f, [], cfg)


class StubClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def chat_json(self, model, system, user):
        self.prompts.append(user)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def test_write_retries_until_valid(cfg):
    bad = {"hook": "3 Aldi Dinners Under £5 😭", "subline": "", "intro": "x"}
    good = {"hook": "5 Aldi Dinners Better Than a Takeaway 🍔", "subline": "",
            "intro": "Which one first? 👀"}
    client = StubClient([bad, good])
    w = writer.write(FIVE_PRICED, [], cfg, client, random.Random(1), log=lambda m: None)
    assert w.source == "ai" and w.hook == good["hook"] and w.intro == good["intro"]
    assert "had these problems" in client.prompts[1]


def test_prompt_states_the_rules(cfg):
    client = StubClient([{"hook": "5 Aldi Dinners Better Than a Takeaway 🍔", "subline": "",
                          "intro": "Go on 👀", "scene": "dusk"}])
    writer.write(FIVE_PRICED, ["Old hook 😭"], cfg, client, random.Random(1), log=lambda m: None)
    prompt = client.prompts[0]
    assert "£13" in prompt and "24 minutes" in prompt and "Old hook" in prompt
    unpriced = StubClient([{"hook": "5 Aldi Dinners Better Than a Takeaway 🍔", "subline": "",
                            "intro": "Go on 👀", "scene": "dusk"}])
    writer.write([recipe(i) for i in range(5)], [], cfg, unpriced, random.Random(1), log=lambda m: None)
    assert "Do NOT mention any prices" in unpriced.prompts[0]


def test_falls_back_when_openai_fails(cfg):
    client = StubClient([OpenAIError("down", 503)])
    unpriced = [recipe(i) for i in range(5)]
    for seed in range(20):
        client.answers = [OpenAIError("down", 503)]
        w = writer.write(unpriced, [], cfg, client, random.Random(seed), log=lambda m: None)
        assert w.source == "fallback"
        assert "£" not in w.hook + w.subline and "minute" not in w.hook.lower()
        assert problems(w, facts_for(unpriced), [], cfg) == []


def test_fallback_list_is_valid(cfg):
    allowed = set(cfg["words"]["emoji"])
    for hook, sub in writer.load_fallbacks():
        assert "aldi" in hook.lower()
        assert all(c in allowed for c in hook + sub if writer.is_emoji(c)), hook


def test_caption(cfg):
    w = Words("5 Aldi Dinners 😋", "", "Saving these 👇", "sunny", "ai")
    text = writer.caption(w, FIVE_PRICED, cfg)
    assert text.startswith("Saving these 👇\n\n1. Dish number 0")
    assert "5. Dish number 4" in text and "#aldi" in text and cfg["caption"]["cta"] in text


def test_prompt_knows_the_weekday(cfg):
    from datetime import date
    client = StubClient([{"hook": "5 Aldi Dinners Better Than a Takeaway 🍔", "subline": "", "intro": "Go 👀"}])
    writer.write(FIVE_PRICED, [], cfg, client, random.Random(1), log=lambda m: None, day=date(2026, 10, 9))
    assert "Friday morning" in client.prompts[0]
