"""TTS provider interface with per-language ordered fallback.

Providers stream audio chunks and stop promptly when `cancel` is set (barge-in).
`audio_format` tells the transport/client how to decode: "mp3" (browser) or "pcm16_24k" (phone).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator, Protocol

logger = logging.getLogger(__name__)

EDGE_VOICES = {
    "en": "en-IN-NeerjaNeural",
    "hinglish": "hi-IN-SwaraNeural",  # en-IN voices skip Devanagari; hi-IN reads both scripts
    "hi": "hi-IN-SwaraNeural",
}


class TTSProvider(Protocol):
    name: str
    audio_format: str

    def synthesize_stream_cancellable(
        self, text: str, cancel: asyncio.Event
    ) -> AsyncIterator[bytes]: ...


class EdgeTTSProvider:
    """Free Microsoft neural voices via `edge-tts` (unofficial endpoint; keep a fallback)."""

    name = "edge"
    audio_format = "mp3"

    def __init__(self, language: str = "en", voice: str | None = None, rate: str | None = None):
        self.voice = voice or EDGE_VOICES.get(language, EDGE_VOICES["en"])
        self.rate = rate or os.getenv("TTS_RATE", "+0%")

    async def synthesize_stream_cancellable(
        self, text: str, cancel: asyncio.Event
    ) -> AsyncIterator[bytes]:
        import edge_tts

        stream = edge_tts.Communicate(text, self.voice, rate=self.rate).stream()
        try:
            async for item in stream:
                if cancel.is_set():
                    return
                if item["type"] == "audio":
                    yield item["data"]
        finally:
            await stream.aclose()


class DeepgramProvider:
    """Existing Deepgram Aura client (English only), PCM16 24 kHz."""

    name = "deepgram"
    audio_format = "pcm16_24k"

    def __init__(self):
        from newtalk.voice.tts_client import DeepgramTTSClient

        self._client = DeepgramTTSClient()

    def synthesize_stream_cancellable(self, text: str, cancel: asyncio.Event):
        return self._client.synthesize_stream_cancellable(text, cancel)


class FallbackTTS:
    """Try providers in order; move on when one fails before producing audio."""

    def __init__(self, providers: list[TTSProvider]):
        if not providers:
            raise ValueError("FallbackTTS needs at least one provider")
        self.providers = providers
        self.audio_format = providers[0].audio_format
        self.name = "+".join(p.name for p in providers)

    async def synthesize_stream_cancellable(
        self, text: str, cancel: asyncio.Event
    ) -> AsyncIterator[bytes]:
        last_exc: Exception | None = None
        for provider in self.providers:
            produced = False
            try:
                async for chunk in provider.synthesize_stream_cancellable(text, cancel):
                    produced = True
                    yield chunk
                return
            except Exception as exc:
                last_exc = exc
                logger.warning("TTS provider %s failed: %s", provider.name, exc)
                if produced:
                    return  # cannot splice a second voice into a half-played sentence
        if last_exc:
            raise last_exc


def tts_for(language: str, audio_format: str = "mp3") -> TTSProvider:
    """Ordered provider chain for a language and the client's audio format."""
    if audio_format == "mp3":
        return FallbackTTS([EdgeTTSProvider(language)])
    # Phone/PCM path: Deepgram Aura speaks English only.
    return FallbackTTS([DeepgramProvider()])
