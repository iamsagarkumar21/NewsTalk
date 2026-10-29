# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run full pipeline (API + scheduler)
```bash
python3 -m newtalk.scheduler.daily_job
```
API runs at `http://localhost:8000`. Manual triggers: `POST /pipeline/run`, `POST /call/start`, `POST /call/phone`.

### Run voice server separately
```bash
python3 -m newtalk.voice.call_app
# WS: ws://localhost:8001/ws/client
# Phone: POST http://localhost:8001/call/phone
```

### Run individual pipeline stages
```bash
python3 -m newtalk.ingestion.run_ingestion
python3 -m newtalk.processing.dedup
python3 -m newtalk.scoring.importance_engine
python3 -m newtalk.context.context_engine
python3 -m newtalk.composer.script_composer
```

### Tests
```bash
python3 -m pytest newtalk/tests/ -v
python3 -m pytest newtalk/tests/test_db.py -v     # single module
```
Tests use in-memory SQLite. No external services are mocked — some tests make real API calls.

## Architecture

The pipeline runs in five ordered stages:

1. **Ingestion** (`newtalk/ingestion/`) — pulls from RSS, Reddit, YouTube, arXiv, GDELT, and an agentic trending search. All sources emit `RawArticle` rows into the DB.
2. **Dedup + Clustering** (`newtalk/processing/dedup.py`) — generates sentence-transformer embeddings, does incremental cosine-similarity clustering (threshold 0.74) against existing `StoryCluster` centroids. Never wipes clusters. Change detection (`change_detection.py`) classifies updates as `repeat`/`minor`/`major`.
3. **Scoring** (`newtalk/scoring/importance_engine.py`) — hybrid rule + LLM rubric assigns a 0-10 `ImportanceScore` to each cluster.
4. **Context** (`newtalk/context/context_engine.py`) — LLM builds grounded `StoryContext` (background, timeline, India angle) per cluster using tool-calling for optional web lookups.
5. **Composition** (`newtalk/composer/script_composer.py`) — selects stories above `min_story_score` (default 4.0, max 8 stories) and composes a spoken briefing script for "Jiya". Selection diagnostics log to `logs/briefing_selection.jsonl`.

**Voice layer** (`newtalk/voice/`) — FastAPI + WebSocket server. `JiyaSession` orchestrates Deepgram Nova-3 streaming STT (barge-in via VAD), TTS cancellation (<100ms), and a QA LLM for follow-up questions. Supports both local mic (`WebSocketTransport`) and Twilio phone calls (`TwilioTransport`, requires ngrok HTTPS).

**DB** (`newtalk/db/`) — SQLAlchemy models + `NewTalkRepository`. All DB access goes through the repository; swapping to Postgres/Supabase = change `DATABASE_URL` only. Key tables: `raw_articles`, `story_clusters`, `cluster_members`, `importance_scores`, `story_contexts`, `briefings`.

**LLM** (`newtalk/llm/litellm_client.py`) — single `call_llm(role, messages)` entry point. Role→model mapping lives in `newtalk/llm/llm_config.yaml`. Currently all roles route to Groq. `qa` role uses `GROQ_API_KEY_2` to isolate QA from main pipeline quota.

**Memory** (`newtalk/memory/memory_store.py`) — topic familiarity 0-5 scale; composer skips basic context for familiar topics (score ≥2.0).

## Key Conventions

- **All LLM calls** via `call_llm(role, messages)` — never call provider SDKs directly.
- **Voice port** is always `PORT + 1` (default 8001).
- **Timezone** is Asia/Kolkata throughout — scheduler, logs, briefing time.
- **`max_stories`** is a ceiling, not a target — quiet days produce fewer stories.
- **Cluster change detection** only bumps `latest_development_at` on `minor`/`major`, not `repeat`.
- `.env` is searched at `newtalk/.env` then `NewsTalk/.env` — `litellm_client.py` loads it first.

## Required Environment Variables

`YOUTUBE_API_KEY`, `GROQ_API_KEY`, `GROQ_API_KEY_2`, `DEEPGRAM_API_KEY`, `REDDIT_USER_AGENT`

Optional: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `TWILIO_TO_NUMBER`, `PUBLIC_BASE_URL` (ngrok HTTPS for Twilio), `DATABASE_URL` (defaults to `sqlite:///newtalk.db` relative to `newtalk/`).

## Multi-user dashboard, ring and browser call

Users sign in at `/app/` with a personal **invite code**, set name/topics/free text/call time/language
(`en`, `hinglish`, `hi`), connect Telegram and consent. Everything runs in one process
(`python3 -m newtalk.scheduler.daily_job`, port 8000): dashboard (`newtalk/web/`), API
(`newtalk/api/routes.py`), scheduler, Telegram poller and the call WebSocket `/ws/call`.

### Commands
```bash
.venv/bin/python -m pytest newtalk/tests/unit -q          # fast suite, no network
.venv/bin/python -m newtalk.ingestion.feed_health         # probe every RSS feed
scripts/backup_db.sh                                       # SQLite online backup
curl -X POST :8000/api/admin/invites -H "X-Admin-Key: $ADMIN_API_KEY" -d '{"count":3}' -H 'Content-Type: application/json'
```
See `DEPLOY.md` for tunnel + invite + backup steps.

### Flow
1. Shared pipeline (3x/day, `PIPELINE_HOURS`): ingest -> cluster -> score -> **interest-aware context**
   (global top-N plus best stories of every followed category) -> `prewarm_segments`.
2. `composer/segments.py`: one spoken segment per (cluster, language, development_version), cached in
   `story_segments`. Batched LLM calls, sensitive-claim rules, script-form validation, retry then a safe
   fallback line that is never cached. LLM cost = stories x languages, not users.
3. `composer/user_selection.py`: only the user's followed categories/keywords + at most one must-know
   story (score >= 8); freshness gate; repeat suppression via `last_change_kind`.
4. `composer/user_briefing.py`: assembles localized intro + segments + outro (`config/jiya_i18n.py`).
5. `scheduler/ring.py` `tick()` (every minute): assemble at T-10, Telegram ring at T, missed after 10 min
   with one reminder. Idempotent through the unique `(user, local_date, slot)` in `call_attempts`.
6. Browser call: single-use call token (`api/security.py`) -> `/ws/call` -> `voice/session.py`
   (`JiyaSession`) with `voice/tts_providers.py` (edge-tts mp3) and browser Web Speech STT.

### Conventions specific to this layer
- Hindi/Hinglish text is **mixed script** (Devanagari for Hindi words, Latin for English) so the hi-IN
  voice pronounces it correctly; `HINGLISH_SCRIPT=roman` switches. Validators enforce it.
- Q&A answers are grounded in the current story's facts only (`session._story_facts`).
- LLM keys: if `GROQ_API_KEY` is rejected the client falls back to `GROQ_API_KEY_2` automatically.
- `.env` files are indented in places; `python-dotenv` handles it. Never print key values.
- Tests that touch story selection use `newtalk/tests/unit/helpers.py` (`seed_cluster`, `FakeLLM`).
