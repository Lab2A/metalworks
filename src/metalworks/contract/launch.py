"""Launch contract — the Pillar F (Launch) output.

Pillar F turns a finished :class:`~metalworks.contract.research.DemandReport`
(plus its :class:`~metalworks.contract.positioning.PositioningBrief`) into a set
of channel-native, drafting-only launch assets — one per surface (Product Hunt,
Show HN, an X thread) — and a deterministic :class:`ChannelPlan` describing how a
human would sequence them.

Honesty contract (the no-cite-no-claim gate, applied to launch copy):
- Every factual / quantified / attitudinal claim an asset makes carries a
  :class:`ClaimCitation`: the claim's span in the asset body plus an
  :class:`~metalworks.contract.evidence.EvidenceRef` to the verbatim Reddit quote
  that supports it. The ref resolves against the source report's ``evidence`` by
  id — a claim whose support doesn't resolve is DROPPED at assembly, never
  shipped. So a span on a surviving ``ClaimCitation`` always satisfies
  ``body[span_start:span_end] == claim_text``.
- Assets are DRAFTING-ONLY. Nothing here posts. The :class:`ChannelPlan` is a
  plan a human executes: every :class:`ChannelStep` is ``requires_human`` and
  ``posting_gated``. Show HN in particular is never automated.

This is the stable shape ``Metalworks().research(...).launch`` exposes once
Pillar F has run; the demand report's evidence list is what its ``EvidenceRef``s
resolve against.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef


class ClaimCitation(BaseModel):
    """One factual claim in a launch asset, grounded to upstream evidence.

    ``span_start`` / ``span_end`` are character offsets of ``claim_text`` within
    the owning :class:`LaunchAsset.body` — a surviving citation always satisfies
    ``body[span_start:span_end] == claim_text``. NOTE: these are Python
    code-point offsets; a non-Python consumer (JS uses UTF-16 code units) must
    treat ``claim_text`` as authoritative and re-find it rather than slicing by
    these offsets if the body contains astral characters (emoji). ``evidence_ref``
    points at the verbatim Reddit quote backing the claim and resolves against the
    source report's ``evidence`` by id. A claim whose support doesn't resolve is
    dropped before the asset ships (no-cite-no-claim).
    """

    claim_text: str = Field(
        description="The exact claim substring as it appears in the asset body."
    )
    span_start: int = Field(description="0-based char offset of claim_text in body.")
    span_end: int = Field(
        description="Exclusive char offset; body[span_start:span_end]==claim_text."
    )
    evidence_ref: EvidenceRef = Field(
        description="Ref to the supporting quote — resolves against the report's evidence by id."
    )


class LaunchAsset(BaseModel):
    """One channel-native launch draft for a single surface.

    ``surface`` is the channel id (e.g. ``'product_hunt'`` / ``'show_hn'`` /
    ``'x_thread'``). ``variants`` are alternate hooks/headlines a human can pick
    from. ``claim_citations`` carry the grounded claims (see
    :class:`ClaimCitation`) — every surviving citation's span indexes into
    ``body``. DRAFTING ONLY: holding a ``LaunchAsset`` never posts anything.
    """

    surface: str = Field(description="Channel id: 'product_hunt' | 'show_hn' | 'x_thread' | ...")
    title: str = Field(description="The headline / title / first-tweet hook for this surface.")
    body: str = Field(
        description="The channel-native body copy. ClaimCitation spans index into it."
    )
    variants: list[str] = Field(
        default_factory=list[str],
        description="Alternate hooks/headlines a human can choose from.",
    )
    claim_citations: list[ClaimCitation] = Field(
        default_factory=list[ClaimCitation],
        description="Grounded claims; each span indexes body and each ref resolves in the report.",
    )


class ChannelStep(BaseModel):
    """One human-executed step in a launch sequence for a single surface.

    Deterministic — no LLM authored this. ``requires_human`` and ``posting_gated``
    are both true by construction: Pillar F drafts and plans; a person posts.
    """

    surface: str = Field(description="Channel id this step acts on.")
    action: str = Field(description="What the human does (e.g. 'Submit the Product Hunt draft').")
    scheduled_offset: str = Field(description="Relative schedule, e.g. 'T+0h', 'T+2h'.")
    requires_human: bool = Field(
        default=True, description="Always true — a person executes this step, never the library."
    )
    posting_gated: bool = Field(
        default=True, description="Always true — posting is gated behind explicit human action."
    )


class ChannelPlan(BaseModel):
    """Pillar F output — a deterministic, human-executed launch sequence.

    FKs to exactly one report via ``report_id``; one :class:`ChannelStep` per
    requested surface. The plan is a checklist a founder runs by hand — the
    library never posts.
    """

    report_id: str = Field(description="The DemandReport this plan was derived from.")
    steps: list[ChannelStep] = Field(
        default_factory=list[ChannelStep],
        description="One step per launch surface, in execution order.",
    )
