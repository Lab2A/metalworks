"""ReportDiff engine: deterministic count deltas + advisory claim-matched
cluster movement, all offline with the deterministic FakeEmbedding."""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import (
    CorpusStats,
    DemandReport,
    Fork,
    InsightCluster,
    ResolvedCitation,
    SignalStrength,
    SourceMapEntry,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.research.diff import diff_reports

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_EMB = FakeEmbedding()


def _cluster(claim: str, *, score: float, authors: int, rank: int = 1) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=claim,
        demand_score=score,
        distinct_author_count=authors,
        mention_count=authors + 2,
        signal=SignalStrength.MEDIUM,
        quotes=[
            ResolvedCitation(
                text=f"verbatim for {claim}",
                source_url=f"https://reddit.com/{rank}",
                source_name="r/test",
                author_hash="a1",
            )
        ],
    )


def _report(
    *,
    report_id: str,
    version: int,
    lineage_id: str,
    clusters: list[InsightCluster],
    threads: int,
    authors: int,
    source_dist: dict[str, int] | None = None,
) -> DemandReport:
    stats = None
    if source_dist is not None:
        stats = CorpusStats(
            subreddit_distribution=[
                SourceMapEntry(source=label, threads_examined=n) for label, n in source_dist.items()
            ]
        )
    return DemandReport(
        report_id=report_id,
        lineage_id=lineage_id,
        version=version,
        query="focus supplement demand",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="x",
        optimized_axis="y",
        date_range_start=_NOW,
        date_range_end=_NOW,
        total_threads=threads,
        total_distinct_authors=authors,
        ranked_clusters=clusters,
        generated_at=_NOW,
        corpus_stats=stats,
    )


def test_identical_reports_diff_is_empty_and_deterministic() -> None:
    clusters = [
        _cluster("people want stim-free focus", score=0.9, authors=10, rank=1),
        _cluster("afternoon crash help without caffeine", score=0.5, authors=4, rank=2),
    ]
    a = _report(
        report_id="r1", version=1, lineage_id="r1", clusters=clusters, threads=20, authors=14
    )
    # A re-synthesis that produced the identical result (new version, same data).
    b = _report(
        report_id="r2",
        version=2,
        lineage_id="r1",
        clusters=clusters,
        threads=20,
        authors=14,
    )

    d1 = diff_reports(a, b, embeddings=_EMB)
    assert d1.is_empty is True
    assert d1.summary == "No change since the prior version."
    assert d1.clusters_changed == [] and not d1.clusters_added and not d1.clusters_dropped
    assert d1.clusters_unchanged == 2

    # Determinism: diffing again yields a byte-identical result.
    d2 = diff_reports(a, b, embeddings=_EMB)
    assert d1.model_dump() == d2.model_dump()


def test_lineage_identity_fields() -> None:
    a = _report(report_id="r1", version=1, lineage_id="r1", clusters=[], threads=1, authors=1)
    b = _report(report_id="r2", version=2, lineage_id="r1", clusters=[], threads=1, authors=1)
    d = diff_reports(a, b, embeddings=_EMB)
    assert d.lineage_id == "r1"
    assert (d.from_report_id, d.to_report_id) == ("r1", "r2")
    assert (d.from_version, d.to_version) == (1, 2)


def test_added_and_dropped_clusters() -> None:
    old = [_cluster("people want stim-free focus", score=0.9, authors=10, rank=1)]
    new = [
        _cluster("people want stim-free focus", score=0.9, authors=10, rank=1),
        _cluster("budget nootropic stacks under thirty", score=0.4, authors=3, rank=2),
    ]
    a = _report(report_id="r1", version=1, lineage_id="r1", clusters=old, threads=10, authors=10)
    b = _report(report_id="r2", version=2, lineage_id="r1", clusters=new, threads=18, authors=13)
    d = diff_reports(a, b, embeddings=_EMB)

    assert d.clusters_added == ["budget nootropic stacks under thirty"]
    assert d.clusters_dropped == []
    assert d.clusters_unchanged == 1
    assert d.is_empty is False
    assert d.total_threads_delta == 8
    assert d.total_distinct_authors_delta == 3

    # And the reverse direction drops it.
    d_rev = diff_reports(b, a, embeddings=_EMB)
    assert d_rev.clusters_dropped == ["budget nootropic stacks under thirty"]
    assert d_rev.clusters_added == []


def test_changed_cluster_records_movement() -> None:
    claim = "people want stim-free focus"
    a = _report(
        report_id="r1",
        version=1,
        lineage_id="r1",
        clusters=[_cluster(claim, score=0.5, authors=4)],
        threads=10,
        authors=4,
    )
    b = _report(
        report_id="r2",
        version=2,
        lineage_id="r1",
        clusters=[_cluster(claim, score=0.8, authors=9)],
        threads=10,
        authors=9,
    )
    d = diff_reports(a, b, embeddings=_EMB)

    assert len(d.clusters_changed) == 1
    delta = d.clusters_changed[0]
    assert delta.claim_before == claim and delta.claim_after == claim
    assert delta.similarity >= 0.99  # identical claim text → cosine ~1
    assert delta.demand_score_delta == round(0.8 - 0.5, 6)
    assert delta.distinct_authors_delta == 5
    assert d.clusters_added == [] and d.clusters_dropped == []
    assert d.clusters_unchanged == 0


def test_source_distribution_before_after() -> None:
    a = _report(
        report_id="r1",
        version=1,
        lineage_id="r1",
        clusters=[],
        threads=10,
        authors=5,
        source_dist={"r/Supplements": 6, "r/Nootropics": 4},
    )
    b = _report(
        report_id="r2",
        version=2,
        lineage_id="r1",
        clusters=[],
        threads=15,
        authors=8,
        source_dist={"r/Supplements": 6, "r/Nootropics": 4, "hackernews": 5},
    )
    d = diff_reports(a, b, embeddings=_EMB)
    assert d.source_distribution_before == {"r/Supplements": 6, "r/Nootropics": 4}
    assert d.source_distribution_after == {"r/Supplements": 6, "r/Nootropics": 4, "hackernews": 5}
    assert d.is_empty is False  # threads/authors moved even with no clusters
