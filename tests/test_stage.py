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
