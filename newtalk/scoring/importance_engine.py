"""
Hybrid importance scoring: rule signals + LLM judgment.
"""
from __future__ import annotations

import json
import logging
import re

from newtalk.config.settings import DATABASE_URL
from newtalk.db.repository import NewTalkRepository
from newtalk.llm.litellm_client import call_llm
from newtalk.scoring.rubric import compute_rule_signals, load_rubric_config
from newtalk.processing.freshness import is_cluster_fresh, get_freshness_window_hours, cluster_most_recent_timestamp
from newtalk.llm.date_context import get_date_context

logger = logging.getLogger(__name__)


def _build_scorer_prompt(cluster, signals: dict) -> list[dict]:
    articles_summary = []
    for a in cluster.articles[:5]:
        articles_summary.append({
            "source": a.source,
            "tier": a.tier,
            "title": a.title,
            "published_at": str(a.published_at) if a.published_at else None,
            "body_preview": (a.body or "")[:300],
        })

    date_context = get_date_context()
    system = (
        f"{date_context}\n\n"
        "You are an intelligence analyst scoring news importance for an INDIAN audience — NOT popularity. "
        "India relevance is a key signal. "
        "CRITICAL: State-level domestic news (student protests, exam paper leaks, recruitment scams, "
        "bandhs, agrarian agitations, local governance failures, caste/reservation issues, "
        "communal tensions, law-and-order crises, infrastructure failures) that deeply affects "
        "millions of Indian citizens daily MUST score HIGH on India relevance — often higher than "
        "global geopolitical events with indirect impact. "
        "Respond with JSON only:\n"
        '{"llm_score": <0-10>, "long_term_significance": "<low|medium|high>", '
        '"virality_risk": "<low|medium|high>", "could_grow_later": <true|false>, '
        '"india_angle": "<1-2 sentence reason this matters to India>", '
        '"rationale": "<2-3 sentences>"}'
    )
    user = json.dumps({
        "representative_title": cluster.representative_title,
        "articles": articles_summary,
        "rule_signals": signals,
    }, indent=2)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_llm_json(text: str) -> dict:
    text = text.strip()
    # Extract JSON object if wrapped in markdown
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def score_cluster(
    cluster,
    repo: NewTalkRepository,
    past_topics: list[str] | None = None,
    config: dict | None = None,
) -> float:
    """Score a single cluster and persist to importance_scores + india_relevance."""
    if config is None:
        config = load_rubric_config()

    signals = compute_rule_signals(cluster, past_topics=past_topics, config=config)
    rule_base = signals["rule_base_score"]

    # Persist India relevance on the cluster
    india_rel = signals.get("india_relevance", 0.0)
    if india_rel:
        repo.update_cluster_event_fields(cluster.id, india_relevance=india_rel)

    try:
        resp = call_llm(role="scorer", messages=_build_scorer_prompt(cluster, signals))
        llm_data = _parse_llm_json(resp.choices[0].message.content)
        llm_score = float(llm_data.get("llm_score", rule_base))
        rationale = llm_data.get("rationale", "")
        extra = (
            f" [LLM: long_term={llm_data.get('long_term_significance')}, "
            f"virality={llm_data.get('virality_risk')}, "
            f"could_grow={llm_data.get('could_grow_later')}]"
        )
        full_rationale = f"{rationale}{extra} | Rules: {json.dumps(signals)}"
    except Exception as exc:
        logger.warning("LLM scorer failed for cluster %s: %s — using rule base only", cluster.id, exc)
        llm_score = rule_base
        full_rationale = f"Rule-only fallback. Signals: {json.dumps(signals)}"

    blend = config.get("llm_blend_weight", 0.35)
    final = round((1 - blend) * rule_base + blend * llm_score, 2)
    final = max(0.0, min(10.0, final))

    repo.set_importance_score(
        cluster_id=cluster.id,
        score=final,
        rationale=full_rationale,
        rubric_version=config.get("rubric_version", "v1.0"),
    )
    return final


def score_all_clusters(
    repo: NewTalkRepository | None = None,
    limit: int | None = None,
    llm_top_n: int = 25,
) -> list[dict]:
    """
    Score clusters in the DB. Rule signals computed for all; LLM called for top N
  by rule base score to keep latency/cost reasonable on large article sets.

    Returns ranked summary list (all scored clusters).
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    clusters = repo.list_clusters()
    if limit:
        clusters = clusters[:limit]

    window_hours = get_freshness_window_hours()
    fresh_clusters = []
    excluded_stale = 0
    for cluster in clusters:
        if not cluster.articles:
            continue
        if is_cluster_fresh(cluster, window_hours):
            fresh_clusters.append(cluster)
        else:
            excluded_stale += 1
            latest = cluster_most_recent_timestamp(cluster)
            logger.debug(
                "Excluded stale cluster %d (latest=%s, window=%dh)",
                cluster.id, latest, window_hours,
            )

    if excluded_stale:
        logger.info(
            "Hard recency gate: excluded %d clusters outside %dh window (%d candidates remain)",
            excluded_stale, window_hours, len(fresh_clusters),
        )

    past_topics = _get_memory_topics(repo)
    config = load_rubric_config()

    # Pass 1: rule-only scores for ranking (fresh clusters only)
    rule_ranked = []
    for cluster in fresh_clusters:
        signals = compute_rule_signals(cluster, past_topics=past_topics, config=config)
        rule_ranked.append((cluster, signals))

    rule_ranked.sort(key=lambda x: x[1]["rule_base_score"], reverse=True)
    llm_cluster_ids = {c.id for c, _ in rule_ranked[:llm_top_n]}

    results = []
    for cluster, signals in rule_ranked:
        rule_base = signals["rule_base_score"]

        if cluster.id in llm_cluster_ids:
            score = score_cluster(cluster, repo, past_topics=past_topics, config=config)
        else:
            rationale = f"Rule-only score. Signals: {json.dumps(signals)}"
            repo.set_importance_score(
                cluster_id=cluster.id,
                score=rule_base,
                rationale=rationale,
                rubric_version=config.get("rubric_version", "v1.0"),
            )
            score = rule_base

        results.append({
            "cluster_id": cluster.id,
            "title": cluster.representative_title,
            "score": score,
        })
        logger.info("Scored cluster %d: %.2f — %s", cluster.id, score, cluster.representative_title[:60])

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _get_memory_topics(repo: NewTalkRepository) -> list[str]:
    with repo.session_scope() as session:
        from newtalk.db.models import UserMemory
        rows = session.query(UserMemory).all()
        return [r.topic for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ranked = score_all_clusters()
    print(f"\nTop {min(10, len(ranked))} scored clusters:")
    for i, r in enumerate(ranked[:10], 1):
        print(f"  {i}. [{r['score']:.2f}] {r['title'][:75]}")
