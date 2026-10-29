# NewsTalk — Architecture & Design Document

## System Overview

NewsTalk is an **AI Personal Intelligence Briefing Agent** that delivers a daily (or on-demand) voice call from an AI analyst "Jiya". It pulls real news from multiple sources, deduplicates/clusters coverage, scores importance using a hybrid rule+LLM rubric, builds rich context with web grounding, composes a spoken briefing, and delivers it via interruptible voice call.

---

## Architecture Diagram

```
��─────────────────────────────────────────────────────────────────────────────��
│                              INGESTION LAYER                                 │
│  ��──────────��  ��──────────��  ��──────────��  ��──────────��  ��──────────��       │
│  │   RSS    │  │  Reddit  │  │ YouTube  │  │  arXiv   │  │  GDELT   │       │
│  │  (20+)   │  │  (7 sub) │  │ (3 chans)│  │ (3 cats) │  │ (3 qrys) │       │
│  └────��─────��  └────��─────��  └────��─────��  └────��─────��  └────��─────��       │
│       │             │             │             │             │              │
│       └─────────────��─────────────��─────────────��─────────────��              │
│                     ��             ��             ��                            │
│         ��─────────────────────────────────────────────────��                  │
│         │           AGENTIC TREND SCOUT (LLM + Web Search)│                  │
│         │   Categories: policy, economy, tech, science,   │                  │
│         │   geopolitics, health  |  6 searches max        │                  │
│         └────────────────────────��────────────────────────��                  │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                         NORMALIZATION & STORAGE (SQLite)                     │
│  raw_articles table: source, source_type, url, title, body, author,         │
│  published_at, fetched_at, tier (1-4), embedding, canonical_key             │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                    DEDUPLICATION & CLUSTERING (Embeddings)                   │
│  • Local sentence-transformers (all-MiniLM-L6-v2) on CPU                    │
│  • Incremental clustering: match new articles to existing cluster centroids │
│  • Similarity threshold: 0.78 (greedy) / 0.74 (incremental match)          │
│  • Change detection: repeat / minor / major development                     │
│  • Freshness gate: 24h window (configurable)                                │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                  IMPORTANCE SCORING ENGINE (Hybrid Rule + LLM)              │
│                                                                              │
│  RULE SIGNALS (computed):                                                   │
│  • Source corroboration count (independent sources covering story)          │
│  • Recency decay (exponential within 24h window)                            │
│  • Entity scope (government/large org vs individual)                        │
│  • Category weight (policy/economy/tech > entertainment)                    │
│  • Historical continuity (ongoing threads user follows)                     │
│  • India relevance (explicit scoring for Indian audience)                   │
│                                                                              │
│  LLM JUDGMENT (Groq Llama-3.3-70B):                                         │
│  • Long-term significance vs short-term virality                            │
│  • "Could grow later" flag                                                  │
│  • India angle rationale                                                    │
│  • Final score = 0.65 × rule_base + 0.35 × llm_score                       │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                         CONTEXT ENGINE (LLM + Web Grounding)                 │
│                                                                              │
│  For top-N clusters (default 12):                                           │
│  • LLM (Groq Llama-3.3-70B) generates structured JSON:                     │
│    - what_happened, why_it_matters, who_is_affected                         │
│    - background_timeline (cumulative across days)                           │
│    - viewpoints (stance, evidence, source_leaning)                          │
│    - confidence_level (high/medium/developing)                              │
│    - new_development (today's specific update)                              │
│    - grounding_audit (every claim traced to web_search/fetch_url/model)     │
│  • Tools: web_search (DuckDuckGo) + fetch_url (2 calls max per cluster)    │
│  • Cumulative mode: continues from yesterday's context for ongoing stories │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                    PERSONALIZATION / MEMORY (SQLite)                         │
│                                                                              │
│  user_memory table: topic, familiarity_level (0-5), last_covered_at, notes  │
│  • Composer skips basics for familiarity ≥ 2.0                              │
│  • Brief recap only for 0 < familiarity < 2.0                               │
│  • Updated after each briefing + each Q&A exchange                          │
│  • Yesterday's clusters tracked to avoid repetition                         │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                        SCRIPT COMPOSER (LLM)                                 │
│                                                                              │
│  Input: ranked + contextualized stories + memory context                    │
│  Dynamic selection:                                                          │
│  • min_story_score threshold (default 4.0)                                  │
│  • max_stories cap (default 8) — never a target                             │
│  • Quiet day handling (no stories above threshold)                          │
│  • Diagnostics logged for threshold calibration                             │
│                                                                              │
│  Output: spoken script (~4-9 min) with:                                     │
│  • Jiya personality: warm, casual, Indian English, contractions             │
│  • "Stop me if anything's unclear" interruption invites                     │
│  • Depth proportional to importance score                                   │
│  • Memory-aware: skips known basics, continues ongoing threads              │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                        VOICE LAYER (Real-time, Interruptible)               │
│                                                                              │
│  WebSocket Server (FastAPI + websockets):                                   │
│  • /ws/client  — local mic client (browser/CLI)                             │
│  • /ws/twilio — Twilio media stream for phone calls                         │
│                                                                              │
│  STT: Deepgram Nova-3 (streaming, VAD for barge-in detection)              │
│  TTS: Deepgram Aura (streaming chunks, <200ms first-byte)                  │
│                                                                              │
│  Barge-in Logic:                                                            │
│  1. User speech detected during TTS → immediate TTS cancel                 │
│  2. User utterance → QA LLM (Groq Llama-3.1-8B, ultra-low latency)         │
│  3. Context: current story context + briefing position + full briefing      │
│  4. Answer spoken → resume briefing or continue Q&A                         │
│  5. All Q&A logged to qa_log, memory updated                                │
│                                                                              │
│  Phone Call Flow:                                                           │
│  POST /call/phone → Twilio calls USER_PHONE_NUMBER →                        │
│  Twilio fetches TwiML from /voice/twiml → connects to /ws/twilio           │
��──────────────────────────────────��────────────────────────────────────────────��
                                   ��
��─────────────────────────────────────────────────────────────────────────────��
│                         SCHEDULER & ORCHESTRATOR                             │
│                                                                              │
│  APScheduler (BackgroundScheduler):                                         │
│  • Daily cron: 20:00 IST (configurable via audience_config.yaml)           │
│  • Runs full pipeline: ingest → cluster → score → context → compose        │
│                                                                              │
│  FastAPI Endpoints:                                                         │
│  • POST /pipeline/run     — manual trigger                                   │
│  • POST /call/phone       — trigger phone call                               │
│  • POST /call/start       — get WebSocket URL for local client              │
│  • GET  /briefing/latest  — preview latest briefing                         │
│  • GET  /health           — health check                                     │
��─────────────────────────────────────────────────────────────────────────────��
```

---

## News Sources (All Configured in `newtalk/ingestion/sources_config.py`)

### Tier 1 — Official / Primary Sources
| Source | URL | Type | Tier |
|--------|-----|------|------|
| PIB (Press Information Bureau) | https://pib.gov.in/Rss.aspx?CatId=-1 | RSS | 1 |
| RBI Press Releases | https://www.rbi.org.in/Scripts/Publications.aspx?RSS=PressRelease | RSS | 1 |

### Tier 2 — Quality Journalism (India-Focused)
| Source | URL | Type | Tier |
|--------|-----|------|------|
| The Hindu National | https://www.thehindu.com/news/national/feeder/default.rss | RSS | 2 |
| Indian Express India | https://indianexpress.com/section/india/feed/ | RSS | 2 |
| NDTV India | https://feeds.feedburner.com/ndtvnews-india-news | RSS | 2 |
| Times of India | https://timesofindia.indiatimes.com/rssfeedstopstories.cms | RSS | 2 |
| Mint News | https://www.livemint.com/rss/news | RSS | 2 |
| Business Standard | https://www.business-standard.com/rss/home_page_top_stories.rss | RSS | 2 |
| The Hindu Tech | https://www.thehindu.com/sci-tech/technology/feeder/default.rss | RSS | 2 |
| Indian Express Tech | https://indianexpress.com/section/technology/feed/ | RSS | 2 |
| BBC India | http://feeds.bbci.co.uk/news/world/asia/india/rss.xml | RSS | 2 |
| Reuters Top News | https://feeds.reuters.com/reuters/topNews | RSS | 2 |

### Tier 3 — Broad Discovery
| Source | URL | Type | Tier |
|--------|-----|------|------|
| Google News India | https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en | RSS | 3 |
| Google News India Economy | https://news.google.com/rss/search?q=India+economy... | RSS | 3 |
| Google News India Foreign Policy | https://news.google.com/rss/search?q=India+foreign+policy... | RSS | 3 |
| Ars Technica | https://feeds.arstechnica.com/arstechnica/index | RSS | 3 |

### Reddit (Public JSON, No API Key)
| Subreddit | Limit | Window |
|-----------|-------|--------|
| r/india | 25 | day |
| r/IndiaNews | 25 | day |
| r/indianews | 25 | day |
| r/worldnews | 25 | day |
| r/geopolitics | 25 | day |
| r/technology | 25 | day |
| r/economics | 25 | day |

### YouTube (Transcripts via YouTube Data API)
| Channel | ID | Max Results |
|---------|-----|-------------|
| WION | UC8p1rJ8FUXI3YJqYy6XvJ9w | 8 |
| PBS NewsHour | UCXIJgqnII2ZOINSWNOGFThA | 8 |
| BBC News | UC16niRr50-MSBwiO3YDbhRA | 8 |

### arXiv (Public API, No Key)
| Category | Max Results |
|----------|-------------|
| cs.AI | 15 |
| cs.LG | 15 |
| econ.GN | 15 |

### GDELT (Global Event Database)
| Query | Max Records |
|-------|-------------|
| India | 25 |
| Indian economy | 25 |
| India geopolitics | 25 |

### Agentic Trend Scout (LLM + Web Search)
| Category | Searches/Day |
|----------|--------------|
| policy | 1 |
| economy | 1 |
| tech | 1 |
| science | 1 |
| geopolitics | 1 |
| health | 1 |
| **Total** | **≤ 6** |

---

## Standout Features & Differentiators

### 1. **Hybrid Importance Scoring (Not Just LLM)**
- Rule signals computed deterministically (corroboration, recency, entity scope, category weight, India relevance, historical continuity)
- LLM only judges nuance (long-term significance, virality risk, "could grow later")
- Auditable rationale stored with every score
- Configurable weights via YAML — no code changes to retune

### 2. **Incremental Clustering with Change Detection**
- Never wipes clusters — runs incrementally on new articles only
- Matches new articles to existing cluster centroids (0.74 threshold)
- Change classification: `repeat` / `minor` / `major` development
- Only real developments bump `latest_development_at` and increment `development_count`
- 30-day pruning of unclustered stale articles

### 3. **Cumulative Context with Web Grounding**
- Context engine continues from yesterday's context for ongoing stories
- Every factual claim has `grounding_audit` entry: web_search / fetch_url / model_knowledge
- Tools limited (2 calls/cluster) — cost-controlled
- Structured JSON output feeds both Composer and live Q&A

### 4. **Memory-Aware Personalization**
- Topic familiarity tracked 0-5 scale
- Composer dynamically adjusts: skip basics (≥2.0), brief recap (0-2), full explain (0)
- Yesterday's clusters excluded from re-explanation
- Q&A exchanges boost familiarity for follow-up topics

### 5. **True Interruptible Voice (Not Push-to-Talk)**
- Deepgram streaming STT + VAD detects barge-in mid-sentence
- TTS cancelled in <100ms, QA LLM (8B model) responds in <500ms
- Resumes briefing at exact sentence boundary after Q&A
- Works on phone (Twilio) and WebSocket client

### 6. **Dynamic Story Selection (No Fixed Count)**
- `min_story_score` threshold (calibrated from diagnostics)
- `max_stories` is a ceiling, never a target
- Quiet day handling: honest "nothing major today" briefing
- Selection diagnostics logged to JSONL for threshold tuning

### 7. **LiteLLM Abstraction — Provider Swappable**
- 5 logical roles: scorer, context_writer, composer, qa, trend_scout
- Each mapped to model via `llm_config.yaml` (Groq/Gemini/OpenRouter)
- Per-role API key routing across multiple Groq accounts
- Change provider = edit YAML, not code

### 8. **Supabase-Ready Repository Layer**
- All DB access through `NewTalkRepository` class
- SQLite now, swap to Postgres/Supabase = one file change
- Schema designed for migration (no SQLite-specific types)

### 9. **India-First Design**
- All prompts include Indian audience perspective
- India relevance explicit signal in scoring
- Tier 1 sources: PIB, RBI (official GOI)
- Timezone: Asia/Kolkata throughout
- Indian English personality for voice

### 10. **Observable & Debuggable**
- Structured logging at every pipeline stage
- Diagnostics JSONL for story selection calibration
- Grounding audit for every context claim
- Briefing preview endpoint (`/briefing/latest`)
- Health check endpoint (`/health`)

---

## Tech Stack Summary

| Layer | Technology |
|-------|------------|
| Ingestion | feedparser, praw (Reddit JSON), youtube-transcript-api, google-api-python-client, arxiv API, GDELT API |
| Storage | SQLite + SQLAlchemy (repository pattern) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) local CPU |
| Clustering | Custom incremental + greedy (numpy, scikit-learn style) |
| LLM Routing | LiteLLM (Groq Llama-3.3-70B, Llama-3.1-8B) |
| Web Tools | DuckDuckGo (ddgs) + primp fetch |
| Scheduler | APScheduler (cron) |
| API | FastAPI + uvicorn |
| Voice STT | Deepgram Nova-3 streaming |
| Voice TTS | Deepgram Aura streaming |
| Phone | Twilio (outbound + media streams) |
| Config | YAML (llm_config, freshness_config, audience_config) |
| Env | python-dotenv |

---

## Pipeline Performance (Typical Daily Run)

| Stage | Duration | API Calls |
|-------|----------|-----------|
| Ingestion (all sources) | ~60s | 20 RSS + 7 Reddit + 3 YT + 3 arXiv + 3 GDELT + 6 trend |
| Embedding + Clustering | ~30s | Local only |
| Scoring (top 12) | ~20s | 12 Groq calls |
| Context (top 12) | ~60s | 12 Groq + ≤24 web searches |
| Compose | ~5s | 1 Groq call |
| **Total** | **~3-4 min** | **~25 Groq + ≤24 web searches** |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `newtalk/config/settings.py` | API keys, DB URL, host/port, freshness window |
| `newtalk/llm/llm_config.yaml` | Role→model mapping, temperature, max_tokens |
| `newtalk/config/freshness_config.yaml` | 24h window, thresholds, tool limits, selection params |
| `newtalk/config/audience_config.yaml` | Timezone, briefing hour, perspective prompt |
| `newtalk/config/jiya.py` | Personality, prompts, opening/closing lines |
| `newtalk/ingestion/sources_config.py` | All RSS/Reddit/YT/arXiv/GDELT source lists |

---

## Running the Pipeline

```bash
# Full pipeline (manual)
python3 -m newtalk.scheduler.daily_job  # starts API on :8000, voice on :8001
# Then: curl -X POST http://localhost:8000/pipeline/run

# Individual stages
python3 -m newtalk.ingestion.run_ingestion
python3 -m newtalk.processing.dedup
python3 -m newtalk.scoring.importance_engine
python3 -m newtalk.context.context_engine
python3 -m newtalk.composer.script_composer

# Voice test (WebSocket)
# Terminal 1: python3 -m newtalk.voice.call_app
# Terminal 2: python3 -m newtalk.voice.ws_client

# Phone call (requires Twilio + ngrok)
curl -X POST http://localhost:8000/call/phone
```

---

## Environment Variables Required

```bash
# Core APIs
YOUTUBE_API_KEY=
GROQ_API_KEY=           # Primary Groq account
GROQ_API_KEY_2=         # Second Groq account (for QA role isolation)
DEEPGRAM_API_KEY=

# Optional (Gemini/OpenRouter fallback)
GEMINI_API_KEY=
OPENROUTER_API_KEY=

# Phone calls (Twilio)
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=     # e.g. +1xxxxxxxxxx
USER_PHONE_NUMBER=      # e.g. +91xxxxxxxxxx
PUBLIC_BASE_URL=        # ngrok HTTPS URL for webhooks

# App config
DATABASE_URL=sqlite:///newtalk.db
PORT=8000
HOST=0.0.0.0
FRESHNESS_WINDOW_HOURS=24
REDDIT_USER_AGENT=NewTalk/0.1
```

---

## Future Enhancements (Deferred)

- **X/Twitter ingestion** — Paid API, no free tier
- **Supabase migration** — Repository layer ready, just schema export
- **Multi-user support** — Add `user_id` to memory/briefing tables
- **Breaking news interrupt** — Override schedule for urgent events
- **Category weight UI** — Web dashboard for rubric tuning
- **Offline TTS fallback** — Piper/Coqui for zero-API mode