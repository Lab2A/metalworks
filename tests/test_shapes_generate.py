"""Offline unit tests for the ``generate`` base stack and its product shapes.

Deterministic and offline (keyword-coverage path, no embedder). For each shape,
a Research bundle whose top cluster claim reads like a real demand complaint that
shape answers must match that shape on the ``generate`` base with score >= 0.5; an
unrelated claim must yield no match at all.
"""

from __future__ import annotations

from datetime import datetime

import pytest

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


_UNRELATED_CLAIM = "best budget mechanical keyboard for programmers"

# Each claim is phrased like a real demand complaint the named shape answers.
_SHAPE_CASES = [
    ("asset-generator", "we spend hours making assets by hand for each launch"),
    ("doc-generator", "I write the same documents over and over every week"),
    (
        "personalization-at-scale",
        "we personalize emails for every customer by hand and it never scales",
    ),
    ("copilot", "I want an assistant that suggests the next step while I work"),
    ("autonomous-agent", "I need an agent that completes tasks autonomously overnight"),
]


@pytest.mark.parametrize(("shape_name", "claim"), _SHAPE_CASES)
def test_shape_matches_its_demand_complaint(shape_name: str, claim: str) -> None:
    research = Research(demand=_report([_cluster(1, claim)]))
    matches = ShapeMatcher().match(research)
    assert matches, f"{shape_name} demand should produce a match"
    top = matches[0]
    assert top.shape.name == shape_name
    assert top.base_stack.id == "generate"
    assert top.score >= 0.5
    assert [r.cluster_rank for r in top.evidence_refs] == [1]
    assert all(r.kind == "cluster" for r in top.evidence_refs)


def test_unrelated_demand_yields_no_match() -> None:
    research = Research(demand=_report([_cluster(1, _UNRELATED_CLAIM)]))
    assert ShapeMatcher().match(research) == []
