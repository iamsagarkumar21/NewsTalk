"""User-facing interest topics and supported languages.

Each topic maps to the scoring rubric categories it draws stories from. `markets` is a new
rubric category (stocks/finance) that the rubric must learn to detect.
"""

from __future__ import annotations

INTEREST_TOPICS: list[dict] = [
    {
        "slug": "tech",
        "label": "Tech & AI",
        "label_hi": "टेक और AI",
        "categories": ["tech"],
    },
    {
        "slug": "markets",
        "label": "Stocks & markets",
        "label_hi": "शेयर बाज़ार",
        "categories": ["markets"],
    },
    {
        "slug": "economy",
        "label": "Economy & business",
        "label_hi": "अर्थव्यवस्था",
        "categories": ["economy"],
    },
    {
        "slug": "politics",
        "label": "Indian politics & policy",
        "label_hi": "राजनीति और नीति",
        "categories": ["policy", "state"],
    },
    {
        "slug": "geopolitics",
        "label": "Foreign policy & geopolitics",
        "label_hi": "विदेश नीति और भू-राजनीति",
        "categories": ["geopolitics"],
    },
    {
        "slug": "science",
        "label": "Science",
        "label_hi": "विज्ञान",
        "categories": ["science"],
    },
    {
        "slug": "health",
        "label": "Health",
        "label_hi": "स्वास्थ्य",
        "categories": ["health"],
    },
    {"slug": "sports", "label": "Sports", "label_hi": "खेल", "categories": ["sports"]},
    {
        "slug": "entertainment",
        "label": "Entertainment",
        "label_hi": "मनोरंजन",
        "categories": ["entertainment"],
    },
]

TOPIC_SLUGS: frozenset[str] = frozenset(t["slug"] for t in INTEREST_TOPICS)

LANGUAGES: list[dict] = [
    {"code": "en", "label": "English", "label_native": "English"},
    {"code": "hinglish", "label": "Hinglish", "label_native": "Hinglish"},
    {"code": "hi", "label": "Hindi", "label_native": "हिन्दी"},
]

LANGUAGE_CODES: frozenset[str] = frozenset(lang["code"] for lang in LANGUAGES)

DEFAULT_LANGUAGE = "en"
DEFAULT_TIMEZONE = "Asia/Kolkata"


def rubric_categories_for(slugs: list[str]) -> list[str]:
    """Rubric categories covered by the given topic slugs, order preserved, no duplicates."""
    by_slug = {t["slug"]: t["categories"] for t in INTEREST_TOPICS}
    seen: list[str] = []
    for slug in slugs:
        for cat in by_slug.get(slug, []):
            if cat not in seen:
                seen.append(cat)
    return seen
