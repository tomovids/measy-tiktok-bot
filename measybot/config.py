"""Settings (config.toml), accounts, paths and secrets (.env locally, environment variables on GitHub).

Several TikTok accounts can be posted to ([[accounts]] in config.toml). The first account keeps
its files in state/ (and its slides in site/p/); every other account has its own folder
state/<id>/ (and site/p/<id>/). `use_account()` points the paths below at one account; every
module reads them at call time, so the rest of the code works on "the current account".
"""
from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMAGES = ROOT / "images"
RECIPE_DIR = IMAGES / "recipes"
PROMO_DIR = IMAGES / "promo"
STATE = ROOT / "state"
SITE = ROOT / "site"

# The current account's files (see use_account).
ACCOUNT_DIR = STATE
HISTORY_FILE = STATE / "history.json"
TOKEN_FILE = STATE / "tiktok_token.enc"
BACKGROUND_DIR = STATE / "backgrounds"
STATS_FILE = STATE / "stats.json"
TUNING_FILE = STATE / "tuning.json"
POSTS_SUBDIR = ""          # "" or "<id>": slides go in site/p/<POSTS_SUBDIR>/
# The current account's audience ([regions.<id>] in config.toml; "uk" has no block, it's the default).
REGION = "uk"
CURRENCY = {"uk": "£", "us": "$"}


@dataclass
class Account:
    id: str
    name: str
    handle: str = ""
    primary: bool = True
    overrides: dict = field(default_factory=dict)

    @property
    def state_dir(self) -> Path:
        return STATE if self.primary else STATE / self.id

    @property
    def posts_subdir(self) -> str:
        return "" if self.primary else self.id


def accounts(cfg: dict) -> list[Account]:
    rows = cfg.get("accounts") or [{"id": "measy", "name": "Measy"}]
    return [Account(id=r["id"], name=r.get("name", r["id"]), handle=r.get("handle", ""), primary=(i == 0),
                    overrides={k: v for k, v in r.items() if k not in ("id", "name", "handle")})
            for i, r in enumerate(rows)]


def get_account(cfg: dict, account_id: str | None) -> Account:
    accs = accounts(cfg)
    if not account_id:
        return accs[0]
    for a in accs:
        if a.id == account_id or a.handle.lstrip("@") == account_id.lstrip("@"):
            return a
    raise ConfigError(f"No account '{account_id}' in config.toml (have: {', '.join(a.id for a in accs)}).")


def account_cfg(cfg: dict, acct: Account) -> dict:
    """config.toml with the account's own settings applied (times, store plan, stores, dashboard)."""
    out = copy.deepcopy(cfg)
    o = acct.overrides
    if "post_times" in o:
        out["schedule"]["post_times"] = o["post_times"]
    if "store_plan" in o:
        out.setdefault("store_rotation", {})["plan"] = o["store_plan"]
    if "stores" in o:
        # the account's own order is its rotation order
        by_id = {s["id"]: s for s in out.get("stores", [])}
        out["stores"] = [by_id[i] for i in o["stores"] if i in by_id]
    if "dashboard_dir" in o:
        out.setdefault("tracking", {})["dashboard_dir"] = o["dashboard_dir"]
    region = o.get("region", "uk")
    reg = copy.deepcopy(cfg.get("regions", {}).get(region, {}))
    for section in ("caption", "words", "cover"):
        out.setdefault(section, {}).update(reg.pop(section, {}))
    if "timezone" in reg:
        out["schedule"]["timezone"] = reg["timezone"]
    if "timezone" in o:
        out["schedule"]["timezone"] = o["timezone"]
    # stores belong to a region (default uk); an account only ever sees its region's stores
    out["stores"] = [s for s in out.get("stores", []) if s.get("region", "uk") == region]
    out["region"] = {"id": region, "currency": CURRENCY.get(region, "£"), **reg}
    out["account"] = {"id": acct.id, "name": acct.name, "handle": acct.handle, "primary": acct.primary}
    return out


def use_account(acct: Account) -> None:
    """Points the state paths at this account's files."""
    global ACCOUNT_DIR, HISTORY_FILE, TOKEN_FILE, BACKGROUND_DIR, STATS_FILE, TUNING_FILE, POSTS_SUBDIR, REGION
    ACCOUNT_DIR = acct.state_dir
    HISTORY_FILE = ACCOUNT_DIR / "history.json"
    TOKEN_FILE = ACCOUNT_DIR / "tiktok_token.enc"
    BACKGROUND_DIR = ACCOUNT_DIR / "backgrounds"
    STATS_FILE = ACCOUNT_DIR / "stats.json"
    TUNING_FILE = ACCOUNT_DIR / "tuning.json"
    POSTS_SUBDIR = acct.posts_subdir
    REGION = acct.overrides.get("region", "uk")


def currency() -> str:
    return CURRENCY.get(REGION, "£")


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
