import json
from datetime import date

from PIL import Image

from measybot import stage
from measybot.catalogue import Recipe
from measybot.writer import Words


def make(path, size, fmt):
    Image.new("RGB", size, "orange").save(path, fmt)
    return path


def test_stage_post(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr("measybot.config.RECIPE_DIR", src)
    make(src / "a.webp", (941, 1672), "WEBP")
    make(src / "b.webp", (1086, 1448), "WEBP")   # too wide for TikTok: must be resized
    make(src / "c.png", (900, 1600), "PNG")      # PNG isn't accepted: must be converted
    make(src / "d.webp", (941, 1672), "WEBP")
    make(src / "e.webp", (941, 1672), "WEBP")
    promo = make(tmp_path / "promo.webp", (1086, 1448), "WEBP")
    recipes = [Recipe(f, f"Dish {f}", f"g-{f}", "beef", "rice", "GBP", 3.0, None, 4, 20)
               for f in ("a.webp", "b.webp", "c.png", "d.webp", "e.webp")]
    folder = tmp_path / "site" / "p" / "2026-10-09"
    words = Words("5 Aldi Dinners 😋", "", "intro", "scene", "ai")
    post = stage.stage(folder, date(2026, 10, 9), Image.new("RGB", (1080, 1920)), recipes, promo,
                       words, "caption text", {"background": "generated"})

    assert post["slides"][0] == "p/2026-10-09/01.jpg"
    assert post["slides"][1] == "p/2026-10-09/02.webp"
    assert post["slides"][2] == "p/2026-10-09/03.jpg"
    assert post["slides"][3] == "p/2026-10-09/04.jpg"
    assert len(post["slides"]) == 7
    for s in post["slides"]:
        p = tmp_path / "site" / s
        assert stage.slide_ok(p), s
    saved = json.loads((folder / "post.json").read_text(encoding="utf-8"))
    assert saved["files"] == [r.file for r in recipes] and saved["promo"] == "promo.webp"
    assert (folder / "caption.txt").read_text(encoding="utf-8").strip() == "caption text"

    # with this post's shop slide: it goes before the app promo, which stays the last slide
    post = stage.stage(folder, date(2026, 10, 9), Image.new("RGB", (1080, 1920)), recipes, promo,
                       words, "caption text", {}, shop=Image.new("RGB", (1080, 1920), (10, 120, 60)))
    assert len(post["slides"]) == 8 and post["promo"] == "promo.webp" and post["shop_slide"]
    last = Image.open(tmp_path / "site" / post["slides"][-1])
    assert abs(last.width / last.height - 1086 / 1448) < 0.02          # the promo, not the shop slide


def test_title_fits_tiktok_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("measybot.config.RECIPE_DIR", tmp_path)
    recipes = []
    for i in range(5):
        make(tmp_path / f"{i}.webp", (500, 900), "WEBP")
        recipes.append(Recipe(f"{i}.webp", "d", f"g{i}", "beef", "rice", "GBP", 1, None, 1, 1))
    words = Words("😋" * 60, "", "", "", "ai")
    post = stage.stage(tmp_path / "out" / "p" / "x", date(2026, 1, 1), Image.new("RGB", (10, 10)),
                       recipes, tmp_path / "0.webp", words, "c", {})
    assert stage.utf16_len(post["title"]) <= 90


def test_promo_must_be_the_last_slide(tmp_path):
    promo = tmp_path / "promo.webp"
    im = Image.new("RGB", (1086, 1448), (250, 250, 245))
    for x in range(0, 1086, 120):          # some detail, so it isn't mistaken for any plain slide
        im.paste((40, 140, 60), (x, 0, x + 60, 700))
    im.save(promo, "WEBP")
    site = tmp_path / "site"
    (site / "p").mkdir(parents=True)
    im.convert("RGB").resize((810, 1080)).save(site / "p" / "08.jpg", "JPEG")          # a resized copy
    Image.new("RGB", (1080, 1920), (10, 120, 60)).save(site / "p" / "07.jpg", "JPEG")   # the shop slide
    ok = {"slides": ["p/07.jpg", "p/08.jpg"]}
    assert stage.promo_problem(ok, site=site, promos=[promo]) is None
    bad = {"slides": ["p/08.jpg", "p/07.jpg"]}
    assert "isn't the app promo" in stage.promo_problem(bad, site=site, promos=[promo])
    assert "missing" in stage.promo_problem({"slides": ["p/09.jpg"]}, site=site, promos=[promo])


def test_send_refuses_a_post_without_the_promo(tmp_path, monkeypatch):
    import pytest
    from measybot import pipeline
    from measybot.history import History
    from measybot.tiktok import TikTokError
    monkeypatch.setattr(stage, "promo_problem", lambda post: "its last slide (07.jpg) isn't the app promo")
    called = []
    hist = History([])
    hist.path = None
    with pytest.raises(TikTokError, match="Not sent"):
        pipeline.send_post({"slides": ["p/07.jpg"], "title": "t", "caption": "c"},
                           {"tiktok": {"pages_base_url": "https://x"}}, hist, None, "key",
                           log=lambda *_: None, wait_pages=lambda *a, **k: called.append(1))
    assert not called and hist.posts == []
