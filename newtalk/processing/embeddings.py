"""
Local sentence-transformers embeddings for article clustering.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import SentenceTransformer
    logger.info("Loading embedding model: %s", DEFAULT_MODEL)
    return SentenceTransformer(DEFAULT_MODEL)


def article_text(title: str, body: str, max_body_chars: int = 500) -> str:
    """Combine title + truncated body for embedding."""
    body_snip = (body or "").strip()[:max_body_chars]
    return f"{title.strip()}\n{body_snip}".strip()


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """
    Generate L2-normalised embeddings for a list of texts.

    Returns:
        numpy array shape (n, dim)
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)

    model = _load_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 50,
        convert_to_numpy=True,
    )
    return np.asarray(embeddings, dtype=np.float32)
