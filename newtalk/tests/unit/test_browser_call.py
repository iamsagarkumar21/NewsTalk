"""Browser call WebSocket: auth, single-use tokens, streaming, barge-in, goodbye."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newtalk.api import security
from newtalk.config import settings
from newtalk.db.repository import NewTalkRepository
from newtalk.voice import browser_call, session as session_mod


class FakeTTS:
    name = "fake"
    audio_format = "mp3"

    def __init__(self):
        self.spoken = []

    async def synthesize_stream_cancellable(self, text, cancel):
        self.spoken.append(text)
        for part in (b"ID3", text.encode()[:8]):
            if cancel.is_set():
                return
            yield part
            await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_SECRET", "s3cret")
    browser_call._live = 0


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = NewTalkRepository(f"sqlite:///{tmp_path / 'call.db'}")
    repo.create_tables()
    tts = FakeTTS()
    monkeypatch.setattr(browser_call, "get_repo", lambda: repo)
    monkeypatch.setattr(browser_call, "tts_for", lambda lang, fmt="mp3": tts)

    def fake_llm(role, messages, **kw):
        msg = SimpleNamespace(content="Short answer from Jiya.")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr(session_mod, "call_llm", fake_llm)

    app = FastAPI()
    app.include_router(browser_call.router)
    return SimpleNamespace(repo=repo, tts=tts, client=TestClient(app))


def make_call(repo, language="en", script="Hello there. Second sentence here. Third one now."):
    user = repo.create_user(auth_provider="invite")
    repo.upsert_profile(user.id, call_name="Sagar", interests=["tech"], language=language, call_time="21:30")
    repo.set_consent(user.id, True)
    briefing = repo.create_briefing(script, 60, story_count=1, user_id=user.id)
    token = security.issue_call_token(repo, user.id, briefing.id)
    return user, briefing, token


def collect_until(ws, stop_types, limit=60):
    events, binaries = [], 0
    for _ in range(limit):
        msg = ws.receive()
        if msg.get("bytes") is not None:
            binaries += 1
            continue
        ev = json.loads(msg["text"])
        events.append(ev)
        if ev["type"] in stop_types:
            break
    return events, binaries


def test_valid_token_streams_briefing_with_audio(env):
    user, briefing, token = make_call(env.repo)
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        events, binaries = collect_until(ws, {"sentence_end"})
        types = [e["type"] for e in events]
        assert types[0] == "ready"
        start = next(e for e in events if e["type"] == "briefing_start")
        assert start["audio_format"] == "mp3" and start["language"] == "en"
        assert start["stt_lang"] == "en-IN"
        assert any(e["type"] == "speaking" and e["text"].startswith("Hello there.") for e in events)
        assert binaries >= 1
        ws.send_text(json.dumps({"type": "stop"}))
    attempt_updates = env.repo.list_call_attempts(user.id)
    assert attempt_updates == []  # no attempt row was created for this ad-hoc token


def test_token_is_single_use(env):
    _user, _b, token = make_call(env.repo)
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_text(json.dumps({"type": "stop"}))
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        assert json.loads(ws.receive_text())["type"] == "error"


@pytest.mark.parametrize("token", ["", "garbage", "abc.def", None])
def test_bad_tokens_are_rejected(env, token):
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        assert json.loads(ws.receive_text())["type"] == "error"


def test_token_for_another_users_briefing_is_rejected(env):
    user_a, briefing_a, _ = make_call(env.repo)
    user_b = env.repo.create_user(auth_provider="invite")
    env.repo.upsert_profile(user_b.id, call_name="B", interests=["tech"])
    token = security.issue_call_token(env.repo, user_b.id, briefing_a.id)  # B + A's briefing
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        assert json.loads(ws.receive_text())["type"] == "error"
    assert user_a.id != user_b.id


def test_no_auth_frame_closes(env):
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "hello"}))
        with pytest.raises(Exception):
            ws.receive_text()


def test_barge_in_answers_then_goodbye_ends_call(env):
    user, briefing, token = make_call(env.repo)
    env.repo.claim_call_slot(user.id, __import__("datetime").date.today(), "scheduled", briefing.id)
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        collect_until(ws, {"speaking"})
        ws.send_text(json.dumps({"type": "speech_started"}))
        ws.send_text(json.dumps({"type": "transcript", "text": "what does that mean"}))
        events, _ = collect_until(ws, {"qa_response"})
        qa = next(e for e in events if e["type"] == "qa_response")
        assert qa["answer"] == "Short answer from Jiya."
        ws.send_text(json.dumps({"type": "transcript", "text": "ok bye"}))
        events, _ = collect_until(ws, {"call_end"})
        assert any(e["type"] == "goodbye" for e in events)
    qa_rows = env.repo.list_briefings(user.id)[0].qa_logs
    assert [q.question for q in qa_rows] == ["what does that mean"]
    assert env.repo.list_call_attempts(user.id)[0].status in ("completed", "answered")


def test_busy_server_does_not_consume_the_token(env, monkeypatch):
    _user, _b, token = make_call(env.repo)
    monkeypatch.setattr(browser_call, "_live", browser_call.MAX_LIVE_CALLS)
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        assert json.loads(ws.receive_text())["type"] == "busy"
    monkeypatch.setattr(browser_call, "_live", 0)
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_text(json.dumps({"type": "stop"}))


def test_failing_answer_gets_apology_and_call_continues(env, monkeypatch):
    calls = {"n": 0}

    def flaky_llm(role, messages, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("llm down")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Second answer works."))]
        )

    monkeypatch.setattr(session_mod, "call_llm", flaky_llm)
    _user, _b, token = make_call(env.repo)
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "browser"}))
        collect_until(ws, {"speaking"})
        ws.send_text(json.dumps({"type": "transcript", "text": "first question"}))
        events, _ = collect_until(ws, {"qa_response"})
        assert "Sorry" in next(e for e in events if e["type"] == "qa_response")["answer"]
        ws.send_text(json.dumps({"type": "transcript", "text": "second question"}))
        events, _ = collect_until(ws, {"qa_response"}, limit=200)
        assert next(e for e in events if e["type"] == "qa_response")["answer"] == "Second answer works."
        ws.send_text(json.dumps({"type": "stop"}))


def test_story_context_available_for_answers(env):
    """The briefing loaded for a call must carry story contexts (was a detached-instance bug)."""
    from newtalk.tests.unit.helpers import seed_cluster

    user = env.repo.create_user(auth_provider="invite")
    env.repo.upsert_profile(user.id, call_name="S", interests=["tech"])
    cluster = seed_cluster(env.repo, "Chip startup raises funding", source="TechCrunch")
    briefing = env.repo.create_briefing("Hi. There.", 30, story_count=1, user_id=user.id)
    env.repo.add_cluster_to_briefing(briefing.id, cluster.id, 1)
    loaded = env.repo.get_briefing(briefing.id)
    assert loaded.stories[0].cluster.context.background.startswith("Background for")


def test_server_stt_falls_back_to_browser_when_deepgram_unavailable(env, monkeypatch):
    import newtalk.voice.stt_client as stt

    monkeypatch.setattr(stt, "DEEPGRAM_API_KEY", None)
    _user, _b, token = make_call(env.repo)
    with env.client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "stt": "server"}))
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready" and ready["stt"] == "browser"
        ws.send_text(json.dumps({"type": "stop"}))


def _session(env, **kw):
    return session_mod.JiyaSession(
        None, env.repo, language="en", tts=FakeTTS(), external_stt=True, **kw
    )


def test_short_sentences_are_merged_into_speech_chunks(env):
    script = "Hey Sagar! Jiya here. " + " ".join(
        f"Sentence number {i} says something fairly ordinary about the day." for i in range(6)
    )
    plain = _session(env)
    merged = _session(env, min_chunk_chars=150)
    assert len(plain._split_script(script)) == 8
    chunks = merged._split_script(script)
    assert 2 <= len(chunks) < 8
    assert len(chunks[0]) >= 60 and all(len(c) >= 100 for c in chunks[1:-1])
    assert " ".join(chunks).replace("  ", " ") == script.replace("  ", " ")


def test_own_voice_leaking_into_the_mic_is_not_treated_as_the_user(env):
    s = _session(env, min_chunk_chars=0)
    s.script_sentences = s._split_script(
        "The Sensex fell six hundred points today. Foreign investors sold banking shares."
    )
    s._started_idx = 0
    assert s._is_echo("the sensex fell six hundred points today")
    assert not s._is_echo("why did it fall")
    assert not s._is_echo("what about my SIP investments")
