# NewsTalk — AI Personal Intelligence Briefing Agent

A daily (or on-demand) voice call from an AI "personal intelligence analyst" that:
- Pulls from real sources (news, Reddit, YouTube, papers, press releases).
- Deduplicates and clusters coverage of the same story.
- Scores importance (using a hybrid rule + LLM rubric).
- Builds rich context (history, viewpoints, evidence, uncertainty).
- Speaks a ~9-minute briefing, interruptible at any point for follow-up Q&A.
- Remembers what you already know to avoid repeating context.

## Folder Structure

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
│   └── ...
├── .env.example
└── README.md
```

## Setup Instructions

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:
   Copy `.env.example` to `.env` and fill in the API keys.
