"""The recipe catalogue (data/recipes.json) and the promo slides."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class Recipe:
    file: str
    dish: str
    group: str
    protein: str | None
    base: str | None
    currency: str | None
    cost_total: float | None
    cost_per_serving: float | None
    serves: int | None
    time_mins: int | None
    layout: str | None = None

    @property
    def total_gbp(self) -> float | None:
        """Printed cost of the whole dish in pounds, if the card shows one."""
        if self.currency == "USD":
            return None
        if self.cost_total is not None:
            return float(self.cost_total)
        if self.cost_per_serving is not None and self.serves:
            return round(float(self.cost_per_serving) * self.serves, 2)
        return None

    @property
    def per_serving_gbp(self) -> float | None:
        if self.currency == "USD":
            return None
        if self.cost_per_serving is not None:
            return float(self.cost_per_serving)
        if self.cost_total is not None and self.serves:
            return round(float(self.cost_total) / self.serves, 2)
        return None

    @property
    def path(self) -> Path:
        return config.RECIPE_DIR / self.file


def load_recipes(path: Path | None = None, cards: bool = True) -> list[Recipe]:
    """The original recipe images, plus one entry per generated recipe card (photo variant)."""
    path = path or config.DATA / "recipes.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    out = load_cards(rows) if cards else []
    for r in rows:
        if r.get("kind") != "recipe":
            continue
        out.append(Recipe(
            file=r["file"], dish=r["dish"], group=r["group"], protein=r.get("protein"),
            base=r.get("base"), currency=r.get("currency"), cost_total=r.get("cost_total"),
            cost_per_serving=r.get("cost_per_serving"), serves=r.get("serves"),
            time_mins=r.get("time_mins"), layout=r.get("layout")))
    return out


def promo_files(folder: Path | None = None) -> list[Path]:
    folder = folder or config.PROMO_DIR
    return sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in (".jpg", ".jpeg", ".webp", ".png"))


def load_cards(rows: list[dict]) -> list[Recipe]:
    """Recipe cards drawn from data/recipe_library.json, one per food photo in images/photos/."""
    from . import library, photos
    meta = {}
    for r in rows:
        if r.get("kind") == "recipe":
            meta.setdefault(r["group"], r)
    out = []
    for group, e in sorted(library.load().items()):
        m = meta.get(group, {})
        prices = [i.get("price") for i in e.get("ingredients", [])]
        total = round(sum(prices), 2) if prices and all(isinstance(x, (int, float)) for x in prices) else None
        mins = (e.get("prep_mins") or 0) + (e.get("cook_mins") or 0) or None
        for photo in photos.photos_for(group):
            out.append(Recipe(
                file=f"card:{photo.stem}", dish=e["title"], group=group, protein=m.get("protein"),
                base=m.get("base"), currency="USD" if config.REGION == "us" else "GBP", cost_total=total, cost_per_serving=None,
                serves=e.get("serves"), time_mins=mins, layout="card"))
    return out
