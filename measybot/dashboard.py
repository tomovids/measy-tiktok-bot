"""Builds the dashboard's data (site/<dashboard_dir>/data.json) from the stats and the tuning."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median

from . import config, library, stats, stores, themes

HOUR_BUCKETS = [(0, 9, "Before 9am"), (9, 12, "9am-12pm"), (12, 15, "12-3pm"), (15, 18, "3-6pm"),
                (18, 21, "6-9pm"), (21, 24, "After 9pm")]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def folder(cfg: dict):
    return config.SITE / cfg.get("tracking", {}).get("dashboard_dir", "insights")


def _labels(cfg: dict) -> dict:
    th = themes.load()
    lib = library.load()
    return {
        "store": {s.id: s.name for s in stores.load(cfg)},
        "collection": {c["id"]: c["label"][:1].upper() + c["label"][1:] for c in th["collections"]},
        "angle": {a["id"]: a["text"].replace("{store}", "the") for a in th["angles"]},
        "lead": {g: e["title"] for g, e in lib.items()},
    }


def _bucket(hour: int) -> str:
    return next(name for a, b, name in HOUR_BUCKETS if a <= hour < b)


def _table(rows: list[dict], key, labels: dict | None = None) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        k = key(r)
        if k:
            groups[k].append(r)
    out = []
    for name, items in groups.items():
        eng = [i["engagement"] for i in items if i.get("engagement") is not None]
        best = max(items, key=lambda i: i["views72"])
        out.append({"name": name, "label": (labels or {}).get(name, name), "posts": len(items),
                    "median_views": round(median(i["views72"] for i in items)),
                    "avg_ratio": round(sum(i["ratio"] for i in items) / len(items), 2),
                    "engagement": round(sum(eng) / len(eng), 4) if eng else None,
                    "best_hook": best.get("hook"), "best_url": best.get("share_url")})
    return sorted(out, key=lambda r: (-r["avg_ratio"], -r["posts"]))


def build(st: dict, tune: dict, cfg: dict, first_bot_day: str | None = None) -> dict:
    tz = cfg["schedule"]["timezone"]
    labels = _labels(cfg)
    rows = stats.scored_posts(st)
    for r in rows:
        h = stats.local_hour(r["posted"], tz)
        r["hour"] = _bucket(h)
        r["weekday"] = WEEKDAYS[datetime.fromisoformat(r["posted"]).weekday()]

    account = st.get("account", [])
    daily = []
    for prev, cur in zip(account, account[1:]):
        if prev.get("total_views") is not None and cur.get("total_views") is not None:
            daily.append({"date": cur["date"], "views": max(0, cur["total_views"] - prev["total_views"])})
    last7 = sum(d["views"] for d in daily[-7:])
    prev7 = sum(d["views"] for d in daily[-14:-7])

    def followers_ago(days: int):
        if not account:
            return None
        cutoff = (date.fromisoformat(account[-1]["date"]) - timedelta(days=days)).isoformat()
        older = [a for a in account if a["date"] <= cutoff]
        return older[-1].get("followers") if older else account[0].get("followers")

    now_f = account[-1].get("followers") if account else None
    recent14 = rows[-14:]
    eng14 = [r["engagement"] for r in recent14 if r.get("engagement") is not None]

    videos = list(st.get("videos", {}).values())
    bot_videos = [v for v in videos if v.get("post")]
    first = first_bot_day or min((v["post"]["date"] for v in bot_videos), default=None)
    pre = [v for v in videos if not v.get("post") and (not first or v["posted"][:10] < first)]
    pre_views = [v["latest"]["views"] for v in pre if v.get("latest")]

    def post_row(v: dict) -> dict:
        p = v.get("post") or {}
        lt = v.get("latest") or {}
        v72 = stats.views_at(v)
        title = (v.get("title") or "").split(" 1. ")[0].strip()
        if len(title) > 110:
            title = title[:107].rsplit(" ", 1)[0] + "..."
        return {"posted": v.get("posted"), "hook": p.get("hook") or title or "(no title)",
                "store": labels["store"].get(p.get("store"), p.get("store") or ""),
                "collection": labels["collection"].get(p.get("collection"), p.get("collection") or ""),
                "angle": labels["angle"].get(p.get("angle"), p.get("angle") or ""),
                "views": lt.get("views"), "views72": round(v72) if v72 is not None else None,
                "likes": lt.get("likes"), "comments": lt.get("comments"), "shares": lt.get("shares"),
                "engagement": stats.engagement(lt) if lt else None, "url": v.get("share_url"),
                "cover": v.get("cover"), "bot": bool(p), "new": v72 is None}

    by_views = sorted(bot_videos, key=lambda v: -(v.get("latest", {}).get("views") or 0))
    recent = sorted(videos, key=lambda v: v.get("posted") or "", reverse=True)[:25]

    def winners(table: list[dict], n: int = 2) -> list[dict]:
        return [t for t in table if t["posts"] >= 2 and t["avg_ratio"] >= 1.1][:n]

    tables = {
        "store": _table(rows, lambda r: r.get("store"), labels["store"]),
        "collection": _table(rows, lambda r: r.get("collection"), labels["collection"]),
        "angle": _table(rows, lambda r: r.get("angle"), labels["angle"]),
        "hour": _table(rows, lambda r: r.get("hour")),
        "weekday": _table(rows, lambda r: r.get("weekday")),
        "lead": _table(rows, lambda r: r.get("lead"), labels["lead"]),
    }
    return {
        "title": cfg.get("account", {}).get("name", "Measy") + " TikTok performance",
        "handle": cfg.get("account", {}).get("handle", ""),
        "updated": st.get("updated") or datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "kpis": {
            "followers": now_f,
            "followers_7d": (now_f - followers_ago(7)) if now_f is not None and followers_ago(7) is not None else None,
            "likes": account[-1].get("likes") if account else None,
            "views_7d": last7, "views_prev_7d": prev7,
            "posts_tracked": len(bot_videos), "posts_scored": len(rows),
            "median_views_14": round(median(r["views72"] for r in recent14)) if recent14 else None,
            "engagement_14": round(sum(eng14) / len(eng14), 4) if eng14 else None,
            "pre_bot_median": round(median(pre_views)) if pre_views else None,
            "pre_bot_posts": len(pre_views),
        },
        "account": account, "daily_views": daily,
        "top_posts": [post_row(v) for v in by_views[:15]],
        "recent": [post_row(v) for v in recent],
        "tables": tables,
        "double_down": {k: winners(t) for k, t in tables.items() if k in ("collection", "angle", "lead", "hour",
                                                                         "store")},
        "tuning": {"active": tune.get("active", False), "scored": tune.get("scored_posts", 0),
                   "needed": tune.get("needed", 14), "explore": tune.get("explore", 0.25),
                   "multipliers": {k: [{"name": n, "label": labels.get(k, {}).get(n, n), **v}
                                       for n, v in sorted(m.items(), key=lambda kv: -kv[1]["mult"])]
                                   for k, m in tune.get("multipliers", {}).items()},
                   "top_hooks": tune.get("top_hooks", [])},
    }


def write(data: dict, cfg: dict) -> None:
    out = folder(cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---- every account on one page ------------------------------------------------------------------

STATUS = {"SEND_TO_USER_INBOX": "In drafts", "PUBLISH_COMPLETE": "Posted", "FAILED": "Failed",
          "PROCESSING_DOWNLOAD": "Sending", "PROCESSING_UPLOAD": "Sending"}
FLAGS = {"uk": "🇬🇧", "us": "🇺🇸"}
TZ_SHORT = {"Europe/London": "UK", "America/New_York": "ET"}


def _drafts(hist, cfg: dict, labels: dict, now: datetime) -> dict:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    uk = ZoneInfo("Europe/London")
    local = now.astimezone(tz)
    times = [tuple(map(int, t.split(":"))) for t in cfg["schedule"]["post_times"]]
    done = hist.count_on(local.date())
    if done < len(times):
        h, m = times[done]
        nxt, day = local.replace(hour=h, minute=m, second=0, microsecond=0), "today"
    else:
        h, m = times[0]
        nxt, day = (local + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0), "tomorrow"
    overdue = nxt <= local
    short = TZ_SHORT.get(cfg["schedule"]["timezone"], "")
    clock = f"{nxt:%H:%M}" + (f" {short} ({nxt.astimezone(uk):%H:%M} UK)" if short != "UK" else "")
    nxt_txt = f"{clock} draft due now" if overdue else f"next {day} {clock}"
    posts = sorted(hist.posts, key=lambda p: p.get("sent_at") or p.get("built_at") or p["date"], reverse=True)
    rows = []
    for p in posts[:30]:
        th = p.get("theme") or {}
        rows.append({"date": p["date"], "sent_at": p.get("sent_at"), "slot": p.get("slot"),
                     "store": labels["store"].get(p.get("store"), p.get("store") or ""),
                     "theme": labels["collection"].get(th.get("collection"), th.get("label") or ""),
                     "hook": p.get("hook"), "subline": p.get("subline"), "score": p.get("hook_score"),
                     "status": STATUS.get(p.get("status"), (p.get("status") or "").replace("_", " ").title()),
                     "failed": p.get("status") == "FAILED", "test": bool(p.get("extra")),
                     "error": _error(p.get("error"))})
    return {"today": done, "per_day": len(times), "next": nxt_txt, "overdue": overdue, "local_date": local.date().isoformat(),
            "times": cfg["schedule"]["post_times"], "timezone": short or cfg["schedule"]["timezone"],
            "recent": rows}


def _error(text: str | None) -> str | None:
    if not text:
        return None
    if "too_many_pending" in text:
        return "TikTok's limit of 5 waiting drafts was hit"
    first = text.splitlines()[0]
    return first.split(" (log id")[0][:160]


def _login_days() -> float | None:
    import os
    import time
    from . import tokens
    key = os.environ.get("TOKEN_KEY")
    if not key or not config.TOKEN_FILE.exists():
        return None
    try:
        return round((tokens.load(key)["refresh_expires_at"] - time.time()) / 86400)
    except tokens.TokenError:
        return None


def build_all(base_cfg: dict, now: datetime | None = None) -> dict:
    """One dashboard for every account (written to the first account's dashboard folder)."""
    from . import tuning
    from .history import History
    now = now or datetime.now(timezone.utc)
    out = []
    try:
        for acct in config.accounts(base_cfg):
            config.use_account(acct)
            cfg = config.account_cfg(base_cfg, acct)
            st = stats.load()
            has_stats = bool(st.get("account"))
            tune = tuning.compute(st, cfg)
            region = cfg["region"]["id"]
            out.append({
                "id": acct.id, "name": acct.name, "handle": acct.handle, "region": region,
                "flag": FLAGS.get(region, ""), "currency": cfg["region"]["currency"],
                "connected": config.TOKEN_FILE.exists(), "paused": bool(acct.overrides.get("paused")),
                "login_days": _login_days(),
                "stores": [s.name for s in stores.load(cfg)],
                "drafts": _drafts(History.load(), cfg, _labels(cfg), now),
                "stats": build(st, tune, cfg) if has_stats else None,
            })
    finally:
        config.use_account(config.accounts(base_cfg)[0])
    return {"updated": now.isoformat(timespec="minutes"), "accounts": out}


def write_all(base_cfg: dict) -> None:
    write(build_all(base_cfg), config.account_cfg(base_cfg, config.accounts(base_cfg)[0]))
