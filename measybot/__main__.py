"""Command line: python -m measybot <build|send|dry-run|authorize|status|stats|...> [--account ID].

build / status / stats / dashboard / dry-run work on every account in config.toml unless
--account picks one; authorize and send --post work on one account (default: the first)."""
from __future__ import annotations

import argparse
import copy
import json
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

def post_times(cfg: dict) -> list[tuple[int, int]]:
    times = cfg["schedule"].get("post_times") or [cfg["schedule"]["post_time"]]
    return [tuple(map(int, t.split(":"))) for t in times]


def slot_name(index: int, cfg: dict | None = None) -> str:
    """morning / midday / afternoon, from the post's time (before 11:00 / before 14:00 / later)."""
    hour = post_times(cfg)[index][0] if cfg else (7 if index == 0 else 16)
    return "morning" if hour < 11 else "midday" if hour < 14 else "afternoon"


MANIFEST = config.ROOT / "built.json"


def selected_accounts(args, base_cfg: dict) -> list[config.Account]:
    acct = getattr(args, "account", None)
    return [config.get_account(base_cfg, acct)] if acct else config.accounts(base_cfg)


def switch(acct: config.Account, base_cfg: dict) -> dict:
    """Makes `acct` the current account and returns its settings."""
    config.use_account(acct)
    return config.account_cfg(base_cfg, acct)


def other_histories(acct: config.Account, base_cfg: dict) -> list[History]:
    return [History.load(a.state_dir / "history.json") for a in config.accounts(base_cfg) if a.id != acct.id]


def label(acct: config.Account) -> str:
    return acct.handle or acct.name


def cmd_build(args, base_cfg) -> int:
    """Builds every draft that is due, for every account (or just --account). The list of what was
    built goes in built.json for `send`."""
    github_output(built="false")
    built, errors = [], 0
    for acct in selected_accounts(args, base_cfg):
        cfg = switch(acct, base_cfg)
        try:
            entry = build_one(args, cfg, acct, other_histories(acct, base_cfg))
        except (TikTokError, tokens.TokenError, OpenAIError, FileNotFoundError, ValueError) as e:
            log(f"ERROR building for {label(acct)}: {e}")
            errors += 1
            continue
        if entry:
            built.append(entry)
    MANIFEST.write_text(json.dumps(built, indent=1) + "\n", encoding="utf-8")
    if built:
        github_output(built="true")
    return 1 if errors and not built else 0


def build_one(args, cfg: dict, acct: config.Account, others: list[History]) -> dict | None:
    now = local_now(cfg)
    day = date.fromisoformat(args.date) if args.date else now.date()
    hist = History.load()
    times = post_times(cfg)
    done = hist.count_on(day)
    who = label(acct)
    if acct.overrides.get("paused"):
        log(f"{who}: paused in config.toml. Skipping.")
        return None
    if not config.TOKEN_FILE.exists():
        log(f"{who}: TikTok isn't connected yet (no {config.TOKEN_FILE.relative_to(config.ROOT).as_posix()}; "
            f"run `python -m measybot authorize --account {acct.id}`). Skipping.")
        return None
    if args.again:
        index = (args.slot - 1) if args.slot else min(done, len(times) - 1)
        index = max(0, min(index, len(times) - 1))
        name = f"{day.isoformat()}-{now:%H%M%S}"
        log(f"{who}: extra test draft, it won't count as one of today's scheduled posts.")
    else:
        due = len(times) if (args.force or args.date) else sum(1 for t in times if (now.hour, now.minute) >= t)
        if done >= len(times):
            log(f"{who}: all {len(times)} of today's drafts ({day}) were sent. Nothing to do.")
            return None
        if done >= due:
            nxt = times[done]
            log(f"{who}: it's {now:%H:%M}; the next draft is due at {nxt[0]:02d}:{nxt[1]:02d}. Nothing to do yet.")
            return None
        index, name = done, f"{day.isoformat()}-{done + 1}"
    log(f"\n== {who}: draft {index + 1} of {len(times)} for {day} ({slot_name(index, cfg)}) ==")
    build_post(day, cfg, hist, stage.post_folder(day, name=name), openai_client(required=True), log=log,
               extra=args.again, slot=slot_name(index, cfg), index=index, others=others)
    return {"account": acct.id, "date": day.isoformat(), "post": name}


def cmd_send(args, base_cfg) -> int:
    """Sends what `build` made (built.json), or one post with --post (and --account)."""
    if args.post:
        acct = config.get_account(base_cfg, args.account)
        day = args.date or local_now(base_cfg).date().isoformat()
        entries = [{"account": acct.id, "date": day, "post": args.post}]
    else:
        entries = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    if not entries:
        log("Nothing to send.")
        return 0
    tt = TikTok(secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET"))
    key = secret("TOKEN_KEY")
    failed = 0
    for e in entries:
        acct = config.get_account(base_cfg, e["account"])
        cfg = switch(acct, base_cfg)
        log(f"\n== Sending to {label(acct)} ==")
        try:
            post = stage.load_post(stage.post_folder(date.fromisoformat(e["date"]), name=e["post"]))
            send_post(post, cfg, History.load(), tt, key, log=log)
        except (TikTokError, tokens.TokenError, FileNotFoundError) as err:
            log(f"ERROR sending to {label(acct)}: {err}")
            failed += 1
    return 1 if failed else 0


def cmd_dry_run(args, base_cfg) -> int:
    out = Path(args.out).resolve()
    start = date.fromisoformat(args.start) if args.start else local_now(base_cfg).date()
    ai = None if args.no_ai else openai_client(required=False)
    if ai is None:
        log("No OpenAI key (or --no-ai): using saved hooks and a placeholder background.")
    hists = {}
    for a in config.accounts(base_cfg):
        h = copy.deepcopy(History.load(a.state_dir / "history.json"))
        h.path = None
        hists[a.id] = h
    for i in range(args.days):
        day = start + timedelta(days=i)
        for acct in selected_accounts(args, base_cfg):
            cfg = switch(acct, base_cfg)
            for index in range(len(post_times(cfg))):
                log(f"\n== {label(acct)} {day} {slot_name(index, cfg)} ==")
                folder = out / acct.posts_subdir / f"{day.isoformat()}-{index + 1}"
                others = [h for k, h in hists.items() if k != acct.id]
                post = build_post(day, cfg, hists[acct.id], folder, ai, ai_image=not args.no_image,
                                  keep_spares=False, save_background=True, log=log,
                                  slot=slot_name(index, cfg), index=index, others=others)
                hists[acct.id].add({**post, "status": SENT})   # pretend it was sent, so the next one moves on
    log(f"\nSlides are in {out}")
    return 0


def cmd_authorize(args, base_cfg) -> int:
    acct = config.get_account(base_cfg, args.account)
    cfg = switch(acct, base_cfg)
    who = label(acct)
    t = cfg["tiktok"]
    key = secret("TOKEN_KEY")
    tt = TikTok(secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET"))
    state = pysecrets.token_urlsafe(12)
    url = tt.authorize_url(t["redirect_uri"], t["scopes"], state)
    log(f"Opening TikTok in your browser. Log in as {who} and approve access.")
    log("(If the browser is logged in to a different TikTok account, log out of it first.)")
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
        if name and input(f"Is this {who}? [y/n] ").strip().lower() not in ("y", "yes"):
            log(f"Not saved. Log out of TikTok in the browser, log in as {who} and run authorize again.")
            return 1
    except TikTokError as e:
        log(f"(Couldn't read the account name: {e})")
    tokens.save(login, key)
    path = config.TOKEN_FILE.relative_to(config.ROOT).as_posix()
    log(f"Saved the login for {who} to {path} (encrypted).")
    log(f"Now commit and push it:  git add {path} && git commit -m \"TikTok login\" && git push")
    return 0


def cmd_status(args, base_cfg) -> int:
    key = os.environ.get("TOKEN_KEY")
    for acct in selected_accounts(args, base_cfg):
        cfg = switch(acct, base_cfg)
        log(f"\n== {label(acct)} ==")
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
        log(f"{len(used)} of {len({r.group for r in recipes})} dishes posted at least once.")
        if not config.TOKEN_FILE.exists():
            log(f"Not connected to TikTok yet (run `python -m measybot authorize --account {acct.id}`).")
        elif key:
            try:
                login = tokens.load(key)
                days = (login["refresh_expires_at"] - time.time()) / 86400
                log(f"TikTok login valid for about {days:.0f} more days.")
            except tokens.TokenError as e:
                log(str(e))
    return 0


def cmd_stats(args, base_cfg) -> int:
    """Fetches the TikTok numbers, updates the tuning and rebuilds the dashboard, for each account."""
    from . import dashboard, stats, tuning
    key = secret("TOKEN_KEY")
    tt = TikTok(secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET"))
    errors = 0
    for acct in selected_accounts(args, base_cfg):
        cfg = switch(acct, base_cfg)
        who = label(acct)
        if not config.TOKEN_FILE.exists():
            log(f"{who}: not connected to TikTok yet. Skipping.")
            continue
        try:
            login = tokens.load(key)
            needed = [s for s in ("user.info.stats", "video.list") if s not in login.get("scope", "")]
            if needed:
                log(f"{who}: the TikTok login doesn't have {', '.join(needed)} yet. Run "
                    f"`python -m measybot authorize --account {acct.id}` again. Skipping.")
                continue
            login = tt.refresh(login)
            tokens.save(login, key)
            account = tt.account_stats(login["access_token"])
            videos = tt.videos(login["access_token"], max_pages=cfg.get("tracking", {}).get("video_pages", 10))
        except (TikTokError, tokens.TokenError) as e:
            log(f"ERROR reading the stats for {who}: {e}")
            errors += 1
            continue
        st = stats.update(stats.load(), account, videos, History.load())
        stats.save(st)
        tune = tuning.compute(st, cfg)
        tuning.save(tune)
        matched = sum(1 for v in st["videos"].values() if v.get("post"))
        log(f"{who}: followers {account.get('follower_count')}, {len(videos)} posts read, {matched} matched to "
            f"the bot's drafts, {tune['scored_posts']} scored. Auto-tuning {'ON' if tune['active'] else 'not yet'}"
            f" (needs {tune['needed']} scored posts).")
    dashboard.write_all(base_cfg)
    log(f"Dashboard updated for every account ({dashboard.folder(base_cfg) / 'data.json'}).")
    return 1 if errors else 0


def cmd_dashboard(args, base_cfg) -> int:
    """Rebuilds the dashboard data for every account from the saved stats (no TikTok calls)."""
    from . import dashboard
    dashboard.write_all(base_cfg)
    log(f"Dashboard data written to {dashboard.folder(base_cfg) / 'data.json'}")
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


def cmd_localize(args, cfg) -> int:
    from . import library
    lib = library.localize(openai_client(required=True), cfg, args.region, only=_only(args), log=log)
    log(f"{len(lib)} recipes in {library.library_file(args.region).name}")
    return 0


def cmd_photos(args, cfg) -> int:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from . import library, photos
    lib = library.load()
    only = _only(args)
    client = openai_client(required=True)
    n = args.variants or cfg["cards"]["variants"]
    todo = [(g, v) for g in sorted(lib) if not only or g in only for v in range(1, n + 1)
            if args.redo or not photos.photo_path(g, v).exists()]
    log(f"{len(todo)} photos to make")
    failed = 0
    with ThreadPoolExecutor(args.workers) as pool:
        jobs = {pool.submit(photos.generate, client, lib[g], v, cfg): (g, v) for g, v in todo}
        for i, job in enumerate(as_completed(jobs), 1):
            g, v = jobs[job]
            try:
                job.result()
                log(f"[{i}/{len(todo)}] {g} photo {v}")
            except OpenAIError as e:
                failed += 1
                log(f"[{i}/{len(todo)}] FAILED {g} photo {v}: {str(e)[:200]}")
    return 1 if failed else 0


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
    b.add_argument("--slot", type=int, help="with --again: which of the day's posts to copy (1, 2, 3...)")
    b.add_argument("--account", help="only this account (default: every account)")
    s = sub.add_parser("send", help="send the built slides to TikTok drafts (step 2)")
    s.add_argument("--date")
    s.add_argument("--post", help="send one post: its folder name (default: everything build made)")
    s.add_argument("--account", help="with --post: whose post (default: the first account)")
    d = sub.add_parser("dry-run", help="build some days of slides into a folder; nothing is sent")
    d.add_argument("--days", type=int, default=3)
    d.add_argument("--out", default="out")
    d.add_argument("--start", help="first date (default: today)")
    d.add_argument("--no-ai", action="store_true", help="don't call OpenAI at all")
    d.add_argument("--no-image", action="store_true", help="AI words but a placeholder cover picture")
    d.add_argument("--account", help="only this account (default: every account)")
    au = sub.add_parser("authorize", help="log in to TikTok once (run on your PC)")
    au.add_argument("--account", help="which account (default: the first)")
    st = sub.add_parser("status", help="show recent posts")
    st.add_argument("-n", type=int, default=10)
    st.add_argument("--account", help="only this account")
    sub.add_parser("newkey", help="print a new TOKEN_KEY")
    sx = sub.add_parser("stats", help="read the TikTok numbers, update the tuning and the dashboard (daily)")
    sx.add_argument("--account", help="only this account")
    sub.add_parser("dashboard", help="rebuild the dashboard data from the saved stats")
    lb = sub.add_parser("library", help="build the card-ready recipe library with OpenAI (one-off)")
    lb.add_argument("--only", help="comma-separated dish ids")
    lc = sub.add_parser("localize", help="make the recipe cards for another country (one-off, e.g. --region us)")
    lc.add_argument("--region", default="us")
    lc.add_argument("--only", help="comma-separated dish ids (redo just these)")
    ph = sub.add_parser("photos", help="make the AI food photos for the recipe cards (one-off)")
    ph.add_argument("--only", help="comma-separated dish ids")
    ph.add_argument("--variants", type=int, help="photos per dish (default from config)")
    ph.add_argument("--redo", action="store_true", help="replace existing photos")
    ph.add_argument("--workers", type=int, default=4, help="photos made at the same time")
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
                "library": cmd_library, "localize": cmd_localize, "photos": cmd_photos, "cards": cmd_cards,
                "stats": cmd_stats, "dashboard": cmd_dashboard}
    try:
        return commands[args.cmd](args, cfg)
    except (ConfigError, TikTokError, tokens.TokenError, OpenAIError, FileNotFoundError) as e:
        log(f"\nERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
