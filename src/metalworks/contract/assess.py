"""Assessment contract — the GO / PIVOT / NO-GO verdict.

``assess`` is a *gap function* over demand and landscape: is the pain real
(demand), can people already solve it (landscape), and is the gap big enough to
act (the decision). The **decision is deterministic** — computed from demand
strength x landscape saturation — so it is defensible and CI-testable; the LLM
only writes the human-facing ``rationale`` prose.

Three lanes, never two:
- **GO** — real demand, open landscape.
- **PIVOT** — real demand, but the obvious space is saturated; ``pivot_target``
  points at an under-served fork (a wedge or segment the report surfaced).
- **NO_GO** — thin demand, or saturated with no open fork.

Anti-confirmation rule: a ``partial`` landscape (grounding unavailable) can never
yield a hard GO — absence of evidence is not absence of competition.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef
from metalworks.contract.research import SignalStrength


class Decision(StrEnum):
    """The three-lane verdict. PIVOT is the high-value middle — neither ship nor kill."""

    GO = "go"
    PIVOT = "pivot"
    NO_GO = "no_go"


class GapAnalysis(BaseModel):
    """The computed gap the decision rests on — demand minus landscape."""

    demand_strength: SignalStrength = Field(description="From distinct-author breadth.")
    demand_summary: str = Field(description="The demand-strength sentence (from derive_verdict).")
    landscape_saturation: SignalStrength = Field(
        description="How crowded the supply is — competitors + existing solutions."
    )
    open_wedge: str | None = Field(
        default=None, description="The under-served fork's label, when one exists to pivot to."
    )
    reasoning: str = Field(
        default="", description="One line: why these signals imply the decision."
    )
    demand_prevalence: float = Field(
        default=0.0, description="Top fork's distinct authors as a fraction of the pull (0..1)."
    )
    demand_percentile: float | None = Field(
        default=None, description="Top fork's standing among peer forks (0..1); None if no peers."
    )
    confidence: float | None = Field(
        default=None, description="Distance from a band edge (0..1); None if uncomputed."
    )
    reference: str = Field(
        default="", description="What the strength self-calibrated against (e.g. 'top of 4 forks')."
    )


class PivotTarget(BaseModel):
    """Where to aim instead — a real fork id from the report (PIVOT only)."""

    kind: Literal["segment", "wedge"] = Field(description="Which kind of fork to pivot to.")
    target_id: str = Field(description="A real SegmentChoice / CandidateWedge id in the report.")
    why: str = Field(default="", description="Why this fork is the better bet.")


class ForkVerdict(BaseModel):
    """A per-fork GO/NO-GO — the verdict for ONE candidate wedge or segment.

    PIVOT is a report-level move *between* forks, so a single fork is only ever
    GO (real demand, open lane) or NO_GO. The list of these on an ``Assessment``
    is the un-collapsed answer: "GO on the sleep wedge, NO_GO on the broad market,
    GO on the enterprise segment" — instead of one flattened label.
    """

    kind: Literal["wedge", "segment"] = Field(description="Which kind of fork this scores.")
    fork_id: str = Field(description="A real CandidateWedge.id / SegmentChoice.id in the report.")
    label: str = Field(description="The fork's human label.")
    decision: Decision = Field(description="GO | NO_GO at the fork level.")
    demand_strength: SignalStrength = Field(description="Relative strength band for this fork.")
    landscape_saturation: SignalStrength = Field(
        description="Supply crowding (space-level for now — see ForkVerdict v2)."
    )
    demand_prevalence: float = Field(default=0.0, description="Fraction of the pull (0..1).")
    demand_percentile: float = Field(default=0.0, description="Standing among peer forks (0..1).")
    confidence: float = Field(default=0.0, description="Distance from a band edge (0..1).")
    distinct_author_count: int = Field(default=0)


class Assessment(BaseModel):
    """The GO / PIVOT / NO-GO verdict for one report, over its landscape.

    FKs to one report via ``report_id``; ``evidence`` resolves against that
    report. ``pivot_target`` is set iff ``decision == PIVOT``. ``partial`` carries
    the honesty signal (e.g. the landscape was partial, so GO was withheld).
    """

    assessment_id: str = Field(description="Stable id (derived from report_id).")
    report_id: str = Field(description="The DemandReport this verdict was computed from.")
    decision: Decision = Field(description="GO | PIVOT | NO_GO — deterministic from the gap.")
    rationale: str = Field(description="Human-facing argument for the decision (LLM prose).")
    gap: GapAnalysis = Field(description="The computed demand-vs-landscape gap.")
    pivot_target: PivotTarget | None = Field(
        default=None, description="Where to aim instead — set iff decision == PIVOT."
    )
    fork_verdicts: list[ForkVerdict] = Field(
        default_factory=list[ForkVerdict],
        description="Per-fork GO/NO-GO — the un-collapsed answer behind the top-line decision.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef], description="Backing forks for the verdict."
    )
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)
    generated_at: datetime

    @staticmethod
    def make_id(report_id: str) -> str:
        digest = hashlib.sha1(report_id.encode("utf-8")).hexdigest()[:12]
        return f"as:{digest}"
