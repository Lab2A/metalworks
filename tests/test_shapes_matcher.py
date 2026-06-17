"""Offline unit tests for the ShapeMatcher and the first-slice catalog.

All deterministic, no network. Covers the corrected veto path (NO_GO / PIVOT /
missing assessment), the breadth floor, the min_score boundary, the keyword
fallback and the embedding path, and ranking. Module-compatibility and the
Clique->Synthesize conformance check land with their slices (no modules and no
Synthesize base ship yet).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import ClassVar, Literal

from metalworks.contract.assess import Assessment, Decision, GapAnalysis, PivotTarget
from metalworks.contract.bundle import Research
from metalworks.contract.research import (
    CandidateWedge,
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


def _report(
    clusters: list[InsightCluster], *, wedges: list[CandidateWedge] | None = None
) -> DemandReport:
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
        candidate_wedges=wedges or [],
        generated_at=_WHEN,
    )


def _assessment(decision: Decision, *, pivot: PivotTarget | None = None) -> Assessment:
    return Assessment(
        assessment_id="as1",
        report_id="r1",
        decision=decision,
        rationale="computed gap",
        gap=GapAnalysis(
            demand_strength=SignalStrength.HIGH,
            demand_summary="strong demand",
            landscape_saturation=SignalStrength.LOW,
        ),
        pivot_target=pivot,
        generated_at=_WHEN,
    )


class _StubEmbedder:
    """Maps any text touching the portal vocabulary to one axis, else the other."""

    protocol_version: ClassVar[str] = "1.0"
    model_id = "stub/embedding"
    dim = 2
    _VOCAB = (
        "upload",
        "portal",
        "submission",
        "document",
        "intake",
        "collect",
        "chasing",
        "files",
        "client",
        "deadline",
    )

    def embed(
        self, texts: Sequence[str], *, task: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            low = text.lower()
            out.append([1.0, 0.0] if any(v in low for v in self._VOCAB) else [0.0, 1.0])
        return out


_PORTAL_CLAIM = "I need an upload portal to collect documents from clients by the deadline"
_UNRELATED_CLAIM = "best budget mechanical keyboard for programmers"


def test_matches_submission_portal_on_real_demand() -> None:
    research = Research(demand=_report([_cluster(1, _PORTAL_CLAIM)]))
    matches = ShapeMatcher().match(research)
    assert matches, "portal demand should match submission-portal"
    top = matches[0]
    assert top.shape.name == "submission-portal"
    assert top.base_stack.id == "store"
    assert top.score >= 0.5
    assert [r.cluster_rank for r in top.evidence_refs] == [1]
    assert all(r.kind == "cluster" for r in top.evidence_refs)


def test_unrelated_demand_yields_no_match() -> None:
    research = Research(demand=_report([_cluster(1, _UNRELATED_CLAIM)]))
    assert ShapeMatcher().match(research) == []


def test_no_go_short_circuits_to_empty() -> None:
    research = Research(
        demand=_report([_cluster(1, _PORTAL_CLAIM)]),
        assessment=_assessment(Decision.NO_GO),
    )
    assert ShapeMatcher().match(research) == []


def test_missing_assessment_matches_on_demand_alone() -> None:
    research = Research(demand=_report([_cluster(1, _PORTAL_CLAIM)]))
    assert research.assessment is None
    assert ShapeMatcher().match(research), "missing assessment must not crash or veto"


def test_pivot_restricts_to_the_pivot_wedge_clusters() -> None:
    unrelated = _cluster(1, _UNRELATED_CLAIM)
    portal = _cluster(2, _PORTAL_CLAIM)
    wedge = CandidateWedge(label="doc-collector", cluster_ranks=[2])
    report = _report([unrelated, portal], wedges=[wedge])
    research = Research(
        demand=report,
        assessment=_assessment(Decision.PIVOT, pivot=PivotTarget(kind="wedge", target_id=wedge.id)),
    )
    matches = ShapeMatcher().match(research)
    assert matches, "pivot should still match via the pivot fork's cluster"
    assert [r.cluster_rank for r in matches[0].evidence_refs] == [2]


def test_min_signal_floor_drops_low_breadth_clusters() -> None:
    research = Research(demand=_report([_cluster(1, _PORTAL_CLAIM, signal=SignalStrength.LOW)]))
    # submission-portal requires MEDIUM breadth; a LOW cluster must not qualify.
    assert ShapeMatcher().match(research) == []


def test_min_score_boundary() -> None:
    # "upload" hits one of the two tokens in keyword "upload portal" -> coverage 0.5,
    # and nothing else, so the composite score is exactly 0.5.
    partial = "users asked for a simpler upload step"
    research = Research(demand=_report([_cluster(1, partial)]))
    assert ShapeMatcher().match(research, min_score=0.5), "0.5 score should pass a 0.5 floor"
    assert ShapeMatcher().match(research, min_score=0.6) == [], "0.5 score should fail a 0.6 floor"


def test_embedding_path_used_when_provided() -> None:
    matcher = ShapeMatcher(embedder=_StubEmbedder())
    hit = Research(demand=_report([_cluster(1, "a client upload portal")]))
    miss = Research(demand=_report([_cluster(1, _UNRELATED_CLAIM)]))
    assert matcher.match(hit), "embedding path should match portal vocabulary"
    assert matcher.match(miss) == [], "embedding path should reject unrelated demand"


def test_ranks_higher_relevance_first() -> None:
    strong = _cluster(1, _PORTAL_CLAIM)  # full keyword hit
    weak = _cluster(2, "users asked for a simpler upload step")  # partial hit
    # One shape, two clusters: the strongest contributing cluster drives the score
    # and is cited first.
    research = Research(demand=_report([weak, strong]))
    match = ShapeMatcher().match(research)[0]
    assert match.evidence_refs[0].cluster_rank == 1
    assert match.score >= 0.9
