"""Doubling down on what works (state/tuning.json), worked out from state/stats.json.

Each scored post (views at 3 days old vs the median of the last 30) feeds a multiplier for its
theme collection, angle and lead dish: the average score, pulled towards 1.0 by a prior of
`prior_posts` imaginary average posts so one lucky post can't swing it, clamped to 0.5x-2x.
Nothing changes until `min_posts` posts have been scored. `explore` of posts (1 in 4) ignore the
tuning so new ideas keep getting tried. Supermarkets are reported, not tuned: they follow the
fixed test rotation. The best new hooks become examples for the writer.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from . import config, stats

TUNING_FILE = config.STATE / "tuning.json"
DIMENSIONS = {"collection": "collection", "angle": "angle", "lead": "lead"}


def defaults(cfg: dict) -> dict:
    t = cfg.get("tracking", {})
    return {"min_posts": t.get("min_posts", 14), "prior_posts": t.get("prior_posts", 3),
            "explore": t.get("explore", 0.25), "min_mult": t.get("min_mult", 0.5),
            "max_mult": t.get("max_mult", 2.0), "top_hooks": t.get("top_hooks", 6)}


def compute(st: dict, cfg: dict) -> dict:
    d = defaults(cfg)
    rows = stats.scored_posts(st)
    out = {"active": len(rows) >= d["min_posts"], "scored_posts": len(rows), "needed": d["min_posts"],
           "explore": d["explore"], "multipliers": {}, "top_hooks": []}
    for key in DIMENSIONS:
        groups: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            if r.get(key):
                groups[r[key]].append(r["ratio"])
        mults = {}
        for name, ratios in groups.items():
            k = d["prior_posts"]
            m = (sum(ratios) + k * 1.0) / (len(ratios) + k)
            mults[name] = {"mult": round(min(d["max_mult"], max(d["min_mult"], m)), 2),
                           "posts": len(ratios), "avg_ratio": round(sum(ratios) / len(ratios), 2)}
        out["multipliers"][key] = mults
    best = sorted(rows, key=lambda r: -r["views72"])[: d["top_hooks"]]
    out["top_hooks"] = [{"hook": r["hook"], "subline": r.get("subline") or "", "views": int(r["views72"]),
                         "store": r.get("store")} for r in best if r.get("hook")]
    return out


def load() -> dict:
    if TUNING_FILE.exists():
        return json.loads(TUNING_FILE.read_text(encoding="utf-8"))
    return {"active": False, "multipliers": {}, "top_hooks": [], "explore": 0.25}


def save(t: dict) -> None:
    TUNING_FILE.parent.mkdir(parents=True, exist_ok=True)
    TUNING_FILE.write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def for_post(rng: random.Random, t: dict | None = None) -> dict:
    """The multipliers this post uses: {} when tuning is off or this post explores."""
    t = t if t is not None else load()
    if not t.get("active") or rng.random() < t.get("explore", 0.25):
        return {}
    return {k: {n: v["mult"] for n, v in m.items()} for k, m in t.get("multipliers", {}).items()}
