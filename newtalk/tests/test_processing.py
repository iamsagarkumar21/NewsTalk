"""Unit tests for clustering logic (no embedding model load)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from newtalk.processing.clustering import cluster_by_similarity


def test_clustering_groups_similar_vectors():
    # Two pairs of near-identical vectors + one outlier
    base_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    base_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    outlier = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    embeddings = np.stack([
        base_a,
        base_a * 0.99 + np.array([0.01, 0, 0]),
        base_b,
        base_b * 0.99 + np.array([0, 0.01, 0]),
        outlier,
    ])
    titles = ["Story A1", "Story A2", "Story B1", "Story B2", "Unrelated"]

    groups = cluster_by_similarity(embeddings, titles, threshold=0.95)
    assert len(groups) == 3, f"Expected 3 clusters, got {len(groups)}"

    sizes = sorted(len(g.article_indices) for g in groups)
    assert sizes == [1, 2, 2], f"Unexpected cluster sizes: {sizes}"
    print("Clustering unit test passed!")


if __name__ == "__main__":
    test_clustering_groups_similar_vectors()
