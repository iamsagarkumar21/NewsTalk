"""
Change detection for event clusters — rules-first.
Classifies new articles as repeat, minor, or major development
relative to the cluster's known content.
"""
from __future__ import annotations

import numpy as np


def novelty_score(article_embedding: np.ndarray, centroid_embedding: np.ndarray) -> float:
    """Cosine distance between article and cluster centroid (0 = identical, 1 = completely different)."""
    sim = float(np.dot(article_embedding, centroid_embedding))
    sim = max(-1.0, min(1.0, sim))
    return 1.0 - sim


def classify_update(
    article_embedding: np.ndarray,
    centroid_embedding: np.ndarray,
    new_tier: int | None = None,
    novelty_threshold_major: float = 0.35,
    novelty_threshold_repeat: float = 0.15,
) -> str:
    """
    Classify how much new information an article adds to a cluster.

    Returns:
        'repeat' — restates known info (no new high-tier source)
        'minor'  — small update, or new trusted source
        'major'  — significant new development
    """
    novelty = novelty_score(article_embedding, centroid_embedding)

    if novelty >= novelty_threshold_major:
        return "major"

    if novelty >= novelty_threshold_repeat:
        return "minor"

    # Very close to centroid but a new trusted source confirms it → minor
    if new_tier is not None and new_tier <= 2:
        return "minor"

    return "repeat"
