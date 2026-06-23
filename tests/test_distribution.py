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
