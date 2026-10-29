"""
arXiv ingestion source.
Uses the public arXiv API (no key required) to fetch recent papers
from configured categories and writes them to raw_articles.
"""
import logging
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded before anything else
for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

from newtalk.ingestion.sources_config import ARXIV_CATEGORIES, ARXIV_MAX_RESULTS
from newtalk.db.repository import NewTalkRepository
from newtalk.config.settings import DATABASE_URL
from newtalk.processing.freshness import get_freshness_window_hours, is_within_freshness_window
from newtalk.ingestion.canonical import make_canonical_key

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ARXIV_TIER = 3  # broad discovery
_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _fetch_arxiv_category(category: str, max_results: int) -> list[dict]:
    """Fetch recent papers from a single arXiv category via the Atom API."""
    params = urllib.parse.urlencode({
        "search_query": f"cat:{category}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API_URL}?{params}"
    logger.info("Fetching arXiv category %s …", category)

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NewTalk/0.1 (mailto:local@newtalk.dev)"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_bytes = resp.read()
    except Exception as exc:
        logger.warning("arXiv request failed for %s: %s", category, exc)
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("arXiv XML parse error for %s: %s", category, exc)
        return []

    papers = []
    for entry in root.findall("atom:entry", _NS):
        title_el   = entry.find("atom:title",   _NS)
        summary_el = entry.find("atom:summary", _NS)
        id_el      = entry.find("atom:id",      _NS)
        pub_el     = entry.find("atom:published", _NS)

        title   = (title_el.text   or "").strip().replace("\n", " ") if title_el is not None else ""
        summary = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""
        url     = (id_el.text      or "").strip()                     if id_el is not None else ""

        if not title or not url:
            continue

        published_at = None
        if pub_el is not None and pub_el.text:
            try:
                published_at = datetime.datetime.fromisoformat(pub_el.text.rstrip("Z"))
            except ValueError:
                pass

        # Collect author names
        authors = [
            (a.find("atom:name", _NS).text or "").strip()
            for a in entry.findall("atom:author", _NS)
            if a.find("atom:name", _NS) is not None
        ]
        author_str = ", ".join(authors) if authors else None

        papers.append({
            "category": category,
            "title": title,
            "url": url,
            "body": summary,
            "author": author_str,
            "published_at": published_at,
        })

    return papers


def fetch_arxiv_papers(repo: NewTalkRepository | None = None) -> list[dict]:
    """
    Fetch recent papers from all configured arXiv categories.

    Args:
        repo: Optional repository. Writes to DB when provided.

    Returns:
        List of paper dicts that were fetched.
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    fetched = []
    window_hours = get_freshness_window_hours()
    for category in ARXIV_CATEGORIES:
        papers = _fetch_arxiv_category(category, ARXIV_MAX_RESULTS)
        for paper in papers:
            if paper["published_at"] and not is_within_freshness_window(paper["published_at"], window_hours):
                continue
            repo.add_article(
                source=f"arXiv:{paper['category']}",
                source_type="arxiv",
                url=paper["url"],
                title=paper["title"],
                body=paper["body"],
                author=paper["author"],
                published_at=paper["published_at"],
                tier=_ARXIV_TIER,
                canonical_key=make_canonical_key(paper["url"]),
            )
            fetched.append({
                "source": f"arXiv:{paper['category']}",
                "title": paper["title"],
                "url": paper["url"],
            })
        logger.info("arXiv %s → %d papers", category, len(papers))

    return fetched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = fetch_arxiv_papers()
    print(f"\narXiv ingestion complete — {len(results)} papers fetched.")
    for r in results[:5]:
        print(f"  [{r['source']}] {r['title'][:80]}")
