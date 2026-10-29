"""Dashboard API: invite sign-in, profile validation, consent, pause, delete, admin guard."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newtalk.api import security
from newtalk.api.routes import router
from newtalk.config import settings
from newtalk.db.repository import NewTalkRepository

ADMIN_KEY = "test-admin-key"

VALID_PROFILE = {
    "call_name": "Sagar bhai",
    "interests": ["tech", "markets"],
    "free_text": "Indian startups",
    "call_time": "21:30",
    "language": "hinglish",
    "timezone": "Asia/Kolkata",
}


@pytest.fixture
def repo(tmp_path):
    r = NewTalkRepository(f"sqlite:///{tmp_path / 'api.db'}")
    r.create_tables()
    return r


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(settings, "ADMIN_API_KEY", ADMIN_KEY)
    security.login_limiter._events.clear()


@pytest.fixture
def app(repo):
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[security.get_repo] = lambda: repo
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def _signed_in(app, repo):
    c = TestClient(app)
    code = repo.create_invite_code().code
    assert c.post("/api/session", json={"code": code}).status_code == 200
    return c, code


def _detail_fields(response):
    return {
        ".".join(str(p) for p in err["loc"][1:]) for err in response.json()["detail"]
    }


def test_topics_are_public(client):
    data = client.get("/api/topics").json()
    assert {"tech", "markets", "politics", "geopolitics"} <= {
        t["slug"] for t in data["topics"]
    }
    assert [lang["code"] for lang in data["languages"]] == ["en", "hinglish", "hi"]


def test_unauthenticated_requests_see_nothing(client):
    assert client.get("/api/me").status_code == 401
    assert client.put("/api/me", json=VALID_PROFILE).status_code == 401
    assert client.post("/api/me/consent", json={"granted": True}).status_code == 401


def test_invalid_invite_code_creates_no_account(client, repo):
    r = client.post("/api/session", json={"code": "nope"})
    assert r.status_code == 401
    assert "nt_session" not in r.cookies
    assert client.get("/api/me").status_code == 401


def test_invite_signup_then_login_again(app, repo):
    code = repo.create_invite_code().code
    first = TestClient(app)
    r1 = first.post("/api/session", json={"code": code})
    assert r1.json()["is_new"] is True
    second = TestClient(app)  # new device, same code
    r2 = second.post("/api/session", json={"code": code})
    assert r2.json() == {"user_id": r1.json()["user_id"], "is_new": False}


def test_new_user_defaults(app, repo):
    c, _ = _signed_in(app, repo)
    me = c.get("/api/me").json()
    assert me["profile"] is None
    assert me["defaults"] == {"language": "en", "timezone": "Asia/Kolkata"}
    assert me["consented"] is False and me["paused"] is False


@pytest.mark.parametrize(
    "change, field",
    [
        ({"call_name": "   "}, "call_name"),
        ({"call_name": "x" * 41}, "call_name"),
        ({"call_time": "21:33"}, "call_time"),
        ({"call_time": "25:00"}, "call_time"),
        ({"language": "klingon"}, "language"),
        ({"interests": ["cooking"]}, "interests"),
        ({"timezone": "Mars/Olympus"}, "timezone"),
        ({"free_text": "x" * 301}, "free_text"),
        ({"interests": [], "free_text": None}, "interests"),
    ],
)
def test_profile_validation_names_the_field(app, repo, change, field):
    c, _ = _signed_in(app, repo)
    r = c.put("/api/me", json={**VALID_PROFILE, **change})
    assert r.status_code == 422
    assert field in _detail_fields(r)


def test_profile_save_and_read_back(app, repo):
    c, _ = _signed_in(app, repo)
    saved = c.put("/api/me", json=VALID_PROFILE).json()["profile"]
    assert saved["call_name"] == "Sagar bhai"
    assert saved["interests"] == ["tech", "markets"]
    assert saved["call_time"] == "21:30"
    assert saved["language"] == "hinglish"
    assert c.get("/api/me").json()["profile"] == saved


def test_free_text_only_profile_is_accepted(app, repo):
    c, _ = _signed_in(app, repo)
    r = c.put(
        "/api/me",
        json={"call_name": "Asha", "interests": [], "free_text": "SEBI and startups"},
    )
    assert r.status_code == 200
    assert r.json()["profile"]["language"] == "en"
    assert r.json()["profile"]["timezone"] == "Asia/Kolkata"


def test_consent_requires_profile_then_can_be_withdrawn(app, repo):
    c, _ = _signed_in(app, repo)
    assert c.post("/api/me/consent", json={"granted": True}).status_code == 409
    c.put("/api/me", json=VALID_PROFILE)
    assert c.post("/api/me/consent", json={"granted": True}).json()["consented"] is True
    assert (
        c.post("/api/me/consent", json={"granted": False}).json()["consented"] is False
    )


def test_pause_and_resume(app, repo):
    c, _ = _signed_in(app, repo)
    c.put("/api/me", json=VALID_PROFILE)
    assert c.post("/api/me/pause", json={"paused": True}).json()["paused"] is True
    assert c.post("/api/me/pause", json={"paused": False}).json()["paused"] is False


def test_users_only_see_their_own_profile(app, repo):
    a, _ = _signed_in(app, repo)
    b, _ = _signed_in(app, repo)
    a.put("/api/me", json=VALID_PROFILE)
    assert b.get("/api/me").json()["profile"] is None
    assert a.get("/api/me").json()["profile"]["call_name"] == "Sagar bhai"


def test_delete_requires_confirmation_and_erases(app, repo):
    c, code = _signed_in(app, repo)
    c.put("/api/me", json=VALID_PROFILE)
    user_id = c.get("/api/me").json()["user_id"]

    assert c.request("DELETE", "/api/me", json={"confirm": False}).status_code == 400
    assert c.request("DELETE", "/api/me", json={"confirm": True}).json() == {
        "deleted": True
    }

    assert repo.get_user(user_id) is None
    assert repo.get_profile(user_id) is None
    assert c.get("/api/me").status_code == 401
    # the same code starts a brand new account
    r = TestClient(app).post("/api/session", json={"code": code})
    assert r.json()["is_new"] is True and r.json()["user_id"] != user_id


def test_tampered_and_expired_cookies_are_rejected(app, repo):
    c, _ = _signed_in(app, repo)
    good = c.cookies.get("nt_session")
    user_part, exp, sig = good.split(".")

    forged = TestClient(app)
    forged.cookies.set("nt_session", f"999.{exp}.{sig}")
    assert forged.get("/api/me").status_code == 401

    expired = TestClient(app)
    expired.cookies.set("nt_session", security.sign_session(int(user_part), now=0))
    assert expired.get("/api/me").status_code == 401


def test_sign_out_clears_session(app, repo):
    c, _ = _signed_in(app, repo)
    c.delete("/api/session")
    assert c.get("/api/me").status_code == 401


def test_login_attempts_are_rate_limited(client):
    statuses = [
        client.post("/api/session", json={"code": f"bad{i}"}).status_code
        for i in range(12)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10:] == [429, 429]


def test_admin_invites_need_the_key(client, repo):
    assert client.post("/api/admin/invites", json={"count": 2}).status_code == 401
    wrong = client.post(
        "/api/admin/invites", json={"count": 2}, headers={"X-Admin-Key": "x"}
    )
    assert wrong.status_code == 401
    ok = client.post(
        "/api/admin/invites", json={"count": 2}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    codes = ok.json()["codes"]
    assert len(codes) == 2
    assert client.post("/api/session", json={"code": codes[0]}).json()["is_new"] is True


def test_admin_fails_closed_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", None)
    r = client.post("/api/admin/invites", json={}, headers={"X-Admin-Key": "anything"})
    assert r.status_code == 503


def test_rate_limiter_window():
    limiter = security.RateLimiter(max_events=2, window_seconds=10)
    assert limiter.hit("ip", now=0) and limiter.hit("ip", now=1)
    assert not limiter.hit("ip", now=2)
    assert limiter.hit("ip", now=11)
