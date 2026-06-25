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

import logging
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from metalworks.contract import (
    CorpusRecord,
    CorpusStats,
    DemandReport,
    Fork,
    InsightCluster,
    SourceMapEntry,
    SourceSelection,
    WebFinding,
)
from metalworks.research.exploration import run_exploration_triage
from metalworks.research.planner import (
    pick_target_subreddits,
    preflight_lines,
    select_sources,
)
from metalworks.research.sources import SourceWindow
from metalworks.research.sources.ingest import ingest_comments_for, ingest_records
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


logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────


def _maybe_select_sources(deps: ResearchDeps, *, brief: ResearchBrief) -> SourceSelection | None:
    """Run the brief-aware selector (default ON — #167) unless overridden, else ``None``.

    Two short-circuits:

    * An explicit ``deps.sources`` override means the operator already chose the
      connectors — the selector must not second-guess it, so we skip selection and
      ``effective_sources`` returns the override verbatim (override wins).
    * The selector is **on by default** via ``[sources].select`` (#167); set
      ``select = false`` to opt out, in which case we return ``None`` and the
      configured/Reddit path runs exactly as before.

    When the selector runs with no usable selection (no chat model / a failed
    ranking), :func:`~metalworks.research.planner.select_sources` degrades to the
    ``reddit`` floor — so a default-on run with an offline/unscripted model yields a
    reddit-only selection, the same connectors the old default path used.
    """
    if deps.sources is not None:
        return None
    from metalworks import config

    if not config.source_selector_enabled():
        return None
    return select_sources(deps, brief=brief, configured_floor=config.default_source_id())


def _window_months(deps: ResearchDeps, brief: ResearchBrief) -> list[MonthRef]:
    anchor = deps.reader.latest_available_month("submissions")
    return months_back(max(1, brief.time_window_months), anchor=anchor)


# Map a source's registry id to the DemandReport.source provenance label.
_SOURCE_LABELS = {"reddit": "reddit_arctic_shift", "arctic": "reddit_arctic_shift"}


def _source_label(deps: ResearchDeps, selection: SourceSelection | None = None) -> str:
    """The honest provenance label for this run, from the sources actually configured.

    One source → its label (reddit/arctic → ``reddit_arctic_shift``, else the source id
    verbatim, e.g. ``hackernews``); more than one → ``mixed``. Falls back to
    ``reddit_arctic_shift`` only when no source is configured.
    """
    ids = sorted({s.source_id for s in deps.effective_sources(selection)})
    if not ids:
        return "reddit_arctic_shift"
    if len(ids) > 1:
        return "mixed"
    return _SOURCE_LABELS.get(ids[0], ids[0])


def _pull_corpus(
    deps: ResearchDeps,
    brief: ResearchBrief,
    *,
    months: list[MonthRef],
    per_sub_limit: int | None,
    selection: SourceSelection | None = None,
) -> tuple[list[ExplorationItem], dict[str, CorpusRecord]]:
    """Pull candidate records from every configured source for triage.

    Each :class:`ItemSource` is pulled once per brief subreddit (Arctic windows
    by subreddit) over the month window. The pulled :class:`CorpusRecord`s become
    the triage stage's indexed :class:`ExplorationItem`s AND are returned keyed by
    id so the run can ingest the triage-relevant subset (matching the prior
    hydrate-only-the-relevant-subset behavior — we don't durably persist threads
    triage rejected, and we don't re-fetch them).

    `per_sub_limit` is a dev guard (None in production). Triage decides
    relevance, so we never pre-truncate by content. Item indices are the
    triage stage's indexing contract.
    """
    window = SourceWindow(months=tuple(months))
    items: list[ExplorationItem] = []
    records_by_id: dict[str, CorpusRecord] = {}
    for source in deps.effective_sources(selection):
        for sub in brief.target_subreddits:
            for r in source.pull(query=sub.name, window=window, limit=per_sub_limit):
                if not r.id:
                    continue
                records_by_id[r.id] = r
                subreddit = str(r.extra.get("subreddit") or sub.name)
                items.append(
                    ExplorationItem(
                        idx=len(items),
                        post_id=r.id,
                        title=r.title,
                        selftext=r.text,
                        subreddit=subreddit,
                        score=r.engagement,
                        num_comments=r.extra.get("num_comments"),
                    )
                )
    return items, records_by_id


def _apply_magnitude_overlay(
    deps: ResearchDeps,
    *,
    slot_plan_product: str | None,
    clusters: list[InsightCluster],
    web_findings: list[WebFinding],
    months: list[MonthRef],
    stage_errors: list[str],
) -> str | None:
    """Lane-② overlay: attach magnitude numbers to existing clusters, then rescore.

    Deterministic by construction (the determinism non-negotiable): the entities
    handed to providers are EXTRACTED from grounded artifacts — cluster quote source
    names, the brief slot-plan product, web-finding domains — never an LLM guess.
    Active providers (``deps.effective_magnitude_providers()``; empty by default, so
    a default run skips this entirely) measure those entities; matches merge into the
    owning cluster's ``demand_signals`` and rescore via the existing
    ``compute_demand_score`` path (RANKING only — the verdict band never sees it).
    Re-banding + re-ranking follow because a rescore can reorder.

    Best-effort: a provider that raises degrades the stage (``stage_errors`` +
    a returned caveat string) but never aborts the run — the ``web_research``
    posture. A provider can NEVER create a cluster; with no clusters to attach to,
    this is a no-op.
    """
    from metalworks.research.sources.magnitude import (
        extract_entities,
        merge_magnitude_into_clusters,
    )
    from metalworks.research.synthesis.cluster_ranker import (
        compute_demand_score,
        signal_from_breadth,
    )

    providers = deps.effective_magnitude_providers()
    if not providers or not clusters:
        return None  # off by default / nothing to attach to — no-op, no cluster created.

    entities = extract_entities(
        clusters=clusters,
        slot_plan_product=slot_plan_product,
        web_finding_urls=[f.source_url for f in web_findings],
    )
    if not entities:
        return None

    window = SourceWindow(
        months=tuple(months),
        start=_month_to_dt(months[0]),
        end=_month_to_dt(months[-1], end_of_month=True),
    )

    measurements: dict[str, dict[str, float]] = {}
    error: str | None = None
    for provider in providers:
        try:
            got = provider.measure(entities=entities, window=window)
        except Exception as e:  # best-effort, like web_research
            error = f"{type(e).__name__}: {str(e)[:120]}"
            if "magnitude" not in stage_errors:
                stage_errors.append("magnitude")
            continue
        for entity, kinds in got.items():
            bucket = measurements.setdefault(entity, {})
            for kind, value in kinds.items():
                bucket[kind] = bucket.get(kind, 0.0) + float(value)

    if not measurements:
        return error

    changed = merge_magnitude_into_clusters(
        clusters,
        measurements,
        rescore=lambda breadth, signals: compute_demand_score(breadth, signals),
    )
    if changed:
        # A rescore can reorder; re-sort and re-band exactly like build_clusters
        # (the badge is relative to the report's breadth distribution).
        clusters.sort(key=lambda c: c.demand_score, reverse=True)
        population = [c.breadth_count for c in clusters]
        for i, c in enumerate(clusters, start=1):
            c.rank = i
            c.signal = signal_from_breadth(c.breadth_count, population)
    return error


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
    *,
    deps: ResearchDeps,
    report_id: str,
    brief: ResearchBrief,
    months: list[MonthRef],
    caveat: str,
    selection: SourceSelection | None = None,
) -> DemandReport:
    return DemandReport(
        report_id=report_id,
        client_id=brief.workspace_id,
        query=brief.question,
        fork=Fork.PRODUCT_PINNED,
        source=_source_label(deps, selection),
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
        source_selection=selection,
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

    # Brief-aware source selection (opt-in). With the selector disabled — the
    # default — ``selection`` stays ``None`` and every ``effective_sources(None)``
    # call below is byte-for-byte the prior configured/Reddit path. An explicit
    # ``deps.sources`` override still wins inside ``effective_sources``, so a
    # ``--source`` run is unaffected even with the selector on. The selector's own
    # non-removable floor guarantees ``selection.selected`` is never empty (it
    # falls back to ``reddit`` with a distinct caveat), so this can't yield an
    # empty corpus blamed on the picker.
    selection = _maybe_select_sources(deps, brief=brief)
    if selection is not None:
        for line in preflight_lines(selection):
            logger.info("source_selector: %s", line)

    # Effective subreddits: the LLM appends on-topic subs to the user's D5
    # list without mutating the persisted brief (immutability).
    effective_subs = pick_target_subreddits(deps, brief=brief)
    effective_brief = brief.model_copy(update={"target_subreddits": effective_subs})

    months = _window_months(deps, brief)

    deps.emit("pulling")
    items, records_by_id = _pull_corpus(
        deps, effective_brief, months=months, per_sub_limit=per_sub_limit, selection=selection
    )
    if not items:
        return _empty_report(
            deps=deps,
            report_id=report_id,
            brief=brief,
            months=months,
            caveat="No threads pulled from the brief's subreddits in the window.",
            selection=selection,
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

    # Hydration = INGEST the triage-relevant subset into the durable corpus:
    # the records (already pulled, just persist what survived triage) plus their
    # comments (the expensive per-link API fetch, run only on the relevant set).
    # This is the auto-ingest write path: on an empty corpus, a single
    # research() call leaves the relevant threads + quotes persisted as a side
    # effect — no separate ingest step.
    deps.emit("hydrating")
    stage_errors: list[str] = []
    post_ids = [it.post_id for it in relevant_items]
    relevant_records = [records_by_id[pid] for pid in post_ids if pid in records_by_id]
    ingest_records(deps.corpus, relevant_records)
    n_comments = 0
    any_comment_layer = False
    unit_source_ids: set[str] = set()
    for source in deps.effective_sources(selection):
        written, has_comments = ingest_comments_for(deps.corpus, source, post_ids)
        n_comments += written
        any_comment_layer = any_comment_layer or has_comments
        # A source OPTS IN to self-representing units (web): its records carry the
        # demand signal in their own text. This is an explicit flag, NOT inferred
        # from has_comments — a Reddit source with no comment client wired also
        # has no comments, but its posts are still comment-bearing, not units.
        if getattr(source, "yields_units", False):
            unit_source_ids.add(source.source_id)
    # Flag the unit-source records so synthesis promotes each to its own unit.
    # Idempotent re-upsert; only the (small) unit subset is rewritten.
    if unit_source_ids:
        unit_records = [
            r.model_copy(update={"extra": {**r.extra, "is_unit": True}})
            for r in relevant_records
            if r.source in unit_source_ids
        ]
        ingest_records(deps.corpus, unit_records)
    comments_error: str | None = None
    if not any_comment_layer:
        comments_error = "no comment source configured (deps.comments is None)"
        stage_errors.append("comment_hydration")
    elif int(getattr(deps.comments, "last_skipped", 0) or 0):
        # A source dropped links to upstream 5xx/429 — surface partial.
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

    # Lane-② magnitude overlay (issue #122). Deterministically extract measurable
    # entities from the already-grounded artifacts (cluster quote names, slot-plan
    # product, web-finding domains — NO LLM), call any active magnitude providers,
    # and merge their numbers into the matching clusters' demand_signals + rescore
    # (RANKING only). Best-effort, exactly like web research: a provider failure
    # degrades to partial + caveat, never aborts. A provider can NEVER create a
    # cluster — it only attaches to existing ones. Off by default (no providers).
    magnitude_error = _apply_magnitude_overlay(
        deps,
        slot_plan_product=(
            synthesis_out.slot_plan.product if synthesis_out.slot_plan is not None else None
        ),
        clusters=synthesis_out.ranked_clusters,
        web_findings=web_findings,
        months=months,
        stage_errors=stage_errors,
    )

    corpus_stats = _build_corpus_stats(relevant_items)
    exploration_report.threads_synthesized = synthesis_out.n_synthesized
    # Surface the near-dup merge rate (breadth-collapse observability, issue #82).
    exploration_report.dedup_merge_rate = synthesis_out.dedup_merge_rate

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
    if selection is not None and selection.caveat:
        # Surface the selector's floor / skipped-key caveat alongside stage
        # caveats so a reader sees WHY the source set is what it is.
        caveat_parts.append(selection.caveat)
    if web_error:
        caveat_parts.append(f"Web research failed: {web_error}")
    if magnitude_error:
        caveat_parts.append(f"Magnitude overlay failed: {magnitude_error}")
    if comments_error:
        caveat_parts.append(f"Comments unavailable: {comments_error}")
    if triangulation_error:
        caveat_parts.append(f"Triangulator failed: {triangulation_error}")
    is_partial = bool(stage_errors)
    if not is_partial:
        caveat_parts.append(
            f"Ingested {len(relevant_items)} relevant threads and "
            f"{n_comments} comments into the corpus."
        )
    caveat: str | None = " ".join(caveat_parts) if caveat_parts else None

    deps.emit("assembling")
    return DemandReport(
        report_id=report_id,
        lineage_id=report_id,  # v1: the lineage is rooted at this run
        client_id=brief.workspace_id,
        query=brief.question,
        fork=Fork.PRODUCT_PINNED,
        source=_source_label(deps, selection),
        date_range_start=_month_to_dt(months[0]),
        date_range_end=_month_to_dt(months[-1], end_of_month=True),
        total_threads=len(relevant_items),
        total_distinct_authors=synthesis_out.total_distinct_authors,
        ranked_clusters=ranked_clusters_final,
        partial=is_partial,
        caveat=caveat,
        created_by="library",
        generated_at=deps.clock(),
        demand_summary=synthesis_out.demand_summary,
        slot_plan=synthesis_out.slot_plan,
        audience_profile=synthesis_out.audience_profile,
        segments=synthesis_out.segments,
        candidate_wedges=synthesis_out.candidate_wedges,
        market_sizing=synthesis_out.market_sizing,
        price_finding=synthesis_out.price_finding,
        source_map=synthesis_out.source_map,
        brief=brief,
        web_findings=web_findings,
        corpus_stats=corpus_stats,
        corpus_shape=exploration_report,
        cross_references=cross_references,
        must_address_resolution=must_address_resolution,
        source_selection=selection,
    )


__all__ = ["run_research"]
