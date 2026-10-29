"""Canonical dedup key helpers for ingestion sources."""
from __future__ import annotations

import hashlib
import re


def make_canonical_key(raw_url: str) -> str:
    """Stable dedup key from a normalized URL (SHA-1 hex)."""
    norm = normalize_url(raw_url)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def make_title_key(title: str, category: str = "") -> str:
    """Stable dedup key from title + optional category, for URL-less entries."""
    base = f"{title.strip().lower()}|{category}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    """Strip query params, trailing slashes, and fragments."""
    if not url:
        return url
    u = url.strip().lower()
    # Strip fragment
    if "#" in u:
        u = u[:u.index("#")]
    # Strip trailing slash
    u = u.rstrip("/")
    # For most sources, query params are tracking cruft; strip them
    if "?" in u:
        u = u[:u.index("?")]
    return u
