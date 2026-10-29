"""
Free-tier web tools for LiteLLM function calling.
Uses DuckDuckGo search (no API key) and stdlib URL fetch.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for recent news and developments. "
            "Use for breaking stories in the last 24 hours."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (include category + 'last 24 hours' when relevant)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results (1-5)",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    },
}

FETCH_URL_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": "Fetch and extract text from a URL for fact-checking or background.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "HTTP/HTTPS URL to fetch",
                },
            },
            "required": ["url"],
        },
    },
}


def web_search(query: str, max_results: int = 3) -> list[dict]:
    """DuckDuckGo search — tries news first, falls back to web text results."""
    max_results = max(1, min(max_results, 5))
    try:
        from duckduckgo_search import DDGS

        def _format(results, snippet_key="body"):
            out = []
            for r in results:
                title = r.get("title", "")
                url = r.get("url", "") or r.get("href", "")
                if not title or not url:
                    continue
                out.append({
                    "title": title,
                    "url": url,
                    "snippet": (r.get(snippet_key) or r.get("body") or r.get("excerpt") or "")[:500],
                    "date": r.get("date", ""),
                })
            return out

        with DDGS() as ddgs:
            try:
                news = list(ddgs.news(query, max_results=max_results))
                formatted = _format(news)
                if formatted:
                    return formatted
            except Exception as news_exc:
                logger.info("DDG news unavailable for %r (%s) — trying text search", query, news_exc)

            text = list(ddgs.text(query, max_results=max_results))
            return _format(text, snippet_key="body")

    except Exception as exc:
        logger.warning("web_search failed for %r: %s", query, exc)
        return []


def fetch_url(url: str, max_chars: int = 4000) -> dict:
    """Fetch URL and strip HTML to plain text."""
    if not url.startswith(("http://", "https://")):
        return {"error": "Invalid URL", "url": url}
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NewTalk/0.1 (research bot)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"url": url, "text": text[:max_chars]}
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}", "url": url}
    except Exception as exc:
        return {"error": str(exc), "url": url}


def execute_tool(name: str, arguments: str | dict) -> str:
    """Execute a tool by name; returns JSON string for the LLM."""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            args = {}
    else:
        args = arguments

    if name == "web_search":
        results = web_search(
            query=args.get("query", ""),
            max_results=args.get("max_results", 3),
        )
    elif name == "fetch_url":
        results = fetch_url(url=args.get("url", ""))
    else:
        results = {"error": f"Unknown tool: {name}"}

    return json.dumps(results, ensure_ascii=False)
