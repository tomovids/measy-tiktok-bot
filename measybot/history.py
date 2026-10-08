"""What has been posted (state/history.json). Only posts TikTok accepted count as used."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import config

SENT = "SEND_TO_USER_INBOX"
DONE_STATUSES = {SENT, "PUBLISH_COMPLETE"}


class History:
    def __init__(self, posts: list[dict] | None = None, path: Path | None = None):
        self.posts = posts or []
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> "History":
        path = path or config.HISTORY_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data.get("posts", []), path)
        return cls([], path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"posts": self.posts}, ensure_ascii=False, indent=1)
        self.path.write_text(text + "\n", encoding="utf-8")

    def accepted(self) -> list[dict]:
        return [p for p in self.posts if p.get("status") in DONE_STATUSES]

    def done_on(self, day: date) -> bool:
        """Today's scheduled post was sent (extra test drafts don't count)."""
        return any(p["date"] == day.isoformat() and not p.get("extra") for p in self.accepted())

    def count_on(self, day: date) -> int:
        """Scheduled posts sent on this day (extra test drafts don't count)."""
        return sum(1 for p in self.accepted() if p["date"] == day.isoformat() and not p.get("extra"))

    def add(self, post: dict) -> None:
        self.posts.append(post)

    def last_used(self, key: str) -> dict[str, date]:
        """Last date each value of `files` / `groups` appeared in an accepted post."""
        out: dict[str, date] = {}
        for p in self.accepted():
            d = date.fromisoformat(p["date"])
            for v in p.get(key, []):
                if v not in out or d > out[v]:
                    out[v] = d
        return out

    def recent_hooks(self, n: int = 30) -> list[str]:
        posts = sorted(self.accepted(), key=lambda p: p["date"])
        return [p["hook"] for p in posts[-n:] if p.get("hook")]

    def next_promo(self, promos: list[Path]) -> Path:
        """Rotates through the promo slides in file-name order."""
        if not promos:
            raise FileNotFoundError(f"No promo slides in {config.PROMO_DIR}")
        posts = sorted(self.accepted(), key=lambda p: p["date"])
        names = [p.name for p in promos]
        if posts and posts[-1].get("promo") in names:
            return promos[(names.index(posts[-1]["promo"]) + 1) % len(promos)]
        return promos[0]
