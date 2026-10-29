"""Probe every configured RSS feed: HTTP status, item count, items in the last 24h.

    python3 -m newtalk.ingestion.feed_health
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime

import feedparser

from newtalk.ingestion.rss_source import USER_AGENT
from newtalk.ingestion.sources_config import RSS_FEEDS


def _probe(cfg: dict) -> dict:
    try:
        parsed = feedparser.parse(cfg["url"], agent=USER_AGENT)
    except Exception as exc:
        return {**cfg, "items": 0, "fresh": 0, "status": f"ERR {exc}"[:40]}
    now = datetime.datetime.utcnow()
    fresh = 0
    for entry in parsed.entries:
        t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if t and (now - datetime.datetime(*t[:6])).total_seconds() < 86400:
            fresh += 1
    return {**cfg, "items": len(parsed.entries), "fresh": fresh, "status": getattr(parsed, "status", "?")}


def probe_all() -> list[dict]:
    with cf.ThreadPoolExecutor(12) as pool:
        return sorted(pool.map(_probe, RSS_FEEDS), key=lambda r: (r["items"] == 0, -r["fresh"]))


if __name__ == "__main__":
    rows = probe_all()
    print(f"{'source':32} {'topic':14} {'http':>5} {'items':>6} {'<24h':>5}")
    for r in rows:
        print(f"{r['source']:32} {r['topic']:14} {str(r['status']):>5} {r['items']:>6} {r['fresh']:>5}")
    dead = [r["source"] for r in rows if r["items"] == 0]
    print(f"\n{len(rows) - len(dead)}/{len(rows)} feeds returning items.")
    if dead:
        print("No items:", ", ".join(dead))
