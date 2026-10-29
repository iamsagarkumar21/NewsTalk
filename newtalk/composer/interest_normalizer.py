"""Normalize user free-text interests into structured categories + keywords.

Called once at profile-save time (not per briefing). Stores the result in
UserProfile.normalized_json so the per-user selector can use it cheaply.
"""

from __future__ import annotations

import json
import logging

from newtalk.config.interests import INTEREST_TOPICS, TOPIC_SLUGS
from newtalk.db.repository import NewTalkRepository
from newtalk.llm.litellm_client import call_llm

logger = logging.getLogger(__name__)

_TOPIC_DESCRIPTIONS = "\n".join(f"- {t['slug']}: {t['label']}" for t in INTEREST_TOPICS)


def normalize_interests(
    interests: list[str],
    free_text: str | None,
    repo: NewTalkRepository | None = None,
    user_id: int | None = None,
) -> dict:
    """Return {categories: [...], keywords: [...]} from user inputs.

    If there is no free_text, returns categories from the selected topic slugs
    without an LLM call.
    """
    from newtalk.config.interests import rubric_categories_for

    categories = rubric_categories_for(interests)

    if not free_text:
        result = {"categories": categories, "keywords": []}
        _persist(repo, user_id, result)
        return result

    prompt_system = (
        "You understand news interest preferences. The user has selected topic slugs "
        "and also typed a free-text description of what they care about.\n\n"
        f"Available topics:\n{_TOPIC_DESCRIPTIONS}\n\n"
        "From the free text, extract:\n"
        "1. Any additional topic slugs that clearly match (only from the list above)\n"
        "2. Specific keywords/entities the user wants tracked (companies, people, technologies, "
        "sectors, events — lowercase, max 15 keywords)\n\n"
        "Respond with JSON only:\n"
        '{"extra_slugs": ["..."], "keywords": ["..."]}'
    )
    prompt_user = (
        f"Selected topics: {', '.join(interests) if interests else '(none)'}\n"
        f"Free text: {free_text}"
    )

    extra_slugs: list[str] = []
    keywords: list[str] = []

    try:
        resp = call_llm(
            role="qa",
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user},
            ],
        )
        text = resp.choices[0].message.content.strip()
        import re

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            raw_slugs = data.get("extra_slugs", [])
            extra_slugs = [
                s for s in raw_slugs if s in TOPIC_SLUGS and s not in interests
            ]
            from newtalk.composer.user_selection import clean_keywords

            keywords = clean_keywords(data.get("keywords", []))[:15]
    except Exception as exc:
        logger.warning("Interest normalizer LLM failed: %s — using rule-only", exc)

    all_slugs = list(dict.fromkeys(interests + extra_slugs))
    categories = rubric_categories_for(all_slugs)
    result = {"categories": categories, "keywords": keywords}
    _persist(repo, user_id, result)
    return result


def _persist(repo: NewTalkRepository | None, user_id: int | None, result: dict) -> None:
    if repo and user_id:
        try:
            repo.update_normalized_json(user_id, json.dumps(result))
        except Exception as exc:
            logger.warning(
                "Failed to persist normalized interests for user %d: %s", user_id, exc
            )
