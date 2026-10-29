"""Short spoken replies are handled without the Q&A model; real questions still go to it."""

import asyncio
from types import SimpleNamespace

import pytest

from newtalk.composer.user_briefing import assemble_user_briefing
from newtalk.db.repository import NewTalkRepository
from newtalk.tests.unit.helpers import FakeLLM, seed_cluster
from newtalk.voice import session as session_mod
from newtalk.voice.intents import classify_utterance


@pytest.mark.parametrize(
    "text, intent",
    [
        ("hmm", "ack"), ("okay", "ack"), ("haan theek hai", "ack"), ("ठीक है", "ack"),
        ("go on", "continue"), ("ok go on", "continue"), ("haan aage bolo", "continue"),
        ("wait", "pause"), ("ruko", "pause"), ("ruko ek minute", "pause"), ("एक मिनट रुको", "pause"),
        ("next", "skip"), ("skip this please", "skip"), ("agli khabar", "skip"), ("अगली खबर", "skip"),
        ("say that again", "repeat"), ("dobara bolo", "repeat"), ("फिर से बोलो", "repeat"),
        ("why did the Sensex fall", "question"),
        ("what does next quarter GDP mean", "question"),
        ("second quarter results kya the", "question"),
        ("why did you skip that", "question"),
        ("", "question"),
    ],
)
def test_classification(text, intent):
    assert classify_utterance(text) == intent


class Collect:
    def __init__(self):
        self.events, self.audio = [], 0

    async def send_event(self, payload):
        self.events.append(payload)

    async def send_audio(self, chunk):
        self.audio += 1


class FakeTTS:
    audio_format = "mp3"

    def __init__(self):
        self.spoken = []

    async def synthesize_stream_cancellable(self, text, cancel):
        self.spoken.append(text)
        yield b"x"


@pytest.fixture
def call(monkeypatch):
    repo = NewTalkRepository("sqlite:///:memory:")
    repo.create_tables()
    for i, title in enumerate(
        ["AI chip startup raises funding", "New AI model launches from startup", "Chip export curbs tighten again"]
    ):
        seed_cluster(repo, title, source="TechCrunch", score=7.0 - i * 0.1)
    user = repo.create_user(auth_provider="invite")
    repo.upsert_profile(user.id, call_name="Sagar", interests=["tech"], language="en", call_time="21:30")
    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())

    llm_calls = {"n": 0}

    def counting_llm(role, messages, **kw):
        llm_calls["n"] += 1
        msg = SimpleNamespace(content="Direct answer.")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr(session_mod, "call_llm", counting_llm)
    tts, transport = FakeTTS(), Collect()
    s = session_mod.JiyaSession(
        transport, repo, user_id=user.id, language="en", call_name="Sagar", tts=tts,
        external_stt=True, prefetch_window=2,
    )
    s.briefing = repo.get_briefing(out["briefing_id"])
    s.script_sentences = s._split_script(s.briefing.script_text)
    return SimpleNamespace(s=s, llm=llm_calls, tts=tts, transport=transport)


def run(coro):
    return asyncio.run(coro)


def test_ack_resumes_immediately_without_calling_the_llm(call):
    s = call.s
    s.tts_cancel.set()
    s._barge_deadline = 10**9  # as if the user had just started speaking
    run(s._handle_user_speech("hmm okay"))
    assert call.llm["n"] == 0
    assert s._barge_deadline == 0.0, "briefing loop may resume right away"
    assert not any(e["type"] == "qa_response" for e in call.transport.events)


def test_pause_stays_silent_and_acknowledges_briefly(call):
    s = call.s
    run(s._handle_user_speech("ruko ek minute"))
    assert call.llm["n"] == 0
    assert s._paused_until > 0
    assert call.tts.spoken == [s.phrases["pause_ack"]]


def test_skip_jumps_to_the_next_story(call):
    s = call.s
    # position the cursor inside the first story
    first = next(i for i, x in enumerate(s.script_sentences) if "AI chip startup raises funding" in x)
    s._started_idx = first
    s.current_sentence_idx = first + 1
    run(s._handle_user_speech("next"))
    assert call.llm["n"] == 0
    landed = s.script_sentences[s.current_sentence_idx]
    assert "AI chip startup raises funding" not in landed
    assert s.current_sentence_idx > first


def test_repeat_replays_the_current_chunk(call):
    s = call.s
    s._started_idx = 3
    s.current_sentence_idx = 5
    run(s._handle_user_speech("dobara bolo"))
    assert s.current_sentence_idx == 3 and call.llm["n"] == 0


def test_a_real_question_still_reaches_the_model(call):
    s = call.s
    s._started_idx = 2
    run(s._handle_user_speech("why does that matter for startups"))
    assert call.llm["n"] == 1
    assert any(e["type"] == "qa_response" for e in call.transport.events)
