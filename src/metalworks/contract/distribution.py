"""Distribution contract — the output spine of the Distribution pillar.

Distribution is ONE pillar. It replaces the two thin, overlapping pillars that
preceded it — Pillar F ("Launch") and Pillar G ("Content/SEO") — which were just
the spike-vs-compounding ends of a single cadence axis, double-encoded as two
pillars. Distribution collapses them: it plans and drafts the *pushes* (the
one-shot launch moments — Product Hunt, Show HN, an X thread) and the *streams*
(the compounding surfaces — content/SEO pages, ongoing Reddit engagement) off a
finished :class:`~metalworks.contract.research.DemandReport`, and hands them to a
human to execute. Its execution arm is the Reddit engagement module
(``metalworks.reddit``), re-homed under Distribution downstream.

The honesty contract is the same no-cite-no-claim gate the whole library runs
on: every factual / quantified / attitudinal claim a distribution asset makes
carries a :class:`ClaimCitation` — the claim's exact span in the asset body plus
an :class:`~metalworks.contract.evidence.EvidenceRef` to the verbatim Reddit
quote that supports it. The ref resolves against the source report's ``evidence``
by id; a claim whose support doesn't resolve is DROPPED at assembly, never
shipped. DRAFTING ONLY — nothing here posts.

This module is the foundation the rest of the Distribution build fills in. It
carries :class:`ClaimCitation` (the reusable grounding primitive salvaged from
the old pillars) and the audience-derived channel model — :class:`Channel` plus
its vocabularies (:class:`ChannelSurfaceType`, :class:`ProductType`) — over which
selection, assets, and the plan are built downstream. The asset / plan / page
shapes are rebuilt on top of these.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef


class ClaimCitation(BaseModel):
    """One factual claim in a distribution asset, grounded to upstream evidence.

    ``span_start`` / ``span_end`` are character offsets of ``claim_text`` within
    the owning asset's body — a surviving citation always satisfies
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


# ── Channel-space vocabularies ───────────────────────────────────────────────


class ChannelSurfaceType(StrEnum):
    """The kind of surface a distribution channel acts on — the structured space.

    Distribution routes the demand report's recurring named entities + signals
    across THIS whole space, not a hardcoded list of launch platforms (Product
    Hunt / Show HN / an X thread are three ``launch_platform`` instances in one
    corner). Each value is a distinct discovery mechanic with its own
    motion/cadence/playbook. ``paid`` and ``sales`` are modelled so a plan can
    name them, but metalworks does not operate them.
    """

    LAUNCH_PLATFORM = "launch_platform"
    MARKETPLACE = "marketplace"
    COMMUNITY = "community"
    ANSWER_ENGINE_GEO = "answer_engine_geo"
    EMBEDDED_LOOP = "embedded_loop"
    WEDGE_INTEGRATION = "wedge_integration"
    BORROWED_AUDIENCE = "borrowed_audience"
    DATA_ASSET = "data_asset"
    EARNED_MEDIA = "earned_media"
    SOCIAL = "social"
    SEARCH = "search"
    APP_STORE = "app_store"
    PAID = "paid"
    SALES = "sales"


class ProductType(StrEnum):
    """The product/ICP archetype that biases which channels fit.

    Distribution is product-type-aware: a dev tool routes to Show HN + GitHub +
    MCP, a consumer app to short-form video + ASO, a marketplace to manual supply
    seeding. "Post to Product Hunt" is wrong advice for most of these types.
    """

    B2B_SALES_LED = "b2b_sales_led"
    B2B_PLG = "b2b_plg"
    DEV_TOOL = "dev_tool"
    CONSUMER = "consumer"
    AI_PRODUCT = "ai_product"
    MARKETPLACE = "marketplace"
    PROSUMER = "prosumer"


# Per-channel axes. The cadence axis (spike vs compounding) is what makes the
# launch-vs-growth pillar split unnecessary: a channel's own cadence places it as
# a push (a sequenced moment) or a stream (continuous). Small closed sets, so
# Literal aliases (inlined in the generated types) rather than named enums.
ChannelMotion = Literal["push", "pull"]
ChannelCadence = Literal["spike", "compounding"]
ChannelDiscovery = Literal["algorithmic", "curated", "exogenous"]
ChannelRole = Literal["revenue", "lead_gen"]
FunnelStage = Literal["awareness", "consideration", "conversion", "retention"]


class Channel(BaseModel):
    """One distribution channel, placed in the structured channel space.

    The candidate set is DERIVED from the demand report's recurring named entities
    and signals (a named platform → a wedge/marketplace channel; a named community
    → a community channel; a shareable-output signal → an embedded loop), so
    ``routing_signal`` always traces to corpus evidence rather than a hardcoded
    list. ``motion`` / ``cadence`` place the channel as a push (a sequenced
    moment) or a stream (continuous) — the distinction the old launch-vs-growth
    split double-encoded. ``test`` / ``success_threshold`` carry the test→focus
    discipline (most products have ONE channel that works — test cheaply,
    concentrate on the winner) rather than committing to a balanced portfolio.
    Selection + placement are filled in downstream; this is the shape they emit.
    """

    surface_type: ChannelSurfaceType = Field(
        description="Which kind of surface this channel acts on."
    )
    name: str = Field(
        description="The concrete channel id, e.g. 'show_hn' | 'shopify_app_store' | a subreddit.",
    )
    motion: ChannelMotion = Field(description="'push' (you broadcast) vs 'pull' (they find you).")
    cadence: ChannelCadence = Field(
        description="'spike' (a sequenced push moment) vs 'compounding' (a continuous stream)."
    )
    discovery: ChannelDiscovery = Field(
        description="How you get surfaced: 'algorithmic' | 'curated' (co-sell) | 'exogenous'."
    )
    role: ChannelRole = Field(
        description="'revenue' (sells directly) vs 'lead_gen' (feeds the funnel)."
    )
    funnel_stage: FunnelStage = Field(
        description="Where in the funnel this channel acts (awareness…retention)."
    )
    routing_signal: str = Field(
        description="The grounded entity/signal in the corpus that selected this channel."
    )
    requires_spark: bool = Field(
        default=False,
        description="True when this channel is an amplifier needing an initial push to ignite — "
        "marketplaces/loops don't start their own velocity.",
    )
    spark_channel: str | None = Field(
        default=None,
        description="The channel name that ignites this one, when requires_spark is true.",
    )
    test: str = Field(
        default="",
        description="The cheap test to validate this channel (test→focus; set downstream).",
    )
    success_threshold: str = Field(
        default="",
        description="What result counts as the test passing — the bar to concentrate here.",
    )
    worth_it_note: str = Field(
        default="",
        description="Honest 'worth it' read (e.g. 'PH: awareness, not conversions').",
    )
    caveat: str = Field(default="", description="The carried caveat/risk for this channel.")
    rationale: str = Field(
        default="", description="One line: why this channel fits this product + audience."
    )


class ChannelStrategy(BaseModel):
    """The channel-strategy output — entity→channel routing as test→focus experiments.

    The heart of the Distribution pillar's strategy face: it routes the demand
    report's recurring named entities + signals across the structured channel
    space (:class:`Channel`) and emits a small set of **channel experiments**, NOT
    a ranked portfolio. Each selected channel carries a cheap ``test`` + a
    ``success_threshold`` (the test→focus discipline — most products have ONE
    channel that works, so test cheaply and concentrate on the winner), and its
    ``routing_signal`` traces to a real signal/entity in the corpus (the
    no-fabrication rule — channels are derived from what the audience actually
    named, never a hardcoded launch list). Selection is deterministic where it
    can be; the LLM only classifies the product type / writes the ICP line and
    per-channel prose, it never invents grounding. ``funnel_note`` flags an
    all-top-of-funnel plan as a conversion leak.
    """

    report_id: str = Field(description="The source report this strategy was derived from.")
    product_type: ProductType = Field(
        description="The classified product/ICP archetype that biased the channel routing."
    )
    icp_summary: str = Field(
        description="One-line ICP, grounded in the report (who this is for, in their words)."
    )
    channels: list[Channel] = Field(
        description="The selected channel experiments (test→focus), spanning funnel stages."
    )
    focusing_rule: str = Field(
        description="The test→focus guidance — 'test these N, concentrate on the winner'."
    )
    funnel_note: str = Field(
        description="Coverage note across funnel stages; flags an all-top-of-funnel plan as a leak."
    )
