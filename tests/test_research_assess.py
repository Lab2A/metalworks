"""assess() — the GO / PIVOT / NO-GO gap verdict, as a deterministic matrix (offline).

The decision is a pure function of demand strength (distinct authors) x landscape
saturation (supply count), with the anti-confirmation rule (a partial landscape never
yields GO). The LLM rationale is best-effort and not asserted here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from metalworks.contract import (
    CandidateWedge,
    Competitor,
    CompetitorMap,
    Decision,
    DemandReport,
    EvidenceRef,
    ExistingSolution,
    Fork,
    Landscape,
    SignalStrength,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.assess import run_assessment
from metalworks.research.deps import ResearchDeps
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


def _deps() -> ResearchDeps:
    return ResearchDeps(
        chat=FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        clock=lambda: _CLOCK,
    )


def _wedge(label: str, breadth: int) -> CandidateWedge:
    return CandidateWedge(
        label=label,
        pain=label,
        scope="minimal",
        breadth_count=breadth,
        evidence=[EvidenceRef(kind="cluster", cluster_rank=1)],
    )


def _report(authors: int, *, wedges: list[CandidateWedge] | None = None) -> DemandReport:
    return DemandReport(
        report_id="rpt-1",
        query="q",
        fork=Fork.BOTH,
        pinned_axis="",
        optimized_axis="",
        date_range_start=_CLOCK,
        date_range_end=_CLOCK,
        total_threads=1,
        total_distinct_authors=authors,
        ranked_clusters=[],
        candidate_wedges=wedges or [],
        generated_at=_CLOCK,
    )


def _status_quo() -> Competitor:
    return Competitor(
        competitor_index=0, name="Doing nothing", kind="status_quo", one_liner="x", gaps=[]
    )


def _landscape(*, competitors: int = 0, existing: int = 0, partial: bool = False) -> Landscape:
    comps = [
        Competitor(competitor_index=i, name=f"c{i}", kind="direct", one_liner="x", gaps=[])
        for i in range(1, competitors + 1)
    ]
    sols = [
        ExistingSolution(
            name=f"s{i}",
            addresses_clusters=[1],
            evidence=EvidenceRef(kind="cluster", cluster_rank=1),
        )
        for i in range(existing)
    ]
    cm = CompetitorMap(
        map_id="cm:rpt-1",
        report_id="rpt-1",
        competitors=comps,
        status_quo_alternative=_status_quo(),
        generated_at=_CLOCK,
    )
    return Landscape(
        landscape_id="ls:rpt-1",
        report_id="rpt-1",
        competitor_map=cm,
        existing_solutions=sols,
        generated_at=_CLOCK,
        partial=partial,
        caveat="partial scan" if partial else None,
    )


# ── the decision matrix ───────────────────────────────────────────────────────


def test_strong_demand_open_landscape_is_go() -> None:
    a = run_assessment(_deps(), _report(150, wedges=[_wedge("w", 10)]), _landscape(competitors=1))
    assert a.decision == Decision.GO
    assert a.pivot_target is None
    assert a.gap.demand_strength == SignalStrength.HIGH
    assert a.gap.landscape_saturation == SignalStrength.LOW


def test_moderate_demand_open_landscape_is_go() -> None:
    a = run_assessment(_deps(), _report(30, wedges=[_wedge("w", 10)]), _landscape(competitors=1))
    assert a.decision == Decision.GO
    assert a.gap.demand_strength == SignalStrength.MEDIUM


def test_thin_demand_is_no_go() -> None:
    a = run_assessment(_deps(), _report(5, wedges=[_wedge("w", 10)]), _landscape(competitors=1))
    assert a.decision == Decision.NO_GO
    assert a.gap.demand_strength == SignalStrength.LOW


def test_strong_demand_saturated_with_fork_is_pivot() -> None:
    report = _report(150, wedges=[_wedge("narrow", 12)])
    a = run_assessment(_deps(), report, _landscape(competitors=6))  # supply 6, no openings → HIGH
    assert a.decision == Decision.PIVOT
    assert a.gap.landscape_saturation == SignalStrength.HIGH
    assert a.pivot_target is not None
    assert a.pivot_target.kind == "wedge"
    # the pivot target is a REAL fork id in the report
    assert any(w.id == a.pivot_target.target_id for w in report.candidate_wedges)


def test_strong_demand_saturated_no_fork_is_no_go() -> None:
    # no wedges/segments → nothing to pivot to → NO_GO even with strong demand
    a = run_assessment(_deps(), _report(150), _landscape(competitors=6))
    assert a.decision == Decision.NO_GO
    assert a.pivot_target is None


def test_partial_landscape_never_yields_go() -> None:
    # would be GO (strong demand, low supply) but the landscape is partial → PIVOT, never GO
    report = _report(150, wedges=[_wedge("w", 10)])
    a = run_assessment(_deps(), report, _landscape(competitors=1, partial=True))
    assert a.decision == Decision.PIVOT  # anti-confirmation guard
    assert a.partial is True
    assert a.caveat == "partial scan"


def test_partial_landscape_thin_demand_is_no_go() -> None:
    a = run_assessment(_deps(), _report(5), _landscape(partial=True))
    assert a.decision == Decision.NO_GO


def test_assessment_id_and_evidence_shape() -> None:
    a = run_assessment(_deps(), _report(150, wedges=[_wedge("w", 10)]), _landscape(competitors=1))
    assert a.assessment_id.startswith("as:")
    assert a.report_id == "rpt-1"
    assert a.rationale  # falls back to the deterministic reasoning when no model rationale


# ── MCP ───────────────────────────────────────────────────────────────────────


def test_mcp_assess_not_found(monkeypatch: Any) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.assess_from_report("nope")
    assert res["error"]["error_code"] == "not_found"
