# Proposal

## Why

NewsTalk today is a single-user pipeline: one global briefing, one phone number in `.env`, English-only voice, calls triggered by hand. To put it in front of real users for a demo, each person must be able to sign up, say what they care about, pick a time and language, and get *their own* Jiya call every day — without us paying for anything until the demo proves demand.

## What Changes

- **User dashboard (new)**: Google sign-in, then a profile form — call name, interests (topic chips + free text), daily call time (default 21:30 IST), language (default English; Hinglish and Hindi available), consent, pause/delete, "call me now" test, last transcript.
- **Per-user personalization**: shared pipeline (ingest → cluster → score → context) stays global and runs once; each user's briefing is *assembled* from cached per-story spoken segments filtered by their interests, so LLM cost scales with stories × languages, not with users.
- **Per-user scheduling**: a minute-tick scheduler finds users whose local call time is due, prepares their script, and "rings" them — replacing the single fixed daily cron + manual call.
- **Free-first call delivery**: "ring" = Telegram message with an Answer button → in-browser voice call over the existing WebSocket stack. Real PSTN phone calls stay behind a pluggable adapter, enabled only for verified/allow-listed numbers (paid phase).
- **Multilingual voice**: spoken script, TTS voice, STT language and fixed phrases follow the user's language. A TTS provider interface adds a free Hindi/Hinglish-capable voice next to the existing English Deepgram Aura voice.
- **Interest coverage**: add a `markets` (stocks/finance) category and finance sources; current rubric/quotas are India-policy-centric and exclude sports/entertainment from scouting.
- **Security hardening**: per-call signed tokens replace the unauthenticated `/call/start` and `/call/phone`; admin endpoints get a key.
- **BREAKING**: `UserMemory`, `Briefing`, `QALog` gain `user_id`; single-user env `USER_PHONE_NUMBER` flow and `/call/*` endpoints change contract. Existing rows migrate to a default "owner" user.

## Capabilities

### New Capabilities
- `subscriber-profile`: sign-in, profile fields and defaults, consent, pause/delete, test call, transcript view.
- `interest-personalization`: turning interests into a per-user story selection, with rules for sensitive/unverified political claims.
- `call-scheduling`: per-user daily call timing, idempotency, missed-call handling, concurrency limits.
- `call-delivery`: ring notification, authenticated browser call, optional verified phone call, interruptible conversation, text-only transcripts.
- `multilingual-voice`: English / Hinglish / Hindi script, speech output and recognition, localized fixed phrases, free-tier operation.

### Modified Capabilities
<!-- None: openspec/specs/ is empty; existing behavior is not yet captured as specs. -->

## Impact

- **Code**: `newtalk/db/{models,repository,migrations}.py` (users + per-user scoping), `newtalk/composer/script_composer.py` (segment generation + assembly), `newtalk/scheduler/daily_job.py` (tick scheduler, secured endpoints), `newtalk/voice/{session,call_app,tts_client,stt_client,phone_call}.py` (per-user session, TTS provider interface, language), `newtalk/config/jiya.py` (localized strings), `newtalk/ingestion/sources_config.py` + `scoring/rubric_config.yaml` (markets). New: dashboard static app, auth, Telegram ring module.
- **APIs**: new `/api/me*`, `/api/call/*`, Telegram webhook; changed `/call/*`.
- **Dependencies**: `edge-tts`, `google-auth`, `python-telegram-bot` (or raw HTTP), `cloudflared` (tunnel, not a pip dep).
- **External accounts (free tier)**: Google OAuth client ID, Telegram bot token, Groq keys (existing), Cloudflare Tunnel. Optional later: Twilio/Indian CPaaS, Sarvam/Google TTS.
