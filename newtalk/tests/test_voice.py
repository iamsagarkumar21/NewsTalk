"""Smoke tests for Deepgram STT/TTS clients (requires DEEPGRAM_API_KEY)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from newtalk.voice.tts_client import DeepgramTTSClient
from newtalk.config.settings import DEEPGRAM_API_KEY


async def test_tts_returns_audio():
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("DEEPGRAM_API_KEY not set")
    client = DeepgramTTSClient()
    chunks = []
    async for chunk in client.synthesize_stream("Hello, this is a NewsTalk test."):
        chunks.append(chunk)
    total = sum(len(c) for c in chunks)
    assert total > 1000, f"Expected audio bytes, got {total}"
    print(f"TTS test passed — received {len(chunks)} chunks, {total} bytes")


if __name__ == "__main__":
    asyncio.run(test_tts_returns_audio())
