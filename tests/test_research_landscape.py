"""Pillar A — competitive landscape: enumerate, harvest, complaint-match, assemble.

Offline. FakeChatModel is scripted per output_model (the structured enumerate +
per-competitor harvest); FakeEmbedding makes identical text cosine-match (so a
gap whose text equals a real quote matches it, a non-matching gap drops). No
network, no grounding (the ungrounded path is the testable degrade).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("numpy")  # complaint-matching uses cosine_topk (the [research] extra)

from metalworks.contract import (
    DemandReport,
    Fork,
    InsightCluster,
    QuoteCitation,
    SignalStrength,
    WebFinding,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.landscape import (
    _CompetitorCand,
    _CompetitorList,
    _Harvest,
    run_competitor_map,
)
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


def _quote(text: str, permalink: str, author_hash: str = "a1") -> QuoteCitation:
    return QuoteCitation(
        text=text, permalink=permalink, subreddit="SkincareAddiction", author_hash=author_hash
    )


def _cluster(
    rank: int, *, quotes: list[QuoteCitation], distinct_authors: int = 3, demand_score: float = 10.0
) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"pain {rank}",
        demand_score=demand_score,
        distinct_author_count=distinct_authors,
        mention_count=len(quotes),
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _web(index: int, claim: str) -> WebFinding:
    return WebFinding(
        finding_index=index,
        claim=claim,
        specifics="x",
        source_url=f"https://ex.com/{index}",
        source_title="T",
        confidence=SignalStrength.MEDIUM,
    )


def _report(*, clusters: list[InsightCluster], web: list[WebFinding] | None = None) -> DemandReport:
    return DemandReport(
        report_id="rpt-1",
        query="best fade for post-acne marks",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=_CLOCK,
        date_range_end=_CLOCK,
        total_threads=10,
        total_distinct_authors=50,
        ranked_clusters=clusters,
        generated_at=_CLOCK,
        web_findings=web or [],
    )


def _deps(chat: FakeChatModel) -> ResearchDeps:
    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        clock=lambda: _CLOCK,
    )


def _chat(*, competitors: list[_CompetitorCand], harvest: _Harvest) -> FakeChatModel:
    chat = FakeChatModel()  # native_grounding=False → structured enumerate (ungrounded)
    chat.script(_CompetitorList, _CompetitorList(competitors=competitors))
    chat.script(_Harvest, harvest)
    return chat


# ── status quo + map shell ───────────────────────────────────────────────────


def test_status_quo_always_present_even_with_no_competitors() -> None:
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("PIE lingers for months", "https://r/1")])]
    )
    chat = _chat(competitors=[], harvest=_Harvest())
    cmap = run_competitor_map(_deps(chat), report)
    assert cmap.status_quo_alternative.kind == "status_quo"
    assert cmap.status_quo_alternative.gaps  # cost of doing nothing = the top pains
    assert cmap.map_id == "cm:rpt-1"
    assert cmap.report_id == "rpt-1"
    assert cmap.generated_at == _CLOCK


def test_status_quo_gaps_are_verbatim_quotes() -> None:
    q = _quote("PIE lingers for months", "https://r/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    cmap = run_competitor_map(_deps(_chat(competitors=[], harvest=_Harvest())), report)
    refs = [g.evidence for g in cmap.status_quo_alternative.gaps]
    assert all(r.kind == "quote" for r in refs)
    assert q.id in {r.evidence_id for r in refs}


def test_ungrounded_enumeration_marks_partial() -> None:
    report = _report(clusters=[_cluster(1, quotes=[_quote("p", "https://r/1")])])
    cand = _CompetitorCand(name="Paula's Choice", kind="direct", one_liner="BHA brand")
    cmap = run_competitor_map(_deps(_chat(competitors=[cand], harvest=_Harvest())), report)
    assert cmap.partial is True
    assert "ungrounded" in (cmap.caveat or "").lower()
    assert [c.name for c in cmap.competitors] == ["Paula's Choice"]


# ── complaint match ──────────────────────────────────────────────────────────


def test_gap_matched_to_quote_attaches_evidence_and_severity() -> None:
    # A gap whose text equals a real complaint → FakeEmbedding cosine 1.0 → match.
    complaint = "it is gritty and pills under makeup"
    q = _quote(complaint, "https://r/1")
    report = _report(clusters=[_cluster(1, quotes=[q], distinct_authors=25)])
    cand = _CompetitorCand(name="The Ordinary", kind="direct", one_liner="cheap actives")
    harvest = _Harvest(strengths=["cheap"], gaps=[complaint, "lovely packaging"])
    cmap = run_competitor_map(_deps(_chat(competitors=[cand], harvest=harvest)), report)
    comp = cmap.competitors[0]
    # Only the matching gap survives (no-quote-no-gap drops "lovely packaging").
    assert len(comp.gaps) == 1
    gap = comp.gaps[0]
    assert gap.claim == complaint
    assert gap.evidence.kind == "quote"
    assert gap.evidence.evidence_id == q.id
    assert gap.severity == SignalStrength.HIGH  # 25 distinct authors → HIGH (service-assigned)
    assert comp.strengths[0].claim == "cheap"


def test_unmatched_gaps_are_dropped() -> None:
    report = _report(clusters=[_cluster(1, quotes=[_quote("real complaint text", "https://r/1")])])
    cand = _CompetitorCand(name="X", kind="adjacent", one_liner="y")
    harvest = _Harvest(gaps=["totally unrelated gap", "another unrelated one"])
    cmap = run_competitor_map(_deps(_chat(competitors=[cand], harvest=harvest)), report)
    assert cmap.competitors[0].gaps == []  # nothing matched → no-quote-no-gap


def test_gap_matched_to_web_finding() -> None:
    web_claim = "competitor onboarding is slow and confusing"
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("unrelated", "https://r/1")])],
        web=[_web(1, web_claim)],
    )
    cand = _CompetitorCand(name="X", kind="direct", one_liner="y")
    harvest = _Harvest(gaps=[web_claim])
    cmap = run_competitor_map(_deps(_chat(competitors=[cand], harvest=harvest)), report)
    gap = cmap.competitors[0].gaps[0]
    assert gap.evidence.kind == "web"
    assert gap.severity == SignalStrength.MEDIUM


def test_severity_low_for_thin_complaint() -> None:
    complaint = "minor niche gripe"
    cluster = _cluster(1, quotes=[_quote(complaint, "https://r/1")], distinct_authors=2)
    report = _report(clusters=[cluster])
    cand = _CompetitorCand(name="X", kind="direct", one_liner="y")
    cmap = run_competitor_map(
        _deps(_chat(competitors=[cand], harvest=_Harvest(gaps=[complaint]))), report
    )
    assert cmap.competitors[0].gaps[0].severity == SignalStrength.LOW


def test_every_gap_ref_resolves_against_report() -> None:
    complaint = "it is gritty and pills under makeup"
    q = _quote(complaint, "https://r/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    cand = _CompetitorCand(name="X", kind="direct", one_liner="y")
    cmap = run_competitor_map(
        _deps(_chat(competitors=[cand], harvest=_Harvest(gaps=[complaint]))), report
    )
    evidence_ids = {e.id for e in report.evidence}
    all_gaps = list(cmap.status_quo_alternative.gaps)
    for comp in cmap.competitors:
        all_gaps.extend(comp.gaps)
    assert all_gaps
    for gap in all_gaps:
        assert gap.evidence.evidence_id in evidence_ids


# ── MCP tool ─────────────────────────────────────────────────────────────────


def test_mcp_competitor_map_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.competitor_map_from_report("nope")
    assert res["error"]["error_code"] == "not_found"


def test_mcp_competitor_map_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools
    from metalworks.research import arctic

    complaint = "it is gritty and pills under makeup"
    q = _quote(complaint, "https://r/1")
    report = _report(clusters=[_cluster(1, quotes=[q], distinct_authors=25)])
    store = MemoryStores()
    store.save_report(report)
    cand = _CompetitorCand(name="The Ordinary", kind="direct", one_liner="cheap")
    chat = _chat(competitors=[cand], harvest=_Harvest(strengths=["cheap"], gaps=[complaint]))
    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    monkeypatch.setattr(config, "resolve_chat", lambda *_a, **_k: chat)
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr(arctic, "ArcticReader", lambda *a, **k: _NullReader())
    res = tools.competitor_map_from_report(report.report_id)
    assert "competitor_map" in res
    cm = res["competitor_map"]
    assert cm["report_id"] == "rpt-1"
    assert cm["status_quo_alternative"]["kind"] == "status_quo"
    assert cm["competitors"][0]["gaps"][0]["evidence"]["evidence_id"] == q.id
