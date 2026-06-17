"""Offline catalog tests for the synthesize base stack and its product shapes.

Deterministic and offline (keyword-coverage path, no embedder). For each shape a
research bundle whose top cluster claim is phrased like a real demand complaint
that shape answers must match that shape on the synthesize base; an unrelated
claim must yield nothing.
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


# Each claim is phrased like a real complaint and fully covers one of the shape's
# signature keywords, so the keyword-coverage matcher scores it at the top.
_CASES: list[tuple[str, str]] = [
    (
        "demand-intelligence",
        "our team has no easy way to see what people say about a topic",
    ),
    (
        "aggregator-comparison",
        "i'm tired of checking ten tabs to compare prices across stores",
    ),
    (
        "search-discovery",
        "i cannot find anything in all these documents we keep",
    ),
    (
        "analytics-dashboard",
        "we have no single view of how things are trending right now",
    ),
    (
        "review-mining",
        "we need to turn raw reviews into insight for the team",
    ),
]

_UNRELATED_CLAIM = "best budget mechanical keyboard for programmers"


def test_each_synthesize_shape_matches_its_demand() -> None:
    for name, claim in _CASES:
        research = Research(demand=_report([_cluster(1, claim)]))
        matches = ShapeMatcher().match(research)
        assert matches, f"{name} demand should match a shape"
        top = matches[0]
        assert top.shape.name == name, f"expected {name}, got {top.shape.name}"
        assert top.base_stack.id == "synthesize"
        assert top.score >= 0.5
        assert [r.cluster_rank for r in top.evidence_refs] == [1]
        assert all(r.kind == "cluster" for r in top.evidence_refs)


def test_unrelated_demand_yields_no_match() -> None:
    research = Research(demand=_report([_cluster(1, _UNRELATED_CLAIM)]))
    assert ShapeMatcher().match(research) == []
