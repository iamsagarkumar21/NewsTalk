import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import datetime
from newtalk.db.repository import NewTalkRepository

def run_test():
    print("Initializing test database...")
    db_url = "sqlite:///:memory:"  # Use in-memory SQLite for testing
    repo = NewTalkRepository(db_url)
    repo.create_tables()

    print("\n--- Testing RawArticle ---")
    article = repo.add_article(
        source="TechCrunch",
        source_type="rss",
        url="https://techcrunch.com/2026/07/07/ai-chip-breakthrough",
        title="New AI Chip Achieves 10x Efficiency",
        body="Researchers have announced a novel silicon architecture that delivers 10x energy efficiency for transformer models...",
        author="Jane Doe",
        published_at=datetime.datetime.utcnow()
    )
    print(f"Added Article: {article}")

    # Fetch back
    fetched_article = repo.get_article(article.id)
    print(f"Fetched Article: {fetched_article}")
    assert fetched_article.title == article.title
    assert fetched_article.url == article.url

    print("\n--- Testing StoryCluster ---")
    cluster = repo.create_cluster(
        representative_title="Breakthroughs in AI Hardware Efficiency",
        status="developing"
    )
    print(f"Created Cluster: {cluster}")

    # Add article to cluster
    repo.add_article_to_cluster(cluster.id, article.id)
    
    # Fetch cluster and check relationship
    fetched_cluster = repo.get_cluster(cluster.id)
    print(f"Fetched Cluster: {fetched_cluster}")
    print(f"Cluster Articles: {fetched_cluster.articles}")
    assert len(fetched_cluster.articles) == 1
    assert fetched_cluster.articles[0].id == article.id

    print("\n--- Testing ImportanceScore ---")
    score = repo.set_importance_score(
        cluster_id=cluster.id,
        score=8.5,
        rationale="Major silicon architecture shift targeting AI efficiency, backed by top researchers.",
        rubric_version="v1.0"
    )
    print(f"Set Importance Score: {score}")

    # Fetch importance score
    fetched_score = repo.get_importance_score(cluster.id)
    print(f"Fetched Importance Score: {fetched_score}")
    print(f"Rationale: {fetched_score.rationale}")
    assert fetched_score.score == 8.5
    assert fetched_score.cluster_id == cluster.id

    # Check relationship from cluster side
    fetched_cluster_again = repo.get_cluster(cluster.id)
    print(f"Cluster Importance Score from relationship: {fetched_cluster_again.importance_score}")
    assert fetched_cluster_again.importance_score.score == 8.5

    print("\nDB Test Completed Successfully!")

if __name__ == "__main__":
    run_test()
