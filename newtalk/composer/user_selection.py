"""Per-user story selection from the globally scored cluster pool.

The global pipeline (ingest -> cluster -> score -> context) runs once; this module picks, for one
user, only stories they asked for. Out-of-interest stories are excluded except for a single
"must-know" slot reserved for genuinely top-scoring news.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

from newtalk.config.interests import rubric_categories_for
from newtalk.db.repository import NewTalkRepository
from newtalk.processing.freshness import (
    get_freshness_window_hours,
    is_cluster_fresh,
    load_freshness_config,
)
from newtalk.scoring.rubric import _text_blob, cluster_category, load_rubric_config

logger = logging.getLogger(__name__)

MUST_KNOW_SCORE = 8.0
MUST_KNOW_SLOTS = 1
MIN_THRESHOLD_FLOOR = 2.5
CANDIDATE_POOL = 250

_STOPWORDS = frozenset(
    "about after also and any are around because been being but can could did does for from "
    "get give has have how into just keep like more most much news not only other over please "
    "some such than that the their them then there these they this those very want what when "
    "where which while who will with would you your latest updates update stuff things "
    "everything anything related".split()
)


# Terms that match almost any Indian news story; as keywords they would defeat interest filtering.
GENERIC_KEYWORDS = frozenset(
    "india indian indians bharat news world global country nation national government govt "
    "company companies business market markets latest today people public state states "
    "update updates story stories media politics policy economy".split()
)


def clean_keywords(keywords) -> list[str]:
    out: list[str] = []
    for kw in keywords:
        kw = str(kw).lower().strip()
        if len(kw) < 2 or kw in GENERIC_KEYWORDS or kw in _STOPWORDS or kw in out:
            continue
        out.append(kw)
    return out


def interest_profile(profile) -> tuple[set[str], list[str], list[str]]:
    """(wanted rubric categories, keywords, selected topic slugs) for a stored profile."""
    slugs = json.loads(profile.interests_json or "[]")
    categories = set(rubric_categories_for(slugs))
    keywords: list[str] = []
    if profile.normalized_json:
        try:
            data = json.loads(profile.normalized_json)
            categories.update(data.get("categories", []))
            keywords.extend(data.get("keywords", []))
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    if not keywords and profile.free_text:
        words = re.findall(r"[a-z][a-z0-9&.\-]{3,}", profile.free_text.lower())
        keywords = words
    return categories, clean_keywords(keywords), slugs


def keyword_hits(cluster, keywords: list[str]) -> int:
    """Number of distinct keywords found as whole words/phrases in the cluster text."""
    if not keywords:
        return 0
    text = _text_blob(list(cluster.articles))

    def found(kw: str) -> bool:
        forms = {kw}
        if kw.endswith("s") and len(kw) > 3:
            forms.add(kw[:-1])  # "ipos" should match "IPO"
        alt = "|".join(re.escape(f) for f in forms)
        return re.search(rf"(?<![a-z0-9])(?:{alt})(?![a-z0-9])", text) is not None

    return sum(1 for kw in keywords if found(kw))


def select_stories_for_user(
    user_id: int,
    repo: NewTalkRepository,
    max_stories: int | None = None,
    min_score: float | None = None,
    exclude_ids: set[int] | None = None,
) -> list:
    """Stories for one user: interest matches ranked by relevance x importance."""
    cfg = load_freshness_config()
    max_stories = max_stories or int(cfg.get("max_stories", 8))
    base_threshold = (
        min_score if min_score is not None else float(cfg.get("min_story_score", 4.0))
    )
    relief = float(cfg.get("interest_score_relief", 1.0))
    followed_threshold = max(MIN_THRESHOLD_FLOOR, base_threshold - relief)
    rubric_cfg = load_rubric_config()
    exclude_ids = exclude_ids or set()

    profile = repo.get_profile(user_id)
    if profile is None:
        from newtalk.composer.script_composer import select_stories_for_briefing

        picked = select_stories_for_briefing(
            repo=repo, max_stories=max_stories, min_score=base_threshold
        )
        return [c for c in picked if c.id not in exclude_ids]

    wanted, keywords, slugs = interest_profile(profile)
    window = get_freshness_window_hours()
    pool = [
        c
        for c in repo.get_ranked_clusters(limit=CANDIDATE_POOL)
        if c.context
        and c.importance_score
        and c.id not in exclude_ids
        and is_cluster_fresh(c, window)
    ]

    candidates = []  # (user_score, cluster, category, kind)
    for cluster in pool:
        score = cluster.importance_score.score
        cat = cluster_category(cluster, rubric_cfg)
        hits = keyword_hits(cluster, keywords)
        in_category = cat in wanted
        matched = in_category or hits > 0

        if matched:
            if score < (followed_threshold if in_category else base_threshold):
                continue
            relevance = 1.0 + 0.5 * min(hits, 3) + (0.5 if in_category else 0.0)
            candidates.append((score * relevance, cluster, cat, "interest"))
        elif score >= max(MUST_KNOW_SCORE, base_threshold):
            candidates.append((score, cluster, cat, "must_know"))

    if not slugs and not keywords and not wanted:
        # No stated interests at all: behave like the global briefing.
        candidates = [
            (c.importance_score.score, c, cluster_category(c, rubric_cfg), "interest")
            for c in pool
            if c.importance_score.score >= base_threshold
        ]

    candidates.sort(key=lambda t: t[0], reverse=True)

    selected, per_cat = [], defaultdict(int)
    must_know_left = MUST_KNOW_SLOTS
    max_per_cat = max(2, (max_stories + 1) // 2)
    for _user_score, cluster, cat, kind in candidates:
        if len(selected) >= max_stories:
            break
        if kind == "must_know":
            if must_know_left <= 0:
                continue
            must_know_left -= 1
        elif per_cat[cat] >= max_per_cat:
            continue
        selected.append(cluster)
        per_cat[cat] += 1

    logger.info(
        "User %d: %d stories from %d candidates (categories=%s, keywords=%d)",
        user_id,
        len(selected),
        len(candidates),
        sorted(wanted),
        len(keywords),
    )
    return selected
