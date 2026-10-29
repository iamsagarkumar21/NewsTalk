# Design

## Context

Observed in the current code (see proposal.md for motivation):

- The pipeline (ingest → cluster → score → context) is global and already incremental; it is reusable as-is.
- Everything downstream is single-user: `UserMemory` is keyed by topic only, `Briefing`/`QALog` have no user, the phone number is one env var (`USER_PHONE_NUMBER`), the composer writes one whole script per day, and `/call/start`, `/call/phone`, `/pipeline/run` are unauthenticated.
- Voice is English-only: `DEFAULT_VOICE = "aura-asteria-en"`, `jiya.py` strings are English, STT is `nova-3` with no language param.
- Voice stack (`JiyaSession` over a `VoiceTransport` protocol, barge-in via `tts_cancel`) is already transport-agnostic: WebSocket client and Twilio share it. That is what makes a free browser call cheap to add.
- Category rubric covers policy/state/economy/tech/science/geopolitics/health/general/entertainment/sports. There is no stocks/markets category and few finance sources.
- Migrations in `db/migrations.py` use SQLite-only SQL (`INSERT OR IGNORE`, `datetime('now')`).

Hard external constraint: **there is no free way to place real phone calls to Indian numbers at scale.** Twilio trial calls only verified numbers from a foreign caller ID; Indian outbound calling needs a paid CPaaS plus KYC/DLT. The design therefore makes the *call experience* free (browser voice) and the *PSTN ring* a pluggable paid upgrade.

## Goals / Non-Goals

**Goals:**
- A demo-able product for ~10–50 invited users at ₹0 recurring cost, same codebase upgradable to paid providers by config.
- LLM spend proportional to stories × languages, not users.
- Hinglish that sounds like a friend, with honest handling of unverified political claims.

**Non-Goals:**
- Real PSTN calls to arbitrary users, WhatsApp calling, native mobile apps.
- Multi-region / non-India timezones beyond storing a timezone field.
- Payments, billing, or admin analytics.
- Replacing the ingestion/clustering/scoring approach.

## Decisions

### D1. Shared pipeline + per-story segments + per-user assembly
Run the existing pipeline 2–3×/day (cheap, global). After context generation, generate a **spoken segment per story per language** (40–90 words, includes attribution/uncertainty line) into a new `story_segments(cluster_id, language, development_version, text)` table. A user's briefing = their interest-filtered, score-ordered stories → concatenate segments + localized intro (call name, length) + template transitions + outro.

*Why*: LLM calls become `stories × languages` (≈ 30 × 3 = 90 small calls/day, batchable) instead of `users × stories`. Groq free-tier limits are the scarcest resource.
*Alternatives*: (a) compose a full script per user — cost ∝ users, rejected; (b) compose per interest-bucket — combinatorial buckets, loses sharing across buckets; (c) segments (chosen) — least LLM, at the cost of weaker cross-story narrative flow, acceptable because Jiya's value is per-story context.
*Trade-off*: the existing memory-aware recap (`familiarity`) moves from composition to Q&A + repeat suppression (specs: Repeat suppression).

### D2. Interests: taxonomy chips + free text normalized once
Fixed taxonomy = rubric categories + new `markets` (stocks/finance) + `startups` (optional). Free text is normalized by one `scorer`-role LLM call at save time into `{categories[], keywords[]}` and stored; at selection time keywords boost clusters via the existing embedding similarity. Max ~3 categories for the "heavy" interest set keeps selection meaningful.
*Alternative*: embed free text only — cannot give users visible feedback ("we understood X"), rejected.

### D3. Delivery: browser call first, pluggable `CallTransport`
- **Ring** = Telegram bot message with Answer button (free, reliable on every Android/iOS phone in India). Web Push is an optional second channel later (iOS requires installed PWA).
- **Call** = `call.html` opens `wss://…/ws/client?token=…`; reuses `JiyaSession`. Client-side STT via the browser Web Speech API (free, `hi-IN`/`en-IN`) sends transcripts as JSON; server-side Deepgram remains available for phone and as fallback.
- **Phone** = existing Twilio path, parameterized per user, allowed only for verified + enabled numbers.
*Alternatives*: Twilio-only (blocked by trial/cost), WhatsApp Business calling (paid, approval), Telegram voice call (bots cannot place calls), SMS OTP verification (paid). A recorded demo of the PSTN ring to 3–5 verified team numbers on Twilio trial credit is possible without changing this design.

### D4. TTS provider interface; free Hinglish voice
Introduce `TTSProvider.synthesize_stream_cancellable(text, cancel, lang)`. Providers: `deepgram` (existing, English), `edge` (free, `en-IN`/`hi-IN` neural voices via `edge-tts`, unofficial service), later `sarvam`/`google` for production. Config chooses provider per language with an ordered fallback list.
*Script form for Hindi/Hinglish*: Devanagari for Hindi words, Latin for English/proper nouns (matches the spec example). **Spike required** (task 5.1) to confirm the chosen voice reads this mixed script naturally; fallback is Roman-script Hinglish.
*Alternatives*: keep Deepgram only (no Hindi voice); Google Cloud TTS (needs billing account even for free tier); Sarvam (best Hinglish, free credits then paid — chosen as the paid-phase upgrade).

### D5. Scheduling: one minute-tick, DB-driven
A single APScheduler interval job (60 s) queries users with `next_call_at <= now` and no `call_attempts` row for their local date. `call_attempts(user_id, local_date)` has a unique constraint → idempotent across restarts and duplicate ticks. Script is assembled at T−10 min, ring at T. A semaphore caps live calls; overflow is re-queued in ≤5-minute slots with jitter.
*Alternative*: one APScheduler cron job per user — lost on restart, awkward on edits; rejected.

### D6. Auth and call security
- Dashboard auth: **invite code → signed session cookie** for the demo (no external account, works on a changing quick-tunnel URL, caps signups to protect free-tier LLM limits). **Google Sign-In ID token verified server-side** (`google-auth`) is added behind the same session dependency once a stable domain exists. (Alternative: Supabase Auth — same cost, adds a dependency; revisit when moving DB to Supabase.)
- Call token: HMAC-signed `{user_id, briefing_id, exp, jti}`, single use (`jti` stored), 10-minute expiry.
- Admin endpoints (`/pipeline/run`, etc.) behind `ADMIN_API_KEY`; per-user rate limits on test call.
- Phone numbers: stored only after verification call (press 1); never logged in full.

### D7. Data model
New: `users`, `user_profiles` (call_name, interests_json, normalized_json, call_time, tz, language, paused, consented_at), `notification_channels` (telegram_chat_id, phone_e164, phone_verified_at, delivery_mode), `call_attempts`, `story_segments`, `call_tokens`. Changed: `Briefing`, `QALog`, `UserMemory` gain `user_id` (composite key for memory). A default owner user receives existing rows. Migrations are written dialect-neutral so the same code runs on SQLite (demo) and Postgres/Supabase (paid phase).

### D8. Dashboard: static app served by FastAPI
Vanilla HTML/JS (no build step) under `/app`: profile form, Telegram link, "call me now", transcript, pause/delete. Served by the same process → one deploy, no CORS, ₹0.
*Alternative*: Next.js on Vercel — better DX later; rejected for the demo as an extra deployment and CORS/auth surface.

### D9. Free-tier hosting
Run the single FastAPI process (API + scheduler + voice WS) on any always-on box: your own machine or an always-free VM, exposed through a **Cloudflare Tunnel** (stable HTTPS, replaces ngrok; required for Telegram webhook and browser mic access, which needs HTTPS). SQLite file with nightly copy. Sleep-on-idle hosts (e.g. free web dynos) are unsuitable because the scheduler must be alive at call time.

### D10. Free-tier cost map

| Need | Free default | Paid upgrade |
|---|---|---|
| LLM | Groq free (existing keys), segments cached | Groq paid / OpenRouter |
| STT (browser) | Web Speech API | Deepgram nova-3 |
| TTS | edge-tts (hi-IN, en-IN) | Sarvam / Deepgram Aura / Google |
| Ring | Telegram bot | Twilio / Indian CPaaS phone call |
| Auth | Google Sign-In | Supabase Auth |
| DB | SQLite | Supabase Postgres |
| Hosting | own box + Cloudflare Tunnel | VPS / managed |

## Risks / Trade-offs

- **[Free TTS is an unofficial endpoint and can break or throttle]** → provider interface + ordered fallback (Aura English); alert on failure rate; Sarvam/Google swap is config-only.
- **[Hinglish TTS/STT quality unknown]** → spike before building UI (task 5.1); keep Roman-script fallback; collect 5 sample calls for the demo team to rate.
- **[Web Speech API is Chrome/Android-centric]** → feature-detect and fall back to server-side Deepgram STT (free credit) with a "headphones recommended" hint.
- **[Groq free-tier rate limits]** → segment cache, batched generation, existing 429 backoff in `call_llm`, optional OpenRouter/Gemini fallback role; cap new-user signups per day (invite codes).
- **[Political misinformation/defamation risk]** → attribution + "unconfirmed" rules in spec, segment prompt enforces, low-tier single-source stories flagged; dashboard transcript shows sources; consent text states AI-generated summaries.
- **[Phone-number abuse (calling someone who never signed up)]** → PSTN only after verification call + allow-list; consent record; opt-out phrase on call.
- **[Compliance: DPDP Act consent/retention, TRAI rules for automated calls]** → explicit consent, 30-day text retention, delete-on-request; legal check before any paid PSTN rollout (outside this change).
- **[Single process = single point of failure; thundering herd at 21:30]** → concurrency cap + jitter; acceptable for demo, documented.
- **[Segment assembly sounds stitched]** → localized transitions, intro states count and order; revisit per-user LLM polish pass as a paid-phase option.
- **[Schema change is breaking for single-user data]** → backup `newtalk.db` before migration; default owner user keeps old rows.

## Migration Plan

1. Backup `newtalk.db`; run new migrations (additive columns/tables, default owner user).
2. Ship behind existing behavior: legacy `/call/*` keeps working for the owner until the new token endpoints are verified, then removed.
3. Enable dashboard for invited users via invite code; start with 3–5 internal users, then widen.
4. Rollback: restore DB backup and previous commit; new tables are additive so legacy code ignores them.

## Open Questions

- Final TTS voice per language after the listening spike (does not change specs).
- Add Web Push as second ring channel — after Telegram proves out.
- Which Indian CPaaS (Exotel/Plivo/Twilio-India) for the paid phase — decided when going paid.
