from PIL import Image

from measybot import cover


def test_crop_portrait():
    img = cover.crop_portrait(Image.new("RGB", (1024, 1536), "red"))
    assert img.size == (1080, 1920)
    wide = cover.crop_portrait(Image.new("RGB", (1536, 1024), "red"))
    assert wide.size == (1080, 1920)


def test_render_size_and_box(cfg):
    bg = Image.new("RGB", (1080, 1920), (40, 80, 160))
    img = cover.render(bg, "5 Aldi Dinners I'd Make on Repeat 😋", "Big flavour, tiny budget 👀", cfg)
    assert img.size == (1080, 1920) and img.mode == "RGB"
    # the white caption box is drawn around the middle
    y = int(1920 * cfg["cover"]["text_y"])
    row = [img.getpixel((x, y - 60)) for x in range(0, 1080, 4)]
    assert any(p == (255, 255, 255) for p in row)


def test_long_hook_fits(cfg):
    c = cfg["cover"]
    hook = "5 Aldi Dinners for When You're Too Tired to Cook but Too Broke for Takeaway 😭"
    style, lines = cover.fit(hook, c["hook_font"], c["emoji_font"], c["hook_size"],
                             1080 * c["max_width"], 3)
    assert len(lines) <= 3
    assert max(style.width(l) for l in lines) + 2 * style.pad_x <= 1080 * c["max_width"]


def test_emoji_drawn_in_colour(cfg):
    glyph = cover._emoji(cfg["cover"]["emoji_font"], "😭", 64)
    colours = {glyph.getpixel((x, y))[:3] for x in range(glyph.width) for y in range(glyph.height)
               if glyph.getpixel((x, y))[3] > 200}
    assert any(abs(r - g) > 40 or abs(g - b) > 40 for r, g, b in colours)


def test_pick_scene_is_sky_and_angle(cfg):
    import random
    skies = [s["text"] for s in cfg["cover"]["skies"]]
    for seed in range(20):
        scene = cover.pick_scene(cfg, random.Random(seed))
        assert any(scene.startswith(s) for s in skies)
        assert any(scene.endswith(a) for a in cfg["cover"]["angles"])


def test_find_sign_ignores_small_warm_lights():
    from PIL import ImageDraw
    img = Image.new("RGB", (1080, 1920), (90, 100, 110))
    d = ImageDraw.Draw(img)
    d.rectangle([300, 400, 700, 800], fill=(255, 200, 0))      # sign border
    d.rectangle([340, 440, 660, 760], fill=(0, 40, 140))       # blue middle
    d.rectangle([100, 1300, 160, 1330], fill=(255, 190, 40))   # a warm window light lower down
    top, bottom = cover.find_sign(img)
    assert abs(top - 400) <= 16 and abs(bottom - 800) <= 16
    assert cover.find_sign(Image.new("RGB", (1080, 1920), (90, 100, 110))) is None


def test_place_moves_the_caption_off_the_sign():
    assert cover.place(800, 300, None) == 800
    assert cover.place(800, 300, (100, 500)) == 800             # no overlap: stays
    assert cover.place(800, 300, (500, 900)) == 900 + 28        # overlap: goes below
    assert cover.place(800, 300, (700, 1300)) == 700 - 28 - 300  # no room below: goes above


def test_runs_skip_joiners():
    assert cover._runs("Hi 😮‍💨") == [("text", "Hi "), ("emoji", "😮"), ("emoji", "💨")]


def test_lines_are_balanced_and_emoji_never_alone(cfg):
    c = cfg["cover"]
    style, lines = cover.fit("5 Aldi Dinners for a Friday Night In 😏🍗", c["hook_font"], c["emoji_font"],
                             c["hook_size"], 1080 * c["max_width"], 3)
    assert len(lines) == 2 and lines[1] != "In 😏🍗"
    widths = [style.width(l) for l in lines]
    assert max(widths) - min(widths) < 0.35 * max(widths)
    for l in lines:
        assert not all(cover.is_emoji(ch) or ch.isspace() for ch in l)


def test_find_sign_per_store_colour():
    from PIL import ImageDraw
    img = Image.new("RGB", (1080, 1920), (200, 205, 210))
    ImageDraw.Draw(img).rectangle([200, 500, 900, 760], fill=(110, 190, 60))   # green ASDA letters
    top, bottom = cover.find_sign(img, "asda")
    assert abs(top - 500) <= 16 and abs(bottom - 760) <= 16
    assert cover.find_sign(img, "aldi") is None
