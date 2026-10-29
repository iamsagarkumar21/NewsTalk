"""
GDELT DOC 2.0 ingestion source (Tier 3 — broad discovery).
Queries the GDELT API for India-relevant articles from the last 24 hours.
No API key required.
"""
from __future__ import annotations

import json
import logging
import datetime
import urllib.request
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv

for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

from newtalk.db.repository import NewTalkRepository
from newtalk.config.settings import DATABASE_URL
from newtalk.ingestion.sources_config import GDELT_BASE_URL, GDELT_QUERIES, GDELT_MAX_RECORDS
from newtalk.ingestion.canonical import make_canonical_key
from newtalk.processing.freshness import get_freshness_window_hours

logger = logging.getLogger(__name__)

TIER = 3


def _parse_gdelt_timestamp(ts_str: str | None) -> datetime.datetime | None:
    """Parse GDELT's YYYYMMDDHHMMSS string into datetime."""
    if not ts_str or len(ts_str) < 8:
        return None
    try:
        return datetime.datetime.strptime(ts_str[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def fetch_gdelt_articles(repo: NewTalkRepository | None = None) -> list[dict]:
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    fetched = []
    window_hours = get_freshness_window_hours()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=window_hours)

    for query in GDELT_QUERIES:
        params = urllib.parse.urlencode({
            "query": query,
            "mode": "ArtList",
            "maxrecords": GDELT_MAX_RECORDS,
            "format": "json",
            "timespan": f"{window_hours}h",
        })
        url = f"{GDELT_BASE_URL}?{params}"
        logger.info("Fetching GDELT: %s", query)

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "NewTalk/0.1 (+https://github.com/newtalk)"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("GDELT request failed for '%s': %s", query, exc)
            continue

        articles = payload.get("articles", [])
        for art in articles[:GDELT_MAX_RECORDS]:
            title = (art.get("title") or "").strip()
            link = (art.get("url") or "").strip()
            if not title or not link:
                continue

            published_at = _parse_gdelt_timestamp(art.get("seendate"))
            body = (art.get("seendate") or "") + " | " + (art.get("socialimage") or "")

            repo.add_article(
                source=f"GDELT:{query}",
                source_type="gdelt",
                url=link,
                title=title,
                body=body,
                author=None,
                published_at=published_at,
                tier=TIER,
                canonical_key=make_canonical_key(link),
            )
            fetched.append({
                "source": f"GDELT:{query}",
                "title": title,
                "url": link,
            })

    return fetched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = fetch_gdelt_articles()
    print(f"\nGDELT ingestion complete — {len(results)} articles")
    for r in results[:5]:
        print(f"  [{r['source']}] {r['title'][:80]}")
