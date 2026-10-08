"""Settings (config.toml), paths and secrets (.env locally, environment variables on GitHub)."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMAGES = ROOT / "images"
RECIPE_DIR = IMAGES / "recipes"
PROMO_DIR = IMAGES / "promo"
STATE = ROOT / "state"
HISTORY_FILE = STATE / "history.json"
TOKEN_FILE = STATE / "tiktok_token.enc"
BACKGROUND_DIR = STATE / "backgrounds"
SITE = ROOT / "site"


class ConfigError(Exception):
    pass


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.toml"
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_dotenv(path: Path | None = None) -> None:
    """Reads KEY=value lines from .env into os.environ (never overrides real environment variables)."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def secret(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name) or None
    if required and not value:
        raise ConfigError(
            f"{name} is not set. On GitHub add it with `gh secret set {name}`; "
            f"on your PC put it in the .env file (see .env.example).")
    return value
