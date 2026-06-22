"""Candidate wedges (deterministic) + segment enrichment (signal / evidence / overlap).

Wedges are a pure transform over the ranked clusters; segments need one scripted
LLM grouping call (FakeChatModel) but every quantitative field — including the new
signal / evidence / overlap — is computed deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from metalworks.contract import (
    AudienceProfile,
    EvidenceRef,
    InsightCluster,
    ResolvedCitation,
    SegmentChoice,
    SignalStrength,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.synthesis.segments import _SegmentPlan, _SegmentProposal, build_segments
from metalworks.research.synthesis.wedges import build_wedges
from metalworks.stores import MemoryStores

_CLOCK = datetime(2026, 2, 2, tzinfo=UTC)


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        raise NotImplementedError

    def pull_subreddit(self, **_kwargs: Any) -> Any:
        raise NotImplementedError

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _cluster(rank: int, claim: str, *, authors: int = 5, demand: float = 10.0) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=claim,
        demand_score=demand,
        distinct_author_count=authors,
        breadth_count=authors,
        mention_count=authors,
        signal=SignalStrength.HIGH if authors >= 20 else SignalStrength.MEDIUM,
        quotes=[
            ResolvedCitation(text=claim, source_url=f"https://r/{rank}", author_hash=f"a{rank}")
        ],
    )


# ── wedges ────────────────────────────────────────────────────────────────────


def test_build_wedges_emits_minimal_and_broad() -> None:
    clusters = [
        _cluster(1, "fade lingers for months", authors=30, demand=30.0),
        _cluster(2, "products pill under makeup", authors=10, demand=15.0),
    ]
    wedges = build_wedges(clusters, [])
    scopes = [w.scope for w in wedges]
    assert scopes.count("minimal") == 2  # one per cluster
    assert scopes.count("broad") == 1  # combined platform play
    minimal = next(w for w in wedges if w.scope == "minimal")
    assert minimal.pain == "fade lingers for months"  # top cluster first
    assert minimal.cluster_ranks == [1]
    assert minimal.evidence[0].kind == "cluster" and minimal.evidence[0].cluster_rank == 1
    assert minimal.signal == SignalStrength.HIGH
    broad = next(w for w in wedges if w.scope == "broad")
    assert broad.cluster_ranks == [1, 2]
    assert broad.breadth_count == 40  # sum of cluster breadths
    assert broad.id.startswith("w:")


def test_build_wedges_empty_clusters() -> None:
    assert build_wedges([], []) == []


def test_build_wedges_links_segment_id() -> None:
    clusters = [_cluster(1, "pain one", demand=20.0)]
    seg = SegmentChoice(
        name="devs",
        profile=AudienceProfile(),
        evidence=[EvidenceRef(kind="cluster", cluster_rank=1)],  # owns cluster 1
    )
    wedges = build_wedges(clusters, [seg])
    minimal = next(w for w in wedges if w.scope == "minimal")
    assert minimal.segment_id == seg.id  # wedge linked to the owning segment


# ── segment enrichment ────────────────────────────────────────────────────────


def _deps(chat: FakeChatModel) -> ResearchDeps:
    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        clock=lambda: _CLOCK,
    )


def test_build_segments_carries_signal_evidence_and_overlap() -> None:
    clusters = [_cluster(1, "c1"), _cluster(2, "c2"), _cluster(3, "c3")]
    # two distinct segments + their author sets (segment A and B share author "x")
    cluster_authors = [{"x", "y", "z"}, {"x", "p", "q"}, {"m"}]
    chat = FakeChatModel()
    chat.script(
        _SegmentPlan,
        _SegmentPlan(
            segments=[
                _SegmentProposal(name="A", cluster_ranks=[1]),
                _SegmentProposal(name="B", cluster_ranks=[2]),
            ]
        ),
    )
    segs = build_segments(_deps(chat), clusters, cluster_authors, AudienceProfile())
    assert {s.name for s in segs} == {"A", "B"}
    a = next(s for s in segs if s.name == "A")
    # evidence points at the segment's cluster; signal is banded RELATIVE to the
    # report's segments — A and B both have 3 distinct authors, a tied population
    # [3, 3], so each scores midrank 0.5 → MEDIUM (not an absolute cutoff).
    assert a.evidence[0].kind == "cluster" and a.evidence[0].cluster_rank == 1
    assert a.signal == SignalStrength.MEDIUM
    # overlap: shared {x} = 1, union {x,y,z,p,q} = 5, so 1/5 = 0.2, keyed by B's id
    b = next(s for s in segs if s.name == "B")
    assert a.overlap[b.id] == 0.2


def test_segment_signal_is_relative_to_the_report_segments() -> None:
    # The SAME segment author count bands differently depending on the report's
    # segment distribution: a 3-author segment is HIGH when it tops the report and
    # LOW when it's the report's floor — the confidence chip is relative, not a cutoff.
    clusters = [_cluster(1, "c1"), _cluster(2, "c2"), _cluster(3, "c3")]
    plan = _SegmentPlan(
        segments=[
            _SegmentProposal(name="big", cluster_ranks=[1]),
            _SegmentProposal(name="mid", cluster_ranks=[2]),
            _SegmentProposal(name="small", cluster_ranks=[3]),
        ]
    )
    chat = FakeChatModel()
    chat.script(_SegmentPlan, plan)
    # Author-set SIZES are what band: big=4, mid=2, small=1 distinct authors.
    cluster_authors = [{"a", "b", "c", "d"}, {"e", "f"}, {"g"}]
    segs = build_segments(_deps(chat), clusters, cluster_authors, AudienceProfile())
    by = {s.name: s for s in segs}
    assert by["big"].signal == SignalStrength.HIGH  # tops [4, 2, 1]
    assert by["small"].signal == SignalStrength.LOW  # floor of [4, 2, 1]
