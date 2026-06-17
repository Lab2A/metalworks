"""Offline matcher tests for the watch base stack and its product shapes.

Deterministic and offline (keyword-coverage path, no embedder). For each watch
product shape, a Research bundle whose top cluster claim reads like the real
complaint that shape answers must match that shape on the ``watch`` base, and an
unrelated claim must yield no match.
"""

from __future__ import annotations

from datetime import datetime

from metalworks.contract.bundle import Research
from metalworks.contract.research import (
    DemandReport,
    Fork,
    InsightCluster,
    ResolvedCitation,
    SignalStrength,
)
from metalworks.shapes.matcher import ShapeMatcher

_WHEN = datetime(2026, 1, 1)
_UNRELATED_CLAIM = "best budget mechanical keyboard for programmers"


def _cluster(
    rank: int, claim: str, *, signal: SignalStrength = SignalStrength.HIGH
) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=claim,
        demand_score=10.0 - rank,
        distinct_author_count=20,
        mention_count=30,
        signal=signal,
        quotes=[ResolvedCitation(text=f"quote for {claim}", author_hash=f"a{rank}")],
    )


def _report(clusters: list[InsightCluster]) -> DemandReport:
    return DemandReport(
        report_id="r1",
        query="is there demand for X",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=_WHEN,
        date_range_end=_WHEN,
        total_threads=100,
        total_distinct_authors=50,
        ranked_clusters=clusters,
        candidate_wedges=[],
        generated_at=_WHEN,
    )


def _match_top(claim: str) -> tuple[str, str, float]:
    research = Research(demand=_report([_cluster(1, claim)]))
    matches = ShapeMatcher().match(research)
    assert matches, f"expected a watch match for claim: {claim!r}"
    top = matches[0]
    return top.shape.name, top.base_stack.id, top.score


def test_price_monitor_matches_price_alert_demand() -> None:
    name, base, score = _match_top("can you alert me when the price changes on this product")
    assert name == "price-monitor"
    assert base == "watch"
    assert score >= 0.5


def test_listing_monitor_matches_new_listing_demand() -> None:
    name, base, score = _match_top("please alert me when a new listing appears in the marketplace")
    assert name == "listing-monitor"
    assert base == "watch"
    assert score >= 0.5


def test_uptime_monitor_matches_downtime_demand() -> None:
    name, base, score = _match_top("alert me when my site goes down so I can react fast")
    assert name == "uptime-monitor"
    assert base == "watch"
    assert score >= 0.5


def test_anomaly_detector_matches_anomaly_demand() -> None:
    name, base, score = _match_top("please detect anomalies in my metrics automatically")
    assert name == "anomaly-detector"
    assert base == "watch"
    assert score >= 0.5


def test_status_tracker_matches_status_change_demand() -> None:
    name, base, score = _match_top("track a status and ping me on change please")
    assert name == "status-tracker"
    assert base == "watch"
    assert score >= 0.5


def test_unrelated_demand_yields_no_watch_match() -> None:
    research = Research(demand=_report([_cluster(1, _UNRELATED_CLAIM)]))
    assert ShapeMatcher().match(research) == []
