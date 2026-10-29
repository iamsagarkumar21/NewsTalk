"""
Agentic trend scout — LLM + web search for breaking developments.
Runs alongside passive RSS/Reddit/YouTube ingestion (not instead of it).
Writes to raw_articles with source_type='agentic_search'.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path

from dotenv import load_dotenv

for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

from newtalk.config.settings import DATABASE_URL
from newtalk.db.repository import NewTalkRepository
from newtalk.llm.litellm_client import call_llm_with_tools
from newtalk.llm.tools.web_tools import WEB_SEARCH_TOOL, execute_tool, web_search
from newtalk.processing.freshness import load_freshness_config
from newtalk.config.audience import get_perspective_prompt
from newtalk.ingestion.sources_config import TREND_SCOUT_REGION_SUFFIX
from newtalk.ingestion.canonical import make_title_key
from newtalk.llm.date_context import get_date_context

logger = logging.getLogger(__name__)


def _is_valid_story_title(title: str) -> bool:
    if not title or len(title) < 8:
        return False
    lower = title.lower()
    if lower.startswith("error:") or lower.startswith("http error"):
        return False
    if "ratelimit" in lower and len(title) < 40:
        return False
    return True


def _normalize_story(item, default_category: str = "general") -> dict | None:
    """Coerce LLM output item into a story dict."""
    if isinstance(item, str):
        title = item.strip()
        if not _is_valid_story_title(title):
            return None
        return {"category": default_category, "title": title, "url": "", "summary": "", "significance": ""}
    if isinstance(item, dict):
        if item.get("error"):
            return None
        title = (item.get("title") or item.get("headline") or "").strip()
        if not _is_valid_story_title(title):
            return None
        return {
            "category": item.get("category") or default_category,
            "title": title,
            "url": (item.get("url") or item.get("link") or "").strip(),
            "summary": (item.get("summary") or item.get("snippet") or item.get("body") or "").strip(),
            "significance": (item.get("significance") or item.get("importance") or "").strip(),
        }
    return None


def _stories_from_tool_audit(audit: list[dict]) -> list[dict]:
    """Fallback: extract stories from web_search tool results when LLM JSON is malformed."""
    stories = []
    for entry in audit:
        if entry.get("tool") != "web_search":
            continue
        try:
            args = json.loads(entry.get("arguments") or "{}")
            category = "general"
            query = (args.get("query") or "").lower()
            for cat in ("policy", "economy", "tech", "science", "geopolitics", "health"):
                if cat in query:
                    category = cat
                    break
            result = json.loads(entry.get("result_full") or entry.get("result_preview") or "[]")
            if isinstance(result, dict) and "error" in result:
                continue
            if not isinstance(result, list):
                continue
            for hit in result:
                if not isinstance(hit, dict):
                    continue
                story = _normalize_story({
                    "category": category,
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "summary": hit.get("snippet", ""),
                }, default_category=category)
                if story:
                    stories.append(story)
        except (json.JSONDecodeError, TypeError):
            continue
    return stories


def _parse_stories_json(text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []

    # Try raw parse first
    candidates = [text]
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        candidates.insert(0, match.group(0))
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        candidates.append(obj_match.group(0))

    raw_items = []
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                raw_items = data
                break
            if isinstance(data, dict):
                raw_items = data.get("stories") or data.get("results") or data.get("items") or []
                if isinstance(raw_items, list):
                    break
        except json.JSONDecodeError:
            continue

    stories = []
    for item in raw_items:
        story = _normalize_story(item)
        if story:
            stories.append(story)
    return stories


def _fetch_via_direct_search(categories: list[str], per_category: int = 2) -> list[dict]:
    """Deterministic fallback when LLM JSON is malformed."""
    import time
    stories = []
    for i, cat in enumerate(categories):
        if i > 0:
            time.sleep(1.5)  # reduce DuckDuckGo rate-limit hits
        hits = web_search(f"{cat} breaking news India", max_results=per_category)
        for hit in hits:
            if not isinstance(hit, dict) or hit.get("error"):
                continue
            story = _normalize_story({
                "category": cat,
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
                "summary": hit.get("snippet", ""),
            }, default_category=cat)
            if story:
                stories.append(story)
    return stories


def fetch_trending_developments(repo: NewTalkRepository | None = None) -> list[dict]:
    """
    Use trend_scout LLM + web_search tool to find breaking stories per category.

    Returns list of fetched article dicts written to DB.
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    config = load_freshness_config()
    categories = config.get("trend_scout_categories", [])
    max_searches = int(config.get("trend_scout_max_searches", 6))

    perspective = get_perspective_prompt()
    date_context = get_date_context()
    system = (
        f"{date_context}\n\n"
        "You are a trend scout for a personal intelligence briefing aimed at an Indian audience. "
        f"\n{perspective}\n\n"
        "Use the web_search tool to find the most significant BREAKING developments "
        "in the last 24 hours for each category you are given. "
        "Prioritize stories with direct relevance to India and South Asia. "
        "CRITICAL for state_politics/regional_issues: Search for state-level breaking news — "
        "student protests, exam paper leaks, recruitment scams, bandhs, farmer agitations, "
        "caste/communal tensions, law-and-order crises, infrastructure failures in major states "
        "(Jharkhand, Uttar Pradesh, Bihar, Maharashtra, Tamil Nadu, Karnataka, West Bengal, "
        "Gujarat, Rajasthan, Madhya Pradesh, Kerala). These often don't make national headlines "
        "but deeply affect millions. "
        "Make at most one web_search per category. "
        "After searching, respond with JSON array only:\n"
        '[{"category": "...", "title": "...", "url": "...", "summary": "...", '
        '"significance": "...", "india_relevance": "..."}]'
    )
    user = (
        f"Categories to scout (last 24 hours, India perspective): {', '.join(categories)}. "
        f"Search context: {TREND_SCOUT_REGION_SUFFIX}. "
        "Focus on importance, not virality. Include source URL for each finding."
    )

    audit: list[dict] = []
    try:
        resp, audit = call_llm_with_tools(
            role="trend_scout",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=[WEB_SEARCH_TOOL],
            tool_executor=execute_tool,
            max_tool_rounds=max_searches,
        )
        content = resp.choices[0].message.content or "[]"
        stories = _parse_stories_json(content)
        if not stories:
            logger.warning("Trend scout LLM JSON empty/malformed — trying tool audit, then direct search")
            stories = _stories_from_tool_audit(audit)
        if not stories:
            stories = _fetch_via_direct_search(categories)
    except Exception as exc:
        logger.error("Trend scout failed: %s", exc)
        return []

    if not stories:
        logger.warning("Trend scout produced no valid stories — skipping agentic_search write")
        return []

    fetched = []
    for story in stories:
        if not isinstance(story, dict):
            story = _normalize_story(story)
        if not story:
            continue
        title = story.get("title", "").strip()
        url = story.get("url", "").strip()
        if not title:
            continue
        if not url:
            url = f"agentic://trend/{story.get('category', 'general')}/{make_title_key(title, story.get('category', ''))}"

        body = (
            f"{story.get('summary', '')}\n\n"
            f"Significance: {story.get('significance', '')}\n"
            f"Category: {story.get('category', '')}\n"
            f"Tool audit: {json.dumps(audit)[:500]}"
        ).strip()

        repo.add_article(
            source=f"TrendScout:{story.get('category', 'general')}",
            source_type="agentic_search",
            url=url,
            title=title,
            body=body,
            author="trend_scout",
            published_at=None,        # unknown publish time — freshness gated by fetched_at
            tier=4,                    # early signals
            canonical_key=make_title_key(title, story.get('category', '')),
        )
        fetched.append({
            "source": f"TrendScout:{story.get('category', '')}",
            "title": title,
            "url": url,
        })

    logger.info("Trend scout wrote %d agentic_search articles (%d tool calls)", len(fetched), len(audit))
    return fetched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = fetch_trending_developments()
    print(f"\nTrend scout complete — {len(results)} stories")
    for r in results[:8]:
        print(f"  [{r['source']}] {r['title'][:75]}")
