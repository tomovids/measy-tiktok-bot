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
    acfg = config.account_cfg(cfg, config.get_account(cfg, "mealswithmeasy"))
    assert acfg["schedule"]["post_times"] == ["09:30", "14:30"]
    assert acfg["store_rotation"]["plan"] == ["rotate", "rotate"]
    assert {s.id for s in stores.load(acfg)} == {"tesco", "sainsburys", "asda", "lidl"}
    assert acfg["tracking"]["dashboard_dir"] != cfg["tracking"]["dashboard_dir"]
    assert acfg["account"]["primary"] is False
    # the first account is unchanged
    main = config.account_cfg(cfg, config.get_account(cfg, None))
    assert main["schedule"]["post_times"] == cfg["schedule"]["post_times"]
    assert len(stores.load(main)) == len(stores.load(cfg))


def test_unknown_account(cfg):
    with pytest.raises(config.ConfigError):
        config.get_account(cfg, "nobody")


def test_second_account_never_uses_aldi(cfg):
    acfg = config.account_cfg(cfg, config.get_account(cfg, "mealswithmeasy"))
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


def test_accounts_start_on_different_stores(cfg):
    firsts = []
    for acct_id in ("mealswithmeasy", "ethaniscookingdaily"):
        acfg = config.account_cfg(cfg, config.get_account(cfg, acct_id))
        hist = History()
        day = []
        for i in range(2):
            s = stores.choose(hist, acfg, random.Random(i), i)
            day.append(s.id)
            hist.add({"date": "2026-10-10", "store": s.id, "status": SENT})
        firsts.append(set(day))
    assert not firsts[0] & firsts[1]


def test_yesterdays_dishes_elsewhere_are_only_avoided_when_possible(cfg):
    recipes = load_recipes()
    groups = {r.group for r in recipes}
    # the other accounts used every dish yesterday: still five dishes
    picks = pick(recipes, History(), date(2026, 10, 9), cfg, random.Random(2), avoid=dict.fromkeys(groups, 1))
    assert len({r.group for r in picks}) == 5
    # ...and all of them today: their posts are ignored rather than failing
    picks = pick(recipes, History(), date(2026, 10, 9), cfg, random.Random(2), avoid=dict.fromkeys(groups, 0))
    assert len({r.group for r in picks}) == 5
