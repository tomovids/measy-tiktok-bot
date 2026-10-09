import random
from datetime import datetime, timedelta, timezone

from measybot import dashboard, stats, themes, tuning
from measybot.history import SENT, History
from measybot.tiktok import TikTok
from tests.conftest import FakeResponse, FakeSession

NOW = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
OK = {"code": "ok", "message": "", "log_id": ""}


def bot_post(i, store="aldi", collection="cheesy", angle="payday", groups=("dish-a", "dish-b")):
    return {"date": (NOW - timedelta(days=30 - i)).date().isoformat(), "sent_at": f"x{i:03d}",
            "hook": f"5 Aldi Dinners Number {i} You Need 😋", "store": store, "slot": "morning",
            "theme": {"collection": collection, "angle": angle}, "groups": list(groups),
            "publish_id": f"p{i}", "status": SENT}


def video(i, views, days_old, title=None):
    created = NOW - timedelta(days=days_old)
    return {"id": f"v{i}", "create_time": int(created.timestamp()), "title": title or f"5 Aldi Dinners Number {i} You Need 😋",
            "video_description": "caption", "view_count": views, "like_count": views // 10,
            "comment_count": views // 100, "share_count": views // 50, "share_url": f"https://tiktok.com/v{i}"}


def test_matching_and_snapshots():
    hist = History([bot_post(1), bot_post(2)])
    st = stats.update(stats.load_empty() if hasattr(stats, "load_empty") else {"account": [], "videos": {}},
                      {"follower_count": 1000, "likes_count": 5000, "video_count": 3},
                      [video(1, 900, 5), video(2, 400, 1), video(99, 50, 400, title="An old video")], hist, now=NOW)
    assert st["videos"]["v1"]["post"]["hook"].endswith("Number 1 You Need 😋")
    assert st["videos"]["v2"]["post"]["collection"] == "cheesy"
    assert st["videos"]["v99"].get("post") is None
    assert st["account"][-1]["followers"] == 1000 and st["account"][-1]["total_views"] == 1350


def test_views_at_three_days_is_interpolated():
    rec = {"snapshots": [{"age_h": 48, "views": 100}, {"age_h": 96, "views": 300}],
           "latest": {"age_h": 96, "views": 300}}
    assert stats.views_at(rec) == 200
    young = {"snapshots": [{"age_h": 20, "views": 50}], "latest": {"age_h": 20, "views": 50}}
    assert stats.views_at(young) is None


def make_stats(n=20):
    st = {"account": [], "videos": {}}
    posts = []
    for i in range(n):
        coll = "cheesy" if i % 2 == 0 else "pasta"
        posts.append(bot_post(i, collection=coll))
    hist = History(posts)
    vids = [video(i, 3000 if i % 2 == 0 else 1000, 30 - i) for i in range(n)]
    # three snapshots per post: at 1, 3 and 5 days old
    for age in (1, 3, 5):
        st = stats.update(st, {"follower_count": 1000 + age}, [
            {**v, "view_count": v["view_count"] * age // 5} for v in vids], hist,
            now=NOW - timedelta(days=5 - age))
    st = stats.update(st, {"follower_count": 1200}, vids, hist, now=NOW)
    return st


def test_tuning_doubles_down_on_winners(cfg):
    st = make_stats()
    t = tuning.compute(st, cfg)
    assert t["active"] and t["scored_posts"] >= cfg["tracking"]["min_posts"]
    cheesy = t["multipliers"]["collection"]["cheesy"]["mult"]
    pasta = t["multipliers"]["collection"]["pasta"]["mult"]
    assert cheesy > 1.0 > pasta and cfg["tracking"]["min_mult"] <= pasta and cheesy <= cfg["tracking"]["max_mult"]
    # the posts were already past 3 days at their first reading, so that reading counts:
    # 3000 x 1/5 = 600 for the winners vs 200 for the others; the best hooks are all winners
    assert t["top_hooks"] and all(h["views"] == 600 for h in t["top_hooks"])


def test_tuning_waits_for_enough_data(cfg):
    st = make_stats(6)
    assert not tuning.compute(st, cfg)["active"]
    assert tuning.for_post(random.Random(1), {"active": False}) == {}


def test_boost_changes_theme_odds(cfg):
    from measybot import tags
    t = tags.all_tags()
    picks = {"cheesy": 0, "other": 0}
    boost = {"collection": {"cheesy": 2.0}}
    for seed in range(300):
        th = themes.choose(NOW.date(), "morning", History(), t, cfg, random.Random(seed), boost=boost)
        picks["cheesy" if th.collection == "cheesy" else "other"] += 1
    plain = sum(themes.choose(NOW.date(), "morning", History(), t, cfg, random.Random(s)).collection == "cheesy"
                for s in range(300))
    assert picks["cheesy"] > plain


def test_dashboard_data(cfg):
    st = make_stats()
    data = dashboard.build(st, tuning.compute(st, cfg), cfg)
    assert data["kpis"]["followers"] == 1200 and data["kpis"]["posts_tracked"] == 20
    top = data["tables"]["collection"][0]
    assert top["name"] == "cheesy" and top["avg_ratio"] > 1
    assert data["double_down"]["collection"][0]["name"] == "cheesy"
    assert data["top_posts"][0]["views"] == 3000


def test_tiktok_video_list_paginates():
    s = FakeSession([
        FakeResponse(200, {"data": {"videos": [{"id": "1"}], "has_more": True, "cursor": 123}, "error": OK}),
        FakeResponse(200, {"data": {"videos": [{"id": "2"}], "has_more": False}, "error": OK}),
    ])
    tt = TikTok("k", "s", session=s)
    assert [v["id"] for v in tt.videos("tok")] == ["1", "2"]
    assert s.calls[1][2]["json"]["cursor"] == 123
