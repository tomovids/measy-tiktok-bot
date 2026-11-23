"""AI food photos for the recipe cards: images/photos/<dish>-<n>.jpg for the recipe library (made once
per dish and kept), images/fresh/<dish>-1.jpg for a post's brand-new dishes (fresh.py; not kept)."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from . import config
from .openai_api import OpenAI

PHOTO_DIR = config.IMAGES / "photos"
FRESH_DIR = config.IMAGES / "fresh"
CHEESES = ("cheese", "cheddar", "mozzarella", "parmesan", "halloumi", "feta", "mascarpone")


def photo_path(group: str, n: int) -> Path:
    return PHOTO_DIR / f"{group}-{n}.jpg"


def photos_for(group: str) -> list[Path]:
    return sorted(PHOTO_DIR.glob(f"{group}-*.jpg"))


def find(stem: str) -> Path:
    """The photo for a card file 'card:<stem>': a library photo or a fresh one."""
    path = PHOTO_DIR / f"{stem}.jpg"
    return path if path.exists() else FRESH_DIR / f"{stem}.jpg"


def prompt_for(entry: dict, n: int, cfg: dict, angle: int | None = None) -> str:
    c = cfg["cards"]
    key = ", ".join(i["item"] for i in entry["ingredients"][:9])
    angle = c["photo_angles"][(n - 1 if angle is None else angle) % len(c["photo_angles"])]
    dish = entry["title"] + (f" ({entry['subtitle']})" if entry.get("subtitle") else "")
    items = " ".join(i["item"].lower() for i in entry["ingredients"])
    cheesy = any(w in items for w in CHEESES)
    cheese = "melted, stretchy, golden cheese" if cheesy else "no cheese anywhere in the picture"
    return c["photo_prompt"].format(dish=dish, ingredients=key, angle=angle, cheese=cheese)


def generate(client: OpenAI, entry: dict, n: int, cfg: dict, folder: Path | None = None,
             angle: int | None = None) -> Path:
    o, c = cfg["openai"], cfg["cards"]
    data, _ = client.image(o["image_models"], prompt_for(entry, n, cfg, angle), c["photo_size"],
                           c["photo_quality"])
    folder = folder or PHOTO_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{entry['group']}-{n}.jpg"
    Image.open(io.BytesIO(data)).convert("RGB").save(path, "JPEG", quality=90)
    return path
