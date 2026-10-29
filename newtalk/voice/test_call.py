"""
Quick voice test — hear your latest briefing without a full WebSocket client.

Generates a WAV file from the latest composed script using Deepgram TTS.

Usage:
    python3 -m newtalk.voice.test_call
    # Then play:
    aplay /tmp/newtalk_briefing.wav        # Linux
    ffplay -nodisp -autoexit /tmp/newtalk_briefing.wav
"""
from __future__ import annotations

import asyncio
import logging
import struct
import wave
from pathlib import Path

from dotenv import load_dotenv

for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

from newtalk.config.settings import DATABASE_URL
from newtalk.db.repository import NewTalkRepository
from newtalk.voice.tts_client import DeepgramTTSClient

logger = logging.getLogger(__name__)
OUTPUT_WAV = Path("/tmp/newtalk_briefing.wav")
SAMPLE_RATE = 24000


async def _synthesize_to_wav(text: str, output: Path) -> None:
    client = DeepgramTTSClient()
    chunks: list[bytes] = []
    async for chunk in client.synthesize_stream(text):
        chunks.append(chunk)

    if not chunks:
        raise RuntimeError("TTS returned no audio — check DEEPGRAM_API_KEY")

    pcm = b"".join(chunks)
    with wave.open(str(output), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)

    duration_sec = len(pcm) / (SAMPLE_RATE * 2)
    logger.info("Saved %s (%.1f sec, %d bytes)", output, duration_sec, len(pcm))


def main():
    logging.basicConfig(level=logging.INFO)
    repo = NewTalkRepository(DATABASE_URL)
    briefing = repo.get_latest_briefing()
    if not briefing:
        print("No briefing found. Run the pipeline first:")
        print("  python3 -m newtalk.scheduler.daily_job  # then POST /pipeline/run")
        print("  # or step-by-step: ingestion → dedup → scoring → context → composer")
        return

    print(f"Briefing #{briefing.id} — ~{briefing.duration_estimate_sec}s script")
    print("Synthesizing audio via Deepgram TTS …")
    asyncio.run(_synthesize_to_wav(briefing.script_text, OUTPUT_WAV))
    print(f"\n✅ Audio ready: {OUTPUT_WAV}")
    print("Play it:")
    print(f"  aplay {OUTPUT_WAV}")
    print(f"  ffplay -nodisp -autoexit {OUTPUT_WAV}")
    print("\nFor live interruptible call (mic + barge-in), run:")
    print("  python3 -m newtalk.voice.realtime_server")


if __name__ == "__main__":
    main()
