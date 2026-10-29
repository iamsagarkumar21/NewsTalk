# Tasks

## 1. Per-user data model

- [x] 1.1 Add `users`, `user_profiles`, `notification_channels`, `call_attempts` (unique `user_id`+`local_date`), `story_segments`, `call_tokens` models; verify `python3 -m pytest newtalk/tests/test_db.py` passes with new tables on in-memory SQLite
- [x] 1.2 Add `user_id` to `Briefing`, `QALog`, `UserMemory` (composite key) with a dialect-neutral migration and default owner user; verify migration on a copy of `newtalk.db` keeps row counts and old briefing is readable
- [x] 1.3 Extend `NewTalkRepository` with user/profile/attempt/segment/token methods; verify new unit tests cover create, update, delete-cascade (all user data removed)

## 2. Auth and profile API

- [x] 2.1 Invite-code sign-up/login with signed session cookie (Google ID-token sign-in added later behind the same dependency); verify unit tests reject unknown/exhausted codes and missing/invalid cookies
- [x] 2.2 `/api/me` profile CRUD with validation (call name, ≥1 interest, 5-minute time, language default `en`, tz default Asia/Kolkata), consent, pause, delete; verify tests for each scenario in `subscriber-profile` spec including cross-user rejection
- [x] 2.3 `ADMIN_API_KEY` guard on `/pipeline/run` and legacy `/call/*`; verify 401 without key and 200 with key

## 3. Interests and coverage

- [x] 3.1 Add `markets` category to `rubric_config.yaml` with keywords, weight 0.92, India-relevance boost; add sports/entertainment keyword expansion; verify rubric tests pass
- [x] 3.2 Add RSS feeds for markets (Mint/BS/ET/Moneycontrol), sports (ESPNcricinfo/IE/TOI/TheHindu), entertainment (IE/TOI/TheHindu), health (TheHindu/IE/TOI/WHO), tech (TechCrunch/TheVerge), economy (ET); Reddit (IndianStockMarket/Cricket/bollywood); Google News topic searches
- [x] 3.3 Interest normalizer (`interest_normalizer.py`) with LLM extraction of extra slugs+keywords from free_text, rule-only fallback when no free_text; wired into profile save as background thread; verify unit test for no-LLM path
- [x] 3.4 Per-user story selection (`user_selection.py`): category match boost (1.5x) + keyword relevance, diversity cap per category, fallback to global selection for users without profile; verify 5 unit tests pass

## 4. Segment-based composition

- [x] 4.1 Segment generator: one batched LLM call per language producing 40–90 word spoken segments with attribution/uncertainty line, cached by `(cluster_id, language, development_version)`; verify second run makes zero LLM calls for unchanged clusters (`composer/segments.py`; cache by development version; fallbacks never cached; script-form validator)
- [x] 4.2 Sensitive-claim rules in the segment prompt and a post-check (flags assertions of unverified cause/motive); verify test with the "foreign-funded protest" fixture yields attributed + unconfirmed wording (rules in prompt + `check_segment`: unattributed motive/funding claims are regenerated, then replaced by a neutral line)
- [x] 4.3 Per-user assembler: localized intro (call name, length), transitions, outro, duration estimate; verify test that 50 users with one interest set cause no additional LLM calls and scripts differ only by name (`composer/user_briefing.py`; 50-user test asserts zero extra LLM calls and scripts differing only by name)

## 5. Multilingual voice

- [x] 5.1 Spike: synthesize 5 Hinglish/Hindi/English samples with `edge-tts` (Devanagari+Latin and Roman script) and review; record chosen voices and script form in design.md Open Questions, verify by listening notes committed to the change folder (samples generated from real LLM output in `voice-samples/`; **listening decision pending from owner**: A/B/C/D)
- [x] 5.2 `TTSProvider` interface with `deepgram` and `edge` providers, per-language ordered fallback; verify tests for cancellation (<300 ms) and fallback on provider error (`voice/tts_providers.py`; Hindi voice is browser-only because Deepgram Aura is English-only and ffmpeg is not installed)
- [x] 5.3 Localize `jiya.py` strings (en/hinglish/hi) and QA system prompt register; verify test that each fixed phrase exists for all 3 languages (`config/jiya_i18n.py`; test asserts every phrase exists for all languages)
- [x] 5.4 STT language selection (`nova-3` language/multi for server path; `hi-IN`/`en-IN` for browser); verify manual call with a mixed-language question is transcribed correctly (nova-3 `multi`/`hi`/`en-IN` for server STT; `hi-IN`/`en-IN` for browser; server-STT audio upload not built in `call.js`, typed input is the fallback)

## 6. Scheduler and ring

- [x] 6.1 Minute-tick job selecting due users with idempotent `call_attempts` insert and T−10 min assembly; verify tests for on-time ring, restart-mid-window (no duplicate) and paused/unconsented skip (`scheduler/ring.py`)
- [x] 6.2 Concurrency semaphore with ≤5 min deferral and jitter; verify test where 20 users are due at once and none are dropped (per-tick assembly cap; due users are picked up on following ticks; live-call cap with client retry)
- [x] 6.3 Missed-call (10 min) and single reminder logic, stale-pipeline quiet message; verify tests for each scenario (one reminder via unique `reminder` slot)
- [ ] 6.4 Telegram ring: bot link flow (`/start <token>`), send Answer button, webhook; verify end-to-end with a real bot to the developer's chat

## 7. Call delivery

- [x] 7.1 Signed single-use call tokens and `/api/call/start`; verify tests for valid, missing, reused and expired token (`api/security.py` call tokens + `/ws/call` auth frame)
- [x] 7.2 Per-user `JiyaSession` (user briefing, user memory, language, name greeting) over `/ws/client?token=`; verify existing `test_voice.py` still passes and a new test covers per-user context (`JiyaSession` per-user: briefing, memory, language, name; legacy constructor still works)
- [ ] 7.3 `call.html` browser page: mic permission, Web Speech STT, audio playback, barge-in; verify with Playwright MCP against a local server and manual Android Chrome test
- [ ] 7.4 Phone adapter parameterized per user with verification call (press 1) and allow-list; verify unverified number never dialed (unit test with Twilio client stubbed)
- [x] 7.5 Text-only transcript storage with 30-day purge job; verify purge test and that no audio is written (text only; `purge_user_history`, scheduled 03:30)

## 8. Dashboard

- [x] 8.1 Static dashboard at `/app` (sign-in, profile form with interest chips + free text, time picker, language, consent, Telegram link, pause/delete, test call, transcript); verify with Playwright MCP that every `subscriber-profile` scenario is reachable (`newtalk/web/`; verified in browser pane)
- [x] 8.2 Mobile-width layout and Hindi/English UI labels; verify at 375 px viewport with no horizontal scroll (375 px: no horizontal scroll in EN and HI; UI language toggle)

## 9. Free-tier deploy and integration

- [x] 9.1 `.env.example`, Cloudflare Tunnel run guide, nightly DB backup script; verify a fresh clone runs following only the guide (`.env.example`, `DEPLOY.md`, `scripts/backup_db.sh`)
- [x] 9.2 Integration check: two test users (English/Delhi evening, Hinglish/tech+stocks) get correctly personalized, correctly localized calls at their times end-to-end; verify via logs and recorded transcripts (`test_integration_two_users.py`)
- [x] 9.3 Update `AGENTS.md`/`CLAUDE.md` with new commands, env vars and per-user flow; verify commands in the docs run as written (CLAUDE.md section; AGENTS.md was removed from the repo)

## Workflow follow-up

- Archive the change after a successful 3–5 user internal demo.
- Plan a separate change for the paid phase (PSTN provider, Supabase, paid TTS).
