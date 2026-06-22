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
    CorpusRecord,
    DemandReport,
    Fork,
    InsightCluster,
    ResolvedCitation,
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
    run_landscape,
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


def _quote(text: str, permalink: str, author_hash: str = "a1") -> ResolvedCitation:
    return ResolvedCitation(
        text=text, source_url=permalink, source_name="r/SkincareAddiction", author_hash=author_hash
    )


def _cluster(
    rank: int,
    *,
    quotes: list[ResolvedCitation],
    distinct_authors: int = 3,
    demand_score: float = 10.0,
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
    # Severity is banded RELATIVE to the report's demand-cluster author counts
    # (option b): 25 tops [25, 8, 3], so it's the top-third → HIGH.
    complaint = "it is gritty and pills under makeup"
    q = _quote(complaint, "https://r/1")
    report = _report(
        clusters=[
            _cluster(1, quotes=[q], distinct_authors=25),
            _cluster(2, quotes=[_quote("c2", "https://r/2")], distinct_authors=8),
            _cluster(3, quotes=[_quote("c3", "https://r/3")], distinct_authors=3),
        ]
    )
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
    assert gap.severity == SignalStrength.HIGH  # tops the report's clusters → HIGH
    assert comp.strengths[0].claim == "cheap"


def test_gap_severity_is_relative_to_report_clusters() -> None:
    # Option b: the SAME absolute complaint count yields a DIFFERENT severity
    # depending on the report's demand-cluster distribution. 10 authors is HIGH when
    # it tops the report and LOW when it sits at the report's floor.
    complaint = "it is gritty and pills under makeup"
    cand = _CompetitorCand(name="X", kind="direct", one_liner="y")
    harvest = _Harvest(gaps=[complaint])

    top = _report(
        clusters=[
            _cluster(1, quotes=[_quote(complaint, "https://r/1")], distinct_authors=10),
            _cluster(2, quotes=[_quote("c2", "https://r/2")], distinct_authors=4),
            _cluster(3, quotes=[_quote("c3", "https://r/3")], distinct_authors=2),
        ]
    )
    floor = _report(
        clusters=[
            _cluster(1, quotes=[_quote(complaint, "https://r/1")], distinct_authors=10),
            _cluster(2, quotes=[_quote("c2", "https://r/2")], distinct_authors=40),
            _cluster(3, quotes=[_quote("c3", "https://r/3")], distinct_authors=20),
        ]
    )
    sev_top = run_competitor_map(_deps(_chat(competitors=[cand], harvest=harvest)), top)
    sev_floor = run_competitor_map(_deps(_chat(competitors=[cand], harvest=harvest)), floor)
    assert sev_top.competitors[0].gaps[0].severity == SignalStrength.HIGH
    assert sev_floor.competitors[0].gaps[0].severity == SignalStrength.LOW


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
    # A complaint at the bottom of the report's clusters → LOW severity.
    complaint = "minor niche gripe"
    report = _report(
        clusters=[
            _cluster(1, quotes=[_quote(complaint, "https://r/1")], distinct_authors=2),
            _cluster(2, quotes=[_quote("c2", "https://r/2")], distinct_authors=30),
            _cluster(3, quotes=[_quote("c3", "https://r/3")], distinct_authors=15),
        ]
    )
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


# ── landscape (thick): competitor map + existing-solutions scan ───────────────


class _FakeSource:
    """A minimal ItemSource over canned records (or a pull that raises)."""

    source_id = "producthunt"

    def __init__(self, records: list[CorpusRecord] | None, *, raises: bool = False) -> None:
        self._records = records or []
        self._raises = raises

    def pull(self, *, query: str, window: object, limit: int | None = None) -> Any:
        if self._raises:
            raise RuntimeError("source down")
        return iter(self._records)

    def comments_for(self, record_ids: Any) -> None:
        return None

    def latest_window(self) -> Any:
        from metalworks.research.sources import SourceWindow

        return SourceWindow()


def _product(rid: str, title: str, *, votes: int = 100, url: str = "https://ph/x") -> CorpusRecord:
    return CorpusRecord(
        id=rid, source="producthunt", source_id=rid, title=title, text="", url=url, engagement=votes
    )


def test_landscape_wraps_map_and_scans_existing_solutions() -> None:
    # cluster claim is "pain 1"; a product titled "pain 1" matches it (FakeEmbedding cosine 1.0).
    report = _report(clusters=[_cluster(1, quotes=[_quote("PIE lingers", "https://r/1")])])
    source = _FakeSource(
        [_product("p1", "pain 1", votes=340), _product("p2", "unrelated", votes=9)]
    )
    ls = run_landscape(
        _deps(_chat(competitors=[], harvest=_Harvest())), report, existing_source=source
    )
    assert ls.landscape_id == "ls:rpt-1"
    assert ls.competitor_map.report_id == "rpt-1"  # the wrapped map is intact
    # only the matching product survives (no-cluster-no-solution drops "unrelated")
    assert [s.name for s in ls.existing_solutions] == ["pain 1"]
    sol = ls.existing_solutions[0]
    assert sol.traction == 340
    assert sol.addresses_clusters == [1]
    assert sol.evidence.kind == "cluster" and sol.evidence.cluster_rank == 1
    # the existing-scan succeeded → its degrade caveat must be absent
    assert "Existing-solutions scan unavailable" not in (ls.caveat or "")


def test_landscape_partial_when_source_errors() -> None:
    report = _report(clusters=[_cluster(1, quotes=[_quote("PIE lingers", "https://r/1")])])
    source = _FakeSource(None, raises=True)
    ls = run_landscape(
        _deps(_chat(competitors=[], harvest=_Harvest())), report, existing_source=source
    )
    assert ls.partial is True
    assert ls.existing_solutions == []
    assert "Existing-solutions scan unavailable" in (ls.caveat or "")
    assert ls.competitor_map.status_quo_alternative.kind == "status_quo"  # map still holds


def test_landscape_no_clusters_scans_nothing_but_does_not_fail() -> None:
    report = _report(clusters=[])
    source = _FakeSource([_product("p1", "anything")])
    ls = run_landscape(
        _deps(_chat(competitors=[], harvest=_Harvest())), report, existing_source=source
    )
    assert ls.existing_solutions == []  # nothing to ground against
    assert "Existing-solutions scan unavailable" not in (ls.caveat or "")  # not a failure


# ── corpus-mining + cluster-tagged competitors ───────────────────────────────


def test_corpus_mining_adds_cluster_tagged_competitor() -> None:
    """A product NAMED in a cluster's quotes surfaces as a competitor tagged to that cluster,
    even when the web enumeration finds nothing."""
    from metalworks.research.landscape import _CorpusMention, _CorpusMentions

    complaint = "vitamin C serums sting and oxidize fast"
    q = _quote(complaint, "https://r/1")
    report = _report(clusters=[_cluster(1, quotes=[q], distinct_authors=30)])
    chat = FakeChatModel()
    chat.script(_CompetitorList, _CompetitorList(competitors=[]))  # web finds nothing
    chat.script(_Harvest, _Harvest(strengths=["cheap"], gaps=[complaint]))
    chat.script(
        _CorpusMentions,
        _CorpusMentions(
            mentions=[
                _CorpusMention(
                    name="The Ordinary", kind="direct", one_liner="cheap actives", cluster_rank=1
                )
            ]
        ),
    )
    cmap = run_competitor_map(_deps(chat), report)
    comp = next(c for c in cmap.competitors if c.name == "The Ordinary")
    assert 1 in comp.addresses_clusters  # tagged to the cluster it was named in


def test_web_and_corpus_competitor_dedupe_unions_clusters() -> None:
    """The same rival from web + corpus dedupes to one, keeps the web kind, unions cluster tags."""
    from metalworks.research.landscape import _CorpusMention, _CorpusMentions

    q = _quote("it pills under makeup", "https://r/2")
    report = _report(clusters=[_cluster(2, quotes=[q], distinct_authors=20)])
    chat = FakeChatModel()
    chat.script(
        _CompetitorList,
        _CompetitorList(
            competitors=[_CompetitorCand(name="The Ordinary", kind="direct", one_liner="cheap")]
        ),
    )
    chat.script(_Harvest, _Harvest(gaps=[]))
    chat.script(
        _CorpusMentions,
        _CorpusMentions(
            mentions=[_CorpusMention(name="the  ordinary!", kind="adjacent", cluster_rank=2)]
        ),
    )
    cmap = run_competitor_map(_deps(chat), report)
    named = [c for c in cmap.competitors if c.name == "The Ordinary"]
    assert len(named) == 1  # web + corpus deduped to one
    assert named[0].kind == "direct"  # web kind wins
    assert 2 in named[0].addresses_clusters  # corpus mention cluster unioned in


def test_corpus_mine_drops_hallucinated_cluster() -> None:
    """A mention pointing at a cluster rank that doesn't exist is dropped."""
    from metalworks.research.landscape import _CorpusMention, _CorpusMentions

    report = _report(
        clusters=[_cluster(1, quotes=[_quote("x", "https://r/1")], distinct_authors=9)]
    )
    chat = FakeChatModel()
    chat.script(_CompetitorList, _CompetitorList(competitors=[]))
    chat.script(_Harvest, _Harvest(gaps=[]))
    chat.script(
        _CorpusMentions,
        _CorpusMentions(mentions=[_CorpusMention(name="Ghost", kind="direct", cluster_rank=99)]),
    )
    cmap = run_competitor_map(_deps(chat), report)
    assert all(c.name != "Ghost" for c in cmap.competitors)
