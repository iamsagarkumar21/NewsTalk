"""Tests for freshness window and cluster recency logic."""
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from newtalk.processing.freshness import (
    get_freshness_window_hours,
    is_within_freshness_window,
    is_cluster_fresh,
    compute_latest_article_at,
)
from newtalk.db.models import RawArticle, StoryCluster


def test_freshness_window_default_24h():
    assert get_freshness_window_hours() == 24


def test_is_within_window():
    now = datetime.datetime.utcnow()
    assert is_within_freshness_window(now, 24) is True
    old = now - datetime.timedelta(hours=30)
    assert is_within_freshness_window(old, 24) is False


def test_cluster_freshness_uses_most_recent_member():
    now = datetime.datetime.utcnow()
    old = now - datetime.timedelta(days=5)

    a_old = RawArticle(
        id=1, source="A", source_type="rss", url="http://a", title="Old",
        body="", published_at=old,
    )
    a_new = RawArticle(
        id=2, source="B", source_type="rss", url="http://b", title="New",
        body="", published_at=now,
    )

    latest = compute_latest_article_at([a_old, a_new])
    assert latest == now

    cluster = StoryCluster(
        id=1, representative_title="Story", latest_article_at=now, articles=[a_old, a_new],
    )
    assert is_cluster_fresh(cluster, 24) is True

    stale_cluster = StoryCluster(
        id=2, representative_title="Stale", latest_article_at=old, articles=[a_old],
    )
    assert is_cluster_fresh(stale_cluster, 24) is False


if __name__ == "__main__":
    test_freshness_window_default_24h()
    test_is_within_window()
    test_cluster_freshness_uses_most_recent_member()
    print("Freshness tests passed!")
