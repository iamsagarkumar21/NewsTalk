"""Shared builders for unit tests."""

import datetime
import json
from types import SimpleNamespace


def seed_cluster(
    repo,
    title,
    *,
    source="Test",
    body="",
    score=7.0,
    tier=2,
    change_kind=None,
    development_count=0,
):
    """A scored, contextualized, one-article cluster."""
    n = len(repo.list_clusters()) + 1
    art = repo.add_article(
        source=source,
        source_type="rss",
        url=f"https://test.example/{n}",
        title=title,
        body=body or title,
        author=None,
        published_at=datetime.datetime.utcnow(),
        tier=tier,
    )
    cluster = repo.create_cluster(representative_title=title)
    repo.add_article_to_cluster(cluster.id, art.id)
    repo.set_importance_score(
        cluster_id=cluster.id, score=score, rationale="t", rubric_version="t"
    )
    repo.set_story_context(
        cluster_id=cluster.id,
        background=f"Background for {title}.",
        timeline_json="[]",
        viewpoints_json="[]",
        confidence_level="confirmed",
        evidence_json=json.dumps({"why_it_matters": "It matters to India."}),
    )
    repo.update_cluster_event_fields(
        cluster.id, last_change_kind=change_kind, development_count=development_count
    )
    return cluster


class FakeLLM:
    """Counts calls; writes one valid segment per story id it is given."""

    def __init__(self, override=None):
        self.calls = 0
        self.override = override or {}
        self.seen_feedback = []

    def __call__(self, role, messages, **kw):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        if "fix_these_problems" in payload:
            self.seen_feedback.append(payload["fix_these_problems"])
        segments = []
        for story in payload["stories"]:
            sid = story["id"]
            fixed = "fix_these_problems" in payload
            text = self.override.get((sid, fixed))
            if text is None:
                system = messages[0]["content"]
                if "SCRIPT RULE" in system:  # hinglish, mixed script
                    text = (
                        f"{story['title']}। Officials ने कहा कि ये एक बड़ा development है और "
                        "details आगे confirm होंगी। इसका असर भारतीय नागरिकों और markets पर पड़ "
                        "सकता है, इसलिए नज़र रखना ज़रूरी है क्योंकि agencies बता रही हैं कि अभी "
                        "और जानकारी आएगी।"
                    )
                elif "Clear, simple spoken Hindi" in system:
                    text = (
                        f"{story['title']}। अधिकारियों ने कहा कि यह एक बड़ा घटनाक्रम है और "
                        "आगे और जानकारी सामने आएगी। इसका असर भारतीय नागरिकों और बाज़ार पर "
                        "पड़ सकता है, इसलिए इस पर नज़र रखना ज़रूरी है क्योंकि एजेंसियाँ अभी "
                        "पुष्टि कर रही हैं कि वास्तव में क्या हुआ है।"
                    )
                else:
                    text = (
                        f"{story['title']}. Officials said the development is significant for "
                        "Indian citizens and markets, and further details are expected through "
                        "the day as agencies confirm what happened and who is affected by it."
                    )
            segments.append({"id": sid, "text": text})
        content = json.dumps({"segments": segments}, ensure_ascii=False)
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
