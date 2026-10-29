"""Assemble one user's briefing from cached story segments (no per-user LLM calls)."""

from __future__ import annotations

import logging
from typing import Callable

from newtalk.composer.segments import ensure_segments
from newtalk.composer.user_selection import select_stories_for_user
from newtalk.config.interests import DEFAULT_LANGUAGE, LANGUAGE_CODES
from newtalk.config.jiya_i18n import phrases_for
from newtalk.db.repository import NewTalkRepository
from newtalk.llm.litellm_client import call_llm
from newtalk.memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)

WORDS_PER_MINUTE = 140


def estimate_duration_sec(text: str) -> int:
    return max(20, int(len(text.split()) / WORDS_PER_MINUTE * 60))


def _repeats(repo: NewTalkRepository, user_id: int) -> set[int]:
    """Clusters the user already heard that have had no real development since."""
    heard = repo.get_yesterdays_briefing_cluster_ids(user_id)
    if not heard:
        return set()
    stale = set()
    for cluster in repo.get_ranked_clusters(limit=300):
        if cluster.id in heard and cluster.last_change_kind not in ("minor", "major"):
            stale.add(cluster.id)
    return stale


def assemble_user_briefing(
    user_id: int,
    repo: NewTalkRepository,
    llm: Callable = call_llm,
    max_stories: int | None = None,
) -> dict:
    """Select stories for the user, fetch/generate segments, and store the briefing."""
    profile = repo.get_profile(user_id)
    if profile is None:
        raise ValueError(f"user {user_id} has no profile")

    language = (
        profile.language if profile.language in LANGUAGE_CODES else DEFAULT_LANGUAGE
    )
    phrases = phrases_for(language)
    name = profile.call_name

    stale = _repeats(repo, user_id)
    if max_stories is None:
        from newtalk.processing.freshness import load_freshness_config

        max_stories = int(load_freshness_config().get("max_stories_per_call", 6))
    clusters = select_stories_for_user(
        user_id, repo, max_stories=max_stories, exclude_ids=stale
    )
    heard_before = repo.get_yesterdays_briefing_cluster_ids(user_id)

    if not clusters:
        text = (
            f"{phrases['opening_quiet'].format(name=name)}\n\n{phrases['quiet_script']}"
        )
        briefing = repo.create_briefing(
            script_text=text,
            duration_estimate_sec=estimate_duration_sec(text),
            story_count=0,
            is_quiet_day=True,
            user_id=user_id,
        )
        logger.info("User %d: quiet-day briefing %d", user_id, briefing.id)
        return {
            "briefing_id": briefing.id,
            "script_text": text,
            "story_count": 0,
            "language": language,
            "titles": [],
        }

    segments = ensure_segments(repo, clusters, [language], llm=llm)

    parts: list[str] = []
    used: list = []
    for cluster in clusters:
        text = segments.get((cluster.id, language))
        if not text:
            continue
        used.append(cluster)
        idx = len(used) - 1
        if idx == 0:
            lead = phrases["first"]
        elif idx == len(clusters) - 1 and len(clusters) > 2:
            lead = phrases["last"]
        else:
            lead = phrases["middle"][(idx - 1) % len(phrases["middle"])]
        if cluster.id in heard_before:
            lead = phrases["update"]
        parts.append(f"{lead} {text}")

    body = "\n\n".join(parts)
    estimated = estimate_duration_sec(body)
    minutes = max(1, round(estimated / 60))
    story_word = phrases["story_one"] if len(used) == 1 else phrases["story_many"]
    minute_word = phrases["minute_one"] if minutes == 1 else phrases["minute_many"]
    opening = phrases["opening"].format(
        name=name,
        count=len(used),
        stories=story_word,
        minutes=minutes,
        minute_word=minute_word,
    )
    full_text = f"{opening}\n\n{body}\n\n{phrases['closing']}"

    briefing = repo.create_briefing(
        script_text=full_text,
        duration_estimate_sec=estimate_duration_sec(full_text),
        story_count=len(used),
        is_quiet_day=False,
        user_id=user_id,
    )
    for pos, cluster in enumerate(used, start=1):
        repo.add_cluster_to_briefing(briefing.id, cluster.id, position=pos)

    MemoryStore(repo, user_id=user_id).update_after_briefing(
        [
            {
                "topic": c.representative_title[:80],
                "title": c.representative_title,
                "summary": (c.context.background if c.context else "")[:300],
            }
            for c in used
        ]
    )
    logger.info(
        "User %d: briefing %d (%s) with %d stories",
        user_id,
        briefing.id,
        language,
        len(used),
    )
    return {
        "briefing_id": briefing.id,
        "script_text": full_text,
        "story_count": len(used),
        "language": language,
        "titles": [c.representative_title for c in used],
    }


def active_scope(repo: NewTalkRepository) -> tuple[set[str], set[str], int]:
    """(rubric categories followed, languages needed, number of active users)."""
    from newtalk.composer.user_selection import interest_profile

    categories: set[str] = set()
    languages: set[str] = set()
    profiles = repo.list_active_profiles()
    for profile in profiles:
        wanted, _keywords, _slugs = interest_profile(profile)
        categories |= wanted
        languages.add(profile.language if profile.language in LANGUAGE_CODES else DEFAULT_LANGUAGE)
    return categories, languages, len(profiles)


def prewarm_segments(
    repo: NewTalkRepository,
    categories: set[str],
    languages: set[str],
    llm: Callable = call_llm,
    limit: int = 40,
) -> int:
    """Generate segments ahead of call time for every story some user could be given."""
    from newtalk.composer.user_selection import MUST_KNOW_SCORE
    from newtalk.processing.freshness import get_freshness_window_hours, is_cluster_fresh
    from newtalk.scoring.rubric import cluster_category, load_rubric_config

    window = get_freshness_window_hours()
    cfg = load_rubric_config()
    picked = []
    for cluster in repo.get_ranked_clusters(limit=250):
        if not (cluster.context and cluster.importance_score and is_cluster_fresh(cluster, window)):
            continue
        in_scope = not categories or cluster_category(cluster, cfg) in categories
        if in_scope or cluster.importance_score.score >= MUST_KNOW_SCORE:
            picked.append(cluster)
        if len(picked) >= limit:
            break
    if not picked or not languages:
        return 0
    ensure_segments(repo, picked, sorted(languages), llm=llm)
    return len(picked)
