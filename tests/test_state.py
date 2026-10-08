import pytest

from measybot import pipeline, tokens
from measybot.history import SENT, History
from measybot.tiktok import TikTokError


def test_token_round_trip(tmp_path):
    key = tokens.new_key()
    path = tmp_path / "t.enc"
    tokens.save({"access_token": "a", "refresh_token": "r"}, key, path)
    assert b"refresh_token" not in path.read_bytes()
    assert tokens.load(key, path)["refresh_token"] == "r"
    with pytest.raises(tokens.TokenError):
        tokens.load(tokens.new_key(), path)


def test_history(tmp_path):
    h = History([
        {"date": "2026-10-01", "files": ["a"], "groups": ["g1"], "hook": "h1", "promo": "p1.webp",
         "status": SENT},
        {"date": "2026-10-02", "files": ["b"], "groups": ["g2"], "hook": "h2", "status": "FAILED"},
    ], tmp_path / "h.json")
    assert h.done_on(__import__("datetime").date(2026, 10, 1))
    assert not h.done_on(__import__("datetime").date(2026, 10, 2))
    assert set(h.last_used("groups")) == {"g1"}
    assert h.recent_hooks() == ["h1"]
    p1, p2 = tmp_path / "p1.webp", tmp_path / "p2.webp"
    assert h.next_promo([p1, p2]) == p2
    h.save()
    assert History.load(tmp_path / "h.json").posts == h.posts


class FakeTikTok:
    def __init__(self, fail=None):
        self.fail = fail

    def refresh(self, login):
        return {**login, "access_token": "new", "refresh_expires_at": 9e12}

    def send_photo_draft(self, token, urls, title, desc, ai, log):
        if self.fail:
            raise TikTokError(self.fail)
        assert token == "new" and len(urls) == 7
        return "pid"

    def wait_until_sent(self, token, pid, log):
        return SENT


POST = {"date": "2026-10-09", "slides": [f"p/2026-10-09/0{i}.jpg" for i in range(1, 8)],
        "title": "t", "caption": "c", "hook": "h", "files": ["a"], "groups": ["g"], "promo": "p"}


def test_send_records_success(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr("measybot.config.TOKEN_FILE", tmp_path / "t.enc")
    key = tokens.new_key()
    tokens.save({"access_token": "old", "refresh_token": "r"}, key)
    hist = History([], tmp_path / "h.json")
    status = pipeline.send_post(POST, cfg, hist, FakeTikTok(), key, log=lambda m: None,
                                wait_pages=lambda urls, log: None)
    assert status == SENT
    saved = History.load(tmp_path / "h.json").posts[0]
    assert saved["status"] == SENT and saved["publish_id"] == "pid"
    assert saved["urls"][0] == cfg["tiktok"]["pages_base_url"] + "p/2026-10-09/01.jpg"
    assert tokens.load(key)["access_token"] == "new"


def test_send_records_failure(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr("measybot.config.TOKEN_FILE", tmp_path / "t.enc")
    key = tokens.new_key()
    tokens.save({"access_token": "old", "refresh_token": "r"}, key)
    hist = History([], tmp_path / "h.json")
    with pytest.raises(TikTokError):
        pipeline.send_post(POST, cfg, hist, FakeTikTok("spam_risk_too_many_pending_share"), key,
                           log=lambda m: None, wait_pages=lambda urls, log: None)
    saved = History.load(tmp_path / "h.json")
    assert saved.posts[0]["status"] == "FAILED" and not saved.accepted()


def test_extra_drafts_dont_count_as_the_days_post():
    from datetime import date
    h = History([{"date": "2026-10-09", "files": [], "groups": [], "status": SENT, "extra": True}])
    assert not h.done_on(date(2026, 10, 9))
    h.add({"date": "2026-10-09", "files": [], "groups": [], "status": SENT})
    assert h.done_on(date(2026, 10, 9))
