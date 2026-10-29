# NewsTalk — Agent Instructions

## Project Overview
AI Personal Intelligence Briefing Agent delivering daily voice calls from "Jiya" — an AI analyst that ingests real news, deduplicates/clusters coverage, scores importance via hybrid rule+LLM rubric, builds grounded context, composes spoken briefings, and delivers via interruptible voice (WebSocket + Twilio). India-first design, local SQLite storage (Supabase-ready).

## Developer Commands

### Run Full Pipeline (API + Scheduler)
```bash
python3 -m newtalk.scheduler.daily_job
# API at http://localhost:8000
# POST /pipeline/run  — manual trigger
# POST /call/start    — WebSocket URL for voice
# POST /call/phone    — ring phone via Twilio
```

### Run Voice Server Separately
```bash
python3 -m newtalk.voice.call_app
# WS: ws://localhost:8001/ws/client
# Phone: POST http://localhost:8001/call/phone
```

### Run Individual Pipeline Stages
```bash
python3 -m newtalk.ingestion.run_ingestion
python3 -m newtalk.processing.dedup
python3 -m newtalk.scoring.importance_engine
python3 -m newtalk.context.context_engine
python3 -m newtalk.composer.script_composer
```

### Voice Test (Local)
```bash
# Terminal 1
python3 -m newtalk.voice.call_app
# Terminal 2
python3 -m newtalk.voice.ws_client
```

## Configuration Files (All in `newtalk/config/`)

| File | Purpose |
|------|---------|
| `settings.py` | API keys, DB URL, host/port, freshness window (reads `.env`) |
| `llm/llm_config.yaml` | Role→model mapping (scorer, context_writer, composer, qa, trend_scout) |
| `freshness_config.yaml` | 24h window, similarity thresholds, tool limits, selection params |
| `audience_config.yaml` | Timezone (Asia/Kolkata), briefing hour (20:00 IST), perspective prompt |
| `jiya.py` | Personality, prompts, opening/closing lines |
| `ingestion/sources_config.py` | All RSS/Reddit/YouTube/arXiv/GDELT source lists |

## Environment Variables (`.env` in `newtalk/` or project root)

Required: `YOUTUBE_API_KEY`, `GROQ_API_KEY`, `GROQ_API_KEY_2`, `DEEPGRAM_API_KEY`, `REDDIT_USER_AGENT`
Optional: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `TWILIO_*`, `PUBLIC_BASE_URL` (ngrok HTTPS), `DATABASE_URL`

## Architecture Highlights

- **Repository Pattern**: All DB access via `NewTalkRepository` in `newtalk/db/repository.py` — swap to Postgres/Supabase = one file change
- **LiteLLM Abstraction**: 5 logical roles, each mapped to model in `llm_config.yaml` — provider swap = edit YAML, not code
- **Incremental Clustering**: Never wipes clusters; matches new articles to existing centroids (0.74 threshold); change detection: `repeat`/`minor`/`major`
- **Dynamic Story Selection**: `min_story_score` threshold (default 4.0), `max_stories` cap (default 8) — never a target; quiet day handling
- **Memory-Aware**: Topic familiarity 0-5 scale; composer skips basics (≥2.0), brief recap (0-2)
- **Interruptible Voice**: Deepgram Nova-3 streaming STT + VAD barge-in detection; TTS cancelled <100ms; QA LLM (8B) responds <500ms

## Key Entry Points

- `newtalk/scheduler/daily_job.py` — APScheduler + FastAPI orchestrator (main entry)
- `newtalk/voice/call_app.py` — Unified WebSocket server (client + Twilio)
- `newtalk/composer/script_composer.py` — Story selection + script composition
- `newtalk/ingestion/run_ingestion.py` — All source ingestion

## Testing

```bash
# Run all tests
python3 -m pytest newtalk/tests/ -v

# Individual test modules
python3 -m newtalk.tests.test_db
python3 -m newtalk.tests.test_memory
python3 -m newtalk.tests.test_freshness
```

Tests use in-memory SQLite (`sqlite:///:memory:`). No external services mocked — real API calls where applicable.

## Operational Gotchas

1. **Two Groq Keys**: `GROQ_API_KEY` (primary) and `GROQ_API_KEY_2` (QA role isolation) — both required
2. **PUBLIC_BASE_URL**: Must be HTTPS ngrok URL for Twilio webhooks (`ngrok http 8001`)
3. **Database Path**: `DATABASE_URL=sqlite:///newtalk.db` resolves relative to `newtalk/` dir via `settings.py`
4. **Voice Port**: Always `PORT + 1` (8001 if PORT=8000)
5. **Freshness Window**: Default 24h, configurable in `freshness_config.yaml` or `FRESHNESS_WINDOW_HOURS` env
6. **Diagnostics**: Story selection logs to `logs/briefing_selection.jsonl` for threshold calibration

## Non-Obvious Conventions

- All LLM calls via `newtalk.llm.litellm_client.call_llm(role, messages)` — never call provider SDKs directly
- Timezone is **Asia/Kolkata** throughout (scheduler, logs, briefing time)
- Indian English personality in `config/jiya.py` (contractions, "yaar", warm casual tone)
- `max_stories` is a **ceiling**, not a target — selection diagnostics logged for calibration
- Cluster change detection only bumps `latest_development_at` on `minor`/`major` (not `repeat`)
- 30-day pruning of unclustered stale articles runs during dedup