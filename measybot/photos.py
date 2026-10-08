"""AI food photos for the recipe cards (images/photos/<dish>-<n>.jpg), made once per dish and kept."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from . import config
from .openai_api import OpenAI

PHOTO_DIR = config.IMAGES / "photos"
CHEESES = ("cheese", "cheddar", "mozzarella", "parmesan", "halloumi", "feta", "mascarpone")


def photo_path(group: str, n: int) -> Path:
    return PHOTO_DIR / f"{group}-{n}.jpg"


def photos_for(group: str) -> list[Path]:
    return sorted(PHOTO_DIR.glob(f"{group}-*.jpg"))


def prompt_for(entry: dict, n: int, cfg: dict) -> str:
    c = cfg["cards"]
    key = ", ".join(i["item"] for i in entry["ingredients"][:9])
    angle = c["photo_angles"][(n - 1) % len(c["photo_angles"])]
    dish = entry["title"] + (f" ({entry['subtitle']})" if entry.get("subtitle") else "")
    items = " ".join(i["item"].lower() for i in entry["ingredients"])
    cheesy = any(w in items for w in CHEESES)
    cheese = "melted, stretchy, golden cheese" if cheesy else "no cheese anywhere in the picture"
    return c["photo_prompt"].format(dish=dish, ingredients=key, angle=angle, cheese=cheese)


def generate(client: OpenAI, entry: dict, n: int, cfg: dict) -> Path:
    o, c = cfg["openai"], cfg["cards"]
    data, _ = client.image(o["image_models"], prompt_for(entry, n, cfg), c["photo_size"], c["photo_quality"])
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    path = photo_path(entry["group"], n)
    Image.open(io.BytesIO(data)).convert("RGB").save(path, "JPEG", quality=90)
    return path
