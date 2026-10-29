"""
Context engine: generate structured story context via LLM for top clusters.
Optional web_search / fetch_url tools for live grounding (auditable).
"""
from __future__ import annotations

import json
import logging
import re

from newtalk.config.settings import DATABASE_URL
from newtalk.db.repository import NewTalkRepository
from newtalk.llm.litellm_client import call_llm, call_llm_with_tools
from newtalk.llm.tools.web_tools import WEB_SEARCH_TOOL, FETCH_URL_TOOL, execute_tool
from newtalk.processing.freshness import load_freshness_config
from newtalk.config.audience import get_perspective_prompt
from newtalk.llm.date_context import get_date_context

logger = logging.getLogger(__name__)

CONTEXT_SCHEMA = {
    "what_happened": "",
    "why_it_matters": "",
    "who_is_affected": "",
    "background_timeline": [],
    "viewpoints": [{"stance": "", "supporting_evidence": "", "source_leaning": ""}],
    "confidence_level": "medium",
    "open_questions": [],
    "grounding_audit": [],
    "new_development": "",  # what's new since the last briefing
}

_VALID_CONFIDENCE = {"high", "medium", "developing"}


def _validate_context(ctx: dict) -> dict:
    """Validate and coerce context JSON, raising ValueError on unfixable issues."""
    for key in CONTEXT_SCHEMA:
        if key not in ctx:
            ctx[key] = CONTEXT_SCHEMA[key]
    # Validate confidence
    if ctx.get("confidence_level") not in _VALID_CONFIDENCE:
        ctx["confidence_level"] = "developing"
    # Ensure timeline is a list
    if not isinstance(ctx.get("background_timeline"), list):
        ctx["background_timeline"] = [str(ctx["background_timeline"])]
    # Ensure viewpoints is a list
    if not isinstance(ctx.get("viewpoints"), list):
        ctx["viewpoints"] = [{"stance": str(ctx["viewpoints"]), "supporting_evidence": "", "source_leaning": ""}]
    return ctx


def _parse_context_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    data = json.loads(text)
    return _validate_context(data)


def _build_context_prompt(cluster, enable_tools: bool = False, previous_context: dict | None = None) -> list[dict]:
    articles = []
    article_urls = []
    for a in cluster.articles[:6]:
        articles.append({
            "source": a.source,
            "title": a.title,
            "body": (a.body or "")[:800],
            "published_at": str(a.published_at) if a.published_at else None,
            "url": a.url,
        })
        if a.url.startswith("http"):
            article_urls.append(a.url)

    continuation = ""
    if previous_context:
        continuation = (
            "This is a CONTINUING event. Previous briefing context:\n"
            + json.dumps(previous_context, indent=2)[:2000]
            + "\n\nSummarize what's NEW since the last briefing. "
            "Keep the timeline cumulative — append today's developments at the end. "
            "Fill the new_development field with today's specific development. "
            "Do NOT repeat previously covered background unless it's essential for understanding today's update.\n\n"
        )

    tool_instruction = ""
    if enable_tools:
        tool_instruction = (
            "\nYou MAY use web_search or fetch_url tools to ground background_timeline "
            "and viewpoints in live sources. For each factual claim, add a grounding_audit entry:\n"
            '{"claim": "...", "source_type": "web_search|fetch_url|model_knowledge", '
            '"tool_query_or_url": "...", "verified": true|false}'
        )

    perspective = get_perspective_prompt()
    date_context = get_date_context()
    system = (
        f"{date_context}\n\n"
        "You are an intelligence analyst building briefing context for an Indian audience. "
        f"\nAUDIENCE:\n{perspective}\n\n"
        + continuation
        + "Respond with JSON only matching this schema:\n"
        + json.dumps(CONTEXT_SCHEMA, indent=2)
        + "\nconfidence_level must be one of: high, medium, developing."
        + tool_instruction
    )
    user = json.dumps({
        "story_title": cluster.representative_title,
        "articles": articles,
        "article_urls_for_fetch": article_urls[:3],
    }, indent=2)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_context_for_cluster(cluster, repo: NewTalkRepository) -> dict:
    """Generate and store context for one cluster (with optional tool grounding).
    If cluster already has context from a previous run, use cumulative mode."""
    config = load_freshness_config()
    max_tool_rounds = int(config.get("context_writer_max_tool_calls", 2))

    # Check for previous context — cumulative mode for continuing events
    prev_ctx = repo.get_story_context(cluster.id)
    previous_context = None
    if prev_ctx:
        try:
            previous_context = {
                "what_happened": prev_ctx.background,
                "background_timeline": json.loads(prev_ctx.timeline_json or "[]"),
                "viewpoints": json.loads(prev_ctx.viewpoints_json or "[]"),
                "confidence_level": prev_ctx.confidence_level,
            }
        except (json.JSONDecodeError, AttributeError):
            pass

    messages = _build_context_prompt(cluster, enable_tools=True, previous_context=previous_context)
    tools = [WEB_SEARCH_TOOL, FETCH_URL_TOOL]
    tool_audit: list[dict] = []

    try:
        resp, tool_audit = call_llm_with_tools(
            role="context_writer",
            messages=messages,
            tools=tools,
            tool_executor=execute_tool,
            max_tool_rounds=max_tool_rounds,
        )
        ctx = _parse_context_json(resp.choices[0].message.content)
    except Exception as exc:
        logger.warning(
            "Tool-enabled context failed for cluster %s (%s) — falling back to plain LLM",
            cluster.id, exc,
        )
        try:
            resp = call_llm(role="context_writer", messages=_build_context_prompt(
                cluster, enable_tools=False, previous_context=previous_context,
            ))
            ctx = _parse_context_json(resp.choices[0].message.content)
        except Exception as exc2:
            # Second attempt without previous context (fallback)
            logger.warning("Context with prev-ctx failed for cluster %s (%s) — retrying without", cluster.id, exc2)
            resp = call_llm(role="context_writer", messages=_build_context_prompt(cluster, enable_tools=False))
            ctx = _parse_context_json(resp.choices[0].message.content)
        ctx["grounding_audit"] = [
            {"claim": "full_context", "source_type": "model_knowledge", "note": "tool fallback"}
        ]

    # Merge runtime tool audit into grounding_audit
    grounding = ctx.get("grounding_audit") or []
    for entry in tool_audit:
        grounding.append({
            "claim": f"tool_call:{entry.get('tool')}",
            "source_type": entry.get("tool"),
            "tool_query_or_url": entry.get("arguments"),
            "verified": True,
        })
    ctx["grounding_audit"] = grounding

    repo.set_story_context(
        cluster_id=cluster.id,
        background=ctx.get("what_happened", ""),
        timeline_json=json.dumps(ctx.get("background_timeline", [])),
        viewpoints_json=json.dumps(ctx.get("viewpoints", [])),
        confidence_level=ctx.get("confidence_level", "medium"),
        evidence_json=json.dumps({
            "why_it_matters": ctx.get("why_it_matters", ""),
            "who_is_affected": ctx.get("who_is_affected", ""),
            "open_questions": ctx.get("open_questions", []),
            "grounding_audit": grounding,
        }),
    )
    return ctx


def select_context_candidates(
    repo: NewTalkRepository,
    top_n: int,
    per_category: int = 0,
    categories: set[str] | None = None,
) -> list:
    """Global top-N plus the best `per_category` clusters of each wanted category.

    Without the per-category pass, low-weight categories (sports, entertainment, health) never
    reach the context stage and users who follow them get nothing to hear.
    """
    from newtalk.processing.freshness import get_freshness_window_hours, is_cluster_fresh

    window = get_freshness_window_hours()
    ranked = [
        c
        for c in repo.get_ranked_clusters(limit=max(top_n * 10, 150))
        if is_cluster_fresh(c, window)
    ]
    chosen = list(ranked[:top_n])
    if per_category and categories:
        from newtalk.scoring.rubric import cluster_category, load_rubric_config

        cfg = load_rubric_config()
        seen = {c.id for c in chosen}
        taken: dict[str, int] = {}
        for cluster in ranked[top_n:]:
            if cluster.id in seen or not cluster.articles:
                continue
            cat = cluster_category(cluster, cfg)
            if cat in categories and taken.get(cat, 0) < per_category:
                chosen.append(cluster)
                seen.add(cluster.id)
                taken[cat] = taken.get(cat, 0) + 1
    return chosen


def generate_context_for_top_clusters(
    repo: NewTalkRepository | None = None,
    top_n: int = 5,
    per_category: int = 0,
    categories: set[str] | None = None,
) -> list[dict]:
    """Generate context for the top-N scored clusters (+ best per wanted category)."""
    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    clusters = select_context_candidates(repo, top_n, per_category, categories)
    results = []

    for cluster in clusters:
        if not cluster.articles:
            continue
        if cluster.context and cluster.last_change_kind not in ("minor", "major"):
            continue  # already contextualised and nothing new happened: save the LLM calls
        logger.info("Generating context for cluster %d: %s", cluster.id, cluster.representative_title[:60])
        try:
            ctx = generate_context_for_cluster(cluster, repo)
            results.append({
                "cluster_id": cluster.id,
                "title": cluster.representative_title,
                "context": ctx,
                "grounding_audit": ctx.get("grounding_audit", []),
            })
        except Exception as exc:
            logger.error("Context generation failed for cluster %d: %s", cluster.id, exc)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = generate_context_for_top_clusters(top_n=3)
    for r in results:
        print(f"\n=== {r['title'][:70]} ===")
        print(json.dumps(r["context"], indent=2)[:1500])
        print("Grounding audit:", json.dumps(r.get("grounding_audit", []), indent=2)[:500])
