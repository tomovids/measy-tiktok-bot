import pytest

from measybot.tiktok import SENT, TikTok, TikTokError, wait_for_urls
from tests.conftest import FakeResponse, FakeSession

OK = {"code": "ok", "message": "", "log_id": "L1"}
URLS = [f"https://x.github.io/r/p/d/0{i}.jpg" for i in range(1, 8)]


def tiktok(responses, clock=None):
    s = FakeSession(responses)
    t = [0.0]
    now = clock or (lambda: t[0])
    return TikTok("key", "secret", session=s, sleep=lambda sec: t.__setitem__(0, t[0] + sec), now=now), s


def test_photo_draft_body():
    tt, s = tiktok([FakeResponse(200, {"data": {"publish_id": "p_1"}, "error": OK})])
    pid = tt.send_photo_draft("tok", URLS, "Title 😋", "Caption", ai_generated=True)
    assert pid == "p_1"
    method, url, kw = s.calls[0]
    assert url.endswith("/v2/post/publish/content/init/")
    body = kw["json"]
    assert body["media_type"] == "PHOTO" and body["post_mode"] == "MEDIA_UPLOAD"
    assert body["is_aigc"] is True
    assert body["post_info"] == {"title": "Title 😋", "description": "Caption"}
    assert body["source_info"] == {"source": "PULL_FROM_URL", "photo_images": URLS,
                                   "photo_cover_index": 0}
    assert kw["headers"]["Authorization"] == "Bearer tok"


def test_ai_label_dropped_if_refused():
    tt, s = tiktok([
        FakeResponse(400, {"error": {"code": "invalid_param", "message": "is_aigc"}}),
        FakeResponse(200, {"data": {"publish_id": "p_2"}, "error": OK}),
    ])
    assert tt.send_photo_draft("tok", URLS, "t", "d", True, log=lambda m: None) == "p_2"
    assert "is_aigc" not in s.calls[1][2]["json"]


def test_pending_drafts_error_has_a_hint():
    tt, _ = tiktok([FakeResponse(403, {"error": {"code": "spam_risk_too_many_pending_share",
                                                 "message": "too many", "log_id": "x"}})])
    with pytest.raises(TikTokError) as e:
        tt.send_photo_draft("tok", URLS, "t", "d", False)
    assert e.value.code == "spam_risk_too_many_pending_share"
    assert "5 waiting drafts" in str(e.value)


def test_retries_server_errors():
    tt, s = tiktok([FakeResponse(503, None, text="busy"),
                    FakeResponse(200, {"data": {"publish_id": "p_3"}, "error": OK})])
    assert tt.send_photo_draft("tok", URLS, "t", "d", False) == "p_3"
    assert len(s.calls) == 2


def test_wait_until_sent():
    tt, _ = tiktok([
        FakeResponse(200, {"data": {"status": "PROCESSING_DOWNLOAD"}, "error": OK}),
        FakeResponse(200, {"data": {"status": SENT}, "error": OK}),
    ])
    assert tt.wait_until_sent("tok", "p_1", log=lambda m: None) == SENT


def test_wait_reports_failure():
    tt, _ = tiktok([FakeResponse(200, {"data": {"status": "FAILED", "fail_reason": "photo_pull_failed"},
                                       "error": OK})])
    with pytest.raises(TikTokError) as e:
        tt.wait_until_sent("tok", "p_1", log=lambda m: None)
    assert e.value.code == "photo_pull_failed"


def test_refresh_token():
    tt, s = tiktok([FakeResponse(200, {"access_token": "a2", "refresh_token": "r2", "open_id": "o",
                                       "scope": "user.info.basic,video.upload", "expires_in": 86400,
                                       "refresh_expires_in": 31536000})],
                   clock=lambda: 1000.0)
    login = tt.refresh({"refresh_token": "r1"})
    assert login["access_token"] == "a2" and login["expires_at"] == 1000 + 86400
    form = s.calls[0][2]["data"]
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "r1"
    assert form["client_key"] == "key" and form["client_secret"] == "secret"


def test_expired_login():
    tt, _ = tiktok([FakeResponse(400, {"error": "invalid_grant", "error_description": "expired"})])
    with pytest.raises(TikTokError) as e:
        tt.refresh({"refresh_token": "r1"})
    assert "authorize" in str(e.value)


def test_authorize_url():
    tt, _ = tiktok([])
    url = tt.authorize_url("https://x.github.io/r/auth.html", ["user.info.basic", "video.upload"], "s1")
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/?client_key=key")
    assert "scope=user.info.basic%2Cvideo.upload" in url and "state=s1" in url


def test_wait_for_urls():
    t = [0.0]
    img = {"Content-Type": "image/jpeg"}
    s = FakeSession([FakeResponse(404, {}, headers={}), FakeResponse(200, {}, headers=img),
                     FakeResponse(200, {}, headers=img), FakeResponse(200, {}, headers=img)])
    wait_for_urls(URLS[:2], session=s, sleep=lambda x: t.__setitem__(0, t[0] + x),
                  now=lambda: t[0], log=lambda m: None)
    assert len(s.calls) == 4
