# Jiya: what we built, how it runs, where it is limited

Jiya is a personal news call. A user signs up on a dashboard (name, topics, call time, language),
and at that time gets a Telegram "ring". Tapping Answer opens a browser call in which Jiya speaks a
short, personalised briefing in English, Hinglish or Hindi, and can be interrupted and questioned.

## 1. What is used for what

| Layer | Tool | Used for | Cost today |
|---|---|---|---|
| News intake | 86 RSS feeds, Google News topic searches, Reddit, arXiv, YouTube, GDELT | Raw articles for every interest (markets, tech, sports, politics, health...) | Free |
| Clustering | sentence-transformers embeddings | Group duplicate coverage into one story; detect repeat / minor / major change | Free (local) |
| Scoring | Rules + LLM (Groq `gpt-oss-120b`) | 0-10 importance with India relevance; source-topic prior sets the category | Free tier |
| Context | LLM + web tools | Background, timeline, "why it matters" per story | Free tier |
| Segments | LLM (batched, cached) | One short spoken text per story and language, with attribution rules | Free tier |
| Personalisation | Python rules + one LLM call at profile save | Interest categories + keywords; selection, repeat suppression | Free |
| Ring | Telegram bot (long polling) | Free "phone ring" with an Answer button | Free |
| Voice out | `edge-tts` (hi-IN Swara, en-IN Neerja) | Spoken audio, streamed as MP3 chunks | Free, unofficial |
| Voice in | Deepgram Nova-3 streaming (`multi` for Hinglish) | Live transcription, speech-start detection (barge-in) | Credits |
| Q&A | Groq `gpt-oss-20b`, grounded in the current story | Answers questions, 1-2 sentences | Free tier |
| App | FastAPI + SQLite + APScheduler, static dashboard | API, scheduler, WebSocket call, storage | Free |
| Exposure | ngrok / Cloudflare Tunnel | HTTPS for mic access and Telegram button | Free |

## 2. How a day runs

```
06:00 / 13:00 / 19:00   Shared pipeline (once for everyone)
  ingest -> cluster -> score -> context (global top-N + best of each followed category)
  -> pre-generate spoken segments (cluster x language, cached)

every minute            Scheduler tick
  T-10 min  pick the user's stories (only followed topics + max one must-know), assemble script
  T         Telegram ring with Answer button          (one reminder if missed after 10 min)

on Answer               Browser call over WebSocket
  single-use token -> Jiya speaks chunk by chunk (client acks, server stays 2 chunks ahead)
  user speaks -> audio flushes in ~0.6 s -> transcript -> command / answer -> resume
```

**Interaction rules.** Short replies never reach the LLM: "hmm / haan / ok / go on" resumes at once,
"ruko / wait" makes Jiya stop and listen (up to 25 s), "next / agli khabar" jumps to the next story,
"dobara" repeats the chunk. Anything else is a question, answered from the current story's facts only.
Noise with no words resumes after 2 s.

**News style.** Each story opens with the news itself. Normal stories are 25-45 words. Only big or
fast-moving stories (score 7.5+, major development) get 50-90 words with the background that is
needed. No generic "this matters because..." filler. At most 6 stories per call.

## 3. Limitations

- **Free LLM quota is the ceiling.** Groq rate-limits hit during real runs; a full pipeline took ~40 min,
  and when segments fail Jiya falls back to a plain headline line. One of the two Groq keys is invalid.
- **No real phone calls.** Free tiers cannot dial Indian numbers; users need Telegram and a browser.
- **Free TTS is unofficial** (Microsoft endpoint) and can throttle or change. No ffmpeg, so Hindi voice
  works only in the browser path, not on Twilio.
- **Echo.** Without headphones, Jiya's voice can leak into the mic; echo cancellation helps but is not perfect.
- **Hinglish script is a bet:** Devanagari+Latin mixed text reads best with the Hindi voice, but the
  final voice choice is still pending the owner's listening test.
- **Source quality varies.** Feeds are headlines + summaries, not full articles; some stories have a
  single source; the keyword category rules are still crude for unusual topics.
- **Single process, single SQLite file.** One server restart drops live calls; fine for a demo,
  not for hundreds of concurrent users.
- **Call quality depends on the user's network** (ngrok adds latency; MP3 chunks need ~2 s of buffer).
- Not yet built: per-user phone dialing, Google sign-in, push notifications, transcripts export.

## 4. Where it can improve

| Area | Next step | Effect |
|---|---|---|
| LLM | Paid key (GPT / Groq paid) or Gemini as fallback; batch segments for all active users once per run | Removes rate limits, fallbacks and the 40 min pipeline |
| Voice | Sarvam / Google / Azure TTS; streaming TTS per sentence with a local jitter buffer | Natural Hinglish, no unofficial endpoint |
| Latency | Start TTS on the first LLM tokens for answers; local VAD in the browser for instant stop | Faster response when interrupting |
| News | Fetch full article text for top stories; per-source reliability weights; cross-source conflict notes | Better facts, fewer single-source claims |
| Personalisation | Learn from skips / follow-up questions; per-user pace (brief vs detailed) | "To the point" tuned per person |
| Delivery | Real PSTN via an Indian CPaaS with verified numbers; WhatsApp / push as extra rings | Calls that actually ring the phone |
| Ops | Postgres/Supabase, worker split (pipeline vs call server), health dashboard, alerts | Scale beyond a demo |
