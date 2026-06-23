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
