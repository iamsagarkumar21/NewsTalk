"""
Personalization / memory store interface.
Tracks topic familiarity so the composer skips re-explaining basics.
"""
from __future__ import annotations

import datetime
import json
import logging
import re

from newtalk.config.settings import DATABASE_URL
from newtalk.db.models import OWNER_USER_ID
from newtalk.db.repository import NewTalkRepository

logger = logging.getLogger(__name__)

FAMILIARITY_INCREMENT = 0.5
FAMILIARITY_MAX = 5.0


class MemoryStore:
    def __init__(self, repo: NewTalkRepository | None = None, user_id: int = OWNER_USER_ID):
        self.repo = repo or NewTalkRepository(DATABASE_URL)
        self.repo.create_tables()
        self.user_id = user_id

    def get_context_for(self, topic: str) -> dict:
        """
        Return memory context for a topic (familiarity + notes).

        Returns:
            {"topic": str, "familiarity_level": float, "last_covered_at": str|None, "notes": str|None}
        """
        mem = self.repo.get_user_memory(topic, user_id=self.user_id)
        if not mem:
            return {
                "topic": topic,
                "familiarity_level": 0.0,
                "last_covered_at": None,
                "notes": None,
            }
        return {
            "topic": mem.topic,
            "familiarity_level": mem.familiarity_level,
            "last_covered_at": mem.last_covered_at.isoformat() if mem.last_covered_at else None,
            "notes": mem.notes,
        }

    def get_all_topics(self) -> list[str]:
        with self.repo.session_scope() as session:
            from newtalk.db.models import UserMemory
            return [
                m.topic
                for m in session.query(UserMemory).filter_by(user_id=self.user_id).all()
            ]

    def update_after_briefing(
        self,
        stories: list[dict],
        briefing_id: int | None = None,
    ) -> None:
        """
        Update familiarity after a briefing.

        Args:
            stories: list of {"topic": str, "title": str, "summary": str}
        """
        for story in stories:
            topic = story.get("topic") or story.get("title", "")[:80]
            if not topic:
                continue
            mem = self.repo.get_user_memory(topic, user_id=self.user_id)
            current = mem.familiarity_level if mem else 0.0
            new_level = min(current + FAMILIARITY_INCREMENT, FAMILIARITY_MAX)
            notes = story.get("summary", "")[:500] or None
            self.repo.set_user_memory(
                topic=topic, familiarity_level=new_level, notes=notes, user_id=self.user_id
            )
            logger.info("Memory updated after briefing: %s → %.1f", topic[:50], new_level)

    def update_after_qa(self, question: str, answer: str, topic: str | None = None) -> None:
        """Boost familiarity for topics touched in Q&A."""
        if not topic:
            # Extract a simple topic from the question
            words = re.findall(r"[A-Za-z]{4,}", question)
            topic = " ".join(words[:4]) if words else question[:60]

        mem = self.repo.get_user_memory(topic, user_id=self.user_id)
        current = mem.familiarity_level if mem else 0.0
        new_level = min(current + 0.3, FAMILIARITY_MAX)
        notes = f"Q: {question[:200]} | A: {answer[:300]}"
        self.repo.set_user_memory(
                topic=topic, familiarity_level=new_level, notes=notes, user_id=self.user_id
            )
        logger.info("Memory updated after Q&A: %s → %.1f", topic[:50], new_level)

    def build_composer_memory_context(self, story_titles: list[str]) -> str:
        """Build a text block instructing the composer about known topics."""
        lines = []
        for title in story_titles:
            topic = title[:80]
            ctx = self.get_context_for(topic)
            if ctx["familiarity_level"] >= 2.0:
                lines.append(
                    f"- '{topic}': user familiarity {ctx['familiarity_level']:.1f}/5 "
                    f"(last covered {ctx['last_covered_at'] or 'unknown'}) — "
                    "skip basic background, continue from last known state."
                )
            elif ctx["familiarity_level"] > 0:
                lines.append(
                    f"- '{topic}': partial familiarity {ctx['familiarity_level']:.1f}/5 — brief recap only."
                )
        if not lines:
            return "No prior familiarity with these topics — explain fully."
        return "User memory context:\n" + "\n".join(lines)
