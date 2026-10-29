# NewTalk — AI Personal Intelligence Briefing Agent

### Full Implementation Plan (No Shortcuts, No Hardcoding)

---

## 0. Ground Rules for This Build

These rules apply to every coding agent session working on this project. Paste the "Agent Operating Rules" section (§10) at the start of every agent session.

1. **Nothing is mocked or hardcoded to "make it work for now."** If real ingestion is needed, build real ingestion. If a real API call is needed, build the real call. Placeholder/stub code is only acceptable when explicitly marked `# TODO: Phase X` and confirmed with the human first.
2. **No Supabase / external DB for now.** Use local SQLite (via a thin repository/interface layer) so swapping to Supabase Postgres later is a one-file change, not a rewrite.
3. **LLM calls route through LiteLLM**, so the actual model/provider (OpenRouter, Groq, Gemini, Anthropic, etc.) is a config swap, not a code change.
4. **Any time the agent needs something only a human can provide** (API key, OAuth consent, paid signup, a UI decision, a file path on the human's machine, a phone number for the call, etc.) — **the agent must stop and explicitly ask**, listing exactly what's needed and why. It must never silently skip the step, fake a response, or invent a placeholder key.
5. **Build order matters.** Each module should be runnable and testable on its own before the next one is wired in.

---

## 1. Recap of the Vision

A daily (or on-demand) voice call from an AI "personal intelligence analyst" that:

- Pulls from real sources (news, Reddit, YouTube, papers, press releases)
- Deduplicates/clusters same-story coverage
- Scores **importance** (not popularity) using a hybrid rule+LLM rubric
- Builds context (history, viewpoints, evidence, uncertainty) per story
- Speaks a ~9-minute briefing, interruptible at any point for follow-up Q&A
- Remembers what you already know so it doesn't repeat itself over time

This document plans the **real, complete system** — not a demo skeleton.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                       │
│  RSS feeds │ Reddit API │ YouTube (transcripts) │ arXiv      │
│  Gov/press release feeds │ (X/Twitter — deferred, paid API)  │
└──────────────────────────┬────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              NORMALIZATION + STORAGE (SQLite)                 │
│  raw_articles table: source, url, title, body, published_at   │
└──────────────────────────┬────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│         DEDUPLICATION & CLUSTERING (embeddings)                │
│  Group same real-world story across multiple sources           │
└──────────────────────────┬────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           IMPORTANCE SCORING ENGINE (rules + LLM judge)         │
│  Output: ranked list of top N stories w/ scores + rationale     │
└──────────────────────────┬────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     CONTEXT ENGINE (LLM)                       │
│  Per story: background, timeline, viewpoints, evidence,        │
│  confidence level, what-might-happen-next                      │
└──────────────────────────┬────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              PERSONALIZATION / MEMORY (SQLite)                 │
│  Known-topics store, past briefing log, user interest weights   │
└──────────────────────────┬────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    SCRIPT COMPOSER (LLM)                       │
│  Turns ranked+contextualized stories into a spoken script       │
└──────────────────────────┬────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│          VOICE LAYER (STT + TTS + interruption/barge-in)        │
│  Delivers the call, handles live Q&A, updates memory after      │
└─────────────────────────────────────────────────────────────┘
```

All LLM calls in the Scoring, Context, and Composer stages go through **one LiteLLM client wrapper** — so the model backing each stage is a config value, not hardwired code.

---

## 3. Tech Stack (Final, for real build — nothing deferred)


| Layer                         | Choice                                                                                                                                                                                 | Why                                                                                                 |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Ingestion                     | `feedparser` (RSS), Reddit public JSON endpoints (`reddit.com/r/<sub>/top.json`, no OAuth/key needed), `youtube-transcript-api` + YouTube Data API, arXiv API                          | All free-tier or key-free, real data, no scraping-ToS issues                                        |
| Storage                       | SQLite (via SQLAlchemy or a small repository class)                                                                                                                                    | Zero-cost, file-based, swappable to Postgres/Supabase later behind the same interface               |
| Embeddings (dedup/clustering) | Local `sentence-transformers` model (e.g. `all-MiniLM-L6-v2`) run on CPU                                                                                                               | Free, no API cost, good enough for clustering                                                       |
| LLM routing                   | **LiteLLM**                                                                                                                                                                            | Single interface across OpenRouter, Groq, Gemini, Anthropic — swap models via config, not code      |
| LLM models (initial mix)      | Groq (Llama 3.3 70B or similar) for fast/cheap scoring passes; Gemini Flash for context generation; a stronger model (via OpenRouter) for final script composition if quality needs it | Use cheap/fast models for high-volume scoring, reserve a stronger model for the final spoken script |
| STT                           | Deepgram Nova-3 (streaming)                                                                                                                                                            | Best latency for live interruption detection                                                        |
| TTS                           | Deepgram Aura, or Cartesia Sonic as fallback                                                                                                                                           | Fast, cheap, good enough quality; swappable                                                         |
| Realtime orchestration        | Custom WebSocket server (Python `websockets` or `FastAPI` + `ws`) gluing STT → LLM → TTS with barge-in logic                                                                           | Full control over the interrupt-mid-briefing behavior, since this is core to the product feel       |
| Backend framework             | FastAPI (Python)                                                                                                                                                                       | Async-friendly, plays well with streaming voice + scheduled jobs                                    |
| Scheduler                     | APScheduler (in-process) for local dev; can move to GitHub Actions cron later for the daily 8 PM trigger                                                                               | Real scheduling, not manual triggering                                                              |
| Frontend (test harness)       | Minimal web page (or just a phone-call style CLI/websocket client) to place the "call"                                                                                                 | Just enough to test the experience, still real code, not a stub                                     |


**LiteLLM config approach**: a single `llm_config.yaml` mapping logical roles (`scorer`, `context_writer`, `composer`) to actual provider/model strings + API key env var names. Code calls `litellm.completion(model=config["scorer"]["model"], ...)`. Changing providers = editing YAML, not code.

---

## 4. Data Model (SQLite, Supabase-ready)

Tables (all designed so a later Postgres/Supabase migration is a schema export, not a redesign):

- `raw_articles` — id, source, source_type, url, title, body, author, published_at, fetched_at
- `story_clusters` — id, representative_title, first_seen_at, status (developing/settled)
- `cluster_members` — cluster_id, article_id
- `importance_scores` — cluster_id, score, rationale, scored_at, rubric_version
- `story_context` — cluster_id, background, timeline_json, viewpoints_json, confidence_level, evidence_json
- `briefings` — id, date, script_text, duration_estimate_sec, delivered_at
- `briefing_stories` — briefing_id, cluster_id, position
- `user_memory` — topic, familiarity_level, last_covered_at, notes
- `qa_log` — briefing_id, question, answer, asked_at

A `repository.py` module wraps all reads/writes. Nothing else touches SQLite directly — this is the seam where Supabase gets swapped in later.

---

## 5. Importance Scoring Engine (the actual hard part)

This is not "ask the LLM to pick top stories." It's a **hybrid rubric**:

**Rule-based signals (computed, not guessed):**

- Source corroboration count (how many independent clusters/sources cover it)
- Recency decay
- Entity scope (does it involve governments/large orgs/broad populations vs. a single individual)
- Category weight (configurable — e.g., policy/economy/tech/science weighted higher than celebrity/entertainment by default, but user-adjustable)
- Historical continuity (is this a new datapoint in an ongoing tracked thread — e.g., a geopolitical conflict the user has been following)

**LLM judgment layer (given the above signals as structured input):**

- Estimates likely long-term significance vs. short-term virality
- Flags "small story today, could be big later" candidates
- Produces a rationale string stored alongside the score (so the system is auditable, not a black box)

**Final score** = weighted combination, with weights stored in config so they're tunable without code changes. The LLM never scores blind — it always sees the computed signals first, which keeps it grounded rather than just reacting to "sounds important."

This module should have its own standalone test harness: feed it a batch of real pulled articles, inspect the ranked output and rationale, and tune weights before it's wired into the rest of the pipeline.

---

## 6. Context Engine

For each of the top-N clusters, one LLM call (through LiteLLM, `context_writer` role) produces structured JSON:

```json
{
  "what_happened": "...",
  "why_it_matters": "...",
  "who_is_affected": "...",
  "background_timeline": ["...", "..."],
  "viewpoints": [{"stance": "...", "supporting_evidence": "...", "source_leaning": "..."}],
  "confidence_level": "high | medium | developing",
  "open_questions": ["..."]
}
```

This structured output is what the Script Composer and the live Q&A engine both draw from — so follow-up questions during the call ("what are economists saying?") are answered from this stored context rather than a fresh un-grounded LLM guess.

---

## 7. Personalization / Memory

Local, file/SQLite-based for now (`user_memory` table):

- Tracks topics already explained in depth → composer is instructed to skip re-explaining basics
- Tracks ongoing threads (e.g. a conflict followed for weeks) → composer continues from last known state
- Updated after every briefing and after every Q&A exchange

This is designed as a clean interface (`memory.get_context_for(topic)`, `memory.update_after_briefing(...)`) so swapping the storage backend later doesn't touch the logic that uses it.

---

## 8. Voice Layer

Requirements from your spec: interruption mid-sentence, natural conversational follow-up, call-like framing ("Good evening, today's briefing will take about 9 minutes...").

Real implementation (not a demo shortcut):

1. WebSocket server accepts an audio stream from the client.
2. Deepgram streaming STT transcribes in real time; voice-activity detection flags when the user starts speaking **during** TTS playback (barge-in).
3. On barge-in: stop current TTS playback immediately, pass the user's utterance to the LLM (`qa` role) along with the current story's stored context (from §6) and briefing position, generate a response, resume or transition afterward.
4. TTS (Deepgram Aura) streams audio back in chunks, not as one blocking file, so playback starts fast.
5. Full turn history (what was said, what was asked) is logged to `qa_log` and feeds `user_memory` updates.

---

## 9. Repository / Folder Structure

```
newtalk/
├── ingestion/
│   ├── rss_source.py
│   ├── reddit_source.py
│   ├── youtube_source.py
│   ├── arxiv_source.py
│   └── run_ingestion.py
├── processing/
│   ├── embeddings.py
│   ├── clustering.py
│   └── dedup.py
├── scoring/
│   ├── rubric.py
│   └── importance_engine.py
├── context/
│   └── context_engine.py
├── memory/
│   └── memory_store.py
├── composer/
│   └── script_composer.py
├── voice/
│   ├── stt_client.py
│   ├── tts_client.py
│   └── realtime_server.py
├── llm/
│   ├── litellm_client.py
│   └── llm_config.yaml
├── db/
│   ├── models.py
│   ├── repository.py
│   └── newtalk.db   (gitignored)
├── scheduler/
│   └── daily_job.py
├── config/
│   └── settings.py
├── tests/
│   └── ... (one test module per component above)
├── .env.example
└── README.md
```

---

## 10. Agent Operating Rules (paste this at the start of every coding-agent session)

```
You are building a real, production-shaped system — not a demo or prototype
shortcut. Follow these rules strictly:

1. Do NOT hardcode, mock, stub, or fake any data source, API response, or
   pipeline step to "make it work for now" unless I explicitly approve a
   TODO for a clearly labeled later phase.
2. Do NOT skip building a component because it seems hard or time-consuming.
   Build it properly, in full, even if it takes longer.
3. All LLM calls must go through the LiteLLM wrapper and llm_config.yaml —
   never call a provider SDK directly.
4. Do NOT use Supabase or any external hosted DB right now. Use SQLite via
   the repository layer, structured so it can be swapped later.
5. Whenever you need something that ONLY I (the human) can provide or do —
   an API key, an OAuth login, a paid signup, a phone number, a manual
   config choice, credentials, a decision between two valid approaches —
   STOP and explicitly ask me. List exactly what you need and why. Do not
   invent a placeholder key, do not silently skip the feature, do not
   assume an answer on my behalf for anything irreversible or account-related.
6. Build and test one module at a time, in the order given, and confirm
   each one runs correctly with real data before moving to the next.
7. If you get stuck for more than a couple of attempts, tell me clearly
   what's blocking you instead of quietly working around it with fake data.
```

---

## 11. Build-Order Prompts for the Coding Agent

Use these in sequence, one per session/step. Each assumes the Agent Operating Rules (§10) are already in context.

### Prompt 1 — Project scaffold + config

```
Set up the project scaffold at the folder structure below (paste §9).
Create a Python virtual environment, a requirements.txt covering: fastapi,
uvicorn, sqlalchemy, feedparser, praw, youtube-transcript-api,
google-api-python-client, sentence-transformers, litellm, apscheduler,
websockets, python-dotenv.
Create .env.example listing every environment variable this project will
eventually need (leave values blank), including placeholders for:
YOUTUBE_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY,
DEEPGRAM_API_KEY.
(No Reddit key needed — Reddit ingestion uses public JSON endpoints,
no auth required.)
Do not fetch or call any external API yet. If you're unsure which of these
keys I already have vs. need to create, ask me directly rather than assuming.
```

### Prompt 2 — Database layer

```
Implement db/models.py and db/repository.py per the schema in NewTalk.md §4.
Use SQLAlchemy with SQLite. Write a small script to initialize the DB and
a test that inserts and reads back a sample raw_article, story_cluster,
and importance_score row. Run it and show me the output.
```

### Prompt 3 — LiteLLM wrapper

```
Implement llm/llm_config.yaml with three logical roles: scorer,
context_writer, composer, qa — each mapped to a placeholder model string
I'll fill in (e.g. groq/llama-3.3-70b-versatile, gemini/gemini-2.0-flash,
openrouter/<model>). Implement llm/litellm_client.py with a single function
call_llm(role, messages) that reads the role's model from config and calls
litellm.completion(). Do NOT hardcode any API key — read from environment
variables named per provider standard.
Before testing this, ask me which specific models/providers I want mapped
to each role, and confirm the relevant API keys are already in my .env —
if any are missing, tell me exactly which ones and where to get them.
```

### Prompt 4 — Ingestion modules (real, not sample data)

```
Implement ingestion/rss_source.py to pull from a configurable list of real
RSS feed URLs (I will supply the list — ask me for it if it's not already
in config), ingestion/reddit_source.py using Reddit's public JSON
endpoints (e.g. https://www.reddit.com/r/<subreddit>/top.json?limit=25&t=day)
with a proper User-Agent header and reasonable rate-limiting between
requests — no OAuth/API key needed for this, just ask me which subreddits
to pull from — ingestion/youtube_source.py to pull transcripts for a
configurable list of channels/videos, and ingestion/arxiv_source.py using
the public arXiv API (no key needed). Each should write normalized rows
into raw_articles via the repository layer. Write run_ingestion.py to run
all sources and report how many articles were fetched from each. Run it
for real and show me actual fetched output — do not fabricate sample results.
```

### Prompt 5 — Embeddings + clustering + dedup

```
Implement processing/embeddings.py using a local sentence-transformers
model to embed article titles+summaries. Implement processing/clustering.py
to group articles into story_clusters based on embedding similarity
(pick and justify a similarity threshold). Implement processing/dedup.py
to mark duplicate/near-duplicate coverage of the same event into one
cluster. Run this against the real articles pulled in Prompt 4 and show me
the resulting clusters — flag any obviously wrong groupings so we can tune
the threshold together.
```

### Prompt 6 — Importance scoring engine

```
Implement scoring/rubric.py with the rule-based signals from NewTalk.md §5
(source corroboration count, recency decay, entity scope, category weight,
historical continuity) as pure computed functions over a cluster's member
articles. Implement scoring/importance_engine.py which computes these
signals, then calls the LLM (role=scorer) with the signals as structured
input to produce a final score + rationale, storing both in
importance_scores. Ask me for my initial category weight preferences
(e.g. should policy/economy/tech be weighted above entertainment by
default?) before finalizing config defaults. Run against real clustered
data and show me the ranked top 10 with rationale so we can sanity-check it.
```

### Prompt 7 — Context engine

```
Implement context/context_engine.py: for each of the top-N scored
clusters, call the LLM (role=context_writer) to produce the structured
JSON described in NewTalk.md §6, and store it in story_context. Run this
on real top-ranked clusters from Prompt 6 and show me actual generated
context for 2-3 stories so we can review quality before proceeding.
```

### Prompt 8 — Memory store

```
Implement memory/memory_store.py per NewTalk.md §7: get_context_for(topic),
update_after_briefing(...), and update_after_qa(...). Wire it as a
dependency the composer and Q&A engine will call, but don't wire those yet.
Write a test simulating a few days of briefings to confirm familiarity
tracking behaves as expected (topics repeated shouldn't be re-explained
from scratch).
```

### Prompt 9 — Script composer

```
Implement composer/script_composer.py: takes the ranked+contextualized
stories plus relevant memory context, and calls the LLM (role=composer) to
produce a spoken-style script matching the tone in the original spec
("Good evening. Today's briefing will take about 9 minutes...").
Store the result in briefings/briefing_stories. Run it end-to-end on real
pipeline output from Prompts 4-8 and show me the full generated script.
```

### Prompt 10 — Voice layer

```
Implement voice/stt_client.py and voice/tts_client.py as thin wrappers
around Deepgram's streaming APIs (ask me to confirm the Deepgram API key
is in .env before testing — if I haven't created a Deepgram account yet,
tell me exactly what to sign up for and what plan/tier to pick).
Implement voice/realtime_server.py: a WebSocket server that streams TTS of
the composed script to a connected client, listens for incoming audio
concurrently, detects barge-in via voice activity, stops playback, routes
the user's utterance + current story context to the LLM (role=qa), and
resumes. Log all Q&A into qa_log and call memory.update_after_qa.
This is the core "interruptible call" experience — do not simplify the
interrupt handling; build it to genuinely stop and resume mid-sentence.
```

### Prompt 11 — Scheduler + orchestrator

```
Implement scheduler/daily_job.py using APScheduler to run the full
pipeline (ingest → cluster → score → context → compose) on a schedule,
and a separate trigger for "place the call" that a human or webhook can
invoke to start the voice session with today's composed briefing.
Ask me how I actually want to trigger the call for testing right now
(local script run vs. a simple web button) before building the trigger UI.
```

### Prompt 12 — End-to-end test

```
Run the entire pipeline for real, end to end, using real ingested data,
and place an actual test voice call with me so we can evaluate: latency,
interruption handling, script quality, and whether the importance ranking
feels right. Note anything that feels off so we can go back and tune the
specific module responsible, rather than patching symptoms downstream.
```

---

## 12. Manual / Human-Required Setup Checklist

Things only you can do — the agent should ask for these at the relevant prompt above, but here's the consolidated list so you can prep in advance if you want:

- [ ] ~~Reddit developer app~~ — not needed, using public JSON endpoints (no auth)
- [ ] YouTube Data API key via Google Cloud Console — free tier
- [ ] Groq API key — free tier available
- [ ] Gemini API key (Google AI Studio) — free tier available
- [ ] OpenRouter API key — pay-as-you-go, needed only if you want a stronger model for composition
- [ ] Deepgram account + API key — free trial credit ($200 typically) — needed for Prompt 10
- [ ] Your list of preferred RSS feeds / subreddits / YouTube channels to actually ingest from
- [ ] Your category-weight preferences for the importance rubric (Prompt 6)

---

## 13. What We're Explicitly Deferring (not skipping — deferring, on purpose, with your sign-off)

- **X/Twitter ingestion** — API access is paid with no usable free tier; revisit once the rest proves out.
- **Supabase migration** — the repository-layer design in §4 means this is a swap-in later, not a redesign.
- **Multi-user support** — architecture assumes single-user (you) for now; memory/personalization tables would need a `user_id` column added when this changes.

Everything else in this document is meant to be built in full, for real, in this pass.