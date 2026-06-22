"""Surface + screen contract — the product-shape primitives the build spec owns.

The surface decision (sdk / web / mobile / cli / browser-extension / ...) and the
screen skeleton are no longer a standalone pillar: :func:`metalworks.build.spec.
build_spec_from_report` chooses the surface alongside the features it grounds and
sketches the screens AFTER the feature list exists, so each :class:`Screen` maps
to real ``feature_id``s rather than being blind to what gets built.

This module keeps the two shared value types:

- :data:`SurfaceKind` — the closed set of surfaces a build can target.
- :class:`Screen` — one screen in the build's UX skeleton, mapped to the
  feature ids it serves and either citing the voices that asked for it
  (``validated``) or flagged ``scaffolding`` (auth/settings shells — not a
  hypothesis to test).

:class:`DesignBrief` is an UNGROUNDED craft handoff to the design-consultation /
``DESIGN.md`` step — deliberately not evidence-backed, since aesthetics are craft
convention, not a grounded claim.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef

SurfaceKind = Literal["sdk", "web", "mobile", "cli", "browser_extension", "api", "desktop"]


class Screen(BaseModel):
    """One screen in the build's UX skeleton, mapped to the features it serves.

    Generated AFTER the feature list exists, so ``feature_ids`` reference real
    :class:`~metalworks.contract.build.FeatureSpec` ids. ``validated`` iff a real
    voice asked for it; ``scaffolding`` flags shell screens (auth/settings) that
    every product needs — not a hypothesis to test, so honestly excluded from the
    validated/unvalidated count.
    """

    name: str = Field(description="Screen name.")
    purpose: str = Field(description="What this screen is for, one line.")
    primary_action: str = Field(description="The single primary action on this screen.")
    feature_ids: list[str] = Field(
        default_factory=list[str],
        description="Ids of the BuildSpec features this screen serves (real, not invented).",
    )
    serves_wedge: bool = Field(
        default=False, description="True when this screen directly serves the positioning wedge."
    )
    scaffolding: bool = Field(
        default=False,
        description="True for shell screens (auth/settings) — needed by every product, not a "
        "demand hypothesis.",
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Voices asking for this screen. Empty → an unvalidated hypothesis.",
    )
    validated: bool = Field(
        default=False, description="True iff at least one evidence_ref backs the screen."
    )


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
