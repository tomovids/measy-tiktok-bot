"""Puts the day's 7 slides and post.json into one folder (site/p/<date>/ for GitHub Pages)."""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

from PIL import Image

from . import config

MAX_W, MAX_H = 1080, 1920       # TikTok photo limit (portrait)
MAX_BYTES = 20 * 1024 * 1024


def post_folder(day: date, site: Path | None = None, name: str | None = None) -> Path:
    """site/p/[<account>/]<date>, or <name> for a numbered or extra test post (its own URLs, so no
    stale cache). Accounts other than the first have their own subfolder."""
    return (site or config.SITE) / "p" / config.POSTS_SUBDIR / (name or day.isoformat())


def slide_ok(path: Path) -> bool:
    if path.stat().st_size >= MAX_BYTES:
        return False
    with Image.open(path) as im:
        w, h = im.size
        fmt = im.format
    fits = (w <= MAX_W and h <= MAX_H) or (w <= MAX_H and h <= MAX_W)
    return fmt in ("JPEG", "WEBP") and fits


def copy_slide(src: Path, dst_stem: Path) -> Path:
    """Copies a slide as it is when TikTok accepts it, otherwise resizes it to a JPEG."""
    if slide_ok(src):
        dst = dst_stem.with_suffix(src.suffix.lower())
        shutil.copy2(src, dst)
        return dst
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_W, MAX_H), Image.LANCZOS)
        dst = dst_stem.with_suffix(".jpg")
        im.save(dst, "JPEG", quality=92)
    return dst


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _thumb(path: Path) -> list[int]:
    with Image.open(path) as im:
        return list(im.convert("L").resize((16, 16), Image.BILINEAR).tobytes())


def promo_problem(post: dict, site: Path | None = None, promos: list[Path] | None = None) -> str | None:
    """Why this post doesn't end with the app promo, or None if it does. Every post must end with it:
    the last slide's picture is compared with the promo images (so a resized copy still counts)."""
    from .catalogue import promo_files
    promos = promos if promos is not None else promo_files()
    slides = post.get("slides") or []
    if not slides:
        return "it has no slides"
    return slide_problem((site or config.SITE) / slides[-1], promos)


def slide_problem(last: Path, promos: list[Path]) -> str | None:
    """Why this slide isn't one of the app promo images (None if it is)."""
    if not last.exists():
        return f"its last slide ({last.name}) is missing"
    if not promos:
        return f"there are no app promo images in {config.PROMO_DIR}"
    got = _thumb(last)
    for promo in promos:
        want = _thumb(promo)
        if sum(abs(a - b) for a, b in zip(got, want)) / len(got) < 12:
            return None
    return f"its last slide ({last.name}) isn't the app promo"


def stage(folder: Path, day: date, cover: Image.Image, recipes, promo: Path, words, caption: str,
          meta: dict, rel_root: Path | None = None, shop: Image.Image | None = None) -> dict:
    """Slides: the cover, the recipes, this post's shop slide (if drawn), and the app promo last."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    if rel_root is None:
        try:
            folder.relative_to(config.SITE)
            rel_root = config.SITE
        except ValueError:          # dry runs into out/
            rel_root = folder.parent.parent

    slides = [folder / "01.jpg"]
    cover.convert("RGB").save(slides[0], "JPEG", quality=92)
    for i, r in enumerate(recipes, 2):
        if r.file.startswith("card:"):
            from .card import render_for
            dst = folder / f"{i:02d}.jpg"
            render_for(r.file).save(dst, "JPEG", quality=92)
            slides.append(dst)
        else:
            slides.append(copy_slide(r.path, folder / f"{i:02d}"))
    if shop is not None:          # drawn for this post's dishes (card.render_shop)
        slides.append(folder / f"{len(slides) + 1:02d}.jpg")
        shop.convert("RGB").save(slides[-1], "JPEG", quality=92)
    slides.append(copy_slide(promo, folder / f"{len(slides) + 1:02d}"))          # the app promo, always last

    title = words.hook
    while utf16_len(title) > 90:
        title = title[:-1]
    post = {
        "date": day.isoformat(),
        "slides": [s.relative_to(rel_root).as_posix() for s in slides],
        "hook": words.hook,
        "subline": words.subline,
        "title": title.strip(),
        "caption": caption,
        "files": [r.file for r in recipes],
        "groups": [r.group for r in recipes],
        "dishes": [r.dish for r in recipes],
        "promo": promo.name,
        "shop_slide": shop is not None,
        "words_source": words.source,
        **meta,
    }
    (folder / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
    return post


def load_post(folder: Path) -> dict:
    path = folder / "post.json"
    if not path.exists():
        raise FileNotFoundError(f"No built post at {path}. Run `python -m measybot build` first.")
    return json.loads(path.read_text(encoding="utf-8"))
