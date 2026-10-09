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
        return {"posted": v.get("posted"), "hook": p.get("hook") or v.get("title") or "(no title)",
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
