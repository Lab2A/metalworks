"""Ideation — the two entry points of the validate loop (offline).

Idea-first does one structured extraction (FakeChatModel scripted) and builds a
brief (subreddits passed so the picker doesn't call the model). Evidence-first is
a pure transform over a report's forks — candidate wedges first, else top clusters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from metalworks.contract import (
    CandidateWedge,
    DemandReport,
    EvidenceRef,
    Fork,
    InsightCluster,
    ResolvedCitation,
    SignalStrength,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.errors import MissingKeyError, StructuredOutputError
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.ideate import _IdeaExtract, ideate_from_idea, ideate_from_report
from metalworks.stores import MemoryStores

_CLOCK = datetime(2026, 2, 2, tzinfo=UTC)

_T = TypeVar("_T", bound=BaseModel)


class _RaisingChat(FakeChatModel):
    """A FakeChatModel whose structured call always raises ``exc`` (error-path tests)."""

    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    def complete_structured(self, *, output_model: type[_T], **_kw: Any) -> _T:  # type: ignore[override]
        raise self._exc


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        raise NotImplementedError

    def pull_subreddit(self, **_kwargs: Any) -> Any:
        raise NotImplementedError

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _deps(chat: FakeChatModel) -> ResearchDeps:
    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        clock=lambda: _CLOCK,
    )


def _cluster(rank: int, claim: str, *, demand_score: float = 10.0) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=claim,
        demand_score=demand_score,
        distinct_author_count=5,
        mention_count=5,
        signal=SignalStrength.HIGH,
        quotes=[ResolvedCitation(text=claim, source_url="https://r/1", author_hash="a1")],
    )


def _report(
    *, clusters: list[InsightCluster] | None = None, wedges: list[CandidateWedge] | None = None
) -> DemandReport:
    return DemandReport(
        report_id="rpt-1",
        query="q",
        fork=Fork.BOTH,
        pinned_axis="",
        optimized_axis="",
        date_range_start=_CLOCK,
        date_range_end=_CLOCK,
        total_threads=1,
        total_distinct_authors=5,
        ranked_clusters=clusters or [],
        candidate_wedges=wedges or [],
        generated_at=_CLOCK,
    )


# ── idea-first ────────────────────────────────────────────────────────────────


def test_ideate_from_idea_sharpens_and_builds_brief() -> None:
    chat = FakeChatModel()
    chat.script(
        _IdeaExtract,
        _IdeaExtract(
            hypothesis="A jitter-free focus aid for devs", pain="afternoon caffeine crash"
        ),
    )
    sketch = ideate_from_idea(_deps(chat), "a focus app", subreddits=["nootropics"])
    assert sketch.provenance == "idea-first"
    assert sketch.hypothesis == "A jitter-free focus aid for devs"
    assert sketch.pain == "afternoon caffeine crash"
    assert sketch.evidence == []  # a hypothesis carries no evidence yet
    assert sketch.brief is not None
    assert sketch.brief.question == "a focus app"
    assert sketch.sketch_id.startswith("idea:")
    assert sketch.partial is False


def test_ideate_from_idea_degrades_to_raw_idea_when_model_declines() -> None:
    # A genuine "model declined" (StructuredOutputError) → degrade to the raw idea.
    chat = _RaisingChat(StructuredOutputError("fake/chat", "no schema-valid output"))
    sketch = ideate_from_idea(_deps(chat), "a focus app", subreddits=["nootropics"])
    assert sketch.hypothesis == "a focus app"  # raw idea is its own hypothesis
    assert sketch.brief is not None  # brief still built (subreddits passed)


def test_ideate_from_idea_propagates_infra_error() -> None:
    # #76: an auth/network error during extraction must RAISE — never silently
    # downgrade to a "thin" hypothesis the caller can't tell apart from success.
    chat = _RaisingChat(MissingKeyError("GOOGLE_API_KEY", provider="gemini"))
    with pytest.raises(MissingKeyError):
        ideate_from_idea(_deps(chat), "a focus app", subreddits=["nootropics"])


# ── evidence-first ────────────────────────────────────────────────────────────


def test_ideate_from_report_preserves_wedge_order_no_re_rank() -> None:
    # candidate_wedges arrives already ranked from synthesis/wedges; ideate must
    # NOT re-sort it (one ranking source). The first wedge in stays the first out.
    wedges = [
        CandidateWedge(
            label="first wedge",
            pain="p-1",
            scope="minimal",
            breadth_count=2,
            rationale="the obvious one",
            evidence=[EvidenceRef(kind="cluster", cluster_rank=1)],
        ),
        CandidateWedge(
            label="second wedge",
            pain="p-2",
            scope="broad",
            breadth_count=40,  # higher breadth must NOT jump it to the top
            evidence=[EvidenceRef(kind="cluster", cluster_rank=2)],
        ),
    ]
    result = ideate_from_report(_deps(FakeChatModel()), _report(wedges=wedges))
    assert result.report_id == "rpt-1"
    assert [s.idea for s in result.sketches] == ["first wedge", "second wedge"]  # input order
    top = result.sketches[0]
    assert top.provenance == "evidence-first"
    assert top.hypothesis == "the obvious one"  # the wedge's grounded rationale
    assert top.evidence[0].cluster_rank == 1
    assert result.partial is False


def test_ideate_from_report_emits_no_templated_hypothesis() -> None:
    # #75: a wedge without a rationale carries an empty hypothesis, never a Mad-Lib.
    wedges = [
        CandidateWedge(
            label="rationale-less wedge",
            pain="p-x",
            scope="minimal",
            breadth_count=5,
            evidence=[EvidenceRef(kind="cluster", cluster_rank=1)],
        ),
    ]
    result = ideate_from_report(_deps(FakeChatModel()), _report(wedges=wedges))
    s = result.sketches[0]
    assert s.hypothesis == ""  # no rationale → no hypothesis, not a template
    assert "Build the narrowest thing" not in s.hypothesis
    assert "Build for the people" not in s.hypothesis


def test_ideate_from_report_falls_back_to_clusters() -> None:
    report = _report(clusters=[_cluster(1, "PIE lingers", demand_score=9.0)])
    result = ideate_from_report(_deps(FakeChatModel()), report)
    assert len(result.sketches) == 1
    s = result.sketches[0]
    assert s.provenance == "evidence-first"
    assert s.pain == "PIE lingers"
    assert s.hypothesis == ""  # cluster sketches carry no templated hypothesis
    assert s.evidence[0].kind == "cluster" and s.evidence[0].cluster_rank == 1


def test_ideate_from_report_cluster_order_not_re_ranked() -> None:
    # ranked_clusters arrives ordered by the cluster ranker; ideate preserves it.
    report = _report(
        clusters=[
            _cluster(1, "top pain", demand_score=3.0),  # lower score but rank 1, already first
            _cluster(2, "second pain", demand_score=9.0),
        ]
    )
    result = ideate_from_report(_deps(FakeChatModel()), report)
    assert [s.idea for s in result.sketches] == ["top pain", "second pain"]


def test_ideate_from_report_empty_is_partial() -> None:
    result = ideate_from_report(_deps(FakeChatModel()), _report())
    assert result.sketches == []
    assert result.partial is True
    assert "no clusters" in (result.caveat or "").lower()


# ── MCP ───────────────────────────────────────────────────────────────────────


def test_mcp_ideate_from_report_not_found(monkeypatch: Any) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.ideate_from_report("nope")
    assert res["error"]["error_code"] == "not_found"
