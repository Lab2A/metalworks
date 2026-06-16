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


class PivotTarget(BaseModel):
    """Where to aim instead — a real fork id from the report (PIVOT only)."""

    kind: Literal["segment", "wedge"] = Field(description="Which kind of fork to pivot to.")
    target_id: str = Field(description="A real SegmentChoice / CandidateWedge id in the report.")
    why: str = Field(default="", description="Why this fork is the better bet.")


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
