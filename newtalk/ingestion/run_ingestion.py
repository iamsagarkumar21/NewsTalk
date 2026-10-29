"""
Ingestion orchestrator.
Runs all configured ingestion sources and reports how many articles
were fetched from each. Writes everything to the local SQLite DB
via the repository layer.

Usage:
    python3 -m newtalk.ingestion.run_ingestion
    # or
    python3 newtalk/ingestion/run_ingestion.py
"""
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded before anything else
for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from newtalk.db.repository import NewTalkRepository
from newtalk.config.settings import DATABASE_URL
from newtalk.ingestion.rss_source import fetch_rss_feeds
from newtalk.ingestion.reddit_source import fetch_reddit_feeds
from newtalk.ingestion.arxiv_source import fetch_arxiv_papers
from newtalk.ingestion.youtube_source import fetch_youtube_transcripts
from newtalk.ingestion.trending_agent import fetch_trending_developments
from newtalk.ingestion.gdelt_source import fetch_gdelt_articles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_ingestion")


def run_all_ingestion() -> dict[str, int]:
    """
    Run every ingestion source, sharing a single DB repository instance.

    Returns:
        Dict mapping source name → number of articles fetched.
    """
    repo = NewTalkRepository(DATABASE_URL)
    repo.create_tables()
    logger.info("DB ready at: %s", DATABASE_URL)

    totals: dict[str, int] = {}

    # ── RSS ───────────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("Starting RSS ingestion …")
    try:
        rss_articles = fetch_rss_feeds(repo=repo)
    except Exception as exc:
        logger.error("RSS ingestion failed (non-fatal): %s", exc)
        rss_articles = []
    totals["RSS"] = len(rss_articles)
    logger.info("RSS done — %d articles", totals["RSS"])

    # ── Reddit ────────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("Starting Reddit ingestion …")
    try:
        reddit_articles = fetch_reddit_feeds(repo=repo)
    except Exception as exc:
        logger.error("Reddit ingestion failed (non-fatal): %s", exc)
        reddit_articles = []
    totals["Reddit"] = len(reddit_articles)
    logger.info("Reddit done — %d posts", totals["Reddit"])

    # ── GDELT ─────────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("Starting GDELT ingestion …")
    try:
        gdelt_articles = fetch_gdelt_articles(repo=repo)
    except Exception as exc:
        logger.error("GDELT ingestion failed (non-fatal): %s", exc)
        gdelt_articles = []
    totals["GDELT"] = len(gdelt_articles)
    logger.info("GDELT done — %d articles", totals["GDELT"])

    # ── arXiv ─────────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("Starting arXiv ingestion …")
    try:
        arxiv_articles = fetch_arxiv_papers(repo=repo)
    except Exception as exc:
        logger.error("arXiv ingestion failed (non-fatal): %s", exc)
        arxiv_articles = []
    totals["arXiv"] = len(arxiv_articles)
    logger.info("arXiv done — %d papers", totals["arXiv"])

    # ── YouTube ───────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("Starting YouTube ingestion …")
    try:
        yt_articles = fetch_youtube_transcripts(repo=repo)
    except Exception as exc:
        logger.error("YouTube ingestion failed (non-fatal): %s", exc)
        yt_articles = []
    totals["YouTube"] = len(yt_articles)
    logger.info("YouTube done — %d transcripts", totals["YouTube"])

    # ── Agentic trend scout (alongside passive sources) ───────────────────────
    logger.info("=" * 50)
    logger.info("Starting agentic trend scout …")
    import os

    try:
        if os.getenv("LOW_LLM_MODE") == "1":
            logger.info("LOW_LLM_MODE: trend scout skipped to save LLM quota")
            agentic_articles = []
        else:
            agentic_articles = fetch_trending_developments(repo=repo)
    except Exception as exc:
        logger.error("Trend scout failed (non-fatal): %s", exc)
        agentic_articles = []
    totals["AgenticSearch"] = len(agentic_articles)
    logger.info("Trend scout done — %d stories", totals["AgenticSearch"])

    return totals


def print_report(totals: dict[str, int]) -> None:
    total_all = sum(totals.values())
    print("\n" + "=" * 50)
    print("  INGESTION REPORT")
    print("=" * 50)
    for source, count in totals.items():
        print(f"  {source:<12}  {count:>5} articles")
    print("-" * 50)
    print(f"  {'TOTAL':<12}  {total_all:>5} articles")
    print("=" * 50)


if __name__ == "__main__":
    totals = run_all_ingestion()
    print_report(totals)
