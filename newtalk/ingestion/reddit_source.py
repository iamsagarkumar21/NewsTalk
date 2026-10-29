"""
Reddit ingestion source.
Pulls posts from configured subreddits via Reddit's public JSON endpoints
(no OAuth/API key required). Uses a proper User-Agent and rate-limits
between subreddit requests.
"""
import json
import logging
import time
import datetime
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv

for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

from newtalk.ingestion.sources_config import REDDIT_SUBREDDITS, REDDIT_POST_LIMIT
from newtalk.db.repository import NewTalkRepository
from newtalk.config.settings import DATABASE_URL, REDDIT_USER_AGENT
from newtalk.processing.freshness import get_freshness_window_hours, is_within_freshness_window
from newtalk.ingestion.canonical import make_canonical_key

logger = logging.getLogger(__name__)

_USER_AGENT = (
    REDDIT_USER_AGENT
    or "Mozilla/5.0 (compatible; NewTalk/0.1; +https://github.com/newtalk)"
)
# Reddit time filter — always last 24h (t=day), enforced at query level
REDDIT_TIME_FILTER = "day"
_REDDIT_TIER = 4  # early signals
_REQUEST_DELAY_SEC = 2.0


def _post_within_window(published_at: datetime.datetime | None) -> bool:
    if published_at is None:
        return True
    return is_within_freshness_window(published_at, get_freshness_window_hours())


def _fetch_subreddit_via_rss(sub_name: str, limit: int) -> list[dict]:
    """Fallback when Reddit JSON API returns 403 (common on cloud/datacenter IPs)."""
    import feedparser
    import datetime as _dt

    url = f"https://www.reddit.com/r/{sub_name}/.rss"
    logger.info("Fetching r/%s via RSS fallback …", sub_name)
    try:
        parsed = feedparser.parse(url, agent=_USER_AGENT)
    except Exception as exc:
        logger.warning("RSS fallback failed for r/%s: %s", sub_name, exc)
        return []

    posts = []
    for entry in parsed.entries[:limit]:
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not title or not link:
            continue
        summary = (
            getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        ).strip()
        # Parse timestamp from RSS — stop losing freshness on the fallback path
        published_at = None
        t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if t:
            try:
                published_at = _dt.datetime(*t[:6])
            except Exception:
                pass
        posts.append({
            "title": title,
            "url": link,
            "body": summary,
            "author": getattr(entry, "author", None),
            "published_at": published_at,
        })
    return posts


def _fetch_subreddit_posts(sub_name: str, limit: int) -> list[dict]:
    """Fetch top posts for a subreddit from Reddit's public JSON API."""
    url = (
        f"https://www.reddit.com/r/{sub_name}/top.json"
        f"?limit={min(limit, 100)}&t={REDDIT_TIME_FILTER}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("HTTP %s for r/%s: %s", exc.code, sub_name, exc.reason)
        if exc.code in (403, 429):
            return _fetch_subreddit_via_rss(sub_name, limit)
        return []
    except Exception as exc:
        logger.warning("Failed to fetch r/%s: %s", sub_name, exc)
        return []

    children = payload.get("data", {}).get("children", [])
    posts = []
    for child in children:
        post = child.get("data", {})
        title = (post.get("title") or "").strip()
        if not title:
            continue

        if post.get("is_self"):
            body = (post.get("selftext") or "").strip()
            link = f"https://www.reddit.com{post.get('permalink', '')}"
        else:
            body = ""
            link = post.get("url") or f"https://www.reddit.com{post.get('permalink', '')}"

        created = post.get("created_utc")
        published_at = (
            datetime.datetime.utcfromtimestamp(created) if created else None
        )
        author = post.get("author")

        posts.append({
            "title": title,
            "url": link,
            "body": body,
            "author": author,
            "published_at": published_at,
        })
    return posts


def fetch_reddit_feeds(repo: NewTalkRepository | None = None) -> list[dict]:
    """
    Pull top posts from all configured subreddits via public JSON endpoints.

    Returns:
        List of article dicts that were fetched.
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    fetched = []
    for i, sub_name in enumerate(REDDIT_SUBREDDITS):
        if i > 0:
            time.sleep(_REQUEST_DELAY_SEC)

        logger.info("Fetching r/%s (top %d, t=%s) …", sub_name, REDDIT_POST_LIMIT, REDDIT_TIME_FILTER)
        posts = _fetch_subreddit_posts(sub_name, REDDIT_POST_LIMIT)

        for post in posts:
            if not _post_within_window(post["published_at"]):
                continue
            repo.add_article(
                source=f"r/{sub_name}",
                source_type="reddit",
                url=post["url"],
                title=post["title"],
                body=post["body"],
                author=post["author"],
                published_at=post["published_at"],
                tier=_REDDIT_TIER,
                canonical_key=make_canonical_key(post["url"]),
            )
            fetched.append({
                "source": f"r/{sub_name}",
                "title": post["title"],
                "url": post["url"],
            })

    return fetched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = fetch_reddit_feeds()
    print(f"\nReddit ingestion complete — {len(results)} posts fetched.")
    for r in results[:5]:
        print(f"  [{r['source']}] {r['title'][:80]}")
