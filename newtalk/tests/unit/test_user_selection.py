"""Per-user story selection and interest normalizer tests."""

import json

import pytest

from newtalk.db.repository import NewTalkRepository
from newtalk.config.interests import rubric_categories_for


@pytest.fixture
def repo():
    r = NewTalkRepository("sqlite:///:memory:")
    r.create_tables()
    return r


def _seed_clusters(repo, categories_and_scores):
    """Create scored+contextualized clusters for testing selection."""
    for i, (cat, score, title) in enumerate(categories_and_scores, 1):
        art = repo.add_article(
            source=f"Test:{cat}",
            source_type="rss",
            url=f"https://test.com/{i}",
            title=title,
            body=f"{cat} news body with keywords for detection",
            author=None,
            published_at=None,
            tier=2,
        )
        cluster = repo.create_cluster(representative_title=title)
        repo.add_article_to_cluster(cluster.id, art.id)
        repo.set_importance_score(
            cluster_id=cluster.id,
            score=score,
            rationale="test",
            rubric_version="test",
        )
        repo.set_story_context(
            cluster_id=cluster.id,
            background="test context",
            timeline_json="[]",
            viewpoints_json="[]",
            confidence_level="confirmed",
            evidence_json='{"why_it_matters": "test"}',
        )


def test_rubric_categories_for_maps_correctly():
    assert rubric_categories_for(["tech"]) == ["tech"]
    assert rubric_categories_for(["politics"]) == ["policy", "state"]
    assert rubric_categories_for(["markets"]) == ["markets"]
    assert "tech" in rubric_categories_for(["tech", "markets"])
    assert "markets" in rubric_categories_for(["tech", "markets"])


def test_user_with_tech_interest_gets_tech_stories(repo):
    from newtalk.composer.user_selection import select_stories_for_user

    _seed_clusters(
        repo,
        [
            ("tech", 7.0, "AI breakthrough in machine learning technology"),
            ("tech", 6.0, "New startup raises funding in software tech"),
            ("sports", 8.0, "Cricket IPL match results and sports championship"),
            ("markets", 7.5, "Nifty Sensex stock market rally today"),
            ("policy", 6.5, "Parliament passes new legislation bill policy"),
        ],
    )

    user = repo.create_user(auth_provider="invite")
    repo.upsert_profile(user.id, call_name="Dev", interests=["tech"], language="en")

    stories = select_stories_for_user(user.id, repo, max_stories=3)
    titles = [c.representative_title for c in stories]
    assert any("technology" in t.lower() or "tech" in t.lower() for t in titles)


def test_user_with_no_profile_gets_global_selection(repo):
    from newtalk.composer.user_selection import select_stories_for_user

    _seed_clusters(
        repo,
        [
            ("tech", 7.0, "AI breakthrough in machine learning technology"),
            ("policy", 8.0, "Parliament passes new legislation bill policy"),
        ],
    )

    user = repo.create_user(auth_provider="invite")
    stories = select_stories_for_user(user.id, repo, max_stories=3)
    assert len(stories) >= 1


def test_update_normalized_json(repo):
    user = repo.create_user(auth_provider="invite")
    repo.upsert_profile(user.id, call_name="Test", interests=["tech"])
    repo.update_normalized_json(
        user.id, json.dumps({"categories": ["tech"], "keywords": ["openai"]})
    )

    profile = repo.get_profile(user.id)
    data = json.loads(profile.normalized_json)
    assert data["keywords"] == ["openai"]


def test_normalize_without_free_text_is_rule_only():
    from newtalk.composer.interest_normalizer import normalize_interests

    result = normalize_interests(["tech", "markets"], None)
    assert "tech" in result["categories"]
    assert "markets" in result["categories"]
    assert result["keywords"] == []
