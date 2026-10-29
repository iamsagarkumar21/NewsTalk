"""Test memory store familiarity tracking over simulated briefings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from newtalk.db.repository import NewTalkRepository
from newtalk.memory.memory_store import MemoryStore


def test_memory_familiarity_over_days():
    repo = NewTalkRepository("sqlite:///:memory:")
    repo.create_tables()
    memory = MemoryStore(repo)

    topic = "Ukraine conflict developments"
    story = {"topic": topic, "title": topic, "summary": "Day 1 baseline explanation."}

    # Day 1 — first briefing
    memory.update_after_briefing([story])
    ctx1 = memory.get_context_for(topic)
    assert ctx1["familiarity_level"] == 0.5, f"Expected 0.5, got {ctx1['familiarity_level']}"

    # Day 2 — same topic
    memory.update_after_briefing([story])
    ctx2 = memory.get_context_for(topic)
    assert ctx2["familiarity_level"] == 1.0

    # Day 3
    memory.update_after_briefing([story])
    ctx3 = memory.get_context_for(topic)
    assert ctx3["familiarity_level"] == 1.5

    # Composer should flag familiarity >= 2 after enough briefings
    memory.update_after_briefing([story])
    memory.update_after_briefing([story])
    ctx5 = memory.get_context_for(topic)
    assert ctx5["familiarity_level"] >= 2.0

    composer_ctx = memory.build_composer_memory_context([topic])
    assert "skip basic background" in composer_ctx.lower() or "familiarity" in composer_ctx.lower()

    # Q&A update
    memory.update_after_qa("What are economists saying?", "Growth forecasts revised downward.", topic=topic)
    ctx_qa = memory.get_context_for(topic)
    assert ctx_qa["familiarity_level"] > ctx5["familiarity_level"]

    print("Memory test passed!")
    print(f"  Final familiarity: {ctx_qa['familiarity_level']}")
    print(f"  Composer hint: {composer_ctx[:120]}...")


if __name__ == "__main__":
    test_memory_familiarity_over_days()
