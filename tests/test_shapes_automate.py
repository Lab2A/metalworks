"""Offline unit tests for the ``automate`` base stack and its product shapes.

Deterministic and offline: no embedder, so the matcher takes the keyword-coverage
path. Each product shape gets a Research bundle whose top cluster claim is phrased
like a real demand complaint the shape answers, and we assert ShapeMatcher().match()
returns that shape on the ``automate`` base stack with a passing score. An unrelated
claim must yield no match.
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


def _assert_matches(claim: str, shape_name: str) -> None:
    research = Research(demand=_report([_cluster(1, claim)]))
    matches = ShapeMatcher().match(research)
    assert matches, f"{shape_name} demand should match"
    top = matches[0]
    assert top.shape.name == shape_name
    assert top.base_stack.id == "automate"
    assert top.score >= 0.5


def test_matches_integration_sync_on_real_demand() -> None:
    _assert_matches("we manually copy data between two tools all day", "integration-sync")


def test_matches_workflow_automation_on_real_demand() -> None:
    _assert_matches("I just want to automate this repetitive task", "workflow-automation")


def test_matches_etl_pipeline_on_real_demand() -> None:
    _assert_matches("our scheduled data pipeline keeps breaking every night", "etl-pipeline")


def test_matches_ops_bot_on_real_demand() -> None:
    _assert_matches("I need a bot to run routine ops tasks", "ops-bot")


def test_unrelated_demand_yields_no_match() -> None:
    research = Research(demand=_report([_cluster(1, _UNRELATED_CLAIM)]))
    assert ShapeMatcher().match(research) == []
