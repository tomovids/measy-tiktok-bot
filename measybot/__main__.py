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
    github_output(date=day.isoformat(), built="false")
    if hist.done_on(day):
        log(f"Today's draft ({day}) was already sent. Nothing to do.")
        return 0
    if not config.TOKEN_FILE.exists():
        log("TikTok isn't connected yet (no state/tiktok_token.enc; see SETUP.md step 6). Skipping.")
        return 0
    hh, mm = map(int, cfg["schedule"]["post_time"].split(":"))
    if not (args.force or args.date) and (now.hour, now.minute) < (hh, mm):
        log(f"It's {now:%H:%M} in {cfg['schedule']['timezone']}; posting time is "
            f"{cfg['schedule']['post_time']}. Nothing to do yet.")
        return 0
    build_post(day, cfg, hist, stage.post_folder(day), openai_client(required=True), log=log)
    github_output(built="true")
    return 0


def cmd_send(args, cfg) -> int:
    day = date.fromisoformat(args.date) if args.date else local_now(cfg).date()
    post = stage.load_post(stage.post_folder(day))
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
                          ai_image=not args.no_image, keep_spares=False, log=log)
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
    recipes = catalogue.load_recipes()
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="measybot", description="Measy TikTok slideshow bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build today's slides (GitHub Actions step 1)")
    b.add_argument("--date", help="YYYY-MM-DD (default: today, UK time)")
    b.add_argument("--force", action="store_true", help="build even before the posting time")
    s = sub.add_parser("send", help="send the built slides to TikTok drafts (step 2)")
    s.add_argument("--date")
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
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    cfg = load_config()
    commands = {"build": cmd_build, "send": cmd_send, "dry-run": cmd_dry_run,
                "authorize": cmd_authorize, "status": cmd_status, "newkey": cmd_newkey}
    try:
        return commands[args.cmd](args, cfg)
    except (ConfigError, TikTokError, tokens.TokenError, OpenAIError, FileNotFoundError) as e:
        log(f"\nERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
