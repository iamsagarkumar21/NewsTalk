"""
Deepgram streaming STT client (Nova-3).
"""
from __future__ import annotations

import json
import logging
import asyncio
from typing import AsyncIterator, Callable

import websockets

from newtalk.config.settings import DEEPGRAM_API_KEY

logger = logging.getLogger(__name__)

# nova-3 `multi` handles English/Hindi code-switching (Hinglish); `hi` for pure Hindi.
STT_LANGUAGES = {"en": "en-IN", "hinglish": "multi", "hi": "hi"}
BROWSER_STT_LANGUAGES = {"en": "en-IN", "hinglish": "hi-IN", "hi": "hi-IN"}


def stt_url(language: str = "en") -> str:
    return (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-3"
        f"&language={STT_LANGUAGES.get(language, 'en-IN')}"
        "&encoding=linear16"
        "&sample_rate=16000"
        "&channels=1"
        "&interim_results=true"
        "&vad_events=true"
        "&endpointing=400"
        "&utterance_end_ms=1000"
    )


DEEPGRAM_STT_URL = stt_url("en")


class DeepgramSTTClient:
    """Streaming speech-to-text over WebSocket."""

    def __init__(self, api_key: str | None = None, language: str = "en"):
        self.language = language
        self.api_key = api_key or DEEPGRAM_API_KEY
        if not self.api_key:
            raise EnvironmentError("DEEPGRAM_API_KEY must be set in .env")

    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        on_transcript: Callable[[str, bool], None],
        on_speech_started: Callable[[], None] | None = None,
    ) -> None:
        """
        Stream audio to Deepgram and invoke callbacks.

        Args:
            audio_chunks: async iterator of raw PCM16 16kHz mono bytes
            on_transcript: callback(text, is_final)
            on_speech_started: optional VAD callback for barge-in detection
        """
        headers = {"Authorization": f"Token {self.api_key}"}

        async with websockets.connect(
            stt_url(self.language),
            additional_headers=headers,
            ping_interval=20,
        ) as ws:

            async def _sender():
                async for chunk in audio_chunks:
                    if chunk:
                        await ws.send(chunk)
                await ws.send(json.dumps({"type": "CloseStream"}))

            pending: list[str] = []

            def flush_pending():
                if pending:
                    text = " ".join(pending).strip()
                    pending.clear()
                    if text:
                        on_transcript(text, True)

            async def _receiver():
                async for message in ws:
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    if msg_type == "UtteranceEnd":
                        flush_pending()
                        continue

                    if msg_type == "SpeechStarted" and on_speech_started:
                        on_speech_started()
                        continue

                    if msg_type == "Results":
                        channel = data.get("channel", {})
                        alts = channel.get("alternatives", [])
                        if not alts:
                            continue
                        text = alts[0].get("transcript", "").strip()
                        if not text:
                            continue
                        if data.get("is_final", False):
                            pending.append(text)  # one question may arrive as several finals
                            if data.get("speech_final", False):
                                flush_pending()
                        else:
                            on_transcript(text, False)

            await asyncio.gather(_sender(), _receiver())
