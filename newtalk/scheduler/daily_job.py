"""
Daily pipeline scheduler + orchestrator.

Runs: ingest → cluster → score → context → compose on a schedule.
Exposes FastAPI endpoints to trigger pipeline or start a voice call.

Usage:
    python3 -m newtalk.scheduler.daily_job
    # API at http://localhost:8000
    # POST /pipeline/run   — run full pipeline
    # POST /call/start     — get WebSocket URL for voice briefing
    # GET  /health         — health check
"""
from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from newtalk.config.settings import HOST, PORT, DATABASE_URL
from newtalk.ingestion.run_ingestion import run_all_ingestion
from newtalk.processing.dedup import run_dedup_and_cluster
from newtalk.scoring.importance_engine import score_all_clusters
from newtalk.context.context_engine import generate_context_for_top_clusters
from newtalk.composer.script_composer import compose_briefing_script, select_stories_for_briefing
from newtalk.config.audience import load_audience_config
from newtalk.processing.freshness import load_freshness_config
from newtalk.db.repository import NewTalkRepository
from newtalk.api.routes import router as dashboard_router
from newtalk.api.security import get_repo, require_admin
from newtalk.composer.user_briefing import active_scope, prewarm_segments
from newtalk.voice.browser_call import router as call_router

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="NewsTalk Orchestrator")
app.include_router(dashboard_router)
app.include_router(call_router)
scheduler = BackgroundScheduler()
_stop_telegram = threading.Event()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=()")
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache"
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' wss: ws:; media-src 'self' blob:; img-src 'self' data:; "
            "frame-ancestors 'none'",
        )
    return response

# Pipeline config — read from freshness_config.yaml (tunable)
_freshness = load_freshness_config()
LOW_LLM_MODE = os.getenv("LOW_LLM_MODE", "0") == "1"  # testing on free quotas
CONTEXT_TOP_N = 6 if LOW_LLM_MODE else int(_freshness.get("context_top_n", 12))
MAX_STORIES = int(_freshness.get("max_stories", 8))
_audience = load_audience_config()
DAILY_CRON_HOUR = int(_audience.get("briefing_hour", 20))
DAILY_CRON_MINUTE = int(_audience.get("briefing_minute", 0))
DAILY_CRON_TZ = _audience.get("timezone", "Asia/Kolkata")
VOICE_WS_PORT = PORT + 1


def run_full_pipeline() -> dict:
    """Execute the complete briefing pipeline."""
    logger.info("=== Starting full pipeline ===")
    repo = NewTalkRepository(DATABASE_URL)
    repo.create_tables()

    categories, languages, active_users = active_scope(repo)
    ingestion = run_all_ingestion()
    clustering = run_dedup_and_cluster(repo=repo)
    scoring = score_all_clusters(repo=repo, llm_top_n=CONTEXT_TOP_N)
    context = generate_context_for_top_clusters(
        repo=repo,
        top_n=CONTEXT_TOP_N,
        per_category=1 if LOW_LLM_MODE else int(_freshness.get("context_per_category", 2)),
        categories=categories,
    )
    if active_users:
        prewarmed = prewarm_segments(
            repo, categories, languages, limit=10 if LOW_LLM_MODE else 40
        )
        briefing = {"briefing_id": None, "duration_estimate_sec": None}
        logger.info("Pre-generated segments for %d stories (%s)", prewarmed, sorted(languages))
    else:
        briefing = compose_briefing_script(repo=repo)

    result = {
        "ingestion": ingestion,
        "clustering": {
            "clusters_created": clustering["clusters_created"],
            "articles_processed": clustering["articles_processed"],
        },
        "top_scored": scoring[:10],
        "context_generated": len(context),
        "active_users": active_users,
        "briefing_id": briefing["briefing_id"],
        "duration_estimate_sec": briefing["duration_estimate_sec"],
    }
    logger.info("=== Pipeline complete (active users: %d) ===", active_users)
    return result


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/pipeline/run", dependencies=[Depends(require_admin)])
def trigger_pipeline():
    try:
        result = run_full_pipeline()
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("Pipeline failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/call/phone", dependencies=[Depends(require_admin)])
def trigger_phone_call(briefing_id: int | None = None):
    """Ring user's phone via Twilio — Jiya delivers briefing on answer."""
    from newtalk.voice.phone_call import place_phone_call, twilio_configured
    from newtalk.config.settings import PUBLIC_BASE_URL

    if not twilio_configured():
        return JSONResponse({
            "error": "Twilio not configured",
            "need": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
                     "USER_PHONE_NUMBER", "PUBLIC_BASE_URL"],
            "setup": "1) twilio.com signup  2) buy a number  3) ngrok http 8001  4) set PUBLIC_BASE_URL",
        }, status_code=400)

    repo = NewTalkRepository(DATABASE_URL)
    briefing = repo.get_briefing(briefing_id) if briefing_id else repo.get_latest_briefing()
    if not briefing:
        return JSONResponse({"error": "No briefing. Run /pipeline/run first."}, status_code=404)

    try:
        call_sid = place_phone_call(briefing.id)
        return {"status": "calling", "assistant": "Jiya", "call_sid": call_sid, "briefing_id": briefing.id}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/call/start", dependencies=[Depends(require_admin)])
def start_call(briefing_id: int | None = None):
    """Return WebSocket URL to connect for the voice briefing."""
    repo = NewTalkRepository(DATABASE_URL)
    briefing = repo.get_briefing(briefing_id) if briefing_id else repo.get_latest_briefing()
    if not briefing:
        return JSONResponse({"error": "No briefing available. Run /pipeline/run first."}, status_code=404)

    return {
        "websocket_url": f"ws://127.0.0.1:{VOICE_WS_PORT}/ws/client",
        "briefing_id": briefing.id,
        "assistant": "Jiya",
        "instructions": (
            "Terminal 1: python3 -m newtalk.voice.call_app\n"
            "Terminal 2: python3 -m newtalk.voice.ws_client\n"
            "Or phone: POST /call/phone"
        ),
    }


@app.get("/briefing/latest", dependencies=[Depends(require_admin)])
def latest_briefing():
    repo = NewTalkRepository(DATABASE_URL)
    briefing = repo.get_latest_briefing()
    if not briefing:
        return JSONResponse({"error": "No briefing yet"}, status_code=404)
    return {
        "id": briefing.id,
        "date": str(briefing.date),
        "duration_estimate_sec": briefing.duration_estimate_sec,
        "script_preview": briefing.script_text[:500],
    }


def _run_ring_tick():
    from newtalk.config import settings
    from newtalk.notify.telegram import TelegramClient
    from newtalk.scheduler.ring import tick

    client = TelegramClient() if settings.TELEGRAM_BOT_TOKEN else None
    try:
        tick(get_repo(), client=client)
    except Exception:
        logger.exception("Ring tick failed")


def _run_retention():
    try:
        logger.info("Retention purge: %s", get_repo().purge_user_history(older_than_days=30))
    except Exception:
        logger.exception("Retention purge failed")


def _schedule_jobs():
    hours = os.getenv("PIPELINE_HOURS", "6,13,19")
    if hours.strip().lower() in ("", "off", "none"):
        logger.info("Scheduled pipeline disabled (PIPELINE_HOURS=%s); run it via POST /pipeline/run", hours)
    else:
        scheduler.add_job(
            run_full_pipeline,
            CronTrigger(hour=hours, minute=0, timezone=DAILY_CRON_TZ),
            id="pipeline",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        _run_ring_tick,
        IntervalTrigger(seconds=60),
        id="ring_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_retention,
        CronTrigger(hour=3, minute=30, timezone=DAILY_CRON_TZ),
        id="retention",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Pipeline at hours %s %s; ring tick every 60s", hours, DAILY_CRON_TZ)


def _start_telegram_poller():
    from newtalk.config import settings

    if not settings.TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram ring disabled")
        return
    from newtalk.notify.telegram import TelegramClient, poll_forever

    threading.Thread(
        target=poll_forever,
        args=(get_repo(), _stop_telegram, TelegramClient()),
        daemon=True,
        name="telegram-poller",
    ).start()
    logger.info("Telegram poller started")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")


if WEB_DIR.exists():
    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="app")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    get_repo()
    _schedule_jobs()
    _start_telegram_poller()
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
