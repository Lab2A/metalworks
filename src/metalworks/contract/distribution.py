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


class AssetPart(BaseModel):
    """One channel-SHAPED span of a distribution asset.

    A launch asset for a real surface is not a flat string — a Product Hunt post
    is a tagline + an authentic maker comment + gallery captions; a Show HN is a
    plain title + a technical first comment; an X thread is N numbered tweets; a
    LinkedIn post is carousel slides. ``role`` names which span this is (e.g.
    ``tagline`` | ``maker_comment`` | ``gallery_caption`` | ``title`` |
    ``first_comment`` | ``tweet`` | ``carousel_slide``) and ``text`` is its copy.
    The owning :class:`ChannelAsset` concatenates its parts into ``body`` for
    back-compat; a part's text always appears verbatim inside that body.
    """

    role: str = Field(
        description="Which channel-shaped span this is — tagline | maker_comment | "
        "gallery_caption | title | first_comment | tweet | carousel_slide | …"
    )
    text: str = Field(description="The copy for this span (appears verbatim in the asset body).")


class ChannelAsset(BaseModel):
    """One channel-SHAPED, drafting-only distribution asset for a single channel.

    Replaces the flat ``LaunchAsset.body: str`` of the retired Launch pillar: a
    thread isn't a string and PH's maker comment matters more than the tagline, so
    the copy is broken into channel-native :class:`AssetPart`\\ s while ``body``
    keeps the concatenated copy for back-compat (and as the span space the
    ``claim_citations`` index into).

    Grounding here is RELAXED versus the rest of the library — the
    generate-site (#67) over-grounding correction. The *demand / factual* claims
    an asset makes (that people want this, that they resent the incumbent) are
    still held to no-cite-no-claim: each carries a :class:`ClaimCitation` whose
    span satisfies ``body[span_start:span_end] == claim_text`` and whose
    ``evidence_ref`` resolves against the source report's ``evidence`` by id;
    unresolved ones are DROPPED. But the persuasive hooks, taglines and the
    ``offer`` (the per-channel CTA) are FREE — they are craft, not factual claims,
    and forcing a Reddit quote behind every persuasive sentence was the category
    error. Platform invariants are enforced at assembly: never a "please upvote"
    ask, native-first (no link in the hook), founder-voiced. DRAFTING ONLY.
    """

    channel_name: str = Field(description="The channel this asset is for (matches Channel.name).")
    surface_type: ChannelSurfaceType = Field(
        description="The channel's surface type — which shaped the parts."
    )
    funnel_stage: FunnelStage = Field(
        description="Where in the funnel this asset acts (carried from the channel)."
    )
    body: str = Field(
        description="The concatenated/back-compat copy; parts' text + claim spans index into it."
    )
    parts: list[AssetPart] = Field(
        default_factory=list[AssetPart],
        description="The channel-shaped spans (e.g. PH: tagline + maker_comment + captions).",
    )
    offer: str = Field(
        default="",
        description="The per-channel CTA / conversion ask — persuasive, not grounded. Never an "
        "'upvote us' ask.",
    )
    claim_citations: list[ClaimCitation] = Field(
        default_factory=list[ClaimCitation],
        description="Grounded DEMAND/factual claims only — each resolves against report.evidence; "
        "persuasive hooks/CTAs are free and not listed here.",
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


# ── Data-as-marketing asset (D5) ─────────────────────────────────────────────


class DataReportItem(BaseModel):
    """One ranked row of a corpus-derived data report — a real cluster, projected.

    The numbers are NOT invented: ``rank`` / ``distinct_authors`` / ``mentions``
    are copied straight from the source :class:`~metalworks.contract.research.\
InsightCluster` (``rank`` / ``distinct_author_count`` / ``mention_count``), and
    ``permalinks`` are the real ``source_url``s of that cluster's verified quotes.
    ``quote`` is ONE verbatim supporting quote pulled from the cluster (never
    paraphrased). The LLM only writes ``label`` — a tight, framing-appropriate
    headline for the cluster's claim (a pain point for a complaint index, a
    requested feature for a feature ranking) — it never touches the counts,
    permalinks, or quote text. This is the survey-fabrication trap avoided: real
    numbers, real links, real words.
    """

    rank: int = Field(description="1-based rank, copied from the source cluster's rank.")
    label: str = Field(
        description="The claim/feature/complaint headline for this row, framed to the report "
        "kind. LLM-written from the cluster's claim — the only authored prose in the row."
    )
    distinct_authors: int = Field(
        description="DISTINCT authors expressing this — copied from the cluster's "
        "distinct_author_count, the honest base rate. Never invented."
    )
    mentions: int = Field(
        description="Total mentions (>= distinct_authors) — copied from the cluster's "
        "mention_count. Kept separate so base-rate honesty stays visible."
    )
    permalinks: list[str] = Field(
        description="Real provenance links — the source_urls of the cluster's verified quotes."
    )
    quote: str = Field(
        description="One verbatim supporting quote from the cluster (exact text, not paraphrased)."
    )


class DataReportAsset(BaseModel):
    """A corpus-derived original-research data report — the on-brand flagship asset.

    The data-as-marketing surface of the Distribution pillar: it projects a
    finished :class:`~metalworks.contract.research.DemandReport`'s ranked clusters
    into a publishable, methodology-first data report — a ranking (the top
    AI-cited format) over a proprietary Reddit corpus (the #1 AI-cited domain),
    every row carrying verbatim quotes + real permalinks + the cluster's REAL
    distinct-author / mention counts. Defensibility is the corpus others can't
    reproduce; credibility is the disclosed method.

    Honesty is the whole point. The ranking is DETERMINISTIC — items are the
    report's own ranked clusters with their own numbers, never re-scored or
    invented. ``methodology`` discloses the real base: the thread count, the
    distinct-author counting method, and the date range. The LLM writes only the
    ``title`` and each item's ``label`` prose, grounded in the cluster's claim.
    The three ``kind``s differ only in framing (``complaint_index`` = pain points,
    ``feature_ranking`` = requested features, ``state_of`` = the overall state) —
    all project the same grounded cluster data.
    """

    report_id: str = Field(description="The source demand report this asset was derived from.")
    kind: Literal["complaint_index", "feature_ranking", "state_of"] = Field(
        description="The framing: 'complaint_index' (pain points), 'feature_ranking' (requested "
        "features), or 'state_of' (the overall state of the category)."
    )
    title: str = Field(
        description="The report headline, LLM-written and grounded in the report's query + kind."
    )
    items: list[DataReportItem] = Field(
        description="The ranked rows, projected deterministically from the report's clusters."
    )
    methodology: str = Field(
        description="The disclosed honest base: N threads analyzed, distinct-author counting, and "
        "the corpus date range — the rigor that IS the credibility."
    )


# ── GEO / LLM-citability (D6) ────────────────────────────────────────────────


class ParticipationTarget(BaseModel):
    """One real thread/community worth engaging — the GEO participation stream.

    GEO ("get cited by AI") is a compounding stream, not a separate pillar: Reddit
    is the #1 AI-cited domain and >50% of AI citations are Q&A threads, so the
    fastest path to being the cited answer is to participate in the threads the
    audience is *already* asking in. Every target is pulled DETERMINISTICALLY from
    the report's real permalinks + communities — ``permalink`` is a verbatim
    ``source_url`` from a verified quote, never invented — and ``why`` paraphrases
    what that audience is actually asking there (a cluster claim). DRAFTING ONLY —
    this names where to show up; it never posts.
    """

    community: str = Field(
        description="The real community to engage, e.g. 'r/SideProject' — from the report."
    )
    permalink: str = Field(
        description="A real thread/source_url pulled from the report's verified quotes."
    )
    why: str = Field(
        description="What the audience is asking there, grounded in a cluster claim — not fluff."
    )
    suggested_angle: str = Field(
        description="The honest, value-first angle to engage with (answer the question, disclose)."
    )


class CitabilityProbe(BaseModel):
    """A conversational query to test whether you're the cited answer.

    Derived from the cluster claims — the real questions the audience asks — not
    templated keyword fluff. You run the ``prompt`` against an answer engine and
    check whether your content is cited; ``target_phrase`` is the cluster claim it
    maps back to, so a probe always traces to real demand.
    """

    prompt: str = Field(
        description="A real conversational query you want to be the cited answer to."
    )
    target_phrase: str = Field(
        description="The cluster claim this probe maps to — the demand it traces back to."
    )


class AnswerBrief(BaseModel):
    """One answer-first brief — a grounded, factual answer to an audience question.

    Here cite-or-die is CORRECT: the answer is a factual claim, so it must be
    grounded. ``answer`` is answer-first prose the LLM writes; ``evidence_refs``
    resolve against the source report's ``evidence`` by id (an answer whose
    evidence doesn't resolve is DROPPED at assembly, never shipped); ``stat_anchors``
    carry the cluster's REAL counts (distinct_authors / mentions) so the answer
    leads with a number the report actually measured. DRAFTING ONLY.
    """

    question: str = Field(description="The audience question this brief answers (a cluster claim).")
    answer: str = Field(
        description="Answer-first, grounded prose — the factual answer you want cited."
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Refs into report.evidence backing the answer. An answer with none is dropped.",
    )
    stat_anchors: dict[str, int] = Field(
        default_factory=dict[str, int],
        description="Real counts from the cluster, e.g. {'distinct_authors': 12, 'mentions': 30}.",
    )


class GeoPlan(BaseModel):
    """The assembled GEO / LLM-citability output for one report — the D6 face.

    Bundles the three grounded streams the four surfaces emit together:
    participation targets (where to show up — real threads), citability probes
    (what to test you're cited for), and answer-first briefs (what to say —
    grounded, evidence-resolving answers). Every element traces to the report:
    targets to real permalinks, probes + briefs to cluster claims, briefs to
    resolvable evidence. DRAFTING ONLY — nothing here posts.
    """

    report_id: str = Field(description="The source report this GEO plan was derived from.")
    participation_targets: list[ParticipationTarget] = Field(
        default_factory=list[ParticipationTarget],
        description="Real threads/communities to engage, from the report's permalinks.",
    )
    citability_probes: list[CitabilityProbe] = Field(
        default_factory=list[CitabilityProbe],
        description="Conversational queries to test citation, from the cluster claims.",
    )
    answer_briefs: list[AnswerBrief] = Field(
        default_factory=list[AnswerBrief],
        description="Answer-first grounded briefs; each resolves against report.evidence.",
    )


# ── Distribution → build requirements (D3) ───────────────────────────────────


class LoopRequirement(BaseModel):
    """One embedded-loop channel's BUILD requirements — the distribution→build feed.

    An embedded loop (a watermark, a UGC-SEO surface, a referral, a free tool, an
    OSS wedge, a single-player aha) is a channel that is designed INTO the product,
    not bolted on as a post-hoc marketing tactic — so the moment distribution
    *selects* such a channel it implies concrete things the build must ship.
    Notion's public-page SEO underperformed precisely because the build lacked
    SSR + a sitemap; a watermark loop is worthless without a branded public viewer
    and badge-gating. The mapping ``loop_kind`` → ``build_requirements`` is
    DETERMINISTIC (a fixed table), and ``rationale`` traces to the selected
    channel's grounded ``routing_signal`` so the requirement is never an invented
    feature — it is the build face of a real, audience-derived loop decision.
    """

    loop_kind: Literal["watermark", "ugc_seo", "referral", "free_tool", "oss", "single_player"] = (
        Field(description="The loop mechanic this requirement set serves.")
    )
    build_requirements: list[str] = Field(
        description="Concrete things the build must ship for this loop, e.g. "
        "['public_share_urls', 'branded_viewer', 'badge_gating'] for a watermark; "
        "['ssr_public_pages', 'sitemap'] for UGC-SEO; ['solo_aha_before_invite'] for "
        "single_player.",
    )
    rationale: str = Field(
        description="Why the build needs this, grounded in the selected channel's routing_signal."
    )


class ConversionSurfaceRequirement(BaseModel):
    """The conversion destination every channel points at — a BUILD requirement (D3).

    Distribution channels create attention (awareness/consideration), but attention
    with no surface to catch it leaks out — so the build MUST include a conversion
    destination, and naming its funnel job is a distribution decision that feeds
    build-spec. This re-opens generate-site (#67) from the right side: not
    cite-or-die marketing copy, but "the build must include a conversion
    destination, here is its job per the funnel." Always emitted (every plan needs
    a place to convert); ``destination`` names the surface, ``funnel_job`` its
    conversion job, and ``build_requirements`` the concrete things it must ship.
    """

    destination: str = Field(
        description="The surface channels point at, e.g. 'landing_page' | 'in_product_onboarding'."
    )
    funnel_job: str = Field(
        description="The conversion job this destination does for the funnel (what it converts)."
    )
    build_requirements: list[str] = Field(
        description="Concrete things the conversion destination must ship, e.g. "
        "['above_fold_value_prop', 'single_primary_cta', 'instrumented_signup'].",
    )
    rationale: str = Field(
        description="Why the build needs a conversion destination, grounded in the channel plan."
    )


# ── Distribution plan — pushes + streams, deterministically sequenced (D7) ────


class Push(BaseModel):
    """One sequenced, concentrated launch MOMENT — a spike channel placed in time.

    A push is a ``spike``-cadence channel scheduled into the launch campaign at a
    timing the research dictates, NOT a timing the LLM invents. ``timing`` is read
    from a DETERMINISTIC, module-level playbook table (Product Hunt → "Day 1,
    12:01am PT (Tue/Wed)"; Show HN → "Day 3-4, Tue-Thu 8-10am PT"; …) — the
    opposite of the old toy ``T+{i*2}h`` even-spacing (the arbitrary-constant
    anti-pattern). The sequencer enforces the playbook's rules — at most one
    all-day-attention channel per day, never Product Hunt and a big HN push on the
    same day — by staggering pushes across the campaign's days. Each push is a
    channel *test* in the test→focus discipline (the early pushes prove a channel
    before you concentrate on the winner); ``spark_channel`` carries the
    spark→flywheel edge when this push ignites an amplifier. DRAFTING + PLANNING
    ONLY: ``requires_human`` / ``posting_gated`` default true — metalworks never
    posts a push.
    """

    channel_name: str = Field(
        description="The spike channel this push fires, matching the Channel.name it came from."
    )
    surface_type: ChannelSurfaceType = Field(
        description="The channel's surface type (carried from the channel)."
    )
    timing: str = Field(
        description="When to fire this push, READ from the deterministic playbook table — e.g. "
        "'Day 1, 12:01am PT (Tue/Wed)'. Never an LLM-invented hour."
    )
    spark_channel: str | None = Field(
        default=None,
        description="The amplifier channel this push ignites, when it carries a spark→flywheel "
        "edge (else null).",
    )
    action: str = Field(
        description="The concrete human action for this moment (what to do), e.g. 'Post the Show "
        "HN with a technical maker first comment.'"
    )
    rationale: str = Field(
        description="Why this push is placed here — the playbook reasoning / test→focus framing."
    )
    requires_human: bool = Field(
        default=True,
        description="Always true — a human executes the push; metalworks plans, it does not post.",
    )
    posting_gated: bool = Field(
        default=True,
        description="Always true — posting is gated behind explicit human action (drafting only).",
    )


class Stream(BaseModel):
    """One continuously-running COMPOUNDING channel — a stream, not a moment.

    A stream is a ``compounding``-cadence channel that runs all the time rather
    than firing once: community participation, a UGC/SEO loop, a data-asset cadence,
    the GEO answer-first stream. It carries no playbook timing (it isn't a moment);
    ``cadence_note`` describes how it runs continuously (e.g. "post one story-led
    showcase every 2-3 weeks after participating daily"). Together the pushes (the
    spike campaign) and the streams (the compounding tail) ARE the distribution
    plan — the spike-vs-compounding axis that made the old launch-vs-growth pillar
    split unnecessary.
    """

    channel_name: str = Field(
        description="The compounding channel this stream runs, matching the Channel.name."
    )
    surface_type: ChannelSurfaceType = Field(
        description="The channel's surface type (carried from the channel)."
    )
    cadence_note: str = Field(
        description="How this channel runs continuously — the compounding rhythm, not a one-time "
        "moment."
    )
    rationale: str = Field(
        description="Why this channel is a stream and what it compounds toward, grounded in the "
        "channel's routing signal."
    )


class DistributionPlan(BaseModel):
    """The sequenced distribution plan for one report — pushes + streams (D7).

    Replaces the toy even-spacing plan (``T+{i*2}h``) with distribution-as-a-campaign:
    the report's channels are split by their ``cadence`` axis — ``spike`` channels
    become :class:`Push`\\ es sequenced into concentrated moments from a DETERMINISTIC
    playbook table (reproducible + citable, never LLM-invented hours), ``compounding``
    channels become :class:`Stream`\\ s that run continuously. The sequencer enforces
    the playbook's staggering rules (one all-day-attention channel per day; never
    Product Hunt and a big HN push the same day), opens with pre-launch warming
    steps and closes with a 30-day post step, and pairs each spark-requiring channel
    with its ``spark_channel`` (the spark→flywheel edge). PURE + DETERMINISTIC — no
    LLM, no network. DRAFTING + PLANNING ONLY: every push is human-executed and
    posting-gated.
    """

    report_id: str = Field(description="The source report this plan was sequenced from.")
    pushes: list[Push] = Field(
        default_factory=list[Push],
        description="The spike channels sequenced into concentrated, staggered launch moments.",
    )
    streams: list[Stream] = Field(
        default_factory=list[Stream],
        description="The compounding channels that run continuously.",
    )


# ── Closed-loop measurement — metric + instrumentation, ingest results (D8) ───


class ChannelMetric(BaseModel):
    """The success metric + instrumentation guidance for one distribution channel.

    Everything else in the pillar PLANS; this is where it learns. metalworks
    can't watch live traffic, so in its lane it defines — DETERMINISTICALLY, from a
    table keyed by ``surface_type`` — what "worked" means for a channel
    (``success_metric``, e.g. "attributed signups in 7d") and exactly how to track
    it (``instrumentation``, e.g. a UTM tag, an attributed-signup query). It is the
    falsifiable disposition applied to distribution: name the metric + the
    instrument BEFORE the push, so the human can record a real
    :class:`ChannelResult` against it afterward and the next push re-ranks on
    evidence, not vibes. Emitted one-per-channel; no LLM, no network.
    """

    channel_name: str = Field(description="The channel this metric is for (matches Channel.name).")
    surface_type: ChannelSurfaceType = Field(
        description="The channel's surface type — which keyed the metric + instrumentation."
    )
    success_metric: str = Field(
        description="What 'worked' means for this channel, e.g. 'attributed signups in 7d'."
    )
    instrumentation: str = Field(
        description="How to track the metric — a UTM tag, an attributed-signup query, a citation "
        "check, etc. Concrete enough that a human can wire it before the push."
    )


class ChannelResult(BaseModel):
    """One recorded outcome for a channel — the human's measurement, fed back in.

    The human executes a push, instruments it per the channel's
    :class:`ChannelMetric`, and records the number here: the ``metric`` measured,
    its ``value``, and the ``period`` it covers (e.g. "first 7d"). A list of these
    is the input to :func:`~metalworks.research.distribution.measure.rerank_from_results`
    (and, through it, ``select_channels(..., prior_results=...)`` /
    ``plan_distribution(..., prior_results=...)``) — the channels that actually
    performed rise for the next push, the dead ones fall. This is how
    "long-running / repeatable" becomes real rather than launch theater.
    """

    channel_name: str = Field(description="The channel this result is for (matches Channel.name).")
    metric: str = Field(
        description="The metric that was measured (mirrors the channel's success_metric)."
    )
    value: float = Field(
        description="The measured value — higher is better (e.g. attributed signups, installs)."
    )
    period: str = Field(description="The window the value covers, e.g. 'first 7d'.")
