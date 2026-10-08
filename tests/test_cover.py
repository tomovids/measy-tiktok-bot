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


def test_runs_skip_joiners():
    assert cover._runs("Hi 😮‍💨") == [("text", "Hi "), ("emoji", "😮"), ("emoji", "💨")]
