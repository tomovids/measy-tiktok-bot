"""Measy recipe card (style B): a big photo of the meal with the full recipe underneath.

Everything except the photo is drawn by code, so every word and price is exact.
Layout (1080 x 1920): logo + badge, title + subtitle, photo with a price badge, a stats row,
ingredients (left) and method (right), then a tip and the tagline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

W, H = 1080, 1920
CREAM = (248, 244, 233)
PANEL = (225, 234, 210)
GREEN = (27, 74, 42)
LEAF = (63, 133, 56)
INK = (28, 40, 31)
MUTED = (90, 104, 93)
WHITE = (255, 255, 255)
M = 44  # outer margin

FRAUNCES = "fonts/Fraunces.ttf"
CAVEAT = "fonts/Caveat.ttf"
SANS = "fonts/TikTokSans36pt-Medium.ttf"
SANS_BOLD = "fonts/TikTokSans36pt-Bold.ttf"
LOGO = "images/brand/measy-logo.png"


@dataclass
class Ingredient:
    item: str
    qty: str | None = None
    price: float | None = None


@dataclass
class Step:
    text: str
    title: str | None = None


@dataclass
class CardRecipe:
    title: str
    subtitle: str | None
    serves: int | None
    prep_mins: int | None
    cook_mins: int | None
    calories: int | None
    ingredients: list[Ingredient] = field(default_factory=list)
    method: list[Step] = field(default_factory=list)
    tip: str | None = None
    badge: str = "Budget Friendly"

    @property
    def total(self) -> float | None:
        prices = [i.price for i in self.ingredients]
        return round(sum(prices), 2) if prices and all(p is not None for p in prices) else None

    @property
    def per_serving(self) -> float | None:
        return round(self.total / self.serves, 2) if self.total and self.serves else None

    @classmethod
    def from_dict(cls, d: dict) -> "CardRecipe":
        return cls(
            title=d["title"], subtitle=d.get("subtitle"), serves=d.get("serves"),
            prep_mins=d.get("prep_mins"), cook_mins=d.get("cook_mins"), calories=d.get("calories"),
            ingredients=[Ingredient(i["item"], i.get("qty"), i.get("price")) for i in d.get("ingredients", [])],
            method=[Step(s["text"], s.get("title")) for s in d.get("method", [])],
            tip=d.get("tip"), badge=d.get("badge") or "Budget Friendly")


# ---- fonts ------------------------------------------------------------------------------------

@lru_cache(maxsize=64)
def font(path: str, size: int, weight: int | None = None, soft: int = 100) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(config.ROOT / path), size)
    if path == FRAUNCES:
        f.set_variation_by_axes([min(144, max(9, size)), weight or 900, soft, 0])
    elif path == CAVEAT:
        f.set_variation_by_axes([weight or 700])
    return f


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if not line or f.getlength(trial) <= max_w:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_line(text: str, max_w: float, size: int = 56, min_size: int = 42):
    """One line of Caveat: shrinks to fit; if still too long, ends at the last phrase that fits."""
    text = text.strip()
    for s in range(size, min_size - 1, -2):
        f = font(CAVEAT, s)
        if f.getlength(text) <= max_w:
            return text, f
    f = font(CAVEAT, min_size)
    words, best = text.split(), ""
    for i in range(1, len(words) + 1):
        part = " ".join(words[:i])
        if f.getlength(part) > max_w:
            break
        if part[-1] in ".,!;:–-" or i == len(words):
            best = part
    if not best:
        best = wrap(text, f, max_w)[0]
    return best.rstrip(" ,;:–-"), f


def money(x: float) -> str:
    return f"£{x:.2f}"


# ---- pieces -----------------------------------------------------------------------------------

def _logo(img: Image.Image, x: int, y: int, height: int) -> int:
    """Pastes the Measy logo (or draws a stand-in until the logo file is added). Returns its width."""
    path = config.ROOT / LOGO
    if path.exists():
        logo = Image.open(path).convert("RGBA")
        logo = logo.resize((round(logo.width * height / logo.height), height), Image.LANCZOS)
        img.paste(logo, (x, y), logo)
        return logo.width
    d = ImageDraw.Draw(img)
    f = font(SANS_BOLD, round(height * 0.78))
    d.text((x, y + height * 0.72), "Measy", font=f, fill=GREEN, anchor="ls")
    w = round(f.getlength("Measy"))
    d.arc([x + w * 0.12, y + height * 0.5, x + w * 0.88, y + height * 0.98], 25, 155, fill=LEAF, width=6)
    small = font(SANS_BOLD, round(height * 0.17))
    d.text((x + 4, y + height * 1.22), "MEAL PLANS MADE EASY", font=small, fill=GREEN, anchor="ls")
    return w


def _badge(img: Image.Image, text: str, right: int, top: int) -> None:
    d = ImageDraw.Draw(img)
    f = font(CAVEAT, 46)
    lines = wrap(text, f, 200)
    tw = max(f.getlength(l) for l in lines)
    h = 50 * len(lines) + 24
    box = [right - tw - 44, top, right, top + h]
    d.rounded_rectangle(box, radius=10, fill=PANEL)
    for i, l in enumerate(lines):
        d.text(((box[0] + box[2]) / 2, top + 14 + 50 * i + 40), l, font=f, fill=GREEN, anchor="ms")


def _photo(img: Image.Image, photo: Image.Image, box: tuple[int, int, int, int], radius: int = 30) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    p = photo.convert("RGB")
    scale = max(w / p.width, h / p.height)
    p = p.resize((round(p.width * scale), round(p.height * scale)), Image.LANCZOS)
    left, top = (p.width - w) // 2, (p.height - h) // 2
    p = p.crop((left, top, left + w, top + h))
    shadow = Image.new("L", img.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle([x0, y0 + 10, x1, y1 + 10], radius=radius, fill=90)
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    img.paste((205, 198, 180), (0, 0), shadow)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img.paste(p, (x0, y0), mask)


def _price_badge(img: Image.Image, r: CardRecipe, cx: int, cy: int, radius: int = 118) -> None:
    if r.total is None:
        return
    d = ImageDraw.Draw(img)
    d.ellipse([cx - radius - 6, cy - radius - 6, cx + radius + 6, cy + radius + 6], fill=CREAM)
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=GREEN)
    if r.per_serving is not None:
        d.text((cx, cy - 46), "only", font=font(CAVEAT, 40), fill=WHITE, anchor="ms")
        d.text((cx, cy + 22), money(r.per_serving), font=font(FRAUNCES, 66), fill=WHITE, anchor="ms")
        d.text((cx, cy + 62), "a portion", font=font(SANS_BOLD, 26), fill=WHITE, anchor="ms")
    else:
        d.text((cx, cy - 20), "Total", font=font(CAVEAT, 40), fill=WHITE, anchor="ms")
        d.text((cx, cy + 40), money(r.total), font=font(FRAUNCES, 66), fill=WHITE, anchor="ms")


def _stats(img: Image.Image, r: CardRecipe, top: int) -> int:
    items = []
    if r.serves:
        items.append(("Serves", str(r.serves)))
    if r.prep_mins:
        items.append(("Prep", f"{r.prep_mins} mins"))
    if r.cook_mins:
        items.append(("Cook", f"{r.cook_mins} mins"))
    if r.calories:
        items.append(("Calories", f"{r.calories}"))
    if not items:
        return top
    d = ImageDraw.Draw(img)
    gap = 16
    w = (W - 2 * M - gap * (len(items) - 1)) / len(items)
    for i, (label, value) in enumerate(items):
        x = M + i * (w + gap)
        d.rounded_rectangle([x, top, x + w, top + 96], radius=20, fill=PANEL)
        d.text((x + w / 2, top + 36), label, font=font(SANS, 26), fill=MUTED, anchor="ms")
        d.text((x + w / 2, top + 80), value, font=font(SANS_BOLD, 36), fill=GREEN, anchor="ms")
    return top + 96


def _section_title(d: ImageDraw.ImageDraw, x: float, y: float, text: str) -> None:
    d.text((x, y), text, font=font(FRAUNCES, 46, 800), fill=GREEN, anchor="ls")


def _ingredients(img, r: CardRecipe, box, size: int) -> bool:
    """Draws the ingredient list; returns False if it doesn't fit."""
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    f, fb = font(SANS, size), font(SANS_BOLD, size)
    y = y0 + 52
    _section_title(d, x0, y0 + 40, "Ingredients")
    lh = round(size * 1.28)
    for ing in r.ingredients:
        price = money(ing.price) if ing.price is not None else ""
        pw = fb.getlength(price) + (14 if price else 0)
        text = f"{ing.qty} {ing.item}" if ing.qty else ing.item
        lines = wrap(text, f, x1 - x0 - 30 - pw)
        if y + lh * len(lines) > y1:
            return False
        d.ellipse([x0 + 2, y + lh / 2 - 6, x0 + 14, y + lh / 2 + 6], fill=LEAF)
        for j, line in enumerate(lines):
            d.text((x0 + 26, y + lh * j + lh * 0.78), line, font=f, fill=INK, anchor="ls")
        if price:
            d.text((x1, y + lh * 0.78), price, font=fb, fill=GREEN, anchor="rs")
        y += lh * len(lines) + round(size * 0.32)
    return True


def _method(img, r: CardRecipe, box, size: int, titles: bool = True) -> bool:
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    f, fb = font(SANS, size), font(SANS_BOLD, size)
    _section_title(d, x0, y0 + 40, "Method")
    y = y0 + 52
    lh = round(size * 1.28)
    circle = round(size * 1.35)
    tx = x0 + circle + 14
    for n, step in enumerate(r.method, 1):
        lines = []
        if step.title and titles:
            lines.append(("b", step.title))
        lines += [("r", l) for l in wrap(step.text, f, x1 - tx)]
        h = lh * len(lines)
        if y + max(h, circle) > y1:
            return False
        d.ellipse([x0, y + 2, x0 + circle, y + 2 + circle], fill=GREEN)
        d.text((x0 + circle / 2, y + 2 + circle / 2), str(n), font=font(SANS_BOLD, round(size * 0.9)),
               fill=WHITE, anchor="mm")
        for j, (kind, line) in enumerate(lines):
            d.text((tx, y + lh * j + lh * 0.8), line, font=fb if kind == "b" else f, fill=INK, anchor="ls")
        y += max(h, circle) + round(size * 0.55)
    return True


def _footer(img, r: CardRecipe, top: int) -> None:
    d = ImageDraw.Draw(img)
    box = [M, top, W - M - 300, H - 36]
    d.rounded_rectangle(box, radius=22, fill=PANEL)
    if r.tip:
        d.text((box[0] + 28, top + 52), "Measy tip", font=font(FRAUNCES, 38, 800), fill=GREEN, anchor="ls")
        f = font(SANS, 27)
        lines = wrap(r.tip, f, box[2] - box[0] - 56)[:2]
        for j, line in enumerate(lines):
            d.text((box[0] + 28, top + 90 + j * 34), line, font=f, fill=INK, anchor="ls")
    elif r.total is not None:
        d.text((box[0] + 28, top + 70), f"Total {money(r.total)}", font=font(FRAUNCES, 52), fill=GREEN, anchor="ls")
    cx = W - M - 150
    d.text((cx, top + 60), "Good food.", font=font(CAVEAT, 52), fill=GREEN, anchor="ms")
    d.text((cx, top + 112), "Less stress.", font=font(CAVEAT, 52), fill=GREEN, anchor="ms")


# ---- the card ---------------------------------------------------------------------------------

def render(r: CardRecipe, photo: Image.Image) -> Image.Image:
    """The biggest photo the recipe leaves room for (text no smaller than 22 px)."""
    for photo_h in (760, 700, 640, 580, 520):
        img = _layout(r, photo, photo_h, min_size=22)
        if img is not None:
            return img
    img = _layout(r, photo, 520, min_size=18)
    if img is None:
        raise ValueError(f"The recipe for {r.title} doesn't fit on the card; shorten it.")
    return img


def _layout(r: CardRecipe, photo: Image.Image, photo_h: int, min_size: int) -> Image.Image | None:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    _logo(img, M, 40, 92)
    _badge(img, r.badge, W - M, 44)

    # title: Fraunces Black, up to 2 lines, shrinks to fit
    size = 104
    while True:
        tf = font(FRAUNCES, size)
        lines = wrap(r.title, tf, W - 2 * M)
        if len(lines) <= 2 or size <= 64:
            break
        size -= 4
    y = 172 + size
    for i, line in enumerate(lines[:2]):
        if i:
            y += round(size * 0.98)
        d.text((M, y), line, font=tf, fill=GREEN, anchor="ls")
    if r.subtitle:
        sub, sf = fit_line(r.subtitle, W - 2 * M)
        y += 70
        d.text((M + 4, y), sub, font=sf, fill=INK, anchor="ls")

    photo_top = y + 36
    photo_bottom = photo_top + photo_h
    _photo(img, photo, (M, photo_top, W - M, photo_bottom))
    _price_badge(img, r, W - M - 136, photo_bottom - 136)

    stats_bottom = _stats(img, r, photo_bottom + 26)

    footer_top = H - 36 - 150
    col_top, col_bottom = stats_bottom + 6, footer_top - 14
    split = M + round((W - 2 * M) * 0.41)
    for size, titles in [(s, t) for s in range(30, min_size - 1, -1) for t in (True, False)]:
        trial = img.copy()
        ok = (_ingredients(trial, r, (M, col_top, split - 22, col_bottom), size)
              and _method(trial, r, (split + 22, col_top, W - M, col_bottom), size, titles))
        if ok:
            img = trial
            break
    else:
        return None
    ImageDraw.Draw(img).line([(split, col_top + 30), (split, col_bottom - 10)], fill=PANEL, width=3)

    _footer(img, r, footer_top)
    return img


def render_for(file: str) -> Image.Image:
    """Draws the card for a picked recipe whose file is 'card:<dish>-<n>'."""
    from . import library, photos
    stem = file.split(":", 1)[1]
    group = stem.rsplit("-", 1)[0]
    entry = library.load()[group]
    return render(CardRecipe.from_dict(entry), Image.open(photos.PHOTO_DIR / f"{stem}.jpg"))
