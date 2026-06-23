"""D5 — data-as-marketing: a corpus-derived original-research data report.

The on-brand flagship asset of the Distribution pillar. It projects a finished
:class:`~metalworks.contract.research.DemandReport` into a publishable,
methodology-first :class:`~metalworks.contract.distribution.DataReportAsset` — a
*ranking* (the top AI-cited format) over a proprietary Reddit corpus (the #1
AI-cited domain), every row carrying verbatim quotes + real permalinks + the
cluster's REAL distinct-author / mention counts. It stacks every AI-citation
driver at once: original research + a ranking + verbatim quotes + permalinks. The
defensibility is the corpus others can't reproduce; the credibility is the
disclosed method.

Honesty is the WHOLE point — the survey-fabrication base rate is the trap to
avoid, so rigor IS the credibility:

- The ranking is DETERMINISTIC. Items are the report's own ``ranked_clusters``,
  in their own order, carrying their own ``rank`` / ``distinct_author_count`` /
  ``mention_count`` — never re-scored, never invented.
- ``permalinks`` are the real ``source_url``s of each cluster's verified quotes;
  ``quote`` is one verbatim quote from the cluster, exact text.
- ``methodology`` discloses the real base: N threads, distinct-author counting,
  the corpus date range.
- The LLM writes ONLY the report ``title`` and each item's ``label`` prose,
  grounded in that cluster's claim. On any LLM failure it falls back to the
  cluster's claim verbatim — the numbers, links, and quotes still ship.

``build_data_asset(deps, report, kind)`` is the reusable core the four surfaces
call. The three ``kind``s differ only in framing/label (``complaint_index`` =
pain points, ``feature_ranking`` = requested features, ``state_of`` = the overall
state) — all project the same grounded cluster data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from metalworks.contract import (
    DataReportAsset,
    DataReportItem,
    DemandReport,
)

if TYPE_CHECKING:
    from metalworks.contract.research import InsightCluster
    from metalworks.research.deps import ResearchDeps

DataReportKind = Literal["complaint_index", "feature_ranking", "state_of"]

# Per-kind framing — drives the LLM prompt and the deterministic fallback label.
_KIND_FRAMING: dict[DataReportKind, str] = {
    "complaint_index": "a complaint index — each row is a PAIN POINT consumers raised",
    "feature_ranking": "a feature ranking — each row is a FEATURE / capability consumers asked for",
    "state_of": "a state-of-the-category report — each row is a THEME of what consumers want/feel",
}
_KIND_NOUN: dict[DataReportKind, str] = {
    "complaint_index": "complaints",
    "feature_ranking": "requested features",
    "state_of": "themes",
}


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _ItemLabel(BaseModel):
    """One framed headline for a single cluster row (LLM-written prose only)."""

    rank: int = Field(description="The cluster rank this label is for (echo back to match).")
    label: str = Field(
        description="A tight headline for this row, framed to the report kind. Grounded in the "
        "cluster's claim — do not invent a complaint/feature the claim doesn't support."
    )


class _ReportProse(BaseModel):
    """The only authored prose: the report title + one framed label per cluster."""

    title: str = Field(
        description="A sharp, specific report headline grounded in the category + kind. "
        "No hype, no invented numbers."
    )
    labels: list[_ItemLabel] = Field(
        description="One framed label per ranked cluster, by rank.",
        default_factory=list["_ItemLabel"],
    )


# ── Deterministic projection ─────────────────────────────────────────────────


def _permalinks_for(cluster: InsightCluster) -> list[str]:
    """The real provenance links for a cluster — its quotes' source_urls, deduped.

    Preserves first-seen order, drops empties. Never invented — these are the
    exact links the quote-verification gate already validated.
    """
    seen: dict[str, None] = {}
    for q in cluster.quotes:
        url = q.source_url.strip()
        if url and url not in seen:
            seen[url] = None
    return list(seen.keys())


def _supporting_quote(cluster: InsightCluster) -> str:
    """One verbatim supporting quote from the cluster — exact text, never paraphrased."""
    for q in cluster.quotes:
        if q.text.strip():
            return q.text
    return ""


def _fallback_label(cluster: InsightCluster, kind: DataReportKind) -> str:
    """Honest deterministic label when the LLM prose is unavailable — the claim itself."""
    _ = kind  # framing handled by the prose pass; the claim is the honest fallback either way.
    return cluster.claim


def _methodology(report: DemandReport, n_items: int, kind: DataReportKind) -> str:
    """The disclosed honest base: real thread count, distinct-author method, date range.

    Every number here is read straight off the report — the rigor that IS the
    credibility. No claim the corpus doesn't back.
    """
    start = report.date_range_start.date().isoformat()
    end = report.date_range_end.date().isoformat()
    noun = _KIND_NOUN[kind]
    return (
        f"Method: we analyzed {report.total_threads} Reddit threads "
        f"({report.total_distinct_authors} distinct authors) discussing "
        f'"{report.query}", from {start} to {end}. The top {n_items} {noun} below are ranked '
        "by demand — distinct-author breadth weighted above single-post virality, so a theme "
        "raised by many people outranks one viral post. 'Distinct authors' counts unique "
        "accounts (the honest base rate); 'mentions' counts total raised. Every row links to the "
        "real threads and carries a verbatim quote — no survey, no extrapolation, no invented "
        "numbers. The numbers and links are reproducible from the cited permalinks."
    )


# ── LLM prose pass (private, best-effort) ────────────────────────────────────


def _write_prose(
    deps: ResearchDeps,
    report: DemandReport,
    clusters: list[InsightCluster],
    kind: DataReportKind,
) -> _ReportProse | None:
    """Best-effort: the LLM writes the title + one framed label per cluster.

    Grounded strictly in each cluster's claim — the prompt forbids inventing a
    complaint/feature the claim doesn't support. Returns ``None`` on any failure;
    the caller then falls back to the claim verbatim (the numbers still ship).
    """
    framing = _KIND_FRAMING[kind]
    rows = "\n".join(
        f"- rank {c.rank}: {c.claim}  "
        f"[{c.distinct_author_count} authors, {c.mention_count} mentions]"
        for c in clusters
    )
    system = (
        "You write the prose for a methodology-first data report built from real Reddit "
        "discussion. You write ONLY a report title and one short headline ('label') per ranked "
        "row, grounded strictly in that row's claim. You do NOT invent numbers, you do NOT invent "
        "a complaint or feature the claim doesn't support, and you do NOT editorialize beyond the "
        "evidence. Rigor is the credibility — keep every label faithful to its claim."
    )
    user = (
        f'Category / demand query: "{report.query}"\n'
        f"This report is {framing}.\n\n"
        "Ranked rows (rank, the synthesized claim, and its real counts):\n"
        f"{rows}\n\n"
        "Write a sharp, specific title for the report, and one tight label per rank — each label "
        "a faithful headline for that row's claim, framed to the report kind. Echo each rank back "
        "so labels match rows. No hype, no invented numbers."
    )
    try:
        return deps.chat.complete_structured(
            system=system,
            user=user,
            output_model=_ReportProse,
            max_tokens=1024,
            temperature=0.2,
        )
    except Exception:
        return None


# ── Public entry point ───────────────────────────────────────────────────────


def build_data_asset(
    deps: ResearchDeps,
    report: DemandReport,
    kind: DataReportKind = "complaint_index",
) -> DataReportAsset:
    """Project a demand report into a corpus-derived :class:`DataReportAsset`.

    DETERMINISTIC ranking: the items ARE the report's ranked clusters, in their
    own order, carrying their own ``rank`` / distinct-author / mention counts and
    real permalinks + a verbatim quote — never re-scored, never invented. The LLM
    only writes the report ``title`` and each item's ``label`` prose, grounded in
    the cluster's claim; on failure each label falls back to the claim verbatim.
    ``methodology`` discloses the real base (N threads, distinct-author counting,
    date range). The three ``kind``s differ only in framing/label.
    """
    clusters = list(report.ranked_clusters)

    prose = _write_prose(deps, report, clusters, kind) if clusters else None
    labels_by_rank: dict[int, str] = {}
    title = ""
    if prose is not None:
        title = prose.title.strip()
        labels_by_rank = {lbl.rank: lbl.label.strip() for lbl in prose.labels if lbl.label.strip()}
    if not title:
        title = f"{report.query}: {_KIND_NOUN[kind]} ranked from {report.total_threads} threads"

    items: list[DataReportItem] = []
    for cluster in clusters:
        items.append(
            DataReportItem(
                rank=cluster.rank,
                label=labels_by_rank.get(cluster.rank) or _fallback_label(cluster, kind),
                # Counts copied straight from the cluster — the honest base, never invented.
                distinct_authors=cluster.distinct_author_count,
                mentions=cluster.mention_count,
                permalinks=_permalinks_for(cluster),
                quote=_supporting_quote(cluster),
            )
        )

    return DataReportAsset(
        report_id=report.report_id,
        kind=kind,
        title=title,
        items=items,
        methodology=_methodology(report, len(items), kind),
    )
