"""D2 — channel strategy: entity→channel routing as test→focus experiments.

The strategy face of the Distribution pillar. It reads a finished
:class:`~metalworks.contract.research.DemandReport`, classifies the product/ICP
archetype, extracts the real named entities + signals the audience used (its
communities/permalinks pulled DETERMINISTICALLY from the report's quotes — not
the LLM), and routes those signals across the structured channel space
(:class:`~metalworks.contract.distribution.Channel`) into a small set of
**channel experiments** (test→focus), assembled into a
:class:`~metalworks.contract.distribution.ChannelStrategy`.

The honesty contract: a channel's ``routing_signal`` always traces to a real
entity/signal in the corpus (the no-fabrication rule — channels are derived from
what people actually named, never a hardcoded launch list). Selection is
deterministic where it can be; the LLM only classifies the product type, writes
the one-line ICP, and may enrich named platforms/media from the corpus language
— it never invents the communities/permalinks that ground a community channel.

``build_channel_strategy(deps, report, positioning=None, prior_results=None)`` is
the reusable core the four surfaces call. ``prior_results`` is accepted for D8's
re-rank (unused now; threaded through).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    Channel,
    ChannelStrategy,
    ChannelSurfaceType,
    DemandReport,
    ProductType,
)

if TYPE_CHECKING:
    from metalworks.contract import PositioningBrief
    from metalworks.research.deps import ResearchDeps


# A subreddit reference inside a permalink or an "r/Name" label.
_SUBREDDIT_RE = re.compile(r"\br/([A-Za-z0-9][A-Za-z0-9_]{1,50})\b")
# The funnel stages every plan should try to span; an all-awareness plan is a leak.
_FUNNEL_ORDER = ("awareness", "consideration", "conversion", "retention")


# ── Private signal shape ─────────────────────────────────────────────────────


class _ChannelSignals(BaseModel):
    """The grounded entities + signals routed into the channel space.

    ``named_communities`` are pulled DETERMINISTICALLY from the report (real
    subreddits / permalinks in the quotes + source map) — the LLM never invents
    them. ``named_platforms`` / ``named_media`` and the booleans may be enriched
    by a corpus-language LLM pass, but the community grounding is deterministic.
    """

    named_platforms: list[str] = Field(default_factory=list[str])
    named_communities: list[str] = Field(default_factory=list[str])
    named_media: list[str] = Field(default_factory=list[str])
    shareable_output: bool = False
    hated_incumbent: str | None = None
    benchmark_hunger: bool = False


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _ProductClassification(BaseModel):
    """The product-type pick + a grounded one-line ICP (the only LLM authoring)."""

    product_type: ProductType = Field(
        description="The product/ICP archetype that best fits this audience + demand."
    )
    icp_summary: str = Field(
        description="One tight line: who this is for, grounded in the report (their words, "
        "not invented). No marketing fluff."
    )


class _CorpusEntities(BaseModel):
    """Optional LLM enrichment of named entities from the corpus language.

    The community grounding is already deterministic; this pass only surfaces
    platforms / media / attitudinal booleans the audience NAMED. It must not
    invent — anything not in the quotes is left empty."""

    named_platforms: list[str] = Field(
        default_factory=list[str],
        description="Third-party platforms/tools the audience named in their workflow "
        "(e.g. 'Shopify', 'Figma', 'Cursor'). Empty if none are named.",
    )
    named_media: list[str] = Field(
        default_factory=list[str],
        description="Newsletters / creators / podcasts the audience named following. Empty if none",
    )
    shareable_output: bool = Field(
        default=False,
        description="True only if the product produces output users share publicly / with a "
        "third party (a watermark/UGC-SEO loop signal).",
    )
    hated_incumbent: str | None = Field(
        default=None,
        description="A specific expensive incumbent the audience repeatedly resents, if named.",
    )
    benchmark_hunger: bool = Field(
        default=False,
        description="True if the audience references benchmarks / 'average X' / 'state of' — a "
        "data-as-marketing signal.",
    )


# ── Deterministic helpers ────────────────────────────────────────────────────


def _report_text(report: DemandReport) -> str:
    """All the audience's own language, for the (optional) entity-enrichment pass."""
    parts: list[str] = []
    for c in report.ranked_clusters:
        parts.append(c.claim)
        parts.extend(q.text for q in c.quotes)
    return "\n".join(parts)


def _extract_communities(report: DemandReport) -> list[str]:
    """Real subreddits the audience lives in — pulled DETERMINISTICALLY from the report.

    Sources, in order of trust: each quote's ``source_name`` (the resolved
    'r/Name' label) and ``source_url`` permalink, then the report's source map.
    Dedup case-insensitively, preserve first-seen order. Never the LLM.
    """
    seen: dict[str, str] = {}

    def _add(raw: str) -> None:
        for m in _SUBREDDIT_RE.finditer(raw):
            name = f"r/{m.group(1)}"
            key = name.lower()
            if key not in seen:
                seen[key] = name

    for cluster in report.ranked_clusters:
        for q in cluster.quotes:
            _add(q.source_name)
            _add(q.source_url)
    for entry in report.source_map:
        _add(entry.source)
        _add(entry.subreddit)
    return list(seen.values())


def _permalink_for(report: DemandReport, community: str) -> str:
    """A real permalink in this community, for the community channel's grounding."""
    key = community.lower()
    for cluster in report.ranked_clusters:
        for q in cluster.quotes:
            if q.source_url and key in q.source_url.lower():
                return q.source_url
            if q.source_name and q.source_name.lower() == key and q.source_url:
                return q.source_url
    return ""


def _funnel_stages_present(channels: list[Channel]) -> list[str]:
    present = {c.funnel_stage for c in channels}
    return [s for s in _FUNNEL_ORDER if s in present]


# ── LLM passes (private, best-effort) ────────────────────────────────────────


def _enrich_entities(deps: ResearchDeps, report: DemandReport) -> _CorpusEntities:
    """Best-effort: surface platforms/media/booleans the audience NAMED. Never invents."""
    text = _report_text(report)[:6000]
    model = deps.filter_model  # cheap model when configured, else the main chat
    system = (
        "You extract ONLY entities the audience explicitly named in their own words. Do NOT "
        "invent or infer plausible-but-unstated platforms, media, or attitudes. If the text "
        "doesn't name something, leave it empty / false. You are a strict extractor, not a "
        "brainstormer."
    )
    user = (
        "From these verbatim consumer quotes + cluster claims, extract:\n"
        "- named_platforms: third-party tools/platforms they named in their workflow\n"
        "- named_media: newsletters/creators/podcasts they named following\n"
        "- shareable_output: do they produce output shared publicly / with a third party?\n"
        "- hated_incumbent: a specific expensive incumbent they repeatedly resent (else null)\n"
        "- benchmark_hunger: do they reference benchmarks / 'average X' / 'state of'?\n\n"
        f"{text}"
    )
    return model.complete_structured(
        system=system,
        user=user,
        output_model=_CorpusEntities,
        max_tokens=512,
        temperature=0.0,
    )


# ── Public entry points ──────────────────────────────────────────────────────


def classify_product(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None = None,
) -> tuple[ProductType, str]:
    """Classify the product/ICP archetype + a grounded one-line ICP (one LLM call).

    On any failure, falls back to a deterministic, honest default (``CONSUMER`` +
    the report query as the ICP line) rather than crashing — the strategy still
    ships, just less specific.
    """
    quotes: list[str] = []
    for cluster in report.ranked_clusters[:4]:
        quotes.extend(q.text for q in cluster.quotes[:2])
    quote_block = "\n".join(f'- "{q}"' for q in quotes[:8]) or "(no quotes)"
    wedge_line = ""
    if positioning is not None and positioning.wedge is not None:
        wedge_line = (
            f"\nPositioning wedge (for context): {positioning.wedge.market_category} — "
            f"{positioning.wedge.unique_attribute}"
        )
    system = (
        "You classify a product into one ICP archetype and write a one-line ICP, grounded in "
        "real demand evidence. The archetype biases channel routing (a dev_tool routes to Show "
        "HN + GitHub; a consumer app to short-form video + ASO; a marketplace to manual supply "
        "seeding). Pick the single best-fitting archetype. The ICP line must use the audience's "
        "own framing from the quotes — do not invent a persona the evidence doesn't support."
    )
    user = (
        f"Product / demand query: {report.query}{wedge_line}\n\n"
        f"Top consumer quotes:\n{quote_block}\n\n"
        "Classify the product_type and write a one-line icp_summary grounded in the evidence."
    )
    try:
        out = deps.chat.complete_structured(
            system=system,
            user=user,
            output_model=_ProductClassification,
            max_tokens=512,
            temperature=0.2,
        )
        icp = out.icp_summary.strip() or report.query
        return out.product_type, icp
    except Exception:
        return ProductType.CONSUMER, report.query


def extract_channel_signals(deps: ResearchDeps, report: DemandReport) -> _ChannelSignals:
    """Extract the grounded entities + signals to route on.

    Communities/permalinks are pulled DETERMINISTICALLY from the report. An LLM
    pass may enrich named platforms/media + the attitudinal booleans from the
    corpus language; it is best-effort and never invents the community grounding.
    """
    communities = _extract_communities(report)
    signals = _ChannelSignals(named_communities=communities)
    try:
        enriched = _enrich_entities(deps, report)
        signals.named_platforms = enriched.named_platforms
        signals.named_media = enriched.named_media
        signals.shareable_output = enriched.shareable_output
        signals.hated_incumbent = enriched.hated_incumbent
        signals.benchmark_hunger = enriched.benchmark_hunger
    except Exception:
        # Enrichment is best-effort; the deterministic community grounding stands.
        pass
    return signals


def _beachhead(report: DemandReport) -> str:
    """A short, grounded label for the first audience (for prose only)."""
    if report.segments:
        return report.segments[0].name
    return "early adopters in this niche"


def select_channels(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None,
    product_type: ProductType,
    signals: _ChannelSignals,
    prior_results: object | None = None,
) -> list[Channel]:
    """Route the grounded signals → channel experiments across the channel space.

    Every channel sets all five axes (motion/cadence/discovery/role/funnel_stage),
    carries a cheap ``test`` + ``success_threshold`` (test→focus), and its
    ``routing_signal`` traces to a real entity/signal in the corpus. Pull /
    compounding amplifier channels (marketplaces, loops) are paired with a
    ``spark_channel`` + ``requires_spark=True`` — they don't start their own
    velocity. The set is built to span funnel stages.

    ``prior_results`` is accepted for D8's re-rank (unused now; threaded through).
    """
    _ = prior_results  # D8 will re-rank on recorded ChannelResults; threaded for parity now.
    channels: list[Channel] = []

    # 1. Community-native — the moat. Routes off a REAL named community + permalink.
    for community in signals.named_communities[:3]:
        permalink = _permalink_for(report, community)
        grounding = f"audience names {community} in the corpus"
        if permalink:
            grounding += f" ({permalink})"
        channels.append(
            Channel(
                surface_type=ChannelSurfaceType.COMMUNITY,
                name=community,
                motion="pull",
                cadence="compounding",
                discovery="algorithmic",
                role="lead_gen",
                funnel_stage="consideration",
                routing_signal=grounding,
                test=f"Participate in {community} for 2-3 weeks, then post one story-led "
                "showcase (not a link drop); reply to every comment.",
                success_threshold="The showcase clears the sub's median upvotes and draws "
                "≥3 genuine 'how do I try this' replies.",
                worth_it_note="Highest-intent channel — but only after real participation; "
                "a cold link drop reads as spam and risks a ban.",
                caveat="Reddit auto-detects cross-posting + vote rings; participate first, "
                "disclose affiliation, never astroturf.",
                rationale=f"The audience already lives in {community}; meet them there in "
                "their own language.",
            )
        )

    # 2. Marketplace / wedge — routes off a NAMED host platform. Amplifier (needs a spark).
    spark_for_amplifiers = "show_hn" if product_type == ProductType.DEV_TOOL else "product_hunt"
    for platform in signals.named_platforms[:2]:
        channels.append(
            Channel(
                surface_type=ChannelSurfaceType.MARKETPLACE,
                name=f"{platform.lower().replace(' ', '_')}_marketplace",
                motion="pull",
                cadence="compounding",
                discovery="curated",
                role="revenue",
                funnel_stage="conversion",
                routing_signal=f"audience names {platform} in their workflow",
                requires_spark=True,
                spark_channel=spark_for_amplifiers,
                test=f"List in the {platform} marketplace/ecosystem with a sharp single-job "
                f"description; seed first installs via the {spark_for_amplifiers} push.",
                success_threshold=f"≥10 organic installs from {platform} in 30 days with no "
                "paid spend — proof the in-platform job is sharp enough to pull.",
                worth_it_note="Can be a PRIMARY channel when the audience lives in the host — "
                "but marketplaces amplify existing demand, they don't create it.",
                caveat="Platform-dependency risk: you rent the host's distribution and it can "
                "change the rules.",
                rationale=f"They already work inside {platform}; be a feature of their workflow.",
            )
        )

    # 3. Hated-incumbent → OSS / "alternative to X" wedge (a named, grounded incumbent).
    if signals.hated_incumbent:
        channels.append(
            Channel(
                surface_type=ChannelSurfaceType.WEDGE_INTEGRATION,
                name=f"alternative_to_{signals.hated_incumbent.lower().replace(' ', '_')}",
                motion="pull",
                cadence="compounding",
                discovery="algorithmic",
                role="lead_gen",
                funnel_stage="awareness",
                routing_signal=f"audience repeatedly resents {signals.hated_incumbent}",
                test=f"Publish an honest '{signals.hated_incumbent} alternative' page + "
                "comparison, grounded in the real complaints from the report.",
                success_threshold="The page ranks / gets cited for the 'alternative to "
                f"{signals.hated_incumbent}' intent and converts ≥5 trials in 60 days.",
                worth_it_note="Rides existing branded demand for the incumbent — cheap to test.",
                caveat="Don't overstate parity; an unfair comparison erodes trust faster than "
                "it converts.",
                rationale=f"People already want OUT of {signals.hated_incumbent}; be the way out.",
            )
        )

    # 4. Shareable output → embedded loop (a build-spec decision, grounded in the signal).
    if signals.shareable_output:
        channels.append(
            Channel(
                surface_type=ChannelSurfaceType.EMBEDDED_LOOP,
                name="shareable_output_loop",
                motion="pull",
                cadence="compounding",
                discovery="algorithmic",
                role="lead_gen",
                funnel_stage="awareness",
                routing_signal="product output is shared publicly / with a third party",
                requires_spark=True,
                spark_channel=spark_for_amplifiers,
                test="Ship a branded public share-URL (a light watermark / 'made with' badge) on "
                "the output users already share; instrument the click-through.",
                success_threshold="≥1 new signup per ~20 shared outputs (a real, honestly-"
                "reported loop), not a one-time paid spike.",
                worth_it_note="Compounds for free once it works — but loops AMPLIFY demand, they "
                "never create it; report K honestly.",
                caveat="This is a BUILD-SPEC decision (public viewer + badge-gating), not a "
                "post-hoc marketing tactic.",
                rationale="The output is already leaving the building; make each share a door in.",
            )
        )

    # 5. Benchmark hunger + our corpus → data-as-marketing (the on-brand killer asset).
    if signals.benchmark_hunger:
        channels.append(
            Channel(
                surface_type=ChannelSurfaceType.DATA_ASSET,
                name="state_of_x_report",
                motion="push",
                cadence="compounding",
                discovery="exogenous",
                role="lead_gen",
                funnel_stage="awareness",
                routing_signal="audience references benchmarks / 'average X' / 'state of'",
                requires_spark=True,
                spark_channel=spark_for_amplifiers,
                test="Publish a methodology-first 'State of X' / complaint-index report off the "
                "corpus you already hold; pitch 2-3 niche outlets.",
                success_threshold="≥1 earned citation/backlink from a niche outlet within ~90 "
                "days (data reports take ~3 months to first citation).",
                worth_it_note="On-brand: you already have the corpus. Earned media is ~84% of AI "
                "citations — this compounds into GEO.",
                caveat="Methodology rigor IS the credibility; a sloppy index backfires.",
                rationale="A benchmark-hungry audience + a proprietary corpus is a data-asset fit.",
            )
        )

    # 6. The spark — a launch-platform push that ignites the amplifiers above and
    # covers conversion-adjacent awareness. Dev tools → Show HN; else Product Hunt.
    # Routes off the existence of a real audience to push to (the report itself).
    if product_type == ProductType.DEV_TOOL:
        channels.append(
            Channel(
                surface_type=ChannelSurfaceType.LAUNCH_PLATFORM,
                name="show_hn",
                motion="push",
                cadence="spike",
                discovery="algorithmic",
                role="lead_gen",
                funnel_stage="awareness",
                routing_signal="developer audience surfaced in the corpus (builder language)",
                test="Post a plain, modest-titled Show HN with a technical maker first comment; "
                "Tue-Thu 8-10am PT.",
                success_threshold="Front-page for ≥2 hours / ≥50 points — the spark that seeds "
                "the marketplace + loop channels.",
                worth_it_note="4/5 for dev tools, 1-2/5 for consumer — and vote rings are fatal.",
                caveat="No superlatives, no friend boosters; HN auto-detects and bans vote rings.",
                rationale="A developer audience converts on a technical, modest Show HN.",
            )
        )
    else:
        channels.append(
            Channel(
                surface_type=ChannelSurfaceType.LAUNCH_PLATFORM,
                name="product_hunt",
                motion="push",
                cadence="spike",
                discovery="algorithmic",
                role="lead_gen",
                funnel_stage="awareness",
                routing_signal=f"a reachable {_beachhead(report)} audience surfaced in the corpus",
                test="Launch on Product Hunt 12:01am PT Tue/Wed with an authentic maker first "
                "comment + a video/GIF; reply to everyone.",
                success_threshold="Top-10 of the day (~100 upvotes by 4am) — the spark that "
                "seeds the marketplace + loop channels.",
                worth_it_note="3/5 — Product Hunt drives awareness, not conversions; treat it as "
                "the ignition spark, not the engine.",
                caveat="Never ask for 'upvotes'; no bots. The decline is real-but-contested.",
                rationale="A broad consumer/prosumer audience can be ignited by a single push day.",
            )
        )

    return channels


def build_channel_strategy(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None = None,
    prior_results: object | None = None,
) -> ChannelStrategy:
    """Orchestrate classify → extract → select into a :class:`ChannelStrategy`.

    The reusable core the four surfaces call. Assembles a ``focusing_rule``
    (test→focus) + a ``funnel_note`` that flags an all-top-of-funnel plan as a
    conversion leak. ``prior_results`` is accepted for D8's re-rank (unused now).
    """
    product_type, icp = classify_product(deps, report, positioning)
    signals = extract_channel_signals(deps, report)
    channels = select_channels(
        deps, report, positioning, product_type, signals, prior_results=prior_results
    )

    n = len(channels)
    focusing_rule = (
        f"Test these {n} channel experiment(s) cheaply — don't commit to all of them. Most "
        "products have ONE channel that drives nearly all growth: run each test, watch its "
        "success_threshold, then CONCENTRATE budget + effort on the single winner before adding "
        "another. This is a set of experiments, not a balanced portfolio."
    )

    stages = _funnel_stages_present(channels)
    if not stages:
        funnel_note = "No channels selected — nothing to cover the funnel yet."
    elif stages == ["awareness"]:
        funnel_note = (
            "LEAK: every selected channel is top-of-funnel (awareness only). Attention with no "
            "consideration/conversion surface to catch it leaks out — pair these with a channel "
            "that converts, and make sure the build ships a conversion destination."
        )
    else:
        funnel_note = f"Funnel coverage spans {', '.join(stages)}. " + (
            "Watch that the awareness pushes hand off to a real conversion surface."
            if "conversion" not in stages
            else "Awareness, consideration and conversion are all represented."
        )

    return ChannelStrategy(
        report_id=report.report_id,
        product_type=product_type,
        icp_summary=icp,
        channels=channels,
        focusing_rule=focusing_rule,
        funnel_note=funnel_note,
    )
