"""Refreshing a report — the live-view re-synthesis.

A :class:`~metalworks.contract.DemandReport` is a view over the corpus, not a
frozen artifact. ``refresh_report`` re-runs the prior report's brief against the
*current* state of the corpus + sources and pins the result as a **new version**
in the same lineage, returning it alongside a
:class:`~metalworks.contract.ReportDiff` from the prior version.

What "against the current corpus" means in practice: re-running the brief pulls
each enabled source again and auto-ingests into the durable corpus (idempotent),
so a refresh naturally reflects corpus growth — a newly enabled source, freshly
ingested material, a wider window. The prior version stays frozen on disk (its
citations are materialized inline, self-contained), so "what did I ship against"
is never lost; the refresh only ever appends a version.

This is the orchestration seam; persistence (store / project ``runs/``) is the
caller's job (the CLI and facade), exactly as for a first run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.research.diff import diff_reports
from metalworks.research.pipeline import run_research

if TYPE_CHECKING:
    from metalworks.contract import DemandReport, ReportDiff
    from metalworks.research.deps import ResearchDeps


def refresh_report(
    deps: ResearchDeps,
    prior: DemandReport,
    *,
    per_sub_limit: int | None = None,
    max_findings: int = 10,
) -> tuple[DemandReport, ReportDiff]:
    """Re-synthesize ``prior``'s brief against the current corpus.

    Returns ``(new_version, diff)`` where ``new_version`` is pinned as
    ``prior.version + 1`` in ``prior``'s lineage with ``parent_report_id`` set,
    and ``diff`` is the change from ``prior`` to it.

    Raises ``ValueError`` if ``prior`` carries no brief (a pre-brief report can't
    be re-run — there is nothing to re-synthesize from).
    """
    if prior.brief is None:
        raise ValueError(
            "Cannot refresh a report with no brief — re-run `research run` to "
            "create a fresh lineage instead."
        )

    fresh = run_research(
        deps, brief=prior.brief, per_sub_limit=per_sub_limit, max_findings=max_findings
    )
    new_version = fresh.model_copy(
        update={
            "lineage_id": prior.effective_lineage_id,
            "version": prior.version + 1,
            "parent_report_id": prior.report_id,
        }
    )
    diff = diff_reports(prior, new_version, embeddings=deps.embeddings)
    return new_version, diff


__all__ = ["refresh_report"]
