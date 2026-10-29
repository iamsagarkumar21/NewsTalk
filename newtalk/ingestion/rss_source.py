"""
RSS feed ingestion source.
Pulls articles from the configured list of RSS feed URLs using feedparser
and writes normalised rows to raw_articles via the repository layer.
"""
import logging
import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded before anything else
for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

import feedparser
from newtalk.ingestion.sources_config import RSS_FEEDS
from newtalk.db.repository import NewTalkRepository
from newtalk.config.settings import DATABASE_URL
from newtalk.processing.freshness import get_freshness_window_hours, is_within_freshness_window
from newtalk.ingestion.canonical import make_canonical_key

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; NewTalk/0.1; +news-briefing)"


def _parse_dt(entry) -> datetime.datetime | None:
    """Convert feedparser's time struct to datetime, or return None."""
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if t:
        try:
            return datetime.datetime(*t[:6])
        except Exception:
            pass
    return None


def fetch_rss_feeds(repo: NewTalkRepository | None = None) -> list[dict]:
    """
    Pull articles from all configured RSS feeds.

    Args:
        repo: Optional repository instance. If provided, articles are written
              to the DB automatically. Pass None to just return raw dicts.

    Returns:
        List of article dicts that were fetched (regardless of repo).
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    fetched = []
    skipped_stale = 0
    window_hours = get_freshness_window_hours()

    for feed_cfg in RSS_FEEDS:
        url    = feed_cfg["url"]
        source = feed_cfg["source"]
        tier   = feed_cfg.get("tier", 2)
        logger.info("Fetching RSS: %s (%s)", source, url)

        try:
            parsed = feedparser.parse(url, agent=USER_AGENT)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            continue

        if parsed.bozo:
            logger.warning("Malformed feed at %s: %s", url, parsed.bozo_exception)

        for entry in parsed.entries:
            title = getattr(entry, "title", "").strip()
            link  = getattr(entry, "link",  "").strip()
            if not title or not link:
                continue

            summary = (
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            ).strip()
            author = getattr(entry, "author", None)
            published_at = _parse_dt(entry)

            if published_at and not is_within_freshness_window(published_at, window_hours):
                skipped_stale += 1
                continue

            article = repo.add_article(
                source=source,
                source_type="rss",
                url=link,
                title=title,
                body=summary,
                author=author,
                published_at=published_at,
                tier=tier,
                canonical_key=make_canonical_key(link),
            )
            fetched.append({
                "source": source,
                "title": title,
                "url": link,
            })

    if skipped_stale:
        logger.info("RSS skipped %d entries outside %dh freshness window", skipped_stale, window_hours)
    return fetched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = fetch_rss_feeds()
    print(f"\nRSS ingestion complete — {len(results)} articles fetched.")
    for r in results[:5]:
        print(f"  [{r['source']}] {r['title'][:80]}")
