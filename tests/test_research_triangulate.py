"""Triangulation tests: LLM index validation + retry-to-failure, plus the pure
confidence-weighter downgrade rule.

Offline — FakeChatModel scripted per output_model. No network.
"""

from __future__ import annotations

import pytest

from metalworks.contract import (
    CrossReference,
    InsightCluster,
    ResearchBrief,
    ResolvedCitation,
    SignalStrength,
    TargetSubreddit,
    WebFinding,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.triangulate import (
    TriangulationFailedError,
    apply_cross_stream_confidence,
    triangulate,
)
from metalworks.research.triangulate.triangulator import (
    _LLMCrossReference,
    _LLMOutput,
    _LLMResolution,
)
from metalworks.stores import MemoryStores


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions"):
        raise NotImplementedError

    def pull_subreddit(self, **_kw: object):
        raise NotImplementedError

    def fetch_submissions_by_ids(self, _ids: object, _months: object):
        raise NotImplementedError

    def close(self) -> None:
        return None


def _deps(chat: FakeChatModel) -> ResearchDeps:
    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
    )


def _brief(**kw: object) -> ResearchBrief:
    base: dict[str, object] = dict(
        brief_id="b1",
        question="q",
        decision_context="d",
        success_criteria=["s"],
        must_address=["does it taste good"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core")],
        web_research_directions=["pricing"],
        relevance_rubric="r",
    )
    base.update(kw)
    return ResearchBrief(**base)  # type: ignore[arg-type]


def _cluster(rank: int, signal: SignalStrength = SignalStrength.HIGH) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"claim {rank}",
        demand_score=10.0,
        distinct_author_count=20,
        mention_count=20,
        signal=signal,
        quotes=[
            ResolvedCitation(
                text="t", source_url="p", source_name="r/x", author_hash="a", engagement=1
            )
        ],
    )


def _finding(idx: int) -> WebFinding:
    return WebFinding(
        finding_index=idx,
        claim=f"web claim {idx}",
        specifics="x",
        source_url="https://ex.com",
        source_title="src",
        confidence=SignalStrength.MEDIUM,
    )


# ── triangulate: happy path + validation ────────────────────────────────────


def test_triangulate_valid_indices_build_cross_references() -> None:
    chat = FakeChatModel()
    chat.script(
        _LLMOutput,
        _LLMOutput(
            cross_references=[
                _LLMCrossReference(
                    cluster_id="cluster:1",
                    web_finding_ids=["web:1"],
                    agreement="agree",
                    note="both agree",
                )
            ],
            must_address_resolutions=[
                _LLMResolution(must_address_item="does it taste good", resolved_by="cluster:1")
            ],
        ),
    )
    out = triangulate(
        _deps(chat),
        brief=_brief(),
        ranked_clusters=[_cluster(1)],
        web_findings=[_finding(1)],
    )
    assert len(out.cross_references) == 1
    assert out.cross_references[0].cluster_rank == 1
    assert out.cross_references[0].web_finding_indices == [1]
    assert out.must_address_resolution["does it taste good"] == "cluster:1"


def test_triangulate_rejects_nonexistent_index_then_fails() -> None:
    # Every attempt references a cluster rank that doesn't exist → all 3 fail.
    chat = FakeChatModel()
    bad = _LLMOutput(
        cross_references=[
            _LLMCrossReference(cluster_id="cluster:99", agreement="silent_web", note="nope")
        ],
        must_address_resolutions=[
            _LLMResolution(must_address_item="does it taste good", resolved_by="cluster:99")
        ],
    )
    chat.script(_LLMOutput, [bad, bad, bad])
    with pytest.raises(TriangulationFailedError):
        triangulate(
            _deps(chat),
            brief=_brief(),
            ranked_clusters=[_cluster(1)],
            web_findings=[_finding(1)],
            max_retries=3,
        )


def test_triangulate_rejects_mixed_list_prefix() -> None:
    chat = FakeChatModel()
    # web_finding_ids carrying a 'cluster:' prefix → mixed-list rejection.
    bad = _LLMOutput(
        cross_references=[
            _LLMCrossReference(
                cluster_id="cluster:1",
                web_finding_ids=["cluster:1"],
                agreement="agree",
                note="x",
            )
        ],
        must_address_resolutions=[
            _LLMResolution(must_address_item="does it taste good", resolved_by="cluster:1")
        ],
    )
    chat.script(_LLMOutput, [bad, bad, bad])
    with pytest.raises(TriangulationFailedError):
        triangulate(
            _deps(chat),
            brief=_brief(),
            ranked_clusters=[_cluster(1)],
            web_findings=[_finding(1)],
        )


def test_triangulate_degenerate_no_streams_marks_unaddressable() -> None:
    chat = FakeChatModel()  # never called
    out = triangulate(_deps(chat), brief=_brief(), ranked_clusters=[], web_findings=[])
    assert out.cross_references == []
    assert out.must_address_resolution["does it taste good"].startswith("unaddressable:")
    # No LLM call made in the degenerate path.
    assert chat.calls == []


def test_triangulate_missing_must_address_resolution_fails() -> None:
    chat = FakeChatModel()
    # Resolution omits the required must_address item → validation fails.
    bad = _LLMOutput(
        cross_references=[
            _LLMCrossReference(cluster_id="cluster:1", agreement="silent_web", note="x")
        ],
        must_address_resolutions=[],
    )
    chat.script(_LLMOutput, [bad, bad, bad])
    with pytest.raises(TriangulationFailedError):
        triangulate(
            _deps(chat),
            brief=_brief(),
            ranked_clusters=[_cluster(1)],
            web_findings=[_finding(1)],
        )


# ── confidence_weighter: disagree downgrades, never upgrades ────────────────


def test_confidence_weighter_disagree_downgrades_one_step() -> None:
    clusters = [_cluster(1, SignalStrength.HIGH), _cluster(2, SignalStrength.MEDIUM)]
    cross_refs = [
        CrossReference(
            cluster_rank=1, web_finding_indices=[], agreement="disagree", note="conflict"
        ),
        CrossReference(
            cluster_rank=2, web_finding_indices=[], agreement="disagree", note="conflict"
        ),
    ]
    out = apply_cross_stream_confidence(clusters=clusters, cross_references=cross_refs)
    # HIGH → MEDIUM, MEDIUM → LOW (one step each).
    assert out[0].signal == SignalStrength.MEDIUM
    assert out[1].signal == SignalStrength.LOW


def test_confidence_weighter_low_floors_at_low() -> None:
    clusters = [_cluster(1, SignalStrength.LOW)]
    cross_refs = [
        CrossReference(cluster_rank=1, web_finding_indices=[], agreement="disagree", note="c")
    ]
    out = apply_cross_stream_confidence(clusters=clusters, cross_references=cross_refs)
    assert out[0].signal == SignalStrength.LOW  # already floored


def test_confidence_weighter_agree_never_upgrades() -> None:
    clusters = [_cluster(1, SignalStrength.MEDIUM)]
    cross_refs = [
        CrossReference(cluster_rank=1, web_finding_indices=[1], agreement="agree", note="match")
    ]
    out = apply_cross_stream_confidence(clusters=clusters, cross_references=cross_refs)
    # Agreement is corroborating but never promotes — base-rate is the floor.
    assert out[0].signal == SignalStrength.MEDIUM


def test_confidence_weighter_does_not_mutate_inputs() -> None:
    clusters = [_cluster(1, SignalStrength.HIGH)]
    cross_refs = [
        CrossReference(cluster_rank=1, web_finding_indices=[], agreement="disagree", note="c")
    ]
    apply_cross_stream_confidence(clusters=clusters, cross_references=cross_refs)
    assert clusters[0].signal == SignalStrength.HIGH  # original untouched


def test_confidence_weighter_silent_corpus_orphan_ignored() -> None:
    clusters = [_cluster(1, SignalStrength.HIGH)]
    cross_refs = [
        CrossReference(
            cluster_rank=0, web_finding_indices=[1], agreement="silent_corpus", note="orphan"
        )
    ]
    out = apply_cross_stream_confidence(clusters=clusters, cross_references=cross_refs)
    # cluster:0 orphan bucket has no cluster to adjust.
    assert out[0].signal == SignalStrength.HIGH
