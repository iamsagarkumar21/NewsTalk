"""
Rule-based importance signals for story clusters.
Pure computed functions — no LLM calls here.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

import yaml

from newtalk.db.models import StoryCluster, RawArticle

_CONFIG_PATH = Path(__file__).resolve().parent / "rubric_config.yaml"


def load_rubric_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def _text_blob(articles: list[RawArticle]) -> str:
    parts = [f"{a.title} {a.body}" for a in articles]
    return " ".join(parts).lower()


# Source-declared topic -> rubric category (RSS_FEEDS carry a `topic` hint)
_TOPIC_TO_CATEGORY = {"politics": "policy"}
_SOURCE_TOPIC: dict[str, str] | None = None
SOURCE_PRIOR_WEIGHT = 6.0


def _source_topics() -> dict[str, str]:
    global _SOURCE_TOPIC
    if _SOURCE_TOPIC is None:
        from newtalk.ingestion.sources_config import RSS_FEEDS

        _SOURCE_TOPIC = {
            f["source"]: _TOPIC_TO_CATEGORY.get(f["topic"], f["topic"])
            for f in RSS_FEEDS
            if f.get("topic") and f["topic"] != "general"
        }
    return _SOURCE_TOPIC


def detect_category(text: str, config: dict, articles: list | None = None) -> str:
    """Best-matching category: keyword hits plus a prior from the sources' declared topics.

    The source prior matters because keyword lists overlap heavily (a markets story is also an
    "economy" story); a feed that is *about* markets is the stronger signal.
    """
    keywords = config.get("category_keywords", {})
    scores: dict[str, float] = {}
    for cat, words in keywords.items():
        scores[cat] = float(sum(1 for w in words if w in text))

    if articles:
        topics = _source_topics()
        declared = [topics[a.source] for a in articles if a.source in topics]
        if declared:
            for cat in set(declared):
                share = declared.count(cat) / len(articles)
                scores[cat] = scores.get(cat, 0.0) + SOURCE_PRIOR_WEIGHT * share

    if not scores or max(scores.values()) == 0:
        return "general"
    return max(scores, key=scores.get)


def cluster_category(cluster, config: dict | None = None) -> str:
    """Category of a cluster using both text keywords and source-topic priors."""
    config = config or load_rubric_config()
    articles = list(cluster.articles)
    return detect_category(_text_blob(articles), config, articles)


def compute_source_corroboration(articles: list[RawArticle]) -> float:
    """Independent source count normalised to 0–1 (caps at 5 sources)."""
    unique_sources = {a.source for a in articles}
    return min(len(unique_sources) / 5.0, 1.0)


def compute_tier_weighted_corroboration(articles: list[RawArticle]) -> float:
    """Weight sources by tier: 1=1.0, 2=0.8, 3=0.5, 4=0.3. Caps at ~3.0."""
    TIER_WEIGHTS = {1: 1.0, 2: 0.8, 3: 0.5, 4: 0.3}
    seen = set()
    total = 0.0
    for a in articles:
        key = a.source
        if key not in seen:
            seen.add(key)
            total += TIER_WEIGHTS.get(a.tier, 0.3)
    return min(total / 3.0, 1.0)


def compute_recency_decay(articles: list[RawArticle]) -> float:
    """1.0 for fresh (<6h), decays to ~0.2 after 7 days. Unknown-age gets 0.3."""
    now = datetime.datetime.utcnow()
    best = 0.0
    for a in articles:
        if not a.published_at:
            best = max(best, 0.3)
            continue
        age_hours = max((now - a.published_at).total_seconds() / 3600, 0)
        if age_hours <= 6:
            score = 1.0
        elif age_hours <= 48:
            score = 0.85
        elif age_hours <= 168:
            score = 0.5
        else:
            score = 0.2
        best = max(best, score)
    return best


def compute_entity_scope(text: str, config: dict) -> float:
    """Higher when story involves governments, large populations, broad impact."""
    broad = config.get("entity_scope_keywords", {}).get("broad", [])
    narrow = config.get("entity_scope_keywords", {}).get("narrow", [])
    broad_hits = sum(1 for w in broad if w in text)
    narrow_hits = sum(1 for w in narrow if w in text)
    base = 0.5 + min(broad_hits * 0.1, 0.4) - min(narrow_hits * 0.1, 0.2)
    return max(0.0, min(1.0, base))


def compute_category_weight(category: str, config: dict) -> float:
    weights = config.get("category_weights", {})
    return float(weights.get(category, weights.get("general", 0.7)))


def compute_historical_continuity(
    cluster: StoryCluster,
    past_topics: list[str] | None = None,
) -> float:
    """
    Boost if cluster title overlaps with topics covered in user memory.
    """
    if not past_topics:
        return 0.3

    title_words = set(re.findall(r"[a-z]{4,}", cluster.representative_title.lower()))
    if not title_words:
        return 0.3

    best = 0.3
    for topic in past_topics:
        topic_words = set(re.findall(r"[a-z]{4,}", topic.lower()))
        if not topic_words:
            continue
        overlap = len(title_words & topic_words) / max(len(title_words), 1)
        best = max(best, 0.3 + overlap * 0.7)
    return min(best, 1.0)


def compute_india_relevance(articles: list[RawArticle], config: dict) -> float:
    """
    V1: keyword/entity matching for India relevance.
    Architecture: config-driven, extensible via 'india_strategy' key.
    When strategy='llm' is added later, this dispatches — callers don't change.
    """
    strategy = config.get("india_strategy", "keyword")

    if strategy == "keyword":
        return _india_relevance_keywords(articles, config)
    if strategy == "llm":
        # Stub — plug in later: embedding similarity / LLM call for top candidates
        return _india_relevance_keywords(articles, config)
    return 0.0


def _india_relevance_keywords(articles: list[RawArticle], config: dict) -> float:
    text = _text_blob(articles)
    kw = config.get("india_relevance_keywords", [])
    category = config.get("india_relevance_category_boost", {})

    word_hits = sum(1 for w in kw if w in text)
    base = min(word_hits * 0.15, 1.0)

    # Category base boost — certain topics inherently matter more to India
    detected = detect_category(text, config, articles)
    base += category.get(detected, 0.0)

    # Boost if any article is Tier 1 or 2 (trusted, domestic sources)
    high_tier = any(a.tier and a.tier <= 2 for a in articles)
    if high_tier:
        base += 0.1

    return min(base, 1.0)


def compute_rule_signals(
    cluster: StoryCluster,
    past_topics: list[str] | None = None,
    config: dict | None = None,
) -> dict:
    """
    Compute all rule-based signals for a cluster.

    Returns dict with individual signals (0–1) plus metadata.
    """
    if config is None:
        config = load_rubric_config()

    articles = list(cluster.articles)
    text = _text_blob(articles)
    category = detect_category(text, config, articles)

    signals = {
        "source_corroboration": compute_source_corroboration(articles),
        "tier_corroboration": compute_tier_weighted_corroboration(articles),
        "recency": compute_recency_decay(articles),
        "entity_scope": compute_entity_scope(text, config),
        "category": compute_category_weight(category, config),
        "historical_continuity": compute_historical_continuity(cluster, past_topics),
        "india_relevance": compute_india_relevance(articles, config),
    }
    signals["detected_category"] = category
    signals["source_count"] = len({a.source for a in articles})
    signals["article_count"] = len(articles)

    # Weighted rule base score (0–10 scale) — rebalanced for v2
    weights = config.get("signal_weights", {})
    signal_keys = [
        "tier_corroboration", "recency", "entity_scope",
        "category", "historical_continuity", "india_relevance",
    ]
    weighted = sum(signals.get(k, 0) * weights.get(k, 0) for k in signal_keys)
    total_w = sum(weights.get(k, 0) for k in signal_keys) or 1.0
    signals["rule_base_score"] = round((weighted / total_w) * 10, 2)

    return signals
