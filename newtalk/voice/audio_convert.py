"""Audio format conversion for Twilio (mulaw 8kHz) ↔ Deepgram (PCM16 16k/24k)."""
from __future__ import annotations

import audioop
import base64


def pcm24k_to_mulaw8k(pcm24: bytes) -> bytes:
    """Deepgram TTS output → Twilio media stream format."""
    if not pcm24:
        return b""
    pcm8k, _ = audioop.ratecv(pcm24, 2, 1, 24000, 8000, None)
    return audioop.lin2ulaw(pcm8k, 2)


def mulaw8k_to_pcm16k(mulaw: bytes) -> bytes:
    """Twilio incoming audio → Deepgram STT input."""
    if not mulaw:
        return b""
    pcm8k = audioop.ulaw2lin(mulaw, 2)
    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
    return pcm16k


def twilio_media_payload(mulaw: bytes) -> str:
    return base64.b64encode(mulaw).decode("ascii")


def decode_twilio_media(payload_b64: str) -> bytes:
    return base64.b64decode(payload_b64)
