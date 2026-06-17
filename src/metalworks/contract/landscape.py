"""Competitive-landscape contract — the Pillar A (Landscape) output.

A :class:`CompetitorMap` enumerates the real competitive set for an idea —
direct, adjacent, and the April-Dunford **status-quo "do nothing"** alternative —
and attaches to each competitor what it does well plus an exploitable gap backed
by a cited complaint. The discipline is **no-quote-no-gap**: every
:class:`GapClaim` carries exactly one :class:`~metalworks.contract.evidence.EvidenceRef`
that resolves against the source report's evidence (a verbatim
``ResolvedCitation`` when a real complaint matches the gap, else a grounded
``WebFinding``); a gap with no resolvable evidence is dropped at assembly.

Honesty contract:
- ``severity`` is SERVICE-assigned (from the distinct-author breadth of the
  matched complaint, or the web finding's confidence) — never LLM flourish.
- The status-quo alternative is MANDATORY: the cost of doing nothing is the
  report's strongest pains, each backed verbatim by the cluster's own quote.
- Named-competitor gaps are asymmetric: cluster-matched gaps inherit verbatim
  quotes (high trust); web-matched gaps are ``grounded-web`` (medium). The
  provenance label lives on the resolved ``EvidenceRecord``, not invented here.

This is the stable shape ``Metalworks().research(...).competitors`` exposes once
Pillar A has run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef
from metalworks.contract.research import SignalStrength

CompetitorKind = Literal["direct", "adjacent", "status_quo"]


class StrengthClaim(BaseModel):
    """One thing a competitor does well. Evidence optional (often web-sourced)."""

    claim: str = Field(description="A concrete strength, one clause.")
    evidence: EvidenceRef | None = Field(
        default=None, description="A WebFinding ref backing the strength, when one matched."
    )


class GapClaim(BaseModel):
    """An exploitable gap, backed by exactly one resolvable piece of evidence.

    ``severity`` is service-assigned (complaint breadth or web confidence), never
    LLM-authored. ``evidence`` resolves against the source report's evidence —
    a ``ResolvedCitation`` (verbatim complaint) or a ``WebFinding`` (grounded-web).
    """

    gap_index: int = Field(description="1-based index within the competitor's gaps.")
    claim: str = Field(description="The gap, phrased as what the competitor misses.")
    severity: SignalStrength = Field(description="Service-assigned, never LLM.")
    evidence: EvidenceRef = Field(description="The single resolvable ref backing this gap.")


class Competitor(BaseModel):
    """One competitor in the map, with strengths and evidenced gaps."""

    competitor_index: int = Field(description="1-based index within the map.")
    name: str = Field(description="The competitor / alternative name.")
    kind: CompetitorKind = Field(description="direct | adjacent | status_quo.")
    one_liner: str = Field(description="What it is, in one line.")
    strengths: list[StrengthClaim] = Field(default_factory=list[StrengthClaim])
    gaps: list[GapClaim] = Field(default_factory=list[GapClaim])
    addresses_clusters: list[int] = Field(
        default_factory=list[int],
        description="Demand-cluster ranks this competitor speaks to (gap-matched + mentioned). "
        "Powers per-fork saturation — which wedge/segment this rival actually competes for.",
    )


class CompetitorMap(BaseModel):
    """Pillar A output — the grounded competitive landscape for one report.

    FKs to one report via ``report_id``; every ``EvidenceRef`` resolves against
    that report's evidence. ``status_quo_alternative`` is always present (the
    cost of doing nothing). ``partial`` / ``caveat`` carry the honesty signal
    (e.g. enumeration degraded to ungrounded, or no competitors surfaced).
    """

    map_id: str = Field(description="Stable id for this map (derived from report_id).")
    report_id: str = Field(description="The DemandReport this map was derived from.")
    competitors: list[Competitor] = Field(default_factory=list[Competitor])
    status_quo_alternative: Competitor = Field(
        description="The mandatory 'do nothing' alternative (kind=status_quo)."
    )
    generated_at: datetime
    partial: bool = Field(default=False, description="True when a stage degraded.")
    caveat: str | None = Field(default=None, description="What to treat as lower-confidence.")


class ExistingSolution(BaseModel):
    """One real shipped product in the space, matched to a demand cluster.

    The EMPIRICAL counterpart to the LLM-enumerated competitors: pulled from a
    product source (Product Hunt launches; web) and kept only when its pitch maps
    to a real demand cluster — grounded, not guessed. ``traction`` is the
    source-native signal (e.g. PH votes); ``evidence`` resolves against the
    cluster it speaks to (a ``cluster`` ref), so a solution with no cluster match
    is dropped at assembly.
    """

    name: str = Field(description="The product name.")
    url: str = Field(default="", description="Resolvable link to the product.")
    tagline: str = Field(default="", description="The product's one-line pitch, when available.")
    traction: int = Field(default=0, description="Source-native traction signal (e.g. PH votes).")
    source: str = Field(default="producthunt", description="Where it was found: producthunt | web.")
    addresses_clusters: list[int] = Field(
        default_factory=list[int], description="Demand-cluster ranks this product speaks to."
    )
    evidence: EvidenceRef = Field(description="The cluster ref this product was matched against.")


class Landscape(BaseModel):
    """Pillar A (thick) — the full 'what exists today' for one report.

    Wraps the grounded :class:`CompetitorMap` (direct / adjacent rivals + the
    mandatory status-quo 'do nothing' cost) and ADDS an empirical
    ``existing_solutions`` scan: real shipped products, with traction, each mapped
    to a demand cluster. ``competitors()`` stays the lean map; this is the
    surface ``assess()`` consumes. ``partial`` is true when either half degraded
    (ungrounded enumeration, or no product source / token).
    """

    landscape_id: str = Field(description="Stable id for this landscape (derived from report_id).")
    report_id: str = Field(description="The DemandReport this landscape was derived from.")
    competitor_map: CompetitorMap = Field(
        description="The grounded competitor map (Pillar A core)."
    )
    existing_solutions: list[ExistingSolution] = Field(
        default_factory=list[ExistingSolution],
        description="Real shipped products, grounded to demand clusters.",
    )
    generated_at: datetime
    partial: bool = Field(default=False, description="True when either half degraded.")
    caveat: str | None = Field(default=None, description="What to treat as lower-confidence.")
