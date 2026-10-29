"""
Unified Jiya voice server — WebSocket client + Twilio phone calls.

Usage:
    python3 -m newtalk.voice.call_app

Endpoints:
    WS   ws://localhost:8001/ws/client     — local mic client
    WS   wss://YOUR_PUBLIC_URL/ws/twilio    — Twilio media stream (needs ngrok)
    GET  /voice/twiml?briefing_id=3         — Twilio TwiML (auto-answers call)
    POST /call/phone?briefing_id=3          — rings your phone via Twilio
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv

for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import Response, JSONResponse
import uvicorn

from newtalk.config.settings import HOST, PORT, DATABASE_URL
from newtalk.db.repository import NewTalkRepository
from newtalk.voice.session import JiyaSession, WebSocketTransport
from newtalk.voice.audio_convert import (
    pcm24k_to_mulaw8k,
    mulaw8k_to_pcm16k,
    twilio_media_payload,
    decode_twilio_media,
)
from newtalk.voice.phone_call import place_phone_call, twilio_configured

logger = logging.getLogger(__name__)

VOICE_PORT = PORT + 1
app = FastAPI(title="Jiya Voice Server")


class TwilioTransport:
    """Sends mulaw 8kHz audio back to Twilio media stream."""

    def __init__(self, ws: WebSocket, stream_sid: str):
        self.ws = ws
        self.stream_sid = stream_sid

    async def send_audio(self, chunk: bytes):
        mulaw = pcm24k_to_mulaw8k(chunk)
        if not mulaw:
            return
        msg = {
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": twilio_media_payload(mulaw)},
        }
        await self.ws.send_text(json.dumps(msg))

    async def send_event(self, payload: dict):
        logger.info("Twilio event: %s", payload.get("type"))


@app.websocket("/ws/client")
async def ws_client_handler(ws: WebSocket):
    await ws.accept()
    repo = NewTalkRepository(DATABASE_URL)
    repo.create_tables()
    transport = WebSocketTransport(ws)
    session = JiyaSession(transport, repo)
    stt_task = asyncio.create_task(session._stt_loop())
    briefing_task = None

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await session.feed_audio(msg["bytes"])
            elif msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "start_briefing":
                    bid = data.get("briefing_id")
                    if bid:
                        session.briefing = repo.get_briefing(bid)
                    briefing_task = asyncio.create_task(session._run_briefing())
                elif data.get("type") == "stop":
                    await session.stop()
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await session.stop()
        stt_task.cancel()
        if briefing_task:
            briefing_task.cancel()


@app.websocket("/ws/twilio")
async def ws_twilio_handler(ws: WebSocket):
    await ws.accept()
    repo = NewTalkRepository(DATABASE_URL)
    repo.create_tables()
    session: JiyaSession | None = None
    stt_task = None
    briefing_task = None
    stream_sid = ""

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            event = data.get("event")

            if event == "connected":
                logger.info("Twilio stream connected")

            elif event == "start":
                stream_sid = data["start"]["streamSid"]
                custom = data["start"].get("customParameters", {})
                briefing_id = custom.get("briefing_id")
                bid = int(briefing_id) if briefing_id else None

                transport = TwilioTransport(ws, stream_sid)
                session = JiyaSession(transport, repo)
                if bid:
                    session.briefing = repo.get_briefing(bid)
                stt_task = asyncio.create_task(session._stt_loop())
                briefing_task = asyncio.create_task(session._run_briefing())
                logger.info("Jiya phone briefing started (briefing_id=%s)", bid)

            elif event == "media" and session:
                payload = data["media"]["payload"]
                mulaw = decode_twilio_media(payload)
                pcm = mulaw8k_to_pcm16k(mulaw)
                await session.feed_audio(pcm)

            elif event == "stop":
                logger.info("Twilio stream stopped")
                if session:
                    await session.stop()
                break

    except WebSocketDisconnect:
        logger.info("Twilio WebSocket disconnected")
    finally:
        if session:
            await session.stop()
        if stt_task:
            stt_task.cancel()
        if briefing_task:
            briefing_task.cancel()


@app.get("/voice/twiml")
def voice_twiml(briefing_id: int | None = Query(None)):
    """TwiML returned when user answers the phone call."""
    from newtalk.config.settings import PUBLIC_BASE_URL

    if not PUBLIC_BASE_URL:
        return Response(
            content="<Response><Say>Public URL not configured. Set PUBLIC_BASE_URL in env.</Say></Response>",
            media_type="application/xml",
        )

    ws_base = PUBLIC_BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    params = urlencode({"briefing_id": briefing_id or ""})
    stream_url = f"{ws_base}/ws/twilio?{params}"

    # Twilio custom parameters via stream url query
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Aditi">Hey! Jiya here. Connecting your briefing now.</Say>
  <Connect>
    <Stream url="{ws_base}/ws/twilio">
      <Parameter name="briefing_id" value="{briefing_id or ''}" />
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.post("/call/phone")
def trigger_phone_call(briefing_id: int | None = Query(None)):
    """Ring the user's phone — Jiya delivers the briefing on answer."""
    if not twilio_configured():
        return JSONResponse({
            "error": "Twilio not configured",
            "need": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "USER_PHONE_NUMBER", "PUBLIC_BASE_URL"],
            "hint": "PUBLIC_BASE_URL = your ngrok HTTPS URL for local dev",
        }, status_code=400)

    repo = NewTalkRepository(DATABASE_URL)
    briefing = repo.get_briefing(briefing_id) if briefing_id else repo.get_latest_briefing()
    if not briefing:
        return JSONResponse({"error": "No briefing. Run pipeline first."}, status_code=404)

    try:
        call_sid = place_phone_call(briefing.id)
        return {"status": "calling", "call_sid": call_sid, "briefing_id": briefing.id, "assistant": "Jiya"}
    except Exception as exc:
        logger.exception("Phone call failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok", "assistant": "Jiya", "twilio": twilio_configured()}


def main():
    logging.basicConfig(level=logging.INFO)
    logger.info("Jiya voice server on http://%s:%d", HOST, VOICE_PORT)
    logger.info("  WebSocket client: ws://127.0.0.1:%d/ws/client", VOICE_PORT)
    logger.info("  Phone call API:   POST http://127.0.0.1:%d/call/phone", VOICE_PORT)
    uvicorn.run(app, host=HOST, port=VOICE_PORT)


if __name__ == "__main__":
    main()
