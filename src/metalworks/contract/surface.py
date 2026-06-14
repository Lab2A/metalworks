"""Surface + UX contract — the Pillar C (Design stage) output.

Two artifacts turn the grounded demand + positioning into a product shape:

- :class:`SurfaceRecommendation` — an opinionated pick of the surface to build
  (sdk / web / mobile / cli / browser-extension / ...), a runner-up, and the
  trade-offs, driven by a FIXED rubric. Each rubric dimension cites at least one
  :class:`~metalworks.contract.evidence.EvidenceRef` or is explicitly marked an
  ``assumption`` — the LLM only phrases the rationale, it never invents the
  decision or the evidence.
- :class:`UxSkeleton` — a 3-5 screen skeleton. Each screen names its purpose +
  primary action and either cites the voices asking for it (``validated``) or is
  flagged ``validated=False`` (an unvalidated hypothesis). No pixels — text and
  structure only.

Grounding honesty (this is the highest-risk pillar): the DECISION layer grounds
(rubric dimensions resolve against real evidence); the aesthetic layer cannot, so
:class:`DesignBrief` is explicitly labelled craft-convention / ungrounded and is
a handoff to the design-consultation / ``DESIGN.md`` step, not a grounded claim.
On thin signal the recommendation drops to a labelled hypothesis (``partial``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef
from metalworks.contract.research import SignalStrength

SurfaceKind = Literal["sdk", "web", "mobile", "cli", "browser_extension", "api", "desktop"]

# The fixed rubric dimensions — service-defined, never invented by the model.
RubricName = Literal[
    "where_are_the_users",
    "technical_sophistication",
    "usage_frequency",
    "realtime_or_hardware",
    "distribution",
]


class RubricDimension(BaseModel):
    """One fixed rubric dimension, grounded or explicitly an assumption."""

    name: RubricName = Field(description="The fixed rubric dimension.")
    finding: str = Field(description="What the evidence says for this dimension (LLM-phrased).")
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Refs backing the finding. Empty iff is_assumption is True.",
    )
    is_assumption: bool = Field(
        default=False, description="True when no evidence backs this dimension — a stated guess."
    )


class TradeOff(BaseModel):
    """A trade-off of the chosen surface, cited where the evidence supports it."""

    text: str = Field(description="The trade-off, one clause.")
    evidence_refs: list[EvidenceRef] = Field(default_factory=list[EvidenceRef])


class SurfaceRecommendation(BaseModel):
    """Pillar C output — the grounded surface decision for one report.

    FKs to one report via ``report_id``. ``confidence`` is service-assigned from
    how many rubric dimensions are actually grounded (not LLM-claimed).
    """

    report_id: str
    chosen: SurfaceKind = Field(description="The recommended surface to build.")
    runner_up: SurfaceKind | None = Field(default=None, description="The second-best surface.")
    rationale: str = Field(description="Why this surface, in one short paragraph (LLM-phrased).")
    rubric: list[RubricDimension] = Field(default_factory=list[RubricDimension])
    trade_offs: list[TradeOff] = Field(default_factory=list[TradeOff])
    confidence: SignalStrength = Field(
        default=SignalStrength.LOW, description="Service-assigned from grounded rubric coverage."
    )
    generated_at: datetime
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)


class Screen(BaseModel):
    """One screen in the UX skeleton. ``validated`` iff a real voice asked for it."""

    name: str = Field(description="Screen name.")
    purpose: str = Field(description="What this screen is for, one line.")
    primary_action: str = Field(description="The single primary action on this screen.")
    serves_wedge: bool = Field(
        default=False, description="True when this screen directly serves the positioning wedge."
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Voices asking for this screen. Empty → an unvalidated hypothesis.",
    )
    validated: bool = Field(
        default=False, description="True iff at least one evidence_ref backs the screen."
    )


class UxSkeleton(BaseModel):
    """Pillar C output — a 3-5 screen UX skeleton for the chosen surface."""

    report_id: str
    surface: SurfaceKind
    screens: list[Screen] = Field(default_factory=list[Screen])
    generated_at: datetime
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)


class DesignBrief(BaseModel):
    """An UNGROUNDED craft handoff to the design-consultation / DESIGN.md step.

    Deliberately not evidence-backed — aesthetics are craft convention, not a
    grounded claim. ``note`` always carries that disclaimer so a consumer never
    mistakes it for a finding.
    """

    report_id: str
    summary: str = Field(description="A short brief for the design step (tone, surface, audience).")
    note: str = Field(
        default="craft-convention, ungrounded — hand to design-consultation / DESIGN.md.",
        description="Always present: this brief is NOT evidence-backed.",
    )
