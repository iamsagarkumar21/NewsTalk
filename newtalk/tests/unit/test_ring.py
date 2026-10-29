"""Scheduler tick: assemble at T-10, ring at T, no duplicates, missed-call reminder."""

import datetime
from zoneinfo import ZoneInfo

import pytest

from newtalk.api.security import redeem_call_token
from newtalk.config import settings
from newtalk.db.repository import NewTalkRepository
from newtalk.scheduler.ring import tick

IST = ZoneInfo("Asia/Kolkata")


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, button=None):
        self.sent.append({"chat_id": chat_id, "text": text, "button": button})


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://jiya.example")


@pytest.fixture
def repo():
    r = NewTalkRepository("sqlite:///:memory:")
    r.create_tables()
    return r


def fake_assemble(user_id, repo):
    b = repo.create_briefing("script", 120, story_count=3, user_id=user_id)
    return {"briefing_id": b.id, "story_count": 3}


def make_user(repo, name="Sagar", call_time="21:30", tz="Asia/Kolkata", consent=True,
              paused=False, telegram=True, language="en"):
    user = repo.create_user(auth_provider="invite")
    repo.upsert_profile(
        user.id, call_name=name, interests=["tech"], call_time=call_time, timezone=tz, language=language
    )
    if consent:
        repo.set_consent(user.id, True)
    if paused:
        repo.set_paused(user.id, True)
    if telegram:
        repo.update_channel(user.id, telegram_chat_id=f"chat-{user.id}")
    return user


def at(hour, minute, day=15):
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=IST)


def test_assembles_ten_minutes_early_then_rings_on_time(repo):
    user = make_user(repo)
    tg = FakeTelegram()

    s1 = tick(repo, now=at(21, 19), client=tg, assemble=fake_assemble)  # before the window
    assert s1["assembled"] == 0

    s2 = tick(repo, now=at(21, 20), client=tg, assemble=fake_assemble)
    assert (s2["assembled"], s2["rung"]) == (1, 0) and tg.sent == []

    s3 = tick(repo, now=at(21, 30), client=tg, assemble=fake_assemble)
    assert s3["rung"] == 1
    msg = tg.sent[0]
    assert msg["chat_id"] == f"chat-{user.id}" and "Sagar" in msg["text"]
    label, url = msg["button"]
    assert url.startswith("https://jiya.example/app/call.html#")
    token = url.split("#", 1)[1]
    assert redeem_call_token(repo, token) is not None  # real, redeemable token
    assert redeem_call_token(repo, token) is None  # single use


def test_restart_and_duplicate_ticks_never_double_ring(repo):
    make_user(repo)
    tg = FakeTelegram()
    for minute in (20, 29, 30, 30, 31, 32):
        tick(repo, now=at(21, minute), client=tg, assemble=fake_assemble)
    assert len(tg.sent) == 1


def test_late_start_inside_grace_still_rings_once(repo):
    make_user(repo)
    tg = FakeTelegram()
    tick(repo, now=at(21, 38), client=tg, assemble=fake_assemble)  # server was down until now
    assert len(tg.sent) == 1


def test_far_too_late_is_skipped(repo):
    make_user(repo)
    tg = FakeTelegram()
    tick(repo, now=at(22, 30), client=tg, assemble=fake_assemble)
    assert tg.sent == []


def test_paused_unconsented_and_unlinked_users(repo):
    make_user(repo, name="Paused", paused=True)
    make_user(repo, name="NoConsent", consent=False)
    unlinked = make_user(repo, name="Unlinked", telegram=False)
    tg = FakeTelegram()
    stats = tick(repo, now=at(21, 30), client=tg, assemble=fake_assemble)
    assert tg.sent == []
    assert stats["undeliverable"] == 1
    att = repo.list_call_attempts(unlinked.id)[0]
    assert att.status == "undeliverable"


def test_call_time_respects_user_timezone(repo):
    ny = make_user(repo, name="Ny", call_time="09:00", tz="America/New_York")
    make_user(repo, name="Ist", call_time="21:30")
    tg = FakeTelegram()
    # 21:30 IST == 12:00 noon in New York (EDT, UTC-4) -> only the IST user is due
    tick(repo, now=at(21, 30), client=tg, assemble=fake_assemble)
    assert [m["text"] for m in tg.sent if "Ist" in m["text"]]
    assert not [m for m in tg.sent if m["chat_id"] == f"chat-{ny.id}"]


def test_twenty_users_due_at_once_none_dropped(repo):
    users = [make_user(repo, name=f"U{i}") for i in range(20)]
    tg = FakeTelegram()
    first = tick(repo, now=at(21, 30), client=tg, assemble=fake_assemble, max_assemble=10)
    assert first["assembled"] == 10 and first["deferred"] == 10
    second = tick(repo, now=at(21, 31), client=tg, assemble=fake_assemble, max_assemble=10)
    assert second["assembled"] == 10
    assert len({m["chat_id"] for m in tg.sent}) == 20
    assert len(tg.sent) == 20 and len(users) == 20


def test_missed_call_gets_one_reminder(repo):
    user = make_user(repo)
    tg = FakeTelegram()
    tick(repo, now=at(21, 30), client=tg, assemble=fake_assemble)
    assert len(tg.sent) == 1
    s = tick(repo, now=at(21, 41), client=tg, assemble=fake_assemble)
    assert s["missed"] == 1 and len(tg.sent) == 2
    assert "missed" in tg.sent[1]["text"].lower()
    tick(repo, now=at(21, 50), client=tg, assemble=fake_assemble)
    tick(repo, now=at(22, 5), client=tg, assemble=fake_assemble)
    assert len(tg.sent) == 2  # exactly one reminder
    assert repo.get_call_attempt(user.id, datetime.date(2026, 10, 15), "scheduled").status == "missed"


def test_answered_call_is_not_marked_missed(repo):
    user = make_user(repo)
    tg = FakeTelegram()
    tick(repo, now=at(21, 30), client=tg, assemble=fake_assemble)
    att = repo.get_call_attempt(user.id, datetime.date(2026, 10, 15), "scheduled")
    repo.update_attempts_for_briefing(user.id, att.briefing_id, status="answered")
    tick(repo, now=at(21, 45), client=tg, assemble=fake_assemble)
    assert len(tg.sent) == 1


def test_assembly_failure_is_recorded_and_user_told(repo):
    user = make_user(repo)
    tg = FakeTelegram()

    def boom(uid, repo):
        raise RuntimeError("llm down")

    s = tick(repo, now=at(21, 25), client=tg, assemble=boom)
    assert s["failed"] == 1
    assert "couldn't prepare" in tg.sent[0]["text"]
    assert repo.get_call_attempt(user.id, datetime.date(2026, 10, 15), "scheduled").status == "failed"
    tick(repo, now=at(21, 30), client=tg, assemble=boom)
    assert len(tg.sent) == 1  # no retry storm, no ring


def test_hinglish_ring_text_is_localized(repo):
    make_user(repo, name="Riya", language="hinglish")
    tg = FakeTelegram()
    tick(repo, now=at(21, 30), client=tg, assemble=fake_assemble)
    assert "Jiya" in tg.sent[0]["text"] and "Riya" in tg.sent[0]["text"]
    assert any("ऀ" <= ch <= "ॿ" for ch in tg.sent[0]["text"])
