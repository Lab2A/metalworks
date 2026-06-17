"""Offline unit tests for the ``match`` base stack and its product shapes.

Deterministic and offline: the keyword-coverage path of the ShapeMatcher (no
embedder). Each shape gets a Research bundle whose top cluster claim is phrased
like a real demand complaint that shape answers, and we assert the matcher
returns that shape on the ``match`` base stack above the score floor. An
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
from metalworks.contract.shape import ShapeMatch
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


_UNRELATED_CLAIM = "best budget mechanical keyboard for programmers"


def _match_named(claim: str, name: str) -> ShapeMatch:
    """Match a single-cluster report and return the result for shape ``name``."""
    research = Research(demand=_report([_cluster(1, claim)]))
    matches = ShapeMatcher().match(research)
    by_name = {m.shape.name: m for m in matches}
    assert name in by_name, f"{name!r} should match {claim!r}; got {sorted(by_name)}"
    return by_name[name]


def test_matches_goods_marketplace() -> None:
    match = _match_named(
        "no good app to buy and sell used equipment in my hobby", "goods-marketplace"
    )
    assert match.base_stack.id == "match"
    assert match.score >= 0.5
    assert [r.cluster_rank for r in match.evidence_refs] == [1]
    assert all(r.kind == "cluster" for r in match.evidence_refs)


def test_matches_services_marketplace() -> None:
    match = _match_named(
        "it is a pain to book a vetted service provider near me", "services-marketplace"
    )
    assert match.base_stack.id == "match"
    assert match.score >= 0.5


def test_matches_rental_marketplace() -> None:
    match = _match_named(
        "i just want to find and book rentals nearby for the weekend", "rental-marketplace"
    )
    assert match.base_stack.id == "match"
    assert match.score >= 0.5


def test_matches_community() -> None:
    match = _match_named(
        "there is no shared space to post and discuss with people who get it", "community"
    )
    assert match.base_stack.id == "match"
    assert match.shape.modules == ["feed"]
    assert match.score >= 0.5


def test_matches_intro_matching() -> None:
    match = _match_named(
        "i wish something could match people and introduce them automatically", "intro-matching"
    )
    assert match.base_stack.id == "match"
    assert match.shape.modules == ["threads"]
    assert match.score >= 0.5


def test_unrelated_demand_yields_no_match() -> None:
    research = Research(demand=_report([_cluster(1, _UNRELATED_CLAIM)]))
    assert ShapeMatcher().match(research) == []
