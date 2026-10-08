"""Command line: python -m measybot <build|send|dry-run|authorize|status|newkey>."""
from __future__ import annotations

import argparse
import copy
import os
import secrets as pysecrets
import sys
import time
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import catalogue, config, stage, tokens
from .config import ConfigError, load_config, load_dotenv, secret
from .history import SENT, History
from .openai_api import OpenAI, OpenAIError
from .picker import usable
from .pipeline import build_post, send_post
from .tiktok import TikTok, TikTokError


def log(msg: str) -> None:
    print(msg, flush=True)


def github_output(**values) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def local_now(cfg: dict) -> datetime:
    return datetime.now(ZoneInfo(cfg["schedule"]["timezone"]))


def openai_client(required: bool) -> OpenAI | None:
    key = secret("OPENAI_API_KEY", required=required)
    return OpenAI(key) if key else None


# ---- commands ---------------------------------------------------------------------------------

def cmd_build(args, cfg) -> int:
    now = local_now(cfg)
    day = date.fromisoformat(args.date) if args.date else now.date()
    hist = History.load()
    name = f"{day.isoformat()}-{now:%H%M%S}" if args.again else day.isoformat()
    github_output(date=day.isoformat(), post=name, built="false")
    if hist.done_on(day) and not args.again:
        log(f"Today's draft ({day}) was already sent. Nothing to do.")
        return 0
    if not config.TOKEN_FILE.exists():
        log("TikTok isn't connected yet (no state/tiktok_token.enc; see SETUP.md step 6). Skipping.")
        return 0
    hh, mm = map(int, cfg["schedule"]["post_time"].split(":"))
    if not (args.force or args.again or args.date) and (now.hour, now.minute) < (hh, mm):
        log(f"It's {now:%H:%M} in {cfg['schedule']['timezone']}; posting time is "
            f"{cfg['schedule']['post_time']}. Nothing to do yet.")
        return 0
    if args.again:
        log("Extra test draft: today's draft was already sent, making another one anyway.")
    build_post(day, cfg, hist, stage.post_folder(day, name=name), openai_client(required=True), log=log)
    github_output(built="true")
    return 0


def cmd_send(args, cfg) -> int:
    day = date.fromisoformat(args.date) if args.date else local_now(cfg).date()
    post = stage.load_post(stage.post_folder(day, name=args.post))
    tt = TikTok(secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET"))
    send_post(post, cfg, History.load(), tt, secret("TOKEN_KEY"), log=log)
    return 0


def cmd_dry_run(args, cfg) -> int:
    out = Path(args.out).resolve()
    start = date.fromisoformat(args.start) if args.start else local_now(cfg).date()
    ai = None if args.no_ai else openai_client(required=False)
    if ai is None:
        log("No OpenAI key (or --no-ai): using saved hooks and a placeholder background.")
    hist = copy.deepcopy(History.load())
    hist.path = None
    for i in range(args.days):
        day = start + timedelta(days=i)
        log(f"\n== {day} ==")
        post = build_post(day, cfg, hist, out / day.isoformat(), ai,
                          ai_image=not args.no_image, keep_spares=False, save_background=True, log=log)
        hist.add({**post, "status": SENT})   # pretend it was sent, so the next day moves on
    log(f"\nSlides are in {out}")
    return 0


def cmd_authorize(args, cfg) -> int:
    t = cfg["tiktok"]
    key = secret("TOKEN_KEY")
    tt = TikTok(secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET"))
    state = pysecrets.token_urlsafe(12)
    url = tt.authorize_url(t["redirect_uri"], t["scopes"], state)
    log("Opening TikTok in your browser. Log in as the Measy account and approve access.")
    log(f"If nothing opens, go to:\n{url}\n")
    webbrowser.open(url)
    code = input("Paste the code shown on the page here: ").strip()
    login = tt.exchange_code(code, t["redirect_uri"])
    missing = [s for s in t["scopes"] if s not in login.get("scope", "")]
    if missing:
        log(f"Warning: TikTok didn't grant {', '.join(missing)}. Check the app's scopes (SETUP.md).")
    try:
        name = tt.display_name(login["access_token"])
        log(f"Connected as: {name}" + ("" if name else " (no display name)"))
        if name and input("Is this the Measy account? [y/n] ").strip().lower() not in ("y", "yes"):
            log("Not saved. Log out of TikTok in the browser, log in as the Measy account and run authorize again.")
            return 1
    except TikTokError as e:
        log(f"(Couldn't read the account name: {e})")
    tokens.save(login, key)
    log(f"Saved the login to {config.TOKEN_FILE.relative_to(config.ROOT)} (encrypted).")
    log("Now commit and push it:  git add state/tiktok_token.enc && git commit -m \"TikTok login\" && git push")
    return 0


def cmd_status(args, cfg) -> int:
    hist = History.load()
    posts = sorted(hist.posts, key=lambda p: (p["date"], p.get("sent_at", "")))[-args.n:]
    if not posts:
        log("Nothing sent yet.")
    for p in posts:
        log(f"{p['date']}  {p.get('status', '?'):20s} {p.get('hook', '')}")
        if p.get("error"):
            log("    " + p["error"].splitlines()[0])
    recipes = usable(catalogue.load_recipes(), cfg)
    used = hist.last_used("groups")
    groups = {r.group for r in recipes}
    log(f"\n{len(used)} of {len(groups)} dishes posted at least once.")
    key = os.environ.get("TOKEN_KEY")
    if key and config.TOKEN_FILE.exists():
        try:
            login = tokens.load(key)
            days = (login["refresh_expires_at"] - time.time()) / 86400
            log(f"TikTok login valid for about {days:.0f} more days.")
        except tokens.TokenError as e:
            log(str(e))
    return 0


def cmd_newkey(args, cfg) -> int:
    log(tokens.new_key())
    return 0


def _only(args) -> list[str] | None:
    return [g.strip() for g in args.only.split(",")] if args.only else None


def cmd_library(args, cfg) -> int:
    from . import library
    lib = library.build(openai_client(required=True), cfg, only=_only(args), log=log)
    filled = {g: e["ai_filled"] for g, e in lib.items() if e.get("ai_filled")}
    log(f"\n{len(lib)} recipes in data/recipe_library.json; {len(filled)} have AI-filled parts to check.")
    return 0


def cmd_photos(args, cfg) -> int:
    from . import library, photos
    lib = library.load()
    only = _only(args)
    client = openai_client(required=True)
    n = args.variants or cfg["cards"]["variants"]
    for group, entry in sorted(lib.items()):
        if only and group not in only:
            continue
        for v in range(1, n + 1):
            if photos.photo_path(group, v).exists() and not args.redo:
                continue
            log(f"{group} photo {v} ...")
            photos.generate(client, entry, v, cfg)
    return 0


def cmd_cards(args, cfg) -> int:
    from PIL import Image
    from . import card, library, photos
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    only = _only(args)
    for group, entry in sorted(library.load().items()):
        if only and group not in only:
            continue
        for path in photos.photos_for(group) or [None]:
            photo = Image.open(path) if path else Image.new("RGB", (1536, 1024), (196, 160, 120))
            name = (path.stem if path else group) + ".jpg"
            card.render(card.CardRecipe.from_dict(entry), photo).save(out / name, "JPEG", quality=92)
            log(f"{out / name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="measybot", description="Measy TikTok slideshow bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build today's slides (GitHub Actions step 1)")
    b.add_argument("--date", help="YYYY-MM-DD (default: today, UK time)")
    b.add_argument("--force", action="store_true", help="build even before the posting time")
    b.add_argument("--again", action="store_true",
                   help="make another draft even if today's was already sent (for testing)")
    s = sub.add_parser("send", help="send the built slides to TikTok drafts (step 2)")
    s.add_argument("--date")
    s.add_argument("--post", help="folder name under site/p (default: the date)")
    d = sub.add_parser("dry-run", help="build some days of slides into a folder; nothing is sent")
    d.add_argument("--days", type=int, default=3)
    d.add_argument("--out", default="out")
    d.add_argument("--start", help="first date (default: today)")
    d.add_argument("--no-ai", action="store_true", help="don't call OpenAI at all")
    d.add_argument("--no-image", action="store_true", help="AI words but a placeholder cover picture")
    sub.add_parser("authorize", help="log in to TikTok once (run on your PC)")
    st = sub.add_parser("status", help="show recent posts")
    st.add_argument("-n", type=int, default=10)
    sub.add_parser("newkey", help="print a new TOKEN_KEY")
    lb = sub.add_parser("library", help="build the card-ready recipe library with OpenAI (one-off)")
    lb.add_argument("--only", help="comma-separated dish ids")
    ph = sub.add_parser("photos", help="make the AI food photos for the recipe cards (one-off)")
    ph.add_argument("--only", help="comma-separated dish ids")
    ph.add_argument("--variants", type=int, help="photos per dish (default from config)")
    ph.add_argument("--redo", action="store_true", help="replace existing photos")
    cd = sub.add_parser("cards", help="render recipe cards into a folder to look at")
    cd.add_argument("--only", help="comma-separated dish ids")
    cd.add_argument("--out", default="out/cards")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    cfg = load_config()
    commands = {"build": cmd_build, "send": cmd_send, "dry-run": cmd_dry_run,
                "authorize": cmd_authorize, "status": cmd_status, "newkey": cmd_newkey,
                "library": cmd_library, "photos": cmd_photos, "cards": cmd_cards}
    try:
        return commands[args.cmd](args, cfg)
    except (ConfigError, TikTokError, tokens.TokenError, OpenAIError, FileNotFoundError) as e:
        log(f"\nERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
