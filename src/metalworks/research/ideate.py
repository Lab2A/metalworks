"""Ideation — the front of the validate loop, two entry points.

``ideate_from_idea(deps, idea_text)`` (idea-first) sharpens a raw idea into a
testable hypothesis and attaches a ``ResearchBrief`` to run demand on.
``ideate_from_report(deps, report)`` (evidence-first) surfaces an existing
report's forks — its candidate wedges, else top clusters — as grounded
:class:`IdeaSketch`es to pick from.

Both are best-effort and corpus-light: idea-first does one structured LLM call
(falling back to the raw idea as the hypothesis); evidence-first is a pure,
deterministic transform over a report. Neither decides anything — they frame the
idea handed to demand + landscape + assess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import DemandReport, EvidenceRef
from metalworks.contract.ideate import IdeaSketch, IdeationResult
from metalworks.errors import StructuredOutputError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metalworks.research.deps import ResearchDeps

_MAX_SKETCHES = 4
_MAX_TOKENS = 1024


class _IdeaExtract(BaseModel):
    hypothesis: str = Field(description="The core wedge/segment hypothesis, one sentence.")
    pain: str = Field(default="", description="The specific pain it addresses.")
    target_segment_hint: str = Field(default="", description="Who it's for, if discernible.")


def ideate_from_idea(
    deps: ResearchDeps, idea_text: str, *, subreddits: Sequence[str] | None = None
) -> IdeaSketch:
    """Idea-first: sharpen a raw idea into a hypothesis + a brief to test it.

    One structured call extracts the hypothesis / pain / who-it's-for; a
    ``ResearchBrief`` is built from the idea so demand can run next. Degrades to
    the raw idea as its own hypothesis only when the model *declines* (no
    schema-valid output); an infra error (auth/network/quota) propagates so the
    caller sees a real failure rather than a silently-thinned hypothesis.
    """
    system = (
        "You are a startup advisor. Sharpen a raw product idea into ONE testable "
        "hypothesis sentence, name the specific pain it addresses, and who it's for "
        "if discernible. Be concrete; do not invent demand evidence — this is a hypothesis."
    )
    try:
        ex = deps.chat.complete_structured(
            system=system, user=idea_text, output_model=_IdeaExtract, max_tokens=_MAX_TOKENS
        )
    except StructuredOutputError:
        # Model declined / produced nothing schema-valid → degrade to the raw idea.
        # Infra errors are NOT caught here: they propagate.
        ex = _IdeaExtract(hypothesis=idea_text)

    brief = None
    caveat = None
    try:
        from metalworks.research.planner import brief_or_question

        brief = brief_or_question(deps, None, idea_text, subreddits=subreddits)
    except StructuredOutputError:
        # The brief-builder's own model call declined → honest partial. Infra
        # errors propagate.
        caveat = "Could not build a research brief automatically — pass subreddits or plan one."

    return IdeaSketch(
        idea=idea_text,
        hypothesis=ex.hypothesis or idea_text,
        pain=ex.pain,
        target_segment_hint=ex.target_segment_hint,
        provenance="idea-first",
        brief=brief,
        partial=brief is None,
        caveat=caveat,
    )


def ideate_from_report(deps: ResearchDeps, report: DemandReport) -> IdeationResult:
    """Evidence-first: surface an existing report's forks as grounded sketches.

    Prefers the decision-bearing candidate wedges (PR1) when present; otherwise
    falls back to the top demand clusters. Each sketch carries the fork's own
    evidence — no guessing. A report with no forks yields an empty, ``partial``
    result.

    A thin, order-preserving pass-through: ``candidate_wedges`` already arrives
    ranked from ``synthesis/wedges`` and ``ranked_clusters`` from the cluster
    ranker, so this re-projects them as :class:`IdeaSketch`es without re-sorting
    (one ranking source). It emits no ``hypothesis``: a wedge's grounded
    ``rationale`` becomes the hypothesis when present, otherwise the field is
    left empty — never a templated Mad-Lib dressed as analysis.
    """
    _ = deps  # deterministic transform; deps kept for signature symmetry
    sketches: list[IdeaSketch] = []

    if report.candidate_wedges:
        for w in report.candidate_wedges[:_MAX_SKETCHES]:
            sketches.append(
                IdeaSketch(
                    idea=w.label,
                    hypothesis=w.rationale,
                    pain=w.pain,
                    provenance="evidence-first",
                    evidence=list(w.evidence),
                )
            )
    else:
        for c in report.ranked_clusters[:_MAX_SKETCHES]:
            sketches.append(
                IdeaSketch(
                    idea=c.claim,
                    hypothesis="",
                    pain=c.claim,
                    provenance="evidence-first",
                    evidence=[EvidenceRef(kind="cluster", cluster_rank=c.rank)],
                )
            )

    return IdeationResult(
        report_id=report.report_id,
        sketches=sketches,
        partial=not sketches,
        caveat=None if sketches else "No forks to surface — the report has no clusters yet.",
    )
