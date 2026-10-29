"""
Jiya voice session — interactive briefing with real-time interrupt + open Q&A.

Shared by the browser call, local WebSocket client and Twilio phone calls. A session can be
bound to one user (their briefing, memory, language and name) or run legacy single-user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Protocol

from newtalk.config.jiya import ASSISTANT_NAME, CLOSING_QA_INVITE, QA_SYSTEM_PROMPT
from newtalk.config.jiya_i18n import phrases_for
from newtalk.db.models import OWNER_USER_ID
from newtalk.db.repository import NewTalkRepository
from newtalk.llm.date_context import get_date_context
from newtalk.llm.litellm_client import call_llm
from newtalk.memory.memory_store import MemoryStore
from newtalk.voice.intents import ACK, CONTINUE, PAUSE, REPEAT, SKIP, classify_utterance
from newtalk.voice.stt_client import BROWSER_STT_LANGUAGES

logger = logging.getLogger(__name__)

# If a barge-in produces no transcript (cough, noise) resume the briefing after this long.
BARGE_RESUME_SECONDS = 2.0
PAUSE_SECONDS = 25.0  # after "ruko"/"wait": how long Jiya stays silent for the user
SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


class VoiceTransport(Protocol):
    """Send audio bytes or JSON events to the connected client/phone."""

    async def send_audio(self, chunk: bytes) -> None: ...
    async def send_event(self, payload: dict) -> None: ...


class JiyaSession:
    """Interactive voice briefing with barge-in and post-briefing conversation."""

    def __init__(
        self,
        transport: VoiceTransport,
        repo: NewTalkRepository,
        *,
        user_id: int | None = None,
        language: str = "en",
        call_name: str | None = None,
        tts=None,
        external_stt: bool = False,
        prefetch_window: int | None = None,
        min_chunk_chars: int = 0,
    ):
        """
        external_stt: transcripts arrive via submit_transcript()/speech_started() (browser
            Web Speech API) instead of a server-side Deepgram stream.
        prefetch_window: when set, the client acks played sentences and the server stays at
            most this many sentences ahead of playback (keeps barge-in resume accurate).
        """
        self.transport = transport
        self.repo = repo
        self.user_id = user_id
        self.language = language
        self.call_name = call_name
        self.phrases = phrases_for(language)
        self.memory = MemoryStore(repo, user_id=user_id or OWNER_USER_ID)

        if tts is None:
            from newtalk.voice.tts_client import DeepgramTTSClient

            tts = DeepgramTTSClient()
        self.tts = tts

        self.external_stt = external_stt
        self.stt = None
        if not external_stt:
            from newtalk.voice.stt_client import DeepgramSTTClient

            self.stt = DeepgramSTTClient(language=language)

        self.briefing = None
        self.script_sentences: list[str] = []
        self.current_sentence_idx = 0
        self.qa_mode = False
        self.running = True
        self.tts_cancel = asyncio.Event()
        self.audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.transcript_queue: asyncio.Queue[str] = asyncio.Queue()
        self.prefetch_window = prefetch_window
        self.min_chunk_chars = min_chunk_chars
        self._chunk_parts: list[list[str]] = []
        self._started_at = 0.0
        self._paused_until = 0.0
        self._started_idx = -1
        self._sentence_story: dict[int, object] = {}
        self._answering = False
        self._barge_deadline = 0.0
        self._handling_speech = asyncio.Lock()
        self._briefing_task: asyncio.Task | None = None

    # ── helpers ───────────────────────────────────────────────────────────────

    async def send_json(self, payload: dict):
        await self.transport.send_event(payload)

    def _split_script(self, script: str) -> list[str]:
        """Speech chunks. Very short sentences are merged: every TTS request costs ~1 s of
        start-up, so many tiny requests make playback stutter."""
        sentences = [p.strip() for p in SENTENCE_SPLIT.split(script.strip()) if p.strip()]
        if not self.min_chunk_chars:
            self._chunk_parts = [[s] for s in sentences]
            return sentences
        chunks: list[list[str]] = []
        buf: list[str] = []
        for s in sentences:
            buf.append(s)
            # a short first chunk gets audio out quickly; later chunks amortise TTS start-up
            threshold = 60 if not chunks else self.min_chunk_chars
            if len(" ".join(buf)) >= threshold:
                chunks.append(buf)
                buf = []
        if buf:
            if chunks and len(" ".join(buf)) < 40:
                chunks[-1].extend(buf)
            else:
                chunks.append(buf)
        self._chunk_parts = chunks
        return [" ".join(c) for c in chunks]

    @property
    def audio_format(self) -> str:
        return getattr(self.tts, "audio_format", "pcm16_24k")

    def _load_briefing(self):
        if self.briefing is None:
            self.briefing = self.repo.get_latest_briefing(self.user_id)
        return self.briefing

    def _full_briefing_context(self) -> str:
        return self.briefing.script_text[:4000] if self.briefing else ""

    def _story_for_sentence(self, idx: int):
        """The briefing story whose spoken segment contains sentence `idx` (None if unknown)."""
        if not self.briefing or not self.briefing.stories:
            return None
        if idx in self._sentence_story:
            return self._sentence_story[idx]
        found = None
        if 0 <= idx < len(self.script_sentences):
            parts = (
                self._chunk_parts[idx]
                if idx < len(self._chunk_parts)
                else [self.script_sentences[idx]]
            )
            for story in sorted(self.briefing.stories, key=lambda s: s.position):
                try:
                    text = self.repo.latest_segment_text(story.cluster_id, self.language)
                except Exception:
                    text = None
                if text and any(len(p) > 12 and p in text for p in parts):
                    found = story
                    break
        self._sentence_story[idx] = found
        return found

    def _story_facts(self) -> tuple[str, str]:
        """(title, facts) for the story being spoken — the only ground truth for answers."""
        story = None
        try:
            # walk back from the current position to the nearest sentence we can place
            top = max(self._started_idx, self.current_sentence_idx, 0)
            for idx in range(min(top, len(self.script_sentences) - 1), -1, -1):
                story = self._story_for_sentence(idx)
                if story is not None:
                    break
            if story is None and self.briefing and self.briefing.stories:
                story = sorted(self.briefing.stories, key=lambda s: s.position)[0]
            cluster = story.cluster if story else None
            if cluster is None:
                return "", self._full_briefing_context()
            parts = []
            ctx = cluster.context
            if ctx:
                parts.append(ctx.background[:1500])
                try:
                    why = json.loads(ctx.evidence_json or "{}").get("why_it_matters")
                except ValueError:
                    why = None
                if why:
                    parts.append(f"Why it matters: {why}")
            segment = self.repo.latest_segment_text(cluster.id, self.language)
            if segment:
                parts.append(f"As told on this call: {segment}")
            return cluster.representative_title, "\n".join(parts) or self._full_briefing_context()
        except Exception as exc:  # detached/missing relations must never break the call
            logger.warning("Story facts lookup failed: %s", exc)
            return "", self._full_briefing_context()

    def _is_goodbye(self, text: str) -> bool:
        t = text.lower().strip()
        return any(w.lower() in t for w in self.phrases["goodbye_words"])

    def _qa_system_prompt(self) -> str:
        parts = [get_date_context(), QA_SYSTEM_PROMPT, self.phrases["qa_rules"]]
        if self.call_name:
            parts.append(
                f"The caller's name is {self.call_name}. Use it occasionally, not every reply."
            )
        parts.append(
            "GROUNDING (mandatory): answer ONLY from the STORY FACTS you are given. Do not add "
            "numbers, causes, names, quotes or events that are not in them, and do not mix in "
            "other stories. If the caller asks something the facts do not cover, say plainly "
            "that you don't have that detail yet and give what you do know. Attribute claims "
            "('according to ...') and call anything unconfirmed unconfirmed. Answer in 1-2 "
            "short spoken sentences, answer first; no lists, no markdown."
        )
        return "\n\n".join(parts)

    def _other_titles(self, current_title: str) -> list[str]:
        try:
            return [
                s.cluster.representative_title
                for s in sorted(self.briefing.stories, key=lambda s: s.position)
                if s.cluster and s.cluster.representative_title != current_title
            ]
        except Exception:
            return []

    async def _answer(self, user_text: str) -> str:
        title, facts = self._story_facts()
        spoken = self.script_sentences[
            max(0, max(self._started_idx, self.current_sentence_idx) - 4) :
            max(self._started_idx, self.current_sentence_idx) + 1
        ]
        others = self._other_titles(title)
        user_msg = (
            f"STORY FACTS ({title or 'current briefing'}):\n{facts}\n\n"
            f"JUST SPOKEN: {' '.join(spoken)[-700:]}\n\n"
            + (f"OTHER STORIES IN THIS BRIEFING (titles only): {'; '.join(others)}\n\n" if others else "")
            + f"CALLER ASKED: {user_text}"
        )
        messages = [
            {"role": "system", "content": self._qa_system_prompt()},
            {"role": "user", "content": user_msg},
        ]

        from newtalk.composer.segments import normalize_for_speech, script_issues

        answer = ""
        for attempt in range(2):
            resp = await asyncio.to_thread(call_llm, role="qa", messages=messages)
            answer = normalize_for_speech(resp.choices[0].message.content.strip())
            issues = script_issues(answer, self.language)
            if not issues:
                break
            messages = messages + [
                {"role": "assistant", "content": answer},
                {"role": "user", "content": "Rewrite that answer. " + "; ".join(issues) + "."},
            ]

        if self.briefing:
            self.repo.log_qa(self.briefing.id, user_text, answer, user_id=self.user_id)
        self.memory.update_after_qa(user_text, answer)
        return answer

    async def _play_tts(self, text: str):
        self.tts_cancel.clear()
        try:
            async for chunk in self.tts.synthesize_stream_cancellable(
                text, self.tts_cancel
            ):
                if self.tts_cancel.is_set():
                    break
                await self.transport.send_audio(chunk)
        except Exception as exc:
            logger.error("TTS failed: %s", exc)
            await self.send_json({"type": "tts_error", "message": "voice unavailable"})

    # ── barge-in / user input ─────────────────────────────────────────────────

    def speech_started(self):
        """User started talking: stop audio now; resume later if no words follow."""
        if not self.running:
            return
        loop = asyncio.get_running_loop()
        self.tts_cancel.set()
        self._barge_deadline = loop.time() + BARGE_RESUME_SECONDS
        if self.prefetch_window is not None and not self.qa_mode:
            # resume at the interrupted chunk only if it had barely started, else the next one
            elapsed = loop.time() - self._started_at
            base = max(self._started_idx, 0)
            self.current_sentence_idx = base if elapsed < 2.5 else base + 1
        # tell the client to drop whatever it has buffered right now
        loop.create_task(self.send_json({"type": "flush"}))

    def _is_echo(self, text: str) -> bool:
        """True when the "user" is mostly Jiya's own voice leaking back into the mic."""
        words = re.findall(r"\w+", text.lower())
        if len(words) < 3 or not self.script_sentences:
            return False
        top = min(max(self._started_idx, 0), len(self.script_sentences) - 1)
        spoken = set(
            re.findall(r"\w+", " ".join(self.script_sentences[max(0, top - 1) : top + 2]).lower())
        )
        return sum(w in spoken for w in words) / len(words) >= 0.75

    def _jump_to(self, idx: int) -> None:
        """Move the playback cursor (client buffer was already flushed on barge-in)."""
        idx = max(0, idx)
        self.current_sentence_idx = idx
        self._started_idx = idx - 1  # keeps the prefetch window from blocking after a jump

    def _next_story_index(self) -> int:
        base = max(self._started_idx, 0)
        current = self._story_for_sentence(base)
        for j in range(base + 1, len(self.script_sentences)):
            story = self._story_for_sentence(j)
            if story is not None and story is not current:
                return j
        return len(self.script_sentences)

    async def _handle_command(self, intent: str) -> bool:
        """Short spoken commands that never need the Q&A model. True if handled."""
        loop = asyncio.get_running_loop()
        if intent in (ACK, CONTINUE):
            if self.qa_mode:
                return False  # nothing is playing; let the Q&A model reply naturally
            self._paused_until = 0.0
            self._barge_deadline = 0.0  # resume at once
            return True
        if intent == PAUSE:
            self._paused_until = loop.time() + PAUSE_SECONDS
            await self.send_json({"type": "paused"})
            await self._play_tts(self.phrases["pause_ack"])
            return True
        if intent == SKIP and not self.qa_mode:
            self._paused_until = 0.0
            self._jump_to(self._next_story_index())
            self._barge_deadline = 0.0
            await self.send_json({"type": "skipped"})
            return True
        if intent == REPEAT and not self.qa_mode:
            self._paused_until = 0.0
            self._jump_to(max(self._started_idx, 0))
            self._barge_deadline = 0.0
            return True
        return False

    async def submit_transcript(self, text: str):
        if text.strip():
            await self.transcript_queue.put(text.strip())

    def ack_started(self, index: int):
        """Client began playing sentence `index`."""
        if index > self._started_idx:
            self._started_idx = index
            self._started_at = asyncio.get_running_loop().time()

    async def _handle_user_speech(self, transcript: str):
        if not transcript.strip() or self._is_echo(transcript):
            return
        async with self._handling_speech:
            self._answering = True
            try:
                self.tts_cancel.set()
                await self.send_json({"type": "barge_in", "transcript": transcript})

                if not self._is_goodbye(transcript):
                    intent = classify_utterance(transcript)
                    if intent != "question" and await self._handle_command(intent):
                        return

                if self._is_goodbye(transcript):
                    line = self.phrases["goodbye"].format(name=self.call_name or "")
                    await self.send_json({"type": "goodbye", "text": line})
                    await self._play_tts(line)
                    await self.send_json({"type": "call_end"})
                    self.running = False
                    return

                try:
                    answer = await self._answer(transcript)
                except Exception as exc:
                    logger.exception("Q&A failed: %s", exc)
                    answer = self.phrases["apology"]
                await self.send_json({"type": "qa_response", "answer": answer})
                await self._play_tts(answer)
                if not self.tts_cancel.is_set():
                    await self.send_json({"type": "answer_end"})
            finally:
                self._answering = False

            if not self.qa_mode:
                await self.send_json({"type": "resuming"})
                if self.running and (
                    self._briefing_task is None or self._briefing_task.done()
                ):
                    self._briefing_task = asyncio.create_task(self._run_briefing())

    # ── briefing ──────────────────────────────────────────────────────────────

    async def _run_briefing(self):
        if not self._load_briefing():
            await self.send_json(
                {
                    "type": "error",
                    "message": "No briefing found. Run the pipeline first.",
                }
            )
            return

        loop = asyncio.get_running_loop()
        if not self.script_sentences:
            self.script_sentences = self._split_script(self.briefing.script_text)
            await self.send_json(
                {
                    "type": "briefing_start",
                    "briefing_id": self.briefing.id,
                    "assistant": ASSISTANT_NAME,
                    "sentence_count": len(self.script_sentences),
                    "audio_format": self.audio_format,
                    "language": self.language,
                    "stt_lang": BROWSER_STT_LANGUAGES.get(self.language, "en-IN"),
                }
            )

        while self.current_sentence_idx < len(self.script_sentences) and self.running:
            if self._answering:
                await asyncio.sleep(0.1)
                continue
            if loop.time() < self._paused_until:  # the user asked Jiya to wait and is talking
                await asyncio.sleep(0.1)
                continue
            if self.tts_cancel.is_set():
                if loop.time() < self._barge_deadline:
                    await asyncio.sleep(0.1)
                    continue
                self.tts_cancel.clear()  # false alarm — nothing was said
                if self.prefetch_window is not None:
                    self.current_sentence_idx = max(self._started_idx, 0)
            idx = self.current_sentence_idx
            if (
                self.prefetch_window is not None
                and idx - self._started_idx > self.prefetch_window
            ):
                await asyncio.sleep(0.05)
                continue

            sentence = self.script_sentences[idx]
            await self.send_json(
                {"type": "speaking", "sentence_index": idx, "text": sentence}
            )
            await self._play_tts(sentence)

            if (
                not self.tts_cancel.is_set()
                and not self._answering
                and idx == self.current_sentence_idx
            ):
                await self.send_json({"type": "sentence_end", "sentence_index": idx})
                self.current_sentence_idx += 1

        if self.running and self.current_sentence_idx >= len(self.script_sentences):
            if self.prefetch_window is not None:
                # let the client finish playing the last queued sentences
                while (
                    self.running and self._started_idx < len(self.script_sentences) - 1
                ):
                    await asyncio.sleep(0.1)
            self.qa_mode = True
            await self.send_json({"type": "briefing_done", "qa_mode": True})
            if self.user_id is None:  # legacy scripts carry no spoken closing line
                await self._play_tts(CLOSING_QA_INVITE)

    # ── speech input ──────────────────────────────────────────────────────────

    async def _transcript_consumer(self):
        while self.running:
            try:
                text = await asyncio.wait_for(self.transcript_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            try:
                await self._handle_user_speech(text)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to handle user speech")

    async def _stt_loop(self):
        """Run the transcript consumer, plus Deepgram streaming unless STT is external."""
        loop = asyncio.get_running_loop()
        consumer = asyncio.create_task(self._transcript_consumer())
        try:
            if self.stt is None:
                await consumer
                return

            def on_speech_started():
                loop.call_soon_threadsafe(self.speech_started)

            def on_transcript(text: str, is_final: bool):
                if is_final and text.strip():
                    loop.call_soon_threadsafe(
                        self.transcript_queue.put_nowait, text.strip()
                    )

            async def audio_iter():
                while self.running:
                    chunk = await self.audio_queue.get()
                    if chunk is None:
                        break
                    yield chunk

            await self.stt.transcribe_stream(
                audio_iter(),
                on_transcript=on_transcript,
                on_speech_started=on_speech_started,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("STT error: %s", exc)
        finally:
            consumer.cancel()

    async def start(self, briefing_id: int | None = None):
        if briefing_id:
            self.briefing = self.repo.get_briefing(briefing_id)
        stt_task = asyncio.create_task(self._stt_loop())
        self._briefing_task = asyncio.create_task(self._run_briefing())
        try:
            while self.running:
                await asyncio.sleep(0.5)
        finally:
            self.running = False
            await self.audio_queue.put(None)
            if self._briefing_task:
                self._briefing_task.cancel()
            stt_task.cancel()

    async def feed_audio(self, chunk: bytes):
        if self.running:
            await self.audio_queue.put(chunk)

    async def stop(self):
        self.running = False
        self.tts_cancel.set()
        await self.audio_queue.put(None)


class WebSocketTransport:
    def __init__(self, ws):
        self.ws = ws

    async def send_audio(self, chunk: bytes):
        await self.ws.send(chunk)

    async def send_event(self, payload: dict):
        await self.ws.send(json.dumps(payload))
