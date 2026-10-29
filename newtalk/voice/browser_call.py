"""Browser call over WebSocket: `/ws/call`.

Protocol (JSON text frames unless noted):
  client -> server  {"type":"auth","token":"<single-use token>","stt":"browser"|"server"}
                    {"type":"transcript","text":"..."}       final browser STT result
                    {"type":"speech_started"}                 user began talking (barge-in)
                    {"type":"played","index":n}               sentence n started playing
                    {"type":"stop"}
                    binary frames                             PCM16 16 kHz mono (stt=server)
  server -> client  {"type":"ready", ...}  then events from JiyaSession; binary frames are
                    audio in the format announced by `briefing_start.audio_format`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from newtalk.api.security import get_repo, redeem_call_token
from newtalk.voice.session import JiyaSession
from newtalk.voice.tts_providers import tts_for

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_LIVE_CALLS = int(os.getenv("MAX_LIVE_CALLS", "5"))
MAX_CALL_SECONDS = int(os.getenv("MAX_CALL_SECONDS", "1200"))
AUTH_TIMEOUT_SECONDS = 10

_live = 0


class BrowserTransport:
    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def send_audio(self, chunk: bytes) -> None:
        await self.ws.send_bytes(chunk)

    async def send_event(self, payload: dict) -> None:
        await self.ws.send_text(json.dumps(payload, ensure_ascii=False))


def live_calls() -> int:
    return _live


@router.websocket("/ws/call")
async def ws_call(ws: WebSocket):
    global _live
    await ws.accept()
    repo = get_repo()

    try:
        first = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SECONDS)
        hello = json.loads(first)
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect, RuntimeError):
        await ws.close(code=4401)
        return
    if hello.get("type") != "auth":
        await ws.close(code=4401)
        return

    if _live >= MAX_LIVE_CALLS:
        # do not burn the single-use token: the client retries with the same one
        await ws.send_text(json.dumps({"type": "busy", "retry_after": 30}))
        await ws.close(code=4429)
        return

    token = redeem_call_token(repo, hello.get("token"))
    if token is None:
        await ws.send_text(json.dumps({"type": "error", "message": "This call link has expired."}))
        await ws.close(code=4401)
        return

    profile = repo.get_profile(token.user_id)
    briefing = repo.get_briefing(token.briefing_id) if token.briefing_id else None
    if profile is None or briefing is None or briefing.user_id != token.user_id:
        await ws.send_text(json.dumps({"type": "error", "message": "Briefing not found."}))
        await ws.close(code=4404)
        return

    # Server-side streaming STT is the default: the browser Web Speech API restarts (with a
    # chime) and steals audio focus on Android, which makes playback stutter.
    server_stt = hello.get("stt", "server") == "server"
    transport = BrowserTransport(ws)

    def build(external_stt: bool) -> JiyaSession:
        return JiyaSession(
            transport,
            repo,
            user_id=token.user_id,
            language=profile.language,
            call_name=profile.call_name,
            tts=tts_for(profile.language, "mp3"),
            external_stt=external_stt,
            prefetch_window=2,
            min_chunk_chars=150,
        )

    try:
        try:
            session = build(external_stt=not server_stt)
        except EnvironmentError:  # no Deepgram key: fall back to browser speech recognition
            server_stt = False
            session = build(external_stt=True)
    except Exception as exc:
        logger.error("Could not start session: %s", exc)
        await ws.send_text(json.dumps({"type": "error", "message": "Voice is unavailable."}))
        await ws.close(code=4500)
        return

    session.briefing = briefing
    started = time.time()
    _live += 1
    repo.update_attempts_for_briefing(
        token.user_id, briefing.id, status="answered", answered_at=_now()
    )
    await transport.send_event(
        {"type": "ready", "name": profile.call_name, "stt": "server" if server_stt else "browser"}
    )

    consumer = asyncio.create_task(session._stt_loop())
    briefing_task = asyncio.create_task(session._run_briefing())
    session._briefing_task = briefing_task
    watchdog = asyncio.create_task(_enforce_limit(session))

    try:
        while session.running:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await session.feed_audio(msg["bytes"])
            elif msg.get("text"):
                await _on_text(session, msg["text"])
    except WebSocketDisconnect:
        pass
    finally:
        _live -= 1
        await session.stop()
        for task in (consumer, briefing_task, watchdog):
            task.cancel()
        finished = session.qa_mode or not session.running
        repo.update_attempts_for_briefing(
            token.user_id,
            briefing.id,
            status="completed" if finished else "answered",
            ended_at=_now(),
        )
        logger.info(
            "Call ended user=%s briefing=%s duration=%.0fs", token.user_id, briefing.id, time.time() - started
        )
        try:
            await ws.close()
        except RuntimeError:
            pass


async def _on_text(session: JiyaSession, raw: str) -> None:
    try:
        data = json.loads(raw)
    except ValueError:
        return
    kind = data.get("type")
    if kind == "transcript":
        text = str(data.get("text", ""))[:1000]
        await session.submit_transcript(text)
    elif kind == "speech_started":
        session.speech_started()
    elif kind == "played":
        try:
            session.ack_started(int(data.get("index", -1)))
        except (TypeError, ValueError):
            pass
    elif kind == "stop":
        await session.stop()


async def _enforce_limit(session: JiyaSession) -> None:
    await asyncio.sleep(MAX_CALL_SECONDS)
    await session.send_json({"type": "goodbye", "text": ""})
    await session.stop()


def _now():
    import datetime

    return datetime.datetime.utcnow()
