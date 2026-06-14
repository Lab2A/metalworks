"""Positioning contract — the Pillar B (Market Positioning) output.

A :class:`PositioningBrief` turns a :class:`~metalworks.contract.research.DemandReport`'s
demand evidence into a defensible Dunford wedge (competitive alternative →
unique attribute → value → beachhead → category) plus a price hypothesis, with
every slot tracing back to upstream evidence by id (the same
:class:`~metalworks.contract.evidence.EvidenceRef` spine the demand report uses).

Honesty contract:
- Wedge SELECTION is deterministic, not LLM creativity — it stands on a real
  ``InsightCluster`` whose ``CrossReference.agreement`` is ``silent_web`` or
  ``disagree`` (a pain competitors miss), at ≥ MEDIUM signal. No such white
  space → ``wedge`` is ``None`` and ``partial`` is set (an honest null brief),
  never an invented angle.
- Only ``unique_attribute`` / ``value`` / ``market_category`` are LLM-authored,
  constrained to a Dunford template and verified for entailment against the
  cited quotes; if a clause isn't supported, the brief is marked ``partial`` and
  the caveat says so. The brief is a HYPOTHESIS, not a finding.
- ``PriceHypothesis`` copies ``PriceEvidence`` through (Van-Westendorp PMC/PME
  framing); it is never recomputed here.

This is the stable shape ``Metalworks().research(...).positioning`` exposes once
Pillar B has run; the demand report's evidence list is what its
``EvidenceRef``s resolve against.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef


class WedgeClaim(BaseModel):
    """A Dunford positioning wedge, every slot backed by upstream evidence.

    ``competitive_alternative`` is drawn from real ``WebFinding``s (what the
    market offers today); ``unique_attribute`` / ``value`` / ``market_category``
    are LLM-phrased over the white-space cluster and entailment-verified;
    ``beachhead`` is the narrow first audience. ``source_cluster_rank`` is the
    1-based ``InsightCluster.rank`` the wedge stands on (a silent_web/disagree
    cluster). ``evidence`` collates the refs (cluster quotes + web findings) that
    back the claim — all resolvable against the source report's ``evidence``.
    """

    competitive_alternative: str = Field(
        description="What the beachhead audience uses today, from real web findings."
    )
    unique_attribute: str = Field(
        description="What this product does differently — the white space competitors miss."
    )
    value: str = Field(description="Why that attribute matters to the audience.")
    beachhead: str = Field(description="The narrow first audience to win.")
    market_category: str = Field(description="The frame of reference the product competes in.")
    source_cluster_rank: int = Field(
        description="1-based InsightCluster.rank the wedge stands on (silent_web/disagree)."
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Refs (cluster quotes + web findings) backing the wedge.",
    )


class PriceHypothesis(BaseModel):
    """A price band copied through from the report's ``PriceEvidence``.

    Never recomputed — this is the demand report's ``PriceFinding`` reframed for
    positioning (Van-Westendorp PMC/PME language). ``insufficient_signal`` mirrors
    the source when there isn't enough price talk to recommend a band.
    """

    low: float | None = Field(default=None, description="Low end of the willingness-to-pay band.")
    high: float | None = Field(default=None, description="High end of the band.")
    currency: str = Field(default="USD")
    framing: str = Field(
        default="",
        description="One-line PMC/PME framing of how the band was derived (from price evidence).",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef], description="Refs to the PriceEvidence backing the band."
    )
    insufficient_signal: bool = Field(default=False)


class PositioningBrief(BaseModel):
    """Pillar B output — a grounded positioning hypothesis for one report.

    FKs to exactly one report via ``report_id``; every ``EvidenceRef`` it carries
    resolves against THAT report's ``evidence``. ``partial`` + ``caveat`` carry
    the honesty signal: an absent wedge (no white space) or an unverified clause
    both set ``partial`` and explain why in ``caveat``.
    """

    report_id: str = Field(description="The DemandReport this brief was derived from.")
    positioning_statement: str = Field(
        description="The assembled Dunford statement (or an honest null when no wedge)."
    )
    wedge: WedgeClaim | None = Field(
        default=None, description="The wedge; None when no white-space cluster qualifies."
    )
    price_hypothesis: PriceHypothesis | None = Field(
        default=None, description="Price band copied through from the report; None if absent."
    )
    partial: bool = Field(
        default=False, description="True when the wedge is absent or a clause failed verification."
    )
    caveat: str | None = Field(
        default=None, description="Why the brief is partial / what to treat as unconfirmed."
    )
