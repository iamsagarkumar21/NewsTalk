"""
Freshness utilities — recency filtering and cluster age based on newest member.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import yaml

from newtalk.db.models import RawArticle, StoryCluster

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "freshness_config.yaml"


def load_freshness_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_freshness_window_hours() -> int:
    """Read window from env override or freshness_config.yaml (default 24h)."""
    import os
    env_val = os.getenv("FRESHNESS_WINDOW_HOURS")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    config = load_freshness_config()
    return int(config.get("freshness_window_hours", 24))


def article_timestamp(article: RawArticle) -> datetime.datetime | None:
    """Best available timestamp for an article (published preferred, else fetched)."""
    return article.published_at or article.fetched_at


def is_within_freshness_window(
    dt: datetime.datetime | None,
    window_hours: int | None = None,
) -> bool:
    """True if dt is within the freshness window (or dt is None — keep with penalty later)."""
    if dt is None:
        return True  # unknown age: keep at ingestion, may be gated at scoring
    if window_hours is None:
        window_hours = get_freshness_window_hours()
    age_hours = (datetime.datetime.utcnow() - dt).total_seconds() / 3600
    return age_hours <= window_hours


def cluster_most_recent_timestamp(cluster: StoryCluster) -> datetime.datetime | None:
    """Cluster freshness = latest meaningful development, else newest member timestamp."""
    if getattr(cluster, "latest_development_at", None):
        return cluster.latest_development_at
    if getattr(cluster, "latest_article_at", None):
        return cluster.latest_article_at
    articles = list(cluster.articles)
    if not articles:
        return None
    timestamps = [article_timestamp(a) for a in articles]
    timestamps = [t for t in timestamps if t is not None]
    return max(timestamps) if timestamps else None


def compute_latest_article_at(articles: list[RawArticle]) -> datetime.datetime | None:
    """Compute latest timestamp across a list of articles."""
    timestamps = [article_timestamp(a) for a in articles]
    timestamps = [t for t in timestamps if t is not None]
    return max(timestamps) if timestamps else None


def is_cluster_fresh(
    cluster: StoryCluster,
    window_hours: int | None = None,
) -> bool:
    """Hard recency gate: cluster must have a member within the freshness window."""
    if window_hours is None:
        window_hours = get_freshness_window_hours()
    latest = cluster_most_recent_timestamp(cluster)
    if latest is None:
        return False
    return is_within_freshness_window(latest, window_hours)
