import random
from datetime import date

import pytest

from measybot import config, stage, stores
from measybot.catalogue import load_recipes
from measybot.history import SENT, History
from measybot.picker import pick


@pytest.fixture
def restore_account():
    yield
    config.use_account(config.accounts({})[0])


def test_first_account_keeps_the_old_paths(cfg, restore_account):
    accts = config.accounts(cfg)
    assert [a.id for a in accts][:2] == ["measy", "mealswithmeasy"]
    config.use_account(accts[0])
    assert config.HISTORY_FILE == config.STATE / "history.json"
    assert config.TOKEN_FILE == config.STATE / "tiktok_token.enc"
    assert stage.post_folder(date(2026, 10, 9), name="2026-10-09-1") == config.SITE / "p" / "2026-10-09-1"


def test_second_account_has_its_own_files(cfg, restore_account):
    acct = config.get_account(cfg, "@mealswithmeasy")
    config.use_account(acct)
    assert config.HISTORY_FILE == config.STATE / "mealswithmeasy" / "history.json"
    assert config.TOKEN_FILE == config.STATE / "mealswithmeasy" / "tiktok_token.enc"
    assert config.STATS_FILE.parent == config.STATE / "mealswithmeasy"
    folder = stage.post_folder(date(2026, 10, 9), name="2026-10-09-1")
    assert folder == config.SITE / "p" / "mealswithmeasy" / "2026-10-09-1"


def test_account_settings(cfg):
    acfg = config.account_cfg(cfg, config.get_account(cfg, "ethaniscookingdaily"))
    assert acfg["schedule"]["post_times"] == ["11:00", "19:00"]
    assert acfg["store_rotation"]["plan"] == ["rotate", "rotate"]
    assert {s.id for s in stores.load(acfg)} == {"tesco", "sainsburys", "asda", "lidl"}
    assert acfg["account"]["primary"] is False
    # the first account is unchanged
    main = config.account_cfg(cfg, config.get_account(cfg, None))
    assert main["schedule"]["post_times"] == cfg["schedule"]["post_times"]
    assert len(stores.load(main)) == len(stores.load(cfg))


def test_unknown_account(cfg):
    with pytest.raises(config.ConfigError):
        config.get_account(cfg, "nobody")


def test_uk_tester_account_never_uses_aldi(cfg):
    acfg = config.account_cfg(cfg, config.get_account(cfg, "ethaniscookingdaily"))
    hist = History()
    seen = set()
    for i in range(8):
        s = stores.choose(hist, acfg, random.Random(i), i % 2)
        seen.add(s.id)
        hist.add({"date": f"2026-10-{10 + i // 2:02d}", "store": s.id, "status": SENT})
    assert "aldi" not in seen
    assert seen == {"tesco", "sainsburys", "asda", "lidl"}


def test_avoids_the_other_accounts_dishes(cfg):
    recipes = load_recipes()
    day = date(2026, 10, 9)
    first = pick(recipes, History(), day, cfg, random.Random(1))
    avoid = {r.group for r in first}
    second = pick(recipes, History(), day, cfg, random.Random(1), avoid=avoid)
    assert not avoid & {r.group for r in second}


def test_us_account(cfg):
    acfg = config.account_cfg(cfg, config.get_account(cfg, "mealswithmeasy"))
    assert acfg["region"]["id"] == "us" and acfg["region"]["currency"] == "$"
    assert acfg["schedule"]["timezone"] == "America/New_York"
    assert [s.id for s in stores.load(acfg)] == ["walmart", "aldius", "traderjoes"]
    assert "#ukfood" not in acfg["caption"]["hashtags"]
    assert "parking lot" in acfg["cover"]["prompt"]
    # UK accounts never see the US stores
    for a in ("measy", "ethaniscookingdaily"):
        ids = {s.id for s in stores.load(config.account_cfg(cfg, config.get_account(cfg, a)))}
        assert not ids & {"walmart", "aldius", "traderjoes"}


def test_dollar_claims(cfg):
    from measybot import writer
    acfg = config.account_cfg(cfg, config.get_account(cfg, "mealswithmeasy"))
    facts = writer.Facts(total_gbp=31.2, max_serving_gbp=2.4, max_time=25)
    assert writer.claim_problems("5 dinners for under $35", facts, "$") == []
    assert writer.claim_problems("5 dinners for under $20", facts, "$")
    assert writer.claim_problems("5 dinners for under £35", facts, "$")    # wrong currency
    assert writer.claim_problems("only 99 cents", facts, "$")
    assert writer.load_fallbacks(region="us")
    w = writer.fallback(facts, [], acfg, random.Random(1), store=stores.load(acfg)[0])
    assert "Walmart" in w.hook and "takeaway" not in w.hook.lower()


def test_yesterdays_dishes_elsewhere_are_only_avoided_when_possible(cfg):
    recipes = load_recipes()
    groups = {r.group for r in recipes}
    # the other accounts used every dish yesterday: still five dishes
    picks = pick(recipes, History(), date(2026, 10, 9), cfg, random.Random(2), avoid=dict.fromkeys(groups, 1))
    assert len({r.group for r in picks}) == 5
    # ...and all of them today: their posts are ignored rather than failing
    picks = pick(recipes, History(), date(2026, 10, 9), cfg, random.Random(2), avoid=dict.fromkeys(groups, 0))
    assert len({r.group for r in picks}) == 5


def test_one_dashboard_for_every_account(cfg):
    from measybot import dashboard
    data = dashboard.build_all(cfg)
    assert [a["id"] for a in data["accounts"]] == ["measy", "mealswithmeasy", "ethaniscookingdaily"]
    us = data["accounts"][1]
    assert us["currency"] == "$" and us["region"] == "us"
    assert "ET" in us["drafts"]["next"]
    assert config.HISTORY_FILE == config.STATE / "history.json"      # back on the first account


def test_us_cards_show_dollars(cfg, restore_account):
    from measybot import card, library
    config.use_account(config.get_account(cfg, "mealswithmeasy"))
    lib = library.load()
    assert len(lib) == len(library.load("uk"))
    assert card.money(1.5) == "$1.50"
    config.use_account(config.get_account(cfg, None))
    assert card.money(1.5) == "£1.50"


def test_waits_after_tiktok_inbox_is_full():
    from datetime import datetime, timezone
    from measybot.__main__ import inbox_full_wait
    hist = History()
    hist.add({"date": "2026-10-09", "status": "FAILED", "sent_at": "2026-10-09T14:30:09+00:00",
              "error": "TikTok error spam_risk_too_many_pending_share: ..."})
    assert inbox_full_wait(hist, datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)) == 90
    assert inbox_full_wait(hist, datetime(2026, 10, 9, 16, 31, tzinfo=timezone.utc)) == 0
    hist.add({"date": "2026-10-09", "status": "FAILED", "sent_at": "2026-10-09T15:00:00+00:00", "error": "other"})
    assert inbox_full_wait(hist, datetime(2026, 10, 9, 15, 1, tzinfo=timezone.utc)) == 0
