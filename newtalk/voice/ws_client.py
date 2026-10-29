"""
NewsTalk WebSocket voice client (Option B — live briefing + mic).

Terminal 1 (server):
    python3 -m newtalk.voice.call_app

Terminal 2 (this client):
    python3 -m newtalk.voice.ws_client --listen-only
    python3 -m newtalk.voice.ws_client --briefing-id 3 --listen-only
    python3 -m newtalk.voice.ws_client   # needs mic + PortAudio

If you see 'PortAudio library not found', run:
    sudo apt install libportaudio2
Or use --listen-only which falls back to aplay (no PortAudio needed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from dotenv import load_dotenv

for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

import websockets

from newtalk.config.settings import HOST, PORT, DATABASE_URL
from newtalk.db.repository import NewTalkRepository

logger = logging.getLogger(__name__)


def _client_ws_url() -> str:
    host = HOST if HOST not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"ws://{host}:{PORT + 1}/ws/client"


WS_URL = _client_ws_url()
TTS_SAMPLE_RATE = 24000
MIC_SAMPLE_RATE = 16000
MIC_BLOCK_MS = 100


def _sounddevice_available() -> bool:
    try:
        import sounddevice  # noqa: F401
        return True
    except OSError:
        return False
    except ImportError:
        return False


def _play_via_aplay(pcm: bytes, rate: int = TTS_SAMPLE_RATE) -> None:
    """Linux fallback — uses aplay, no PortAudio required."""
    if not pcm:
        return
    if not shutil.which("aplay"):
        print("(No aplay found — install alsa-utils: sudo apt install alsa-utils)")
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm)
        subprocess.run(["aplay", "-q", path], check=False)
    finally:
        Path(path).unlink(missing_ok=True)


def _play_pcm16(pcm: bytes, rate: int = TTS_SAMPLE_RATE, backend: str = "auto") -> None:
    if not pcm:
        return
    if backend == "aplay" or (backend == "auto" and not _sounddevice_available()):
        _play_via_aplay(pcm, rate)
        return
    import numpy as np
    import sounddevice as sd
    audio = np.frombuffer(pcm, dtype=np.int16)
    sd.play(audio, rate)
    sd.wait()


async def _mic_sender(ws, stop_event: asyncio.Event) -> None:
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    blocksize = int(MIC_SAMPLE_RATE * MIC_BLOCK_MS / 1000)
    q: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata, frames, time_info, status):
        if not stop_event.is_set():
            loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

    with sd.RawInputStream(
        samplerate=MIC_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=blocksize,
        callback=callback,
    ):
        print("Microphone live — speak during playback to interrupt.")
        while not stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=0.5)
                await ws.send(chunk)
            except asyncio.TimeoutError:
                continue


async def run_client(
    briefing_id: int | None,
    listen_only: bool,
    audio_backend: str,
) -> None:
    repo = NewTalkRepository(DATABASE_URL)
    briefing = repo.get_briefing(briefing_id) if briefing_id else repo.get_latest_briefing()
    if not briefing:
        print("No briefing in DB. Run the pipeline first.")
        sys.exit(1)

    bid = briefing.id
    print(f"Connecting to {WS_URL} …")
    print(f"Starting briefing #{bid} (~{briefing.duration_estimate_sec}s)")

    if listen_only:
        backend = "aplay" if audio_backend == "auto" and not _sounddevice_available() else audio_backend
        if backend == "aplay":
            print("Audio: aplay fallback (no PortAudio needed)")
        print("Listen-only mode. Press Ctrl+C to stop.\n")
    else:
        if not _sounddevice_available():
            print("ERROR: Microphone mode needs PortAudio. Run:")
            print("  sudo apt install libportaudio2")
            print("Or test with: python3 -m newtalk.voice.ws_client --listen-only")
            sys.exit(1)
        backend = audio_backend
        print("Mic enabled — speak during playback to ask a question.\n")

    stop_event = asyncio.Event()
    tts_buffer = bytearray()

    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "start_briefing", "briefing_id": bid}))

        mic_task = None
        if not listen_only:
            mic_task = asyncio.create_task(_mic_sender(ws, stop_event))

        try:
            async for message in ws:
                if isinstance(message, bytes):
                    tts_buffer.extend(message)
                    continue

                if tts_buffer:
                    try:
                        _play_pcm16(bytes(tts_buffer), backend=backend)
                    except Exception as exc:
                        print(f"Playback error: {exc}")
                    tts_buffer.clear()

                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    print(message)
                    continue

                msg_type = data.get("type", "")
                if msg_type == "briefing_start":
                    print(f"Briefing started ({data.get('sentence_count')} sentences)\n")
                elif msg_type == "speaking":
                    idx = data.get("sentence_index", "?")
                    text = data.get("text", "")
                    print(f"[{idx}] {text[:120]}{'…' if len(text) > 120 else ''}")
                elif msg_type == "barge_in":
                    print(f"\nYou said: {data.get('transcript', '')}")
                elif msg_type == "qa_response":
                    print(f"Analyst: {data.get('answer', '')}\n")
                elif msg_type == "resuming":
                    print("Resuming briefing…\n")
                elif msg_type == "briefing_done":
                    print("\nJiya: Briefing done! Ask me anything — seriously, anything.")
                    if data.get("qa_mode"):
                        print("(Q&A mode — keep talking)\n")
                elif msg_type == "goodbye":
                    print("\nJiya signed off. Bye!")
                    break
                elif msg_type == "error":
                    print(f"Error: {data.get('message')}")
                    break
                else:
                    print(data)
        except KeyboardInterrupt:
            print("\nStopping…")
            await ws.send(json.dumps({"type": "stop"}))
        finally:
            stop_event.set()
            if mic_task:
                mic_task.cancel()
                try:
                    await mic_task
                except asyncio.CancelledError:
                    pass
            if tts_buffer:
                try:
                    _play_pcm16(bytes(tts_buffer), backend=backend)
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description="NewsTalk live voice call client")
    parser.add_argument("--briefing-id", type=int, default=None)
    parser.add_argument("--listen-only", action="store_true")
    parser.add_argument("--audio", choices=["auto", "sounddevice", "aplay"], default="auto")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run_client(args.briefing_id, args.listen_only, args.audio))


if __name__ == "__main__":
    main()
