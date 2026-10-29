"""
Deepgram Aura TTS client — streams audio chunks for low-latency playback.
"""
from __future__ import annotations

import json
import logging
import asyncio
from typing import AsyncIterator

import websockets

from newtalk.config.settings import DEEPGRAM_API_KEY

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "aura-asteria-en"


class DeepgramTTSClient:
    """Streaming text-to-speech over Deepgram WebSocket API."""

    def __init__(self, api_key: str | None = None, voice: str = DEFAULT_VOICE):
        self.api_key = api_key or DEEPGRAM_API_KEY
        self.voice = voice
        if not self.api_key:
            raise EnvironmentError("DEEPGRAM_API_KEY must be set in .env")

    def _tts_url(self) -> str:
        return (
            "wss://api.deepgram.com/v1/speak"
            f"?model={self.voice}"
            "&encoding=linear16"
            "&sample_rate=24000"
        )

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield PCM16 audio chunks for the given text."""
        headers = {"Authorization": f"Token {self.api_key}"}
        url = self._tts_url()

        async with websockets.connect(url, additional_headers=headers) as ws:
            await ws.send(json.dumps({"type": "Speak", "text": text}))
            await ws.send(json.dumps({"type": "Flush"}))

            async for message in ws:
                if isinstance(message, bytes):
                    yield message
                    continue
                data = json.loads(message)
                if data.get("type") == "Flushed":
                    break
                if data.get("type") == "Metadata":
                    continue

    async def synthesize_stream_cancellable(
        self,
        text: str,
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[bytes]:
        """
        Like synthesize_stream but checks cancel_event between chunks
        for barge-in support.
        """
        async for chunk in self.synthesize_stream(text):
            if cancel_event.is_set():
                logger.info("TTS cancelled (barge-in)")
                return
            yield chunk
