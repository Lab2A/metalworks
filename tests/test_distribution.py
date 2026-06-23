"""Distribution channel model (D1) + channel strategy (D2).

D1: pure contract — the channel-model shape, no behavior.
D2: the entity→channel routing engine — classify_product, deterministic signal
extraction, test→focus select_channels, the assembled ChannelStrategy. Offline:
FakeChatModel scripts the one classification call + the (best-effort) entity
enrichment; the DemandReport fixture carries real subreddit-named quotes so the
deterministic community/permalink extraction runs for real. No network, no keys.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import (
    Channel,
    ChannelSurfaceType,
    DataReportAsset,
    DemandReport,
    Fork,
    InsightCluster,
    ProductType,
    ResolvedCitation,
    SignalStrength,
    SourceMapEntry,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.distribution.channels import (
    _ChannelSignals,
    _CorpusEntities,
    _ProductClassification,
    build_channel_strategy,
    classify_product,
    extract_channel_signals,
    select_channels,
)
from metalworks.research.distribution.data_asset import (
    _ItemLabel,
    _ReportProse,
    build_data_asset,
)
from metalworks.research.distribution.geo import (
    _AnswerDraft,
    answer_briefs,
    build_geo_plan,
    citability_probes,
    participation_targets,
)
from metalworks.research.distribution.requirements import (
    conversion_surface_requirement,
    distribution_requirements,
    loop_requirements,
)
from metalworks.stores import MemoryStores

# ── D1 contract ──────────────────────────────────────────────────────────────


def test_channel_minimal_construction_and_defaults() -> None:
    """A Channel needs only its placement axes + a grounded routing signal."""
    ch = Channel(
        surface_type=ChannelSurfaceType.COMMUNITY,
        name="r/sideproject",
        motion="pull",
        cadence="compounding",
        discovery="algorithmic",
        role="lead_gen",
        funnel_stage="awareness",
        routing_signal="audience names r/sideproject repeatedly in the corpus",
    )
    assert ch.requires_spark is False
    assert ch.spark_channel is None
    assert ch.test == ""
    assert ch.success_threshold == ""
    assert Channel.model_validate_json(ch.model_dump_json()) == ch


def test_surface_type_spans_the_structured_space() -> None:
    values = {s.value for s in ChannelSurfaceType}
    assert {
        "launch_platform",
        "marketplace",
        "community",
        "answer_engine_geo",
        "embedded_loop",
        "wedge_integration",
        "borrowed_audience",
        "data_asset",
    } <= values
    assert len(values) == 14


def test_product_type_archetypes() -> None:
    assert {p.value for p in ProductType} == {
        "b2b_sales_led",
        "b2b_plg",
        "dev_tool",
        "consumer",
        "ai_product",
        "marketplace",
        "prosumer",
    }


# ── D2 fixtures ──────────────────────────────────────────────────────────────


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        raise NotImplementedError

    def pull_subreddit(self, **_kwargs: Any) -> Any:
        raise NotImplementedError

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _quote(
    text: str, permalink: str, source_name: str, author_hash: str = "a1"
) -> ResolvedCitation:
    return ResolvedCitation(
        text=text, source_url=permalink, source_name=source_name, author_hash=author_hash
    )


def _cluster(rank: int, *, quotes: list[ResolvedCitation]) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"consumers want outcome {rank}",
        demand_score=10.0,
        distinct_author_count=len({q.author_hash for q in quotes}),
        mention_count=len(quotes),
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _report(
    *,
    clusters: list[InsightCluster],
    source_map: list[SourceMapEntry] | None = None,
) -> DemandReport:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    return DemandReport(
        report_id="rpt-d2",
        query="an affordable focus tool for indie developers",
        fork=Fork.PRODUCT_PINNED,
        date_range_start=now,
        date_range_end=now,
        total_threads=42,
        total_distinct_authors=88,
        ranked_clusters=clusters,
        generated_at=now,
        source_map=source_map or [],
    )


def _deps(chat: FakeChatModel | None = None) -> ResearchDeps:
    return ResearchDeps(
        chat=chat or FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
    )


def _scripted_chat(
    *,
    product_type: ProductType = ProductType.DEV_TOOL,
    icp: str = "indie developers who want jitter-free focus on a budget",
    entities: _CorpusEntities | None = None,
    raise_on_classify: bool = False,
) -> FakeChatModel:
    chat = FakeChatModel()
    if not raise_on_classify:
        chat.script(
            _ProductClassification,
            _ProductClassification(product_type=product_type, icp_summary=icp),
        )
    chat.script(
        _CorpusEntities,
        entities or _CorpusEntities(),
    )
    return chat


# ── classify_product ─────────────────────────────────────────────────────────


def test_classify_product_returns_product_type_and_icp() -> None:
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("I need focus", "https://r/x/1", "r/Devs")])]
    )
    ptype, icp = classify_product(_deps(_scripted_chat()), report)
    assert ptype == ProductType.DEV_TOOL
    assert icp  # non-empty, grounded line
    assert "developers" in icp


def test_classify_product_falls_back_on_llm_failure() -> None:
    # No _ProductClassification scripted → FakeChatModel raises → honest default.
    report = _report(clusters=[_cluster(1, quotes=[_quote("p", "https://r/x/1", "r/X")])])
    ptype, icp = classify_product(_deps(_scripted_chat(raise_on_classify=True)), report)
    assert ptype == ProductType.CONSUMER
    assert icp == report.query


# ── deterministic signal extraction ──────────────────────────────────────────


def test_extract_signals_pulls_communities_deterministically() -> None:
    report = _report(
        clusters=[
            _cluster(
                1,
                quotes=[
                    _quote("nothing helps", "https://r.com/r/SideProject/c/1/x", "r/SideProject"),
                    _quote("same here", "https://r.com/r/Entrepreneur/c/2/y", "r/Entrepreneur"),
                ],
            )
        ],
        source_map=[SourceMapEntry(source="r/SideProject", threads_examined=10)],
    )
    signals = extract_channel_signals(_deps(_scripted_chat()), report)
    # Communities are real subreddits from the quotes/source_map, deduped.
    assert "r/SideProject" in signals.named_communities
    assert "r/Entrepreneur" in signals.named_communities
    assert len(signals.named_communities) == 2  # deduped across quote + source_map


def test_extract_signals_enrichment_is_best_effort() -> None:
    # Enrichment LLM not scripted → raises → community grounding still stands.
    chat = FakeChatModel()  # nothing scripted
    report = _report(clusters=[_cluster(1, quotes=[_quote("x", "https://r/Foo/1", "r/Foo")])])
    signals = extract_channel_signals(_deps(chat), report)
    assert "r/Foo" in signals.named_communities
    assert signals.named_platforms == []  # enrichment failed silently


# ── test→focus select_channels ───────────────────────────────────────────────


def test_select_channels_grounds_routing_signal_and_sets_axes() -> None:
    report = _report(
        clusters=[
            _cluster(
                1,
                quotes=[
                    _quote("help", "https://reddit.com/r/SideProject/comments/1/x", "r/SideProject")
                ],
            )
        ]
    )
    signals = _ChannelSignals(named_communities=["r/SideProject"])
    channels = select_channels(_deps(_scripted_chat()), report, None, ProductType.DEV_TOOL, signals)
    assert channels
    for ch in channels:
        # routing_signal is grounded (non-empty, traces to a corpus entity/signal).
        assert ch.routing_signal.strip()
        # every axis is set (Literal values, never empty).
        assert ch.motion in {"push", "pull"}
        assert ch.cadence in {"spike", "compounding"}
        assert ch.discovery in {"algorithmic", "curated", "exogenous"}
        assert ch.role in {"revenue", "lead_gen"}
        assert ch.funnel_stage in {"awareness", "consideration", "conversion", "retention"}
    # The community channel routes off the real subreddit + carries a test→focus pair.
    community = next(c for c in channels if c.surface_type == ChannelSurfaceType.COMMUNITY)
    assert "r/SideProject" in community.routing_signal
    assert community.test and community.success_threshold


def test_select_channels_pairs_amplifiers_with_a_spark() -> None:
    report = _report(clusters=[_cluster(1, quotes=[_quote("x", "https://r/X/1", "r/X")])])
    signals = _ChannelSignals(
        named_communities=["r/X"],
        named_platforms=["Shopify"],
        shareable_output=True,
    )
    channels = select_channels(_deps(_scripted_chat()), report, None, ProductType.CONSUMER, signals)
    amplifiers = [c for c in channels if c.requires_spark]
    assert amplifiers  # marketplace + loop are amplifiers
    for amp in amplifiers:
        assert amp.spark_channel  # every amplifier names its igniting channel


def test_dev_tool_routes_to_show_hn_spark() -> None:
    report = _report(clusters=[_cluster(1, quotes=[_quote("x", "https://r/X/1", "r/X")])])
    signals = _ChannelSignals(named_communities=["r/X"], named_platforms=["VS Code"])
    channels = select_channels(_deps(_scripted_chat()), report, None, ProductType.DEV_TOOL, signals)
    launch = next(c for c in channels if c.surface_type == ChannelSurfaceType.LAUNCH_PLATFORM)
    assert launch.name == "show_hn"
    # The marketplace amplifier sparks off the dev-tool launch channel.
    marketplace = next(c for c in channels if c.surface_type == ChannelSurfaceType.MARKETPLACE)
    assert marketplace.spark_channel == "show_hn"


# ── build_channel_strategy ───────────────────────────────────────────────────


def test_build_strategy_spans_funnel_and_carries_test_focus() -> None:
    report = _report(
        clusters=[
            _cluster(
                1,
                quotes=[
                    _quote("help", "https://reddit.com/r/SideProject/comments/1/x", "r/SideProject")
                ],
            )
        ]
    )
    entities = _CorpusEntities(named_platforms=["Notion"], shareable_output=True)
    strategy = build_channel_strategy(_deps(_scripted_chat(entities=entities)), report)
    assert strategy.report_id == "rpt-d2"
    assert strategy.product_type == ProductType.DEV_TOOL
    assert strategy.icp_summary
    assert strategy.focusing_rule  # test→focus guidance
    assert strategy.funnel_note
    # Every channel carries the test→focus pair.
    for ch in strategy.channels:
        assert ch.test
        assert ch.success_threshold
        assert ch.routing_signal.strip()
    # The plan spans more than one funnel stage (community=consideration,
    # marketplace=conversion, launch/loop=awareness).
    stages = {c.funnel_stage for c in strategy.channels}
    assert len(stages) > 1


def test_build_strategy_flags_all_tofu_leak() -> None:
    # No communities, no platforms, consumer → only the awareness launch spark.
    report = _report(clusters=[_cluster(1, quotes=[_quote("x", "https://r/X/1", "r/X")])])
    # Strip the only community so the plan is awareness-only.
    report.ranked_clusters[0].quotes[0].source_name = ""
    report.ranked_clusters[0].quotes[0].source_url = "https://example.com/no-sub"
    strategy = build_channel_strategy(
        _deps(_scripted_chat(product_type=ProductType.CONSUMER)), report
    )
    stages = {c.funnel_stage for c in strategy.channels}
    assert stages == {"awareness"}
    assert "LEAK" in strategy.funnel_note


# ── MCP tool ─────────────────────────────────────────────────────────────────


def test_mcp_distribution_strategy_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.distribution_strategy("nope")
    assert res["error"]["error_code"] == "not_found"


def test_mcp_distribution_strategy_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    store = MemoryStores()
    report = _report(
        clusters=[
            _cluster(
                1,
                quotes=[
                    _quote("help", "https://reddit.com/r/SideProject/comments/1/x", "r/SideProject")
                ],
            )
        ]
    )
    store.save_report(report)
    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    monkeypatch.setattr(config, "resolve_chat", lambda *_a, **_k: _scripted_chat())
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr("metalworks.research.arctic.ArcticReader", lambda *a, **k: _NullReader())
    res = tools.distribution_strategy(report.report_id)
    assert "strategy" in res
    assert res["strategy"]["report_id"] == "rpt-d2"
    assert res["strategy"]["channels"]


# ── D5: data-as-marketing data report ────────────────────────────────────────


def _counted_cluster(
    rank: int,
    *,
    distinct_authors: int,
    mentions: int,
    quotes: list[ResolvedCitation],
) -> InsightCluster:
    """A cluster with EXPLICIT counts that intentionally differ from len(quotes), so a test
    can prove the data report copies the real cluster counts rather than re-deriving them."""
    return InsightCluster(
        rank=rank,
        claim=f"consumers struggle with pain point {rank}",
        demand_score=float(100 - rank),
        distinct_author_count=distinct_authors,
        mention_count=mentions,
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _data_report() -> DemandReport:
    return _report(
        clusters=[
            _counted_cluster(
                1,
                distinct_authors=37,
                mentions=52,
                quotes=[
                    _quote("the jitter ruins my focus", "https://reddit.com/r/A/1", "r/A", "u1"),
                    _quote("it lags constantly", "https://reddit.com/r/A/2", "r/A", "u2"),
                ],
            ),
            _counted_cluster(
                2,
                distinct_authors=21,
                mentions=24,
                quotes=[
                    _quote("too expensive for indie", "https://reddit.com/r/B/9", "r/B", "u3"),
                ],
            ),
        ]
    )


def _data_prose_chat() -> FakeChatModel:
    chat = FakeChatModel()
    chat.script(
        _ReportProse,
        _ReportProse(
            title="State of Indie Focus Tools: the top complaints",
            labels=[
                _ItemLabel(rank=1, label="Audio jitter breaks concentration"),
                _ItemLabel(rank=2, label="Pricing is out of reach for indies"),
            ],
        ),
    )
    return chat


def test_data_report_items_are_ranked_and_carry_real_counts() -> None:
    report = _data_report()
    asset = build_data_asset(_deps(_data_prose_chat()), report, "complaint_index")
    assert isinstance(asset, DataReportAsset)
    assert asset.kind == "complaint_index"
    assert asset.report_id == "rpt-d2"
    # One row per cluster, in rank order.
    assert [it.rank for it in asset.items] == [1, 2]
    first, second = asset.items
    # Counts copied from the REAL cluster numbers — NOT len(quotes), not invented.
    assert (first.distinct_authors, first.mentions) == (37, 52)
    assert (second.distinct_authors, second.mentions) == (21, 24)
    # The LLM-written labels are used.
    assert first.label == "Audio jitter breaks concentration"
    # methodology is disclosed and non-empty, naming the real base.
    assert asset.methodology
    assert "42" in asset.methodology  # total_threads from the fixture
    assert "88" in asset.methodology  # total_distinct_authors from the fixture


def test_data_report_items_carry_real_permalinks_and_verbatim_quote() -> None:
    report = _data_report()
    asset = build_data_asset(_deps(_data_prose_chat()), report, "complaint_index")
    first = asset.items[0]
    # Permalinks are the real source_urls of the cluster's quotes, deduped, in order.
    assert first.permalinks == ["https://reddit.com/r/A/1", "https://reddit.com/r/A/2"]
    # The quote is one verbatim quote from the cluster (exact text, not paraphrased).
    assert first.quote == "the jitter ruins my focus"
    assert asset.items[1].permalinks == ["https://reddit.com/r/B/9"]


def test_data_report_falls_back_to_claim_when_llm_fails() -> None:
    # Nothing scripted → the prose pass raises → labels fall back to the cluster claim verbatim,
    # but the deterministic counts / permalinks / quotes still ship.
    report = _data_report()
    asset = build_data_asset(_deps(FakeChatModel()), report, "feature_ranking")
    assert asset.kind == "feature_ranking"
    assert asset.items[0].label == "consumers struggle with pain point 1"
    assert asset.items[0].distinct_authors == 37
    assert asset.items[0].permalinks == ["https://reddit.com/r/A/1", "https://reddit.com/r/A/2"]
    assert asset.title  # a deterministic title is always produced


def test_data_report_kinds_share_grounded_data() -> None:
    report = _data_report()
    complaint = build_data_asset(_deps(_data_prose_chat()), report, "complaint_index")
    state_of = build_data_asset(_deps(_data_prose_chat()), report, "state_of")
    # Different framing, same grounded numbers + permalinks per row.
    assert complaint.kind == "complaint_index" and state_of.kind == "state_of"
    assert [it.distinct_authors for it in complaint.items] == [
        it.distinct_authors for it in state_of.items
    ]
    assert [it.permalinks for it in complaint.items] == [it.permalinks for it in state_of.items]


def test_mcp_distribution_data_report_invalid_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.distribution_data_report("nope", kind="bogus")
    assert res["error"]["error_code"] == "invalid_argument"


def test_mcp_distribution_data_report_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.distribution_data_report("nope")
    assert res["error"]["error_code"] == "not_found"


def test_mcp_distribution_data_report_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    store = MemoryStores()
    report = _data_report()
    store.save_report(report)
    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    monkeypatch.setattr(config, "resolve_chat", lambda *_a, **_k: _data_prose_chat())
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr("metalworks.research.arctic.ArcticReader", lambda *a, **k: _NullReader())
    res = tools.distribution_data_report(report.report_id, kind="complaint_index")
    assert "data_report" in res
    assert res["data_report"]["report_id"] == "rpt-d2"
    assert res["data_report"]["items"][0]["distinct_authors"] == 37
    assert res["data_report"]["items"][0]["permalinks"]
    assert res["data_report"]["methodology"]


# ── D4: channel-shaped assets ────────────────────────────────────────────────


def _channel(
    *,
    name: str,
    surface_type: ChannelSurfaceType,
    funnel_stage: str = "awareness",
) -> Channel:
    return Channel(
        surface_type=surface_type,
        name=name,
        motion="push",
        cadence="spike",
        discovery="algorithmic",
        role="lead_gen",
        funnel_stage=funnel_stage,  # type: ignore[arg-type]
        routing_signal="grounded in the corpus",
    )


def _asset_chat(drafts: list[Any]) -> FakeChatModel:
    """A FakeChatModel that returns the given _AssetDraft list FIFO (one per channel)."""
    from metalworks.research.distribution.assets import _AssetDraft

    chat = FakeChatModel()
    chat.script(_AssetDraft, drafts)
    return chat


def _grounding_report() -> DemandReport:
    """A report whose quote carries a substring a demand claim can ground against."""
    quote = _quote(
        "I would honestly pay for a focus tool that just works without the jitter",
        "https://reddit.com/r/SideProject/comments/1/x",
        "r/SideProject",
    )
    return _report(clusters=[_cluster(1, quotes=[quote])])


def test_build_channel_assets_shapes_product_hunt() -> None:
    from metalworks.research.distribution.assets import (
        _AssetDraft,
        _DraftedPart,
        build_channel_assets,
    )

    report = _grounding_report()
    draft = _AssetDraft(
        parts=[
            _DraftedPart(role="tagline", text="Focus that just works."),
            _DraftedPart(
                role="maker_comment",
                text="I built this after months of jitter. People want a focus tool "
                "that just works without the jitter, so that's what I shipped.",
            ),
            _DraftedPart(role="gallery_caption", text="The one-tap focus screen."),
        ],
        offer="Try it free today — no card needed.",
        claims=[],
    )
    chat = _asset_chat([draft])
    channel = _channel(name="product_hunt", surface_type=ChannelSurfaceType.LAUNCH_PLATFORM)
    assets = build_channel_assets(_deps(chat), report, [channel])

    assert len(assets) == 1
    asset = assets[0]
    assert asset.channel_name == "product_hunt"
    roles = [p.role for p in asset.parts]
    assert "maker_comment" in roles  # PH has a maker_comment part
    assert "tagline" in roles
    # parts concatenate into body, in order.
    for part in asset.parts:
        assert part.text in asset.body
    assert asset.offer  # the CTA is free (not grounded)


def test_build_channel_assets_shapes_x_thread() -> None:
    from metalworks.research.distribution.assets import (
        _AssetDraft,
        _DraftedPart,
        build_channel_assets,
    )

    report = _grounding_report()
    draft = _AssetDraft(
        parts=[
            _DraftedPart(role="tweet", text="Shipping a focus tool I wish existed."),
            _DraftedPart(role="tweet", text="It kills the jitter that broke my flow."),
            _DraftedPart(role="tweet", text="Built solo over a winter. Here's how."),
        ],
        offer="Link in the reply below.",
        claims=[],
    )
    chat = _asset_chat([draft])
    channel = _channel(name="x_thread", surface_type=ChannelSurfaceType.SOCIAL)
    assets = build_channel_assets(_deps(chat), report, [channel])

    assert len(assets) == 1
    tweets = [p for p in assets[0].parts if p.role == "tweet"]
    assert len(tweets) >= 2  # X has ≥2 tweet parts


def test_demand_claims_ground_but_hooks_are_free() -> None:
    from metalworks.research.distribution.assets import (
        _AssetDraft,
        _ClaimDraft,
        _DraftedPart,
        build_channel_assets,
    )

    report = _grounding_report()
    # A grounded demand claim (verbatim slice of the quote) + an UNGROUNDED claim
    # whose supporting_quote isn't in the corpus → dropped. The persuasive tagline
    # carries no quote and is NOT a claim → it survives un-grounded.
    grounded_text = "People want a focus tool that just works without the jitter"
    draft = _AssetDraft(
        parts=[
            _DraftedPart(role="tagline", text="Finally, focus that sticks."),
            _DraftedPart(
                role="maker_comment",
                text=f"{grounded_text}. I built exactly that.",
            ),
        ],
        offer="Start your first session now.",
        claims=[
            _ClaimDraft(
                text=grounded_text,
                supporting_quote="pay for a focus tool that just works without the jitter",
            ),
            _ClaimDraft(
                text="Thousands of teams switched last month",
                supporting_quote="this number was never said by anyone in the corpus at all",
            ),
        ],
    )
    chat = _asset_chat([draft])
    channel = _channel(name="product_hunt", surface_type=ChannelSurfaceType.LAUNCH_PLATFORM)
    asset = build_channel_assets(_deps(chat), report, [channel])[0]

    # Exactly the grounded demand claim survives; the ungrounded one is dropped.
    assert len(asset.claim_citations) == 1
    cite = asset.claim_citations[0]
    assert cite.claim_text == grounded_text
    # The span resolves verbatim against the body (no-cite-no-claim contract).
    assert asset.body[cite.span_start : cite.span_end] == cite.claim_text
    # The citation's evidence resolves against the report's evidence by id.
    assert cite.evidence_ref.evidence_id in {e.id for e in report.evidence}
    # The persuasive tagline survived without any citation backing it.
    assert any(p.role == "tagline" for p in asset.parts)


def test_no_asset_contains_an_upvote_ask() -> None:
    from metalworks.research.distribution.assets import (
        _AssetDraft,
        _DraftedPart,
        build_channel_assets,
    )

    report = _grounding_report()
    draft = _AssetDraft(
        parts=[
            _DraftedPart(role="title", text="Show HN: a jitter-free focus tool"),
            _DraftedPart(
                role="first_comment",
                text="I built this solo. It works offline. Please upvote us if you like it! "
                "Feedback welcome.",
            ),
        ],
        offer="Smash that upvote button to support the launch.",
        claims=[],
    )
    chat = _asset_chat([draft])
    channel = _channel(name="show_hn", surface_type=ChannelSurfaceType.EARNED_MEDIA)
    asset = build_channel_assets(_deps(chat), report, [channel])[0]

    # The deterministic guard stripped every upvote ask — body, parts AND offer.
    assert "upvote" not in asset.body.lower()
    assert "upvote" not in asset.offer.lower()
    for part in asset.parts:
        assert "upvote" not in part.text.lower()
    # The non-offending copy survived the strip.
    assert "Feedback welcome." in asset.body


def test_unknown_roles_dropped_and_empty_channel_skipped() -> None:
    from metalworks.research.distribution.assets import (
        _AssetDraft,
        _DraftedPart,
        build_channel_assets,
    )

    report = _grounding_report()
    # First channel: every part has a role not in its shape → no parts → skipped.
    bad = _AssetDraft(
        parts=[_DraftedPart(role="not_a_real_role", text="orphaned copy")],
        offer="",
        claims=[],
    )
    good = _AssetDraft(
        parts=[_DraftedPart(role="title", text="A plain, honest post about the tool.")],
        offer="Try it.",
        claims=[],
    )
    chat = _asset_chat([bad, good])
    channels = [
        _channel(name="show_hn", surface_type=ChannelSurfaceType.EARNED_MEDIA),
        _channel(name="state_of_x", surface_type=ChannelSurfaceType.DATA_ASSET),
    ]
    assets = build_channel_assets(_deps(chat), report, channels)
    # The all-bad-roles channel is skipped; only the usable one survives.
    assert [a.channel_name for a in assets] == ["state_of_x"]


def test_mcp_distribution_assets_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools
    from metalworks.research.distribution.assets import _AssetDraft, _DraftedPart

    store = MemoryStores()
    report = _grounding_report()
    store.save_report(report)

    draft = _AssetDraft(
        parts=[_DraftedPart(role="tagline", text="Focus that just works.")],
        offer="Try it free.",
        claims=[],
    )

    def _chat() -> FakeChatModel:
        # One chat scripts BOTH the strategy's classify/enrich calls and the asset
        # drafts — script each output_model the run will touch.
        chat = _scripted_chat()
        chat.script(_AssetDraft, [draft] * 12)
        return chat

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    monkeypatch.setattr(config, "resolve_chat", lambda *_a, **_k: _chat())
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr("metalworks.research.arctic.ArcticReader", lambda *a, **k: _NullReader())

    assert tools.distribution_assets("nope")["error"]["error_code"] == "not_found"
    res = tools.distribution_assets(report.report_id)
    assert "assets" in res
    assert all("parts" in a for a in res["assets"])


# ── D6: GEO / LLM-citability ─────────────────────────────────────────────────


def _answer_chat(
    answer: str = "Most indie devs report that jitter is the deal-breaker.",
) -> FakeChatModel:
    """A FakeChatModel scripting the answer-draft call (one instance, returned per call)."""
    chat = FakeChatModel()
    chat.script(_AnswerDraft, _AnswerDraft(answer=answer))
    return chat


def _geo_report() -> DemandReport:
    """A report whose quotes carry real permalinks + communities, two clusters."""
    return _report(
        clusters=[
            _cluster(
                1,
                quotes=[
                    _quote(
                        "the jitter on cheap focus tools is unbearable",
                        "https://reddit.com/r/SideProject/comments/1/x",
                        "r/SideProject",
                        author_hash="a1",
                    ),
                    _quote(
                        "I'd pay if it just stayed smooth",
                        "https://reddit.com/r/SideProject/comments/2/y",
                        "r/SideProject",
                        author_hash="a2",
                    ),
                ],
            ),
            _cluster(
                2,
                quotes=[
                    _quote(
                        "everything good is locked behind a subscription",
                        "https://reddit.com/r/Entrepreneur/comments/3/z",
                        "r/Entrepreneur",
                        author_hash="a3",
                    ),
                ],
            ),
        ]
    )


# ── participation_targets (deterministic, real permalinks) ───────────────────


def test_participation_targets_use_real_permalinks() -> None:
    report = _geo_report()
    targets = participation_targets(report)
    assert targets
    # Every target's permalink is a REAL source_url drawn from the report's quotes.
    real_urls = {q.source_url for c in report.ranked_clusters for q in c.quotes}
    for t in targets:
        assert t.permalink in real_urls
        assert t.community.startswith("r/")
        # why traces to a real cluster claim.
        assert any(c.claim in t.why for c in report.ranked_clusters)
    # Permalinks are deduped.
    assert len({t.permalink for t in targets}) == len(targets)


def test_participation_targets_skip_quotes_without_permalinks() -> None:
    report = _geo_report()
    for q in report.ranked_clusters[0].quotes:
        q.source_url = ""  # strip permalinks from cluster 1
    targets = participation_targets(report)
    # Only the cluster-2 quote (which still has a permalink) survives.
    assert targets
    assert all("Entrepreneur" in t.permalink for t in targets)


# ── citability_probes (map to cluster claims) ────────────────────────────────


def test_citability_probes_map_to_cluster_claims() -> None:
    report = _geo_report()
    probes = citability_probes(report)
    claims = {c.claim for c in report.ranked_clusters}
    assert probes
    assert len(probes) == len(report.ranked_clusters)
    for p in probes:
        # target_phrase is a real cluster claim; prompt is a question.
        assert p.target_phrase in claims
        assert p.prompt.endswith("?")


# ── answer_briefs (grounded; evidence resolves; ungrounded dropped) ──────────


def test_answer_briefs_are_grounded_and_carry_real_stat_anchors() -> None:
    report = _geo_report()
    # Two clusters → two answer-draft calls; script a list so each pops one.
    chat = FakeChatModel()
    chat.script(
        _AnswerDraft,
        [
            _AnswerDraft(answer="Jitter is the deal-breaker; smoothness wins."),
            _AnswerDraft(answer="Subscriptions are the recurring complaint."),
        ],
    )
    briefs = answer_briefs(_deps(chat), report)
    assert len(briefs) == 2
    resolvable = {rec.id for rec in report.evidence}
    for b in briefs:
        assert b.answer  # grounded prose
        assert b.evidence_refs  # carries refs
        # Every ref resolves against report.evidence.
        for ref in b.evidence_refs:
            assert ref.evidence_id in resolvable
    # stat_anchors carry the cluster's REAL counts.
    first = briefs[0]
    c0 = report.ranked_clusters[0]
    assert first.stat_anchors["distinct_authors"] == c0.distinct_author_count
    assert first.stat_anchors["mentions"] == c0.mention_count


def test_answer_briefs_drops_an_ungrounded_answer() -> None:
    report = _geo_report()
    # A cluster whose quotes are not in report.evidence has no resolvable refs, so its
    # brief is DROPPED (no-cite-no-claim). Clear cluster 1's quotes to force that path.
    report.ranked_clusters[0].quotes = []
    chat = FakeChatModel()
    chat.script(_AnswerDraft, _AnswerDraft(answer="should not appear for the empty cluster"))
    briefs = answer_briefs(_deps(chat), report)
    questions = {b.question for b in briefs}
    assert report.ranked_clusters[0].claim not in questions  # dropped
    assert report.ranked_clusters[1].claim in questions  # kept (still grounded)


# ── build_geo_plan + MCP ─────────────────────────────────────────────────────


def test_build_geo_plan_assembles_three_streams() -> None:
    report = _geo_report()
    chat = FakeChatModel()
    chat.script(_AnswerDraft, [_AnswerDraft(answer="a"), _AnswerDraft(answer="b")])
    plan = build_geo_plan(_deps(chat), report)
    assert plan.report_id == report.report_id
    assert plan.participation_targets
    assert plan.citability_probes
    assert plan.answer_briefs


def test_mcp_distribution_geo_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.distribution_geo("nope")
    assert res["error"]["error_code"] == "not_found"


def test_mcp_distribution_geo_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    store = MemoryStores()
    report = _geo_report()
    store.save_report(report)
    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    monkeypatch.setattr(config, "resolve_chat", lambda *_a, **_k: _answer_chat())
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr("metalworks.research.arctic.ArcticReader", lambda *a, **k: _NullReader())
    res = tools.distribution_geo(report.report_id)
    assert "geo" in res
    assert res["geo"]["report_id"] == "rpt-d2"
    assert res["geo"]["participation_targets"]
    assert res["geo"]["citability_probes"]


# ── D3: distribution → build requirements ────────────────────────────────────


def _loop_channel(name: str = "shareable_output_loop", *, routing_signal: str = "") -> Channel:
    return Channel(
        surface_type=ChannelSurfaceType.EMBEDDED_LOOP,
        name=name,
        motion="pull",
        cadence="compounding",
        discovery="algorithmic",
        role="lead_gen",
        funnel_stage="awareness",
        routing_signal=routing_signal or "product output is shared publicly / with a third party",
    )


def _launch_channel() -> Channel:
    return Channel(
        surface_type=ChannelSurfaceType.LAUNCH_PLATFORM,
        name="product_hunt",
        motion="push",
        cadence="spike",
        discovery="algorithmic",
        role="lead_gen",
        funnel_stage="awareness",
        routing_signal="a reachable audience surfaced in the corpus",
    )


def _conversion_channel() -> Channel:
    return Channel(
        surface_type=ChannelSurfaceType.MARKETPLACE,
        name="notion_marketplace",
        motion="pull",
        cadence="compounding",
        discovery="curated",
        role="revenue",
        funnel_stage="conversion",
        routing_signal="audience names Notion in their workflow",
    )


def test_loop_requirement_maps_watermark_to_build_requirements() -> None:
    """A selected embedded_loop channel → a LoopRequirement carrying the loop's build reqs."""
    loops = loop_requirements([_loop_channel()])
    assert len(loops) == 1
    req = loops[0]
    assert req.loop_kind == "watermark"
    # The deterministic watermark table — designed-in build requirements, grounded.
    assert req.build_requirements == ["public_share_urls", "branded_viewer", "badge_gating"]
    # Rationale traces to the channel's grounded routing_signal.
    assert "shared publicly" in req.rationale


def test_loop_kind_inferred_from_channel_language() -> None:
    """A loop channel that isn't the named watermark loop routes by its language."""
    ugc = loop_requirements([_loop_channel("ugc_loop", routing_signal="public content / UGC SEO")])
    assert ugc[0].loop_kind == "ugc_seo"
    assert ugc[0].build_requirements == ["ssr_public_pages", "sitemap", "canonical_urls"]
    solo = _loop_channel("solo_loop", routing_signal="single-player solo aha before invite")
    assert loop_requirements([solo])[0].loop_kind == "single_player"
    assert loop_requirements([solo])[0].build_requirements == [
        "solo_aha_before_invite",
        "deferred_invite_prompt",
    ]


def test_non_loop_channels_emit_no_loop_requirements() -> None:
    assert loop_requirements([_launch_channel(), _conversion_channel()]) == []


def test_conversion_surface_always_emitted_and_flags_tofu_leak() -> None:
    """Conversion surface is always emitted; its framing flags an all-TOFU plan as a leak."""
    leaky = conversion_surface_requirement([_launch_channel(), _loop_channel()])
    assert leaky.destination == "landing_page"
    assert leaky.build_requirements == [
        "above_fold_value_prop",
        "single_primary_cta",
        "instrumented_signup",
    ]
    assert "leak" in leaky.rationale.lower()
    # A plan that already converts gets the catch-conversion framing, not the leak one.
    catches = conversion_surface_requirement([_launch_channel(), _conversion_channel()])
    assert "leak" not in catches.rationale.lower()


def test_distribution_requirements_returns_loops_and_conversion() -> None:
    loops, conversion = distribution_requirements([_loop_channel(), _launch_channel()])
    assert [lr.loop_kind for lr in loops] == ["watermark"]
    assert len(conversion) == 1  # always exactly one conversion surface


def _spec_chat() -> FakeChatModel:
    """Script the one _BuildPhrasing call build_spec_from_report makes (no screens scripted)."""
    from metalworks.build.spec import _BuildPhrasing, _FeatureDraft

    return FakeChatModel().script(
        _BuildPhrasing,
        _BuildPhrasing(
            features=[
                _FeatureDraft(
                    feature_id="share-it",
                    title="Shareable output",
                    rationale="serves the share loop",
                    source_cluster_rank=1,
                )
            ]
        ),
    )


def _spec_report() -> DemandReport:
    return _report(
        clusters=[
            _cluster(
                1,
                quotes=[_quote("I share my output everywhere", "https://r/x/1", "r/Make")],
            )
        ]
    )


def test_build_spec_records_distribution_requirements() -> None:
    """build_spec_from_report(..., distribution_requirements=...) records them on the spec."""
    from metalworks.build.spec import build_spec_from_report

    reqs = distribution_requirements([_loop_channel(), _launch_channel()])
    spec = build_spec_from_report(
        _deps(_spec_chat()), _spec_report(), surface="cli", distribution_requirements=reqs
    )
    assert [lr.loop_kind for lr in spec.loop_requirements] == ["watermark"]
    assert spec.loop_requirements[0].build_requirements == [
        "public_share_urls",
        "branded_viewer",
        "badge_gating",
    ]
    assert len(spec.conversion_surface_requirements) == 1
    assert spec.conversion_surface_requirements[0].destination == "landing_page"


def test_build_spec_default_none_leaves_requirements_empty() -> None:
    """Default-None path is unchanged: no distribution requirements recorded."""
    from metalworks.build.spec import build_spec_from_report

    spec = build_spec_from_report(_deps(_spec_chat()), _spec_report(), surface="cli")
    assert spec.loop_requirements == []
    assert spec.conversion_surface_requirements == []
    # The rest of the spec still ships normally (the feature grounded).
    assert spec.features and spec.features[0].feature_id == "share-it"


def test_mcp_distribution_requirements_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.distribution_requirements("nope")
    assert res["error"]["error_code"] == "not_found"


def test_mcp_distribution_requirements_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    store = MemoryStores()
    report = _report(
        clusters=[
            _cluster(
                1,
                quotes=[
                    _quote("help", "https://reddit.com/r/SideProject/comments/1/x", "r/SideProject")
                ],
            )
        ]
    )
    store.save_report(report)
    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    # shareable_output=True so select_channels emits an embedded_loop channel.
    monkeypatch.setattr(
        config,
        "resolve_chat",
        lambda *_a, **_k: _scripted_chat(entities=_CorpusEntities(shareable_output=True)),
    )
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr("metalworks.research.arctic.ArcticReader", lambda *a, **k: _NullReader())
    res = tools.distribution_requirements(report.report_id)
    assert "loop_requirements" in res
    assert "conversion_surface_requirements" in res
    assert res["loop_requirements"][0]["loop_kind"] == "watermark"
    assert len(res["conversion_surface_requirements"]) == 1
