"""The cover slide: an AI storefront photo with the hook in TikTok-style white caption boxes."""
from __future__ import annotations

import io
import random
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config
from .openai_api import OpenAI
from .writer import is_emoji

W, H = 1080, 1920
SKIP = {0x200D, 0xFE0F, 0x20E3}   # joiners / variation selectors: not drawn on their own
SS = 4                            # supersampling for smooth box edges
BACKGROUND_POOL = 10              # backgrounds kept for days when image generation fails


# ---- backgrounds ------------------------------------------------------------------------------

def crop_portrait(img: Image.Image) -> Image.Image:
    """Centre-crops to 9:16 and resizes to 1080x1920."""
    img = img.convert("RGB")
    w, h = img.size
    target = W / H
    if w / h > target:
        nw = round(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = round(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return img.resize((W, H), Image.LANCZOS)


def pick_scene(cfg: dict, rng: random.Random) -> str:
    """One weighted sky + one camera angle for the cover photo."""
    c = cfg["cover"]
    sky = rng.choices([s["text"] for s in c["skies"]], weights=[s["weight"] for s in c["skies"]])[0]
    return f"{sky}, {rng.choice(c['angles'])}"


SIGN_COLOURS = {
    # Aldi's border and Lidl's circle are bright yellow; Asda's letters green; Tesco's red;
    # Sainsbury's orange.
    "yellow": lambda r, g, b: r > 200 and g > 120 and b < 70 and r - b > 160,
    "green": lambda r, g, b: g > 140 and r < 150 and b < 110 and g - r > 50 and g - b > 70,
    "red": lambda r, g, b: r > 170 and g < 70 and b < 80,
    "orange": lambda r, g, b: r > 210 and 80 < g < 170 and b < 70 and r - g > 60,
}
STORE_SIGN = {"aldi": "yellow", "lidl": "yellow", "asda": "green", "tesco": "red", "sainsburys": "orange",
              "aldius": "yellow", "walmart": "yellow", "traderjoes": "red"}   # Walmart: its yellow spark


def find_sign(img: Image.Image, store: str = "aldi") -> tuple[int, int] | None:
    """Top and bottom (in pixels) of the store's sign, found by the sign's colour.

    Looks for the biggest solid band of rows with sign-coloured pixels in the top 80% of the
    picture; warm shop-window lights lower down are smaller and get ignored.
    """
    match = SIGN_COLOURS[STORE_SIGN.get(store, "yellow")]
    small = img.convert("RGB").resize((270, 480))
    px = small.load()
    counts = []
    for y in range(int(480 * 0.8)):
        n = 0
        for x in range(270):
            if match(*px[x, y]):
                n += 1
        counts.append(n)
    runs, start, gap, total = [], None, 0, 0
    for y, n in enumerate(counts + [0] * 6):
        if n >= 3:
            if start is None:
                start, total = y, 0
            gap, total, end = 0, total + n, y
        elif start is not None:
            gap += 1
            if gap > 4:
                runs.append((total, start, end))
                start = None
    runs = [r for r in runs if r[2] - r[1] >= 10]   # at least ~40 px tall
    if not runs:
        return None
    _, top, bottom = max(runs)
    scale = img.height / 480
    return round(top * scale), round((bottom + 1) * scale)


def generate_background(client: OpenAI, scene: str, cfg: dict, store=None) -> tuple[Image.Image, str]:
    from .stores import default
    store = store or default()
    o = cfg["openai"]
    prompt = cfg["cover"]["prompt"].format(scene=scene, store=store.name, sign=store.sign)
    data, model = client.image(o["image_models"], prompt, o["image_size"], o["image_quality"])
    return crop_portrait(Image.open(io.BytesIO(data))), model


def _spares(folder: Path, store: str) -> list[Path]:
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.jpg"))
    # files named <store>-<date>.jpg; older ones named just <date>.jpg are Aldi store fronts
    return [p for p in files if p.stem.startswith(f"{store}-") or (store == "aldi" and p.stem[:1].isdigit())]


def keep_background(img: Image.Image, day: date, folder: Path | None = None, store: str = "aldi") -> Path | None:
    """Keeps the first few store fronts of each supermarket as spares for when image generation fails."""
    folder = folder or config.BACKGROUND_DIR
    folder.mkdir(parents=True, exist_ok=True)
    if len(_spares(folder, store)) >= BACKGROUND_POOL:
        return None
    path = folder / f"{store}-{day.isoformat()}.jpg"
    img.save(path, "JPEG", quality=88)
    return path


def spare_background(rng: random.Random, folder: Path | None = None, store: str = "aldi") -> Image.Image | None:
    spares = _spares(folder or config.BACKGROUND_DIR, store)
    return crop_portrait(Image.open(rng.choice(spares))) if spares else None


def placeholder_background(seed: str) -> Image.Image:
    """A plain stand-in (sky + shop front) for dry runs without an OpenAI key."""
    rng = random.Random(seed)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    top, bottom = (58, 132, 214), (186, 218, 245)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    for _ in range(5):
        x, y, r = rng.randint(0, W), rng.randint(80, 600), rng.randint(60, 140)
        d.ellipse([x - r * 2, y - r, x + r * 2, y + r], fill=(245, 248, 252))
    img = img.filter(ImageFilter.GaussianBlur(6))
    d = ImageDraw.Draw(img)
    d.rectangle([80, 520, 1000, 1500], fill=(120, 124, 130))
    d.rectangle([380, 600, 700, 920], fill=(255, 196, 0))
    d.rectangle([396, 616, 684, 904], fill=(224, 72, 32))
    d.rectangle([412, 632, 668, 888], fill=(0, 56, 160))
    d.rectangle([140, 1080, 940, 1500], fill=(60, 74, 88))
    d.rectangle([0, 1500, W, H], fill=(70, 72, 76))
    for x in range(60, W, 180):
        d.line([(x, 1620), (x + 120, 1900)], fill=(235, 235, 235), width=8)
    return img


# ---- text drawing -----------------------------------------------------------------------------

@lru_cache(maxsize=16)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(config.ROOT / path), size)


@lru_cache(maxsize=64)
def _emoji(path: str, ch: str, height: int) -> Image.Image:
    font = ImageFont.truetype(str(config.ROOT / path), 109)  # the only size the bitmap font has
    box = font.getbbox(ch)
    glyph = Image.new("RGBA", (max(1, box[2] - box[0]), max(1, box[3] - box[1])), (0, 0, 0, 0))
    ImageDraw.Draw(glyph).text((-box[0], -box[1]), ch, font=font, embedded_color=True)
    scale = height / glyph.height
    return glyph.resize((max(1, round(glyph.width * scale)), height), Image.LANCZOS)


def _runs(text: str) -> list[tuple[str, str]]:
    """Splits text into ("text", ...) and ("emoji", ch) runs."""
    runs: list[tuple[str, str]] = []
    for ch in text:
        if ord(ch) in SKIP:
            continue
        if is_emoji(ch):
            runs.append(("emoji", ch))
        elif runs and runs[-1][0] == "text":
            runs[-1] = ("text", runs[-1][1] + ch)
        else:
            runs.append(("text", ch))
    return runs


@dataclass
class Style:
    font: str
    emoji_font: str
    size: int

    @property
    def emoji_h(self) -> int:
        return round(self.size * 1.06)

    @property
    def line_h(self) -> int:
        return round(self.size * 1.42)

    @property
    def pad_x(self) -> int:
        return round(self.size * 0.42)

    @property
    def radius(self) -> int:
        return round(self.size * 0.3)

    def width(self, text: str) -> float:
        f = _font(self.font, self.size)
        total = 0.0
        for kind, val in _runs(text):
            total += (_emoji(self.emoji_font, val, self.emoji_h).width + self.size * 0.06
                      if kind == "emoji" else f.getlength(val))
        return total


def wrap(text: str, style: Style, max_w: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if not line or style.width(trial) <= max_w:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def balance(lines: list[str], style: Style, max_w: float) -> list[str]:
    """Same number of lines, but split so they're as even as possible (no emoji-only line)."""
    words = " ".join(lines).split()
    n = len(lines)
    if n < 2 or len(words) > 18:
        return lines
    best, best_w = lines, max(style.width(l) for l in lines)
    for cuts in combinations(range(1, len(words)), n - 1):
        bounds = (0, *cuts, len(words))
        trial = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
        if any(all(is_emoji(c) or c.isspace() for c in l) for l in trial):
            continue
        widest = max(style.width(l) for l in trial)
        if widest <= max_w and widest < best_w - 1:
            best, best_w = trial, widest
    return best


def fit(text: str, font: str, emoji_font: str, size: int, max_w: float, max_lines: int,
        min_size: int = 40) -> tuple[Style, list[str]]:
    """Largest size (down to min_size) at which the text wraps into max_lines within max_w."""
    while True:
        style = Style(font, emoji_font, size)
        lines = wrap(text, style, max_w - 2 * style.pad_x)
        lines = balance(lines, style, max_w - 2 * style.pad_x)
        widest = max(style.width(l) for l in lines) + 2 * style.pad_x
        if (len(lines) <= max_lines and widest <= max_w) or size <= min_size:
            return style, lines
        size -= 2


def _box_mask(lines: list[str], style: Style, cx: float, top: float) -> tuple[Image.Image, list]:
    """White joined boxes like TikTok's caption style, drawn at SS x size for smooth edges."""
    mask = Image.new("L", (W * SS, H * SS), 0)
    d = ImageDraw.Draw(mask)
    widths = [style.width(l) + 2 * style.pad_x for l in lines]
    for i in range(len(widths) - 1):  # nearly equal neighbours share one straight edge
        if abs(widths[i] - widths[i + 1]) < 2 * style.radius:
            widths[i] = widths[i + 1] = max(widths[i], widths[i + 1])
    rects = []
    for i, w in enumerate(widths):
        y0 = top + i * style.line_h
        rects.append((cx - w / 2, y0, cx + w / 2, y0 + style.line_h))
    r = style.radius * SS
    for i, (x0, y0, x1, y1) in enumerate(rects):
        above = widths[i - 1] if i > 0 else 0
        below = widths[i + 1] if i + 1 < len(widths) else 0
        round_top = widths[i] > above + 1
        round_bottom = widths[i] > below + 1
        d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=r, fill=255,
                            corners=(round_top, round_top, round_bottom, round_bottom))
    # concave fillets where a wider line overhangs a narrower one
    for i in range(len(rects) - 1):
        a, b = rects[i], rects[i + 1]
        join = a[3] * SS
        narrow, wide = (b, a) if widths[i + 1] < widths[i] else (a, b)
        if abs(widths[i] - widths[i + 1]) < 2 * style.radius:
            continue
        down = narrow is b  # the narrow line is below the join
        for side in (-1, 1):
            ex = (narrow[0] if side < 0 else narrow[2]) * SS
            sx0, sx1 = (ex - r, ex) if side < 0 else (ex, ex + r)
            sy0, sy1 = (join, join + r) if down else (join - r, join)
            d.rectangle([sx0, sy0, sx1, sy1], fill=255)
            ccx = ex - r if side < 0 else ex + r
            ccy = join + r if down else join - r
            d.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=0)
    return mask.resize((W, H), Image.LANCZOS), rects


def _draw_lines(img: Image.Image, lines: list[str], rects: list, style: Style, colour) -> None:
    f = _font(style.font, style.size)
    d = ImageDraw.Draw(img)
    cap = -f.getbbox("H", anchor="ls")[1]
    for line, (x0, y0, x1, y1) in zip(lines, rects):
        x = (x0 + x1) / 2 - style.width(line) / 2
        baseline = y0 + (style.line_h + cap) / 2
        for kind, val in _runs(line):
            if kind == "emoji":
                e = _emoji(style.emoji_font, val, style.emoji_h)
                ey = round(baseline - cap / 2 - e.height / 2)
                img.paste(e, (round(x + style.size * 0.03), ey), e)
                x += e.width + style.size * 0.06
            else:
                d.text((x, baseline), val, font=f, fill=colour, anchor="ls")
                x += f.getlength(val)


def place(default_top: float, block_h: float, avoid: tuple[int, int] | None,
          margin: int = 28) -> float:
    """Moves the caption block off the sign: below it if there's room, else above it."""
    if not avoid:
        return default_top
    a_top, a_bottom = avoid
    if default_top + block_h + margin <= a_top or default_top >= a_bottom + margin:
        return default_top
    below = a_bottom + margin
    if below + block_h <= H * 0.74:
        return below
    above = a_top - margin - block_h
    if above >= H * 0.1:
        return above
    return default_top


def render(background: Image.Image, hook: str, subline: str, cfg: dict,
           rng: random.Random | None = None, avoid: tuple[int, int] | None = None) -> Image.Image:
    c = cfg["cover"]
    rng = rng or random.Random(hook)
    img = background.convert("RGB").copy()
    max_w = W * c["max_width"]

    hook_style, hook_lines = fit(hook, c["hook_font"], c["emoji_font"], c["hook_size"], max_w, 3)
    sub_style, sub_lines = (fit(subline, c["hook_font"], c["emoji_font"], c["subline_size"], max_w, 2)
                            if subline else (None, []))
    arrow_size = round(hook_style.size * 1.05)
    gap = round(hook_style.line_h * 0.32)

    block_h = len(hook_lines) * hook_style.line_h
    if sub_lines:
        block_h += gap + len(sub_lines) * sub_style.line_h
    block_h += gap + arrow_size
    top = place(H * c["text_y"] - block_h / 2, block_h, avoid)

    white = Image.new("RGB", (W, H), (255, 255, 255))
    mask, hook_rects = _box_mask(hook_lines, hook_style, W / 2, top)
    img.paste(white, (0, 0), mask)
    _draw_lines(img, hook_lines, hook_rects, hook_style, (12, 12, 12))
    y = top + len(hook_lines) * hook_style.line_h + gap

    if sub_lines:
        mask, sub_rects = _box_mask(sub_lines, sub_style, W / 2, y)
        img.paste(white, (0, 0), mask)
        _draw_lines(img, sub_lines, sub_rects, sub_style, (12, 12, 12))
        y += len(sub_lines) * sub_style.line_h + gap

    arrows = ">" * rng.randint(4, 9)
    f = _font(c["arrow_font"], arrow_size)
    ImageDraw.Draw(img).text((W / 2, y + arrow_size * 0.8), arrows, font=f, fill=(255, 255, 255),
                             anchor="ms", stroke_width=max(3, arrow_size // 14), stroke_fill=(20, 20, 20))
    return img
