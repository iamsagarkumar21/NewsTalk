"""Call-me-now, Telegram linking, transcripts and retention."""

import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newtalk.api import security
from newtalk.api.routes import router
from newtalk.config import settings
from newtalk.db.repository import NewTalkRepository
from newtalk.notify import telegram
from newtalk.scheduler import ring

PROFILE = {
    "call_name": "Sagar",
    "interests": ["tech"],
    "call_time": "21:30",
    "language": "en",
    "timezone": "Asia/Kolkata",
}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "stayInNews_bot")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://jiya.example")
    security.login_limiter._events.clear()


@pytest.fixture
def repo(tmp_path):
    r = NewTalkRepository(f"sqlite:///{tmp_path / 'r.db'}")
    r.create_tables()
    return r


@pytest.fixture
def app(repo):
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[security.get_repo] = lambda: repo
    return application


@pytest.fixture
def stub_assemble(monkeypatch):
    def fake(user_id, repo):
        b = repo.create_briefing("Hello. World.", 30, story_count=2, user_id=user_id)
        return {"briefing_id": b.id, "story_count": 2}

    monkeypatch.setattr(ring, "assemble_user_briefing", fake)
    return fake


def signed_in(app, repo, consent=True, profile=True):
    c = TestClient(app)
    code = repo.create_invite_code().code
    uid = c.post("/api/session", json={"code": code}).json()["user_id"]
    if profile:
        assert c.put("/api/me", json=PROFILE).status_code == 200
    if consent:
        c.post("/api/me/consent", json={"granted": True})
    return c, uid


def test_call_now_requires_profile_and_consent(app, repo, stub_assemble):
    c, _ = signed_in(app, repo, consent=False)
    r = c.post("/api/me/call")
    assert r.status_code == 409 and "consent" in r.json()["detail"].lower()


def test_call_now_returns_redeemable_token_and_limits_to_three(app, repo, stub_assemble):
    c, uid = signed_in(app, repo)
    first = c.post("/api/me/call")
    assert first.status_code == 200
    body = first.json()
    assert body["call_path"] == f"/app/call.html#{body['token']}"
    assert security.redeem_call_token(repo, body["token"]).user_id == uid
    assert c.post("/api/me/call").status_code == 200
    assert c.post("/api/me/call").status_code == 200
    fourth = c.post("/api/me/call")
    assert fourth.status_code == 429 and "3 test calls" in fourth.json()["detail"]


def test_telegram_link_flow(app, repo):
    c, uid = signed_in(app, repo, consent=False)
    status = c.get("/api/me/telegram").json()
    assert status["linked"] is False
    assert status["link_url"].startswith("https://t.me/stayInNews_bot?start=")
    token = status["link_url"].split("start=")[1]
    assert security.verify_link_token(token) == uid

    class Bot:
        def __init__(self):
            self.sent = []

        def send_message(self, chat_id, text, button=None):
            self.sent.append((chat_id, text))

    bot = Bot()
    telegram.handle_update(
        {"message": {"text": f"/start {token}", "chat": {"id": 4242}}}, repo, bot
    )
    assert "Connected, Sagar" in bot.sent[0][1]
    assert c.get("/api/me/telegram").json()["linked"] is True

    telegram.handle_update({"message": {"text": "/stop", "chat": {"id": 4242}}}, repo, bot)
    assert c.get("/api/me").json()["paused"] is True
    telegram.handle_update({"message": {"text": "/resume", "chat": {"id": 4242}}}, repo, bot)
    assert c.get("/api/me").json()["paused"] is False

    assert c.delete("/api/me/telegram").json() == {"linked": False}
    assert c.get("/api/me/telegram").json()["linked"] is False


def test_link_token_expires_and_rejects_forgery(repo):
    token = security.sign_link_token(7, now=1000)
    assert security.verify_link_token(token, now=1000) == 7
    assert security.verify_link_token(token, now=1000 + 99999) is None
    assert security.verify_link_token(token.replace("7_", "8_", 1), now=1000) is None
    assert security.verify_link_token("junk") is None


def test_chat_belongs_to_one_user(repo):
    a = repo.create_user(auth_provider="invite")
    b = repo.create_user(auth_provider="invite")
    for u in (a, b):
        repo.upsert_profile(u.id, call_name="x", interests=["tech"])

    class Bot:
        def send_message(self, *a, **k):
            pass

    telegram.handle_update(
        {"message": {"text": f"/start {security.sign_link_token(a.id)}", "chat": {"id": 1}}}, repo, Bot()
    )
    telegram.handle_update(
        {"message": {"text": f"/start {security.sign_link_token(b.id)}", "chat": {"id": 1}}}, repo, Bot()
    )
    assert repo.get_user_id_by_chat("1") == b.id
    assert repo.get_channel(a.id).telegram_chat_id is None


def test_transcripts_are_listed_only_for_owner(app, repo, stub_assemble):
    c1, uid1 = signed_in(app, repo)
    c2, _ = signed_in(app, repo)
    c1.post("/api/me/call")
    mine = c1.get("/api/me/calls").json()
    assert mine["attempts"] and mine["transcripts"][0]["script"] == "Hello. World."
    assert c2.get("/api/me/calls").json() == {"attempts": [], "transcripts": []}
    assert uid1


def test_retention_purges_old_text_but_keeps_owner_history(repo):
    user = repo.create_user(auth_provider="invite")
    old = datetime.date.today() - datetime.timedelta(days=45)
    b_old = repo.create_briefing("old text", 10, date=old, user_id=user.id)
    repo.log_qa(b_old.id, "q", "a", user_id=user.id)
    b_new = repo.create_briefing("new text", 10, user_id=user.id)
    owner_old = repo.create_briefing("owner old", 10, date=old)  # legacy owner row

    out = repo.purge_user_history(older_than_days=30)
    assert out["briefings"] == 1
    assert repo.get_briefing(b_old.id) is None
    assert repo.get_briefing(b_new.id) is not None
    assert repo.get_briefing(owner_old.id) is not None
