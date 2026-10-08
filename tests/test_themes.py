import random
from datetime import date, timedelta

from measybot import tags, themes
from measybot.history import SENT, History

FRIDAY = date(2026, 10, 9)


def dish_tags():
    return tags.all_tags()


def test_every_collection_has_enough_dishes():
    t = dish_tags()
    for c in themes.load()["collections"]:
        n = sum(1 for tg in t.values() if themes.fits(tg, c))
        assert n >= themes.MIN_DISHES, (c["id"], n)


def test_day_limited_angles():
    data = themes.load()
    friday = {a["id"] for a in data["angles"] if themes.angle_allowed(a, FRIDAY, "morning")}
    monday = {a["id"] for a in data["angles"] if themes.angle_allowed(a, FRIDAY + timedelta(days=3), "morning")}
    assert "friday" in friday and "friday" not in monday and "monday" in monday
    assert "tonight" not in friday  # afternoon only


def test_collection_rests_and_angles_vary(cfg):
    t = dish_tags()
    hist = History()
    seen = []
    for i in range(12):
        day = FRIDAY + timedelta(days=i // 2)
        slot = "morning" if i % 2 == 0 else "afternoon"
        th = themes.choose(day, slot, hist, t, cfg, random.Random(i))
        seen.append((day, th.collection, th.angle))
        hist.add({"date": day.isoformat(), "files": [], "groups": [], "status": SENT,
                  "theme": th.record(), "sent_at": f"{day}T{i:02d}"})
    for i, (d, c, a) in enumerate(seen):
        for d2, c2, a2 in seen[:i]:
            if c2 == c:
                assert (d - d2).days >= cfg["picker"]["collection_gap_days"] or c == "anything"
        assert a not in [x[2] for x in seen[max(0, i - 3):i]]


def test_protein_theme_lifts_the_protein_cap(cfg):
    data = themes.load()
    data = dict(data, collections=[c for c in data["collections"] if c["id"] == "chicken"])
    th = themes.choose(FRIDAY, "morning", History(), dish_tags(), cfg, random.Random(1), data=data)
    assert th.collection == "chicken" and "protein" in th.caps_off


def test_count_on_ignores_extra_drafts():
    h = History([{"date": "2026-10-09", "status": SENT, "files": [], "groups": []},
                 {"date": "2026-10-09", "status": SENT, "files": [], "groups": [], "extra": True},
                 {"date": "2026-10-09", "status": "FAILED", "files": [], "groups": []}])
    assert h.count_on(FRIDAY) == 1
