"""End-to-end (minus network): two users, different interests/languages/timezones, one pipeline."""

import datetime
from zoneinfo import ZoneInfo

import pytest

from newtalk.api.security import redeem_call_token
from newtalk.composer.user_briefing import assemble_user_briefing, prewarm_segments
from newtalk.config import settings
from newtalk.db.repository import NewTalkRepository
from newtalk.scheduler.ring import tick
from newtalk.tests.unit.helpers import FakeLLM, seed_cluster


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, button=None):
        self.sent.append({"chat_id": chat_id, "text": text, "button": button})


@pytest.fixture
def repo():
    r = NewTalkRepository("sqlite:///:memory:")
    r.create_tables()
    return r


def test_two_users_get_personalised_localised_calls_at_their_times(repo, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://jiya.example")

    seed_cluster(repo, "OpenAI-style startup unveils new AI chip for data centres", source="TechCrunch", score=7.0)
    seed_cluster(repo, "Sensex slips 400 points as FIIs sell banking shares", source="Mint Markets", score=7.2)
    seed_cluster(repo, "SEBI proposes tighter rules for SME IPO listings", source="ET Markets", score=6.4)
    seed_cluster(repo, "IPL: Mumbai beat Chennai in last-ball thriller", source="ESPNcricinfo", score=5.5)

    asha = repo.create_user(auth_provider="invite")  # English, Delhi evening, tech only
    repo.upsert_profile(asha.id, call_name="Asha", interests=["tech"], language="en",
                        call_time="20:00", timezone="Asia/Kolkata")
    repo.set_consent(asha.id, True)
    repo.update_channel(asha.id, telegram_chat_id="chat-asha")

    ravi = repo.create_user(auth_provider="invite")  # Hinglish, tech + stocks
    repo.upsert_profile(ravi.id, call_name="Ravi", interests=["tech", "markets"],
                        free_text="SEBI and IPOs", language="hinglish",
                        call_time="21:30", timezone="Asia/Kolkata")
    repo.set_consent(ravi.id, True)
    repo.update_channel(ravi.id, telegram_chat_id="chat-ravi")

    # the shared pipeline pre-generates segments once for everyone's languages
    llm = FakeLLM()
    prewarm_segments(repo, {"tech", "markets"}, {"en", "hinglish"}, llm=llm)
    warm_calls = llm.calls

    tg = FakeTelegram()
    ist = ZoneInfo("Asia/Kolkata")
    day = lambda h, m: datetime.datetime(2026, 10, 15, h, m, tzinfo=ist)

    def assemble(uid, repo_):
        return assemble_user_briefing(uid, repo_, llm=llm)

    tick(repo, now=day(19, 52), client=tg, assemble=assemble)
    tick(repo, now=day(20, 0), client=tg, assemble=assemble)
    assert [m["chat_id"] for m in tg.sent] == ["chat-asha"], "Ravi is not due until 21:30"
    asha_attempt = repo.get_call_attempt(asha.id, datetime.date(2026, 10, 15), "scheduled")
    repo.update_attempts_for_briefing(asha.id, asha_attempt.briefing_id, status="answered")

    tick(repo, now=day(21, 20), client=tg, assemble=assemble)
    tick(repo, now=day(21, 30), client=tg, assemble=assemble)
    assert [m["chat_id"] for m in tg.sent] == ["chat-asha", "chat-ravi"]
    assert llm.calls == warm_calls, "assembling for two users made no extra LLM calls"

    briefings = {}
    for msg in tg.sent:
        token = msg["button"][1].split("#", 1)[1]
        row = redeem_call_token(repo, token)
        briefings[msg["chat_id"]] = (row.user_id, repo.get_briefing(row.briefing_id))

    asha_user, asha_b = briefings["chat-asha"]
    ravi_user, ravi_b = briefings["chat-ravi"]
    assert asha_user == asha.id and ravi_user == ravi.id

    asha_titles = [s.cluster.representative_title for s in asha_b.stories]
    ravi_titles = [s.cluster.representative_title for s in ravi_b.stories]
    assert any("AI chip" in t for t in asha_titles)
    assert not any("IPL" in t or "SEBI" in t for t in asha_titles)
    assert any("SEBI" in t for t in ravi_titles) and any("Sensex" in t for t in ravi_titles)
    assert not any("IPL" in t for t in ravi_titles)

    assert asha_b.script_text.startswith("Hey Asha!")
    assert "Ravi" in ravi_b.script_text
    assert any("ऀ" <= ch <= "ॿ" for ch in ravi_b.script_text)
    assert not any("ऀ" <= ch <= "ॿ" for ch in asha_b.script_text)
