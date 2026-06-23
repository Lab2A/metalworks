"""Build contract — the Pillar D (Build stage) output.

A :class:`BuildSpec` turns a grounded :class:`~metalworks.contract.research.DemandReport`
(+ positioning + surface) into a runnable SPEC for the user's OWN Claude Code to
build against — metalworks is NOT a coding agent. Every product/persona/pricing
claim traces to a real Reddit voice by :class:`~metalworks.contract.evidence.EvidenceRef`;
the scaffold's ``cite-or-die`` rule rejects un-cited claims at the SPEC/feature/
copy level (NOT per line of generated code — that would be traceability theater).

Honesty contract:
- Each :class:`FeatureSpec` carries at least one RESOLVABLE ``EvidenceRef`` — the
  LLM cluster→feature mapping can hallucinate a feature, so one with no resolvable
  evidence is dropped at assembly (no-cite-no-feature).
- ``PricingTier`` copies the report's price evidence through (never recomputes);
  ``BuildPersona`` is grounded in the audience/segment evidence.
- ``partial`` / ``caveat`` carry the honesty signal when grounding is thin.

Personas here are :class:`BuildPersona` (the ICP for the product), distinct from
``metalworks.contract.Persona`` (a Reddit posting voice).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from metalworks.contract.distribution import (
    ConversionSurfaceRequirement,
    LoopRequirement,
)
from metalworks.contract.evidence import EvidenceRef
from metalworks.contract.surface import Screen, SurfaceKind


class FeatureSpec(BaseModel):
    """One product feature, derived from a demand cluster and evidence-backed."""

    feature_id: str = Field(description="Stable slug for the feature (e.g. 'fade-tracker').")
    title: str = Field(description="The feature, in a few words.")
    rationale: str = Field(description="Why this feature — what consumer pain it serves.")
    evidence: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="≥1 resolvable ref backing the feature. Empty → dropped at assembly.",
    )
    source_cluster_rank: int = Field(
        default=0,
        description=(
            "1-based rank of the demand cluster this feature derives from (1 = strongest "
            "validated demand). Features in a BuildSpec are ordered by this — the build order "
            "is grounded in demand, not LLM whim; the lead feature is the spine to build first. "
            "0 means unranked (sorts last)."
        ),
    )


class BuildPersona(BaseModel):
    """The product's ICP, grounded in the audience evidence (not a Reddit voice)."""

    name: str = Field(description="Short persona label.")
    description: str = Field(description="Who they are + what they want, one or two lines.")
    evidence: list[EvidenceRef] = Field(default_factory=list[EvidenceRef])


class PricingTier(BaseModel):
    """One pricing tier, copied through from the report's price evidence."""

    name: str = Field(description="Tier name (e.g. 'Starter').")
    price: float | None = Field(default=None, description="Monthly price; None when unpriced.")
    currency: str = Field(default="USD")
    rationale: str = Field(description="What the tier includes / why this price.")
    evidence: list[EvidenceRef] = Field(default_factory=list[EvidenceRef])


class BuildSpec(BaseModel):
    """Pillar D output — an evidence-grounded build spec for one report.

    FKs to one report via ``report_id``; every ``EvidenceRef`` resolves against
    that report's ``evidence``. ``stack`` is the chosen starter (e.g.
    ``next-shipfast`` / ``empty``) — a hint for the build, not vendored code.
    """

    spec_id: str = Field(description="Stable id for this spec (derived from report_id).")
    report_id: str
    surface: SurfaceKind = Field(description="The surface this build targets.")
    stack: str = Field(description="The chosen starter/stack hint (e.g. 'next-shipfast', 'empty').")
    features: list[FeatureSpec] = Field(
        default_factory=list[FeatureSpec],
        description=(
            "Core features, ordered as the build order: strongest validated demand first "
            "(by ``FeatureSpec.source_cluster_rank``). features[0] is the spine — build it first."
        ),
    )
    surface_rationale: str | None = Field(
        default=None,
        description=(
            "One line on why this surface, set when the surface was chosen automatically "
            "(``surface='auto'``). None when the surface was pinned by the caller."
        ),
    )
    personas: list[BuildPersona] = Field(default_factory=list[BuildPersona])
    pricing_tiers: list[PricingTier] = Field(default_factory=list[PricingTier])
    screens: list[Screen] = Field(
        default_factory=list[Screen],
        description=(
            "The build's UX skeleton, sketched AFTER the features so each screen maps to real "
            "``feature_id``s. Shell screens (auth/settings) are flagged ``scaffolding``."
        ),
    )
    loop_requirements: list[LoopRequirement] = Field(
        default_factory=list[LoopRequirement],
        description=(
            "Distribution-driven build requirements (D3): one entry per selected embedded-loop "
            "channel — the build face of a designed-in loop (watermark ⇒ public share-URLs + "
            "branded viewer + badge-gating; UGC-SEO ⇒ SSR pages + sitemap; …). Empty when "
            "distribution requirements weren't supplied or no loop channel was selected."
        ),
    )
    conversion_surface_requirements: list[ConversionSurfaceRequirement] = Field(
        default_factory=list[ConversionSurfaceRequirement],
        description=(
            "Distribution-driven build requirements (D3): the conversion destination the "
            "channels point at (its funnel job + what it must ship) — the build must include a "
            "place to convert. Empty when distribution requirements weren't supplied."
        ),
    )
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)
