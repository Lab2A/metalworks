"""End-to-end research pipeline orchestrator.

The single research entry point. Every stage takes an injected `ResearchDeps`
rather than reaching for module-level singletons. The stage sequence:

    brief
      → pick effective subreddits (LLM, append-only)
      → pull corpus (reader, per subreddit x month window)
      → three-bucket triage (embedding + classifier)
      → hydrate relevant subset (submissions + comments → CorpusRepo)
      → synthesize || web research      (parallel; web is best-effort)
      → triangulate + cross-stream confidence
      → DemandReport

Failure posture (preserved): synthesis is required and raises loud; web
research, comment hydration, and triangulation are best-effort and degrade
to `partial=True` with a concrete caveat. An empty corpus returns a
`partial=True` report, never an empty-looking success.
"""

from __future__ import annotations

import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from metalworks.contract import (
    CorpusStats,
    DemandReport,
    Fork,
    SourceMapEntry,
    WebFinding,
)
from metalworks.research.arctic import hydrate_comments, hydrate_submissions
from metalworks.research.exploration import run_exploration_triage
from metalworks.research.planner import pick_target_subreddits
from metalworks.research.synthesis import synthesize
from metalworks.research.triangulate import (
    TriangulationFailedError,
    apply_cross_stream_confidence,
    triangulate,
)
from metalworks.research.types import ExplorationItem, MonthRef, SynthesisOutput, months_back
from metalworks.research.web import web_research

if TYPE_CHECKING:
    from collections.abc import Iterable

    from metalworks.contract import ResearchBrief
    from metalworks.research.deps import ResearchDeps


# ── Helpers ────────────────────────────────────────────────────────────────


def _window_months(deps: ResearchDeps, brief: ResearchBrief) -> list[MonthRef]:
    anchor = deps.reader.latest_available_month("submissions")
    return months_back(max(1, brief.time_window_months), anchor=anchor)


def _pull_corpus(
    deps: ResearchDeps,
    brief: ResearchBrief,
    *,
    months: list[MonthRef],
    per_sub_limit: int | None,
) -> list[ExplorationItem]:
    """Pull submissions for every brief subreddit into indexed ExplorationItems.

    `per_sub_limit` is a dev guard (None in production). Triage decides
    relevance, so we never pre-truncate by content. Item indices are the
    triage stage's indexing contract.
    """
    items: list[ExplorationItem] = []
    for sub in brief.target_subreddits:
        rows = deps.reader.pull_subreddit(
            subreddit=sub.name,
            content_type="submissions",
            months=months,
            select_cols=["id", "title", "selftext", "subreddit", "score", "num_comments"],
            limit=per_sub_limit,
        )
        for row in rows:
            items.append(
                ExplorationItem(
                    idx=len(items),
                    post_id=str(row["id"]),
                    title=str(row.get("title") or ""),
                    selftext=str(row.get("selftext") or ""),
                    subreddit=str(row.get("subreddit") or sub.name),
                    score=row.get("score"),
                    num_comments=row.get("num_comments"),
                )
            )
    return items


def _build_corpus_stats(items: Iterable[ExplorationItem]) -> CorpusStats:
    """Deterministic distributions over the relevant corpus (never LLM-inferred).

    The rollup keys on a neutral `source_bucket` — for Reddit this is the
    subreddit; other sources supply their own bucket. The `SourceMapEntry`
    contract field stays `subreddit` for now (1c adds a generic alias
    additively), so the bucket value is passed straight through.
    """
    items = list(items)
    by_bucket: Counter[str] = Counter(item.subreddit or "(unknown)" for item in items)
    subreddit_distribution = [
        SourceMapEntry(subreddit=bucket, threads_examined=count)
        for bucket, count in by_bucket.most_common()
    ]
    percentile_bands: dict[str, int] = {}
    scored = [it.score for it in items if it.score is not None]
    if scored:
        scores = sorted(scored)
        for d in range(1, 11):
            lo = scores[int((d - 1) / 10 * (len(scores) - 1))]
            hi = scores[int(d / 10 * (len(scores) - 1))]
            percentile_bands[f"d{d}"] = sum(1 for s in scores if lo <= s <= hi)
    return CorpusStats(
        percentile_bands=percentile_bands,
        subreddit_distribution=subreddit_distribution,
        time_distribution={},
    )


def _month_to_dt(m: MonthRef, *, end_of_month: bool = False) -> datetime:
    if end_of_month:
        ny, nm = (m.year + 1, 1) if m.month == 12 else (m.year, m.month + 1)
        return datetime(ny, nm, 1, tzinfo=UTC) - timedelta(seconds=1)
    return datetime(m.year, m.month, 1, tzinfo=UTC)


def _empty_report(
    *, deps: ResearchDeps, report_id: str, brief: ResearchBrief, months: list[MonthRef], caveat: str
) -> DemandReport:
    return DemandReport(
        report_id=report_id,
        client_id=brief.workspace_id,
        query=brief.question,
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="(no corpus)",
        optimized_axis="(no corpus)",
        source="reddit_arctic_shift",
        date_range_start=_month_to_dt(months[0]),
        date_range_end=_month_to_dt(months[-1], end_of_month=True),
        total_threads=0,
        total_distinct_authors=0,
        ranked_clusters=[],
        partial=True,
        caveat=caveat,
        created_by="library",
        generated_at=deps.clock(),
        brief=brief,
    )


# ── Public surface ─────────────────────────────────────────────────────────


def run_research(
    deps: ResearchDeps,
    *,
    brief: ResearchBrief,
    per_sub_limit: int | None = None,
    max_findings: int = 10,
) -> DemandReport:
    """Run the pipeline against a finalized brief, return a DemandReport.

    `partial=True` with a caveat whenever a best-effort stage (web research,
    comment hydration, triangulation) degraded. Synthesis failures raise.
    """
    report_id = str(uuid.uuid4())

    # Effective subreddits: the LLM appends on-topic subs to the user's D5
    # list without mutating the persisted brief (immutability).
    effective_subs = pick_target_subreddits(deps, brief=brief)
    effective_brief = brief.model_copy(update={"target_subreddits": effective_subs})

    months = _window_months(deps, brief)

    deps.emit("pulling")
    items = _pull_corpus(deps, effective_brief, months=months, per_sub_limit=per_sub_limit)
    if not items:
        return _empty_report(
            deps=deps,
            report_id=report_id,
            brief=brief,
            months=months,
            caveat="No threads pulled from the brief's subreddits in the window.",
        )

    deps.emit("triaging")
    relevant_indices, exploration_report = run_exploration_triage(
        deps,
        question=brief.question,
        relevance_rubric=brief.relevance_rubric,
        items=items,
        thresholds=brief.triage_thresholds,
    )
    relevant_items = [items[i] for i in relevant_indices]

    deps.emit("hydrating")
    stage_errors: list[str] = []
    post_ids = [it.post_id for it in relevant_items]
    hyd_subs = hydrate_submissions(deps, post_ids=post_ids, months=months)
    comments_error: str | None = None
    if deps.comments is not None:
        hyd_comments = hydrate_comments(deps, link_ids=post_ids)
        if hyd_comments.skipped:
            stage_errors.append("comment_hydration")
    else:
        comments_error = "no comment source configured (deps.comments is None)"
        stage_errors.append("comment_hydration")

    # Synthesis || web research — independent, joined at a barrier.
    deps.emit("analyzing")
    synthesis_out: SynthesisOutput
    web_findings: list[WebFinding]
    web_error: str | None = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_synth = pool.submit(synthesize, deps, brief=brief, hydrated_post_ids=post_ids)
        fut_web = pool.submit(web_research, deps, brief=brief, max_findings=max_findings)
        synthesis_out = fut_synth.result()  # required — raises loud
        try:
            web_findings = fut_web.result()
        except Exception as e:  # best-effort
            web_findings = []
            web_error = f"{type(e).__name__}: {str(e)[:120]}"
            stage_errors.append("web_research")

    corpus_stats = _build_corpus_stats(relevant_items)
    exploration_report.threads_synthesized = synthesis_out.n_synthesized

    deps.emit("triangulating")
    triangulation_error: str | None = None
    cross_references = []
    must_address_resolution: dict[str, str] = {}
    ranked_clusters_final = synthesis_out.ranked_clusters
    try:
        triangulation = triangulate(
            deps,
            brief=brief,
            ranked_clusters=synthesis_out.ranked_clusters,
            web_findings=web_findings,
        )
        cross_references = triangulation.cross_references
        must_address_resolution = triangulation.must_address_resolution
        ranked_clusters_final = apply_cross_stream_confidence(
            clusters=synthesis_out.ranked_clusters,
            cross_references=triangulation.cross_references,
        )
    except TriangulationFailedError as e:
        triangulation_error = str(e)[:200]
        stage_errors.append("triangulating")

    caveat_parts: list[str] = []
    if web_error:
        caveat_parts.append(f"Web research failed: {web_error}")
    if comments_error:
        caveat_parts.append(f"Comments unavailable: {comments_error}")
    if triangulation_error:
        caveat_parts.append(f"Triangulator failed: {triangulation_error}")
    is_partial = bool(stage_errors)
    if not is_partial:
        caveat_parts.append(
            f"Hydrated {hyd_subs.upserted} submissions for {len(relevant_items)} relevant threads."
        )
    caveat: str | None = " ".join(caveat_parts) if caveat_parts else None

    deps.emit("assembling")
    return DemandReport(
        report_id=report_id,
        client_id=brief.workspace_id,
        query=brief.question,
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="(slot_plan-driven)",
        optimized_axis="(slot_plan-driven)",
        source="reddit_arctic_shift",
        date_range_start=_month_to_dt(months[0]),
        date_range_end=_month_to_dt(months[-1], end_of_month=True),
        total_threads=len(relevant_items),
        total_distinct_authors=synthesis_out.total_distinct_authors,
        ranked_clusters=ranked_clusters_final,
        partial=is_partial,
        caveat=caveat,
        created_by="library",
        generated_at=deps.clock(),
        verdict=synthesis_out.verdict,
        slot_plan=synthesis_out.slot_plan,
        audience_profile=synthesis_out.audience_profile,
        segments=synthesis_out.segments,
        market_sizing=synthesis_out.market_sizing,
        price_finding=synthesis_out.price_finding,
        source_map=synthesis_out.source_map,
        brief=brief,
        web_findings=web_findings,
        corpus_stats=corpus_stats,
        corpus_shape=exploration_report,
        cross_references=cross_references,
        must_address_resolution=must_address_resolution,
    )


__all__ = ["run_research"]
