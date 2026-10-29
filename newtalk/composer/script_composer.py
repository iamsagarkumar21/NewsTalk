"""
Script composer: selects stories dynamically, handles quiet days,
writes diagnostics for threshold calibration.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from newtalk.config.settings import DATABASE_URL
from newtalk.db.repository import NewTalkRepository
from newtalk.llm.litellm_client import call_llm
from newtalk.config.jiya import (
    COMPOSER_PERSONALITY,
    OPENING_LINE,
    OPENING_QUIET_DAY,
    QUIET_DAY_SCRIPT,
)
from newtalk.config.audience import get_perspective_prompt
from newtalk.memory.memory_store import MemoryStore
from newtalk.processing.freshness import load_freshness_config
from newtalk.llm.date_context import get_date_context
from newtalk.scoring.rubric import load_rubric_config

logger = logging.getLogger(__name__)

WORDS_PER_MINUTE = 150
_DIAGNOSTICS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

# Priority order for quota filling
QUOTA_PRIORITY_ORDER = [
    "state",
    "policy",
    "economy",
    "markets",
    "geopolitics",
    "tech",
    "health",
    "sports",
    "entertainment",
    "general",
]


def _estimate_duration_sec(script: str) -> int:
    word_count = len(script.split())
    return max(20, int((word_count / WORDS_PER_MINUTE) * 60))


def _build_stories_payload(clusters, yesterday_ids: set | None = None) -> list[dict]:
    stories = []
    yesterday_ids = yesterday_ids or set()
    for cluster in clusters:
        ctx = cluster.context
        evidence = {}
        if ctx and ctx.evidence_json:
            try:
                evidence = json.loads(ctx.evidence_json)
            except json.JSONDecodeError:
                pass

        viewpoints = []
        timeline = []
        if ctx:
            try:
                viewpoints = json.loads(ctx.viewpoints_json or "[]")
            except json.JSONDecodeError:
                pass
            try:
                timeline = json.loads(ctx.timeline_json or "[]")
            except json.JSONDecodeError:
                pass

        stories.append(
            {
                "title": cluster.representative_title,
                "score": cluster.importance_score.score
                if cluster.importance_score
                else 0,
                "what_happened": ctx.background if ctx else "",
                "why_it_matters": evidence.get("why_it_matters", ""),
                "who_is_affected": evidence.get("who_is_affected", ""),
                "timeline": timeline,
                "viewpoints": viewpoints,
                "confidence": ctx.confidence_level if ctx else "developing",
                "open_questions": evidence.get("open_questions", []),
                "sources": [a.source for a in cluster.articles[:5]],
                "covered_yesterday": cluster.id in yesterday_ids,
            }
        )
    return stories


def _get_cluster_category(cluster) -> str:
    """Extract detected_category from cluster (stored via rubric signals)."""
    # Try to get from cluster attribute (set during scoring)
    cat = getattr(cluster, "detected_category", None)
    if cat:
        return cat
    # Fallback: recompute from rubric config using cluster articles
    try:
        rubric_cfg = load_rubric_config()
        from newtalk.scoring.rubric import cluster_category
        return cluster_category(cluster, rubric_cfg)
    except Exception:
        return "general"


def select_stories_for_briefing(
    repo: NewTalkRepository | None = None,
    max_stories: int | None = None,
    min_score: float | None = None,
) -> list:
    """
    Load ranked clusters and select with categorical quotas for balanced briefing.
    max_stories is a ceiling, never a target.
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    cfg = load_freshness_config()
    max_stories = max_stories or int(cfg.get("max_stories", 8))
    min_score = (
        min_score if min_score is not None else float(cfg.get("min_story_score", 4.0))
    )
    category_quotas = cfg.get(
        "category_quotas",
        {"state": 3, "policy": 2, "economy": 1, "geopolitics": 1, "tech": 1},
    )

    all_clusters = repo.get_ranked_clusters(
        limit=max_stories * 3
    )  # larger buffer for stratification
    contextualized = [c for c in all_clusters if c.context]
    above_threshold = [
        c
        for c in contextualized
        if c.importance_score and c.importance_score.score >= min_score
    ]

    # Group by detected category
    buckets = defaultdict(list)
    for c in above_threshold:
        cat = _get_cluster_category(c)
        buckets[cat].append(c)

    # Sort each bucket by score desc
    for cat in buckets:
        buckets[cat].sort(key=lambda c: c.importance_score.score, reverse=True)

    # Fill quotas in priority order
    selected = []
    used_ids = set()

    for cat in QUOTA_PRIORITY_ORDER:
        quota = category_quotas.get(cat, 0)
        for c in buckets.get(cat, []):
            if len(selected) >= max_stories:
                break
            if quota > 0 and c.id not in used_ids:
                selected.append(c)
                used_ids.add(c.id)
                quota -= 1

    # Fill remaining slots from global ranking (any category)
    for c in sorted(
        above_threshold, key=lambda c: c.importance_score.score, reverse=True
    ):
        if len(selected) >= max_stories:
            break
        if c.id not in used_ids:
            selected.append(c)
            used_ids.add(c.id)

    # Diagnostics: categorize selected/near/rejected
    selected_ids = {c.id for c in selected}
    near = [c for c in above_threshold if c.id not in selected_ids][: max_stories + 5]
    rejected_contextualized = [
        c
        for c in contextualized
        if c.importance_score and c.importance_score.score < min_score
    ]

    # Write diagnostics
    _write_selection_diagnostics(selected, near, rejected_contextualized)

    logger.info(
        "Selection: %d selected, %d near-threshold, %d rejected (below %.1f), "
        "%d contextualized total | quotas: %s",
        len(selected),
        len(near),
        len(rejected_contextualized),
        min_score,
        len(contextualized),
        category_quotas,
    )
    return selected[:max_stories]


def _write_selection_diagnostics(
    selected: list,
    near_threshold: list,
    rejected: list,
):
    _DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    path = _DIAGNOSTICS_DIR / "briefing_selection.jsonl"
    entries = []
    for bucket, clusters in [
        ("selected", selected),
        ("near_threshold", near_threshold),
        ("rejected", rejected),
    ]:
        for c in clusters:
            score = c.importance_score.score if c.importance_score else 0.0
            entries.append(
                {
                    "bucket": bucket,
                    "cluster_id": c.id,
                    "title": c.representative_title,
                    "score": score,
                    "category": _get_cluster_category(c),
                    "india_relevance": getattr(c, "india_relevance", None),
                    "change_kind": getattr(c, "last_change_kind", None),
                    "development_count": getattr(c, "development_count", 0),
                    "article_count": len(list(c.articles)) if c.articles else 0,
                }
            )
    with open(path, "a") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    logger.info("Diagnostics written to %s (%d entries)", path, len(entries))


def compose_briefing_script(
    repo: NewTalkRepository | None = None,
    top_n: int = 5,
    memory: MemoryStore | None = None,
    clusters: list | None = None,
) -> dict:
    """
    Compose a spoken briefing from top scored+contextualized clusters.
    """
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()
    if memory is None:
        memory = MemoryStore(repo)

    if clusters is None:
        clusters = select_stories_for_briefing(repo=repo)

    # Quiet day path
    if not clusters:
        script = QUIET_DAY_SCRIPT
        opening = OPENING_QUIET_DAY
        full_script = f"{opening}\n\n{script}"
        duration = _estimate_duration_sec(full_script)
        briefing = repo.create_briefing(
            script_text=full_script,
            duration_estimate_sec=duration,
            story_count=0,
            is_quiet_day=True,
        )
        logger.info("Quiet-day briefing %d — %d sec", briefing.id, duration)
        return {
            "briefing_id": briefing.id,
            "script_text": full_script,
            "duration_estimate_sec": duration,
            "stories": [],
        }

    # Check which clusters were covered in yesterday's briefing
    yesterday_ids = repo.get_yesterdays_briefing_cluster_ids()

    stories = _build_stories_payload(clusters, yesterday_ids=yesterday_ids)
    titles = [s["title"] for s in stories]
    memory_context = memory.build_composer_memory_context(titles)

    # Add yesterday-coverage instruction to memory context
    if yesterday_ids:
        covered_titles = [s["title"] for s in stories if s.get("covered_yesterday")]
        if covered_titles:
            yesterday_note = (
                "\n\nYESTERDAY COVERAGE: The following were covered in yesterday's briefing. "
                "Don't repeat basics — focus only on today's update:\n"
                + "\n".join(f"- {t}" for t in covered_titles)
            )
            memory_context += yesterday_note

    perspective = get_perspective_prompt()
    date_context = get_date_context()

    # Composer gets ONLY the stories section — no greeting
    system = (
        f"{date_context}\n\n"
        f"{COMPOSER_PERSONALITY}\n\n"
        f"You are composing ONLY the stories section of a briefing (no greeting, no goodbye).\n"
        f"There are {len(stories)} stories to cover.\n"
        f"Depth should follow importance — spend more time on high-score stories, be brief on lower ones.\n"
        f"Never pad, never repeat, never fill time.\n\n"
        f"AUDIENCE PERSPECTIVE (mandatory):\n{perspective}\n\n"
        "Respect user memory context — skip basics for familiar topics. "
        "Output ONLY the script text, no markdown, no greeting."
    )
    user = json.dumps(
        {
            "memory_context": memory_context,
            "stories": stories,
        },
        indent=2,
    )

    resp = call_llm(
        role="composer",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    stories_text = resp.choices[0].message.content.strip()
    estimated_duration = _estimate_duration_sec(stories_text)
    minutes = max(1, (estimated_duration + 30) // 60)  # round up to nearest minute

    opening = OPENING_LINE.format(minutes=minutes)
    full_script = f"{opening}\n\n{stories_text}"
    total_duration = _estimate_duration_sec(full_script)

    briefing = repo.create_briefing(
        script_text=full_script,
        duration_estimate_sec=total_duration,
        story_count=len(clusters),
        is_quiet_day=False,
    )
    for pos, cluster in enumerate(clusters, start=1):
        repo.add_cluster_to_briefing(briefing.id, cluster.id, position=pos)

    memory.update_after_briefing(
        [
            {
                "topic": s["title"][:80],
                "title": s["title"],
                "summary": s["what_happened"][:300],
            }
            for s in stories
        ]
    )

    logger.info(
        "Briefing %d composed — %d sec, %d stories",
        briefing.id,
        total_duration,
        len(clusters),
    )

    return {
        "briefing_id": briefing.id,
        "script_text": full_script,
        "duration_estimate_sec": total_duration,
        "stories": stories,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = compose_briefing_script()
    print(f"\nBriefing ID: {result['briefing_id']}")
    print(f"Duration estimate: {result['duration_estimate_sec']}s")
    print("\n" + "=" * 60)
    print(result["script_text"])
