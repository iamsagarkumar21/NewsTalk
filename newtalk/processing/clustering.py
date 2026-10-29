"""
Cluster articles by embedding cosine similarity using agglomerative grouping.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Cosine similarity threshold for same-story grouping.
# MiniLM-L6-v2: 0.78 balances merging related coverage vs splitting distinct stories.
DEFAULT_SIMILARITY_THRESHOLD = 0.78


@dataclass
class ClusterGroup:
    article_indices: list[int]
    representative_index: int

    @property
    def representative_title(self) -> int:
        return self.representative_index


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def cluster_by_similarity(
    embeddings: np.ndarray,
    titles: list[str],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[ClusterGroup]:
    """
    Greedy single-linkage clustering: merge articles whose embedding
    similarity to the cluster centroid exceeds `threshold`.

    Args:
        embeddings: (n, dim) normalised vectors
        titles:     parallel list of article titles (for logging)
        threshold:  cosine similarity cutoff (0–1)

    Returns:
        List of ClusterGroup with article index lists.
    """
    n = len(embeddings)
    if n == 0:
        return []

    assigned = [-1] * n
    groups: list[list[int]] = []

    for i in range(n):
        if assigned[i] >= 0:
            continue

        group = [i]
        assigned[i] = len(groups)
        centroid = embeddings[i].copy()

        for j in range(i + 1, n):
            if assigned[j] >= 0:
                continue
            sim = _cosine_sim(centroid, embeddings[j])
            if sim >= threshold:
                group.append(j)
                assigned[j] = len(groups)
                centroid = embeddings[group].mean(axis=0)
                norm = np.linalg.norm(centroid)
                if norm > 0:
                    centroid = centroid / norm

        groups.append(group)

    result = []
    for indices in groups:
        # Representative = article with longest title (usually most descriptive)
        rep = max(indices, key=lambda idx: len(titles[idx]))
        result.append(ClusterGroup(article_indices=indices, representative_index=rep))

    logger.info(
        "Clustered %d articles → %d clusters (threshold=%.2f)",
        n, len(result), threshold,
    )
    return result
