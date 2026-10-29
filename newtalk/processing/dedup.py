"""
Deduplication orchestrator: embed new articles, match to existing clusters
or create new ones. NEVER wipes clusters — runs incrementally.
"""
from __future__ import annotations

import datetime
import json
import logging

import numpy as np

from newtalk.config.settings import DATABASE_URL
from newtalk.db.repository import NewTalkRepository
from newtalk.processing.embeddings import article_text, generate_embeddings
from newtalk.processing.clustering import cluster_by_similarity, DEFAULT_SIMILARITY_THRESHOLD
from newtalk.processing.freshness import get_freshness_window_hours, compute_latest_article_at
from newtalk.processing.change_detection import classify_update, novelty_score

logger = logging.getLogger(__name__)

_INCREMENTAL_THRESHOLD = 0.74  # slightly lower than greedy clustering (0.78)


def _backfill_embeddings(repo: NewTalkRepository, articles: list) -> None:
    """One-time: compute + store embeddings for articles that don't have them yet."""
    missing = [a for a in articles if not a.embedding]
    if not missing:
        return
    logger.info("Backfilling embeddings for %d articles …", len(missing))
    texts = [article_text(a.title, a.body) for a in missing]
    embeddings = generate_embeddings(texts)
    for a, emb in zip(missing, embeddings):
        repo.set_article_embedding(a.id, emb.astype(np.float32).tobytes())


def run_incremental_dedup(
    repo: NewTalkRepository | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    incremental_threshold: float = _INCREMENTAL_THRESHOLD,
    article_limit: int | None = None,
) -> dict:
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    window_hours = get_freshness_window_hours()

    # 1. Get new (unclustered) articles within freshness window
    new_articles = repo.get_unclustered_articles(window_hours)
    if not new_articles:
        logger.info("No new unclustered articles within %dh window — nothing to cluster.", window_hours)
        return {"clusters_created": 0, "articles_processed": 0, "articles_matched": 0, "clusters": []}

    logger.info("Processing %d new articles for incremental clustering …", len(new_articles))

    # 2. Generate embeddings for new articles + backfill existing cluster members
    texts = [article_text(a.title, a.body) for a in new_articles]
    new_embeddings = generate_embeddings(texts)
    new_embeddings_norm = np.asarray(new_embeddings, dtype=np.float32)

    # 3. Compute centroids for existing clusters
    centroids = repo.get_cluster_centroids()
    cluster_ids = list(centroids.keys())
    centroid_vecs = np.array([centroids[cid] for cid in cluster_ids], dtype=np.float32) if centroids else np.zeros((0, 384))

    # 4. Match new articles to existing clusters
    matched = set()
    new_cluster_members = {cid: [] for cid in cluster_ids}
    cluster_summaries = []

    for i, art in enumerate(new_articles):
        art_emb = new_embeddings_norm[i]
        matched_cluster_id = None
        best_sim = incremental_threshold

        for j, cid in enumerate(cluster_ids):
            sim = float(np.dot(art_emb, centroid_vecs[j]))
            if sim >= best_sim:
                best_sim = sim
                matched_cluster_id = cid

        if matched_cluster_id is not None:
            matched.add(i)
            new_cluster_members[matched_cluster_id].append((i, art))

    # 5. Persist matches to DB with change detection + update cluster metadata
    articles_matched = 0
    events_updated = 0
    now = datetime.datetime.utcnow()

    for cid, member_list in new_cluster_members.items():
        centroid = np.array(centroids[cid], dtype=np.float32)
        events_updated += 1

        for idx, art in member_list:
            art_emb = new_embeddings_norm[idx]
            change_kind = classify_update(art_emb, centroid, new_tier=art.tier)

            repo.add_article_to_cluster(cid, art.id)
            repo.set_article_embedding(art.id, art_emb.astype(np.float32).tobytes())
            articles_matched += 1

            if change_kind != "repeat":
                # Only bump latest_development_at for real developments
                latest_at = art.published_at or art.fetched_at or now
                cluster = repo.get_cluster(cid)
                if cluster:
                    new_dev_count = (cluster.development_count or 0) + 1
                    repo.update_cluster_event_fields(cid,
                        latest_development_at=latest_at,
                        development_count=new_dev_count,
                        last_change_kind=change_kind,
                    )

    # 6. Remaining unmatched articles → create new clusters
    unmatched = [i for i in range(len(new_articles)) if i not in matched]
    clusters_created = 0

    if unmatched:
        unmatched_articles = [new_articles[i] for i in unmatched]
        unmatched_embeddings = new_embeddings_norm[unmatched]
        unmatched_titles = [a.title for a in unmatched_articles]
        groups = cluster_by_similarity(
            unmatched_embeddings, unmatched_titles, threshold=similarity_threshold,
        )

        for group in groups:
            rep_idx = group.representative_index
            absolute_idx = unmatched[rep_idx]
            rep_article = new_articles[absolute_idx]
            members = [new_articles[unmatched[i]] for i in group.article_indices]
            latest_at = compute_latest_article_at(members) or now
            sources = sorted({m.source for m in members})
            tiers = sorted({m.tier for m in members})

            cluster = repo.create_cluster(
                representative_title=rep_article.title,
                status="developing",
                latest_article_at=latest_at,
            )
            repo.update_cluster_event_fields(cluster.id,
                event_started_at=rep_article.published_at or rep_article.fetched_at,
                latest_development_at=latest_at,
                development_count=1,
                source_tiers_json=json.dumps(tiers),
            )

            for idx_in_group in group.article_indices:
                art = new_articles[unmatched[idx_in_group]]
                repo.add_article_to_cluster(cluster.id, art.id)
                emb = new_embeddings_norm[unmatched[idx_in_group]]
                repo.set_article_embedding(art.id, emb.astype(np.float32).tobytes())

            cluster_summaries.append({
                "cluster_id": cluster.id,
                "title": rep_article.title,
                "member_count": len(group.article_indices),
                "sources": sources,
            })
            clusters_created += 1

    # 7. Prune old stray articles (unclustered, older than 30 days)
    repo.prune_old_articles(retention_days=30)

    logger.info(
        "Incremental dedup: %d matched to %d existing clusters, %d new clusters, %d articles processed",
        articles_matched, events_updated, clusters_created, len(new_articles),
    )

    return {
        "clusters_created": clusters_created,
        "articles_processed": len(new_articles),
        "articles_matched": articles_matched,
        "events_updated": events_updated,
        "similarity_threshold": similarity_threshold,
        "clusters": cluster_summaries,
    }


def run_dedup_and_cluster(
    repo: NewTalkRepository | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    article_limit: int | None = None,
) -> dict:
    """
    Backward-compatible wrapper — delegates to incremental dedup.
    First run against a pre-v2 DB with no embeddings will backfill and run
    the full clustering pass. Subsequent runs are truly incremental.
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    # One-time backfill of existing cluster embeddings
    all_articles = repo.list_articles()
    _backfill_embeddings(repo, all_articles)

    return run_incremental_dedup(
        repo=repo,
        similarity_threshold=similarity_threshold,
        article_limit=article_limit,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_dedup_and_cluster()
    print(f"\nIncremental dedup complete: {result['clusters_created']} new clusters, "
          f"{result['articles_matched']} matched, "
          f"{result['articles_processed']} articles processed")
    for c in result["clusters"][:10]:
        print(f"  [NEW {c['cluster_id']}] ({c['member_count']} articles) {c['title'][:70]}")
        if c["member_count"] > 1:
            print(f"       sources: {', '.join(c['sources'])}")
