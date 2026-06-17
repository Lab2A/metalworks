"""assess() — the GO / PIVOT / NO-GO gap verdict, as a deterministic matrix (offline).

The decision is a pure function of RELATIVE demand (per fork: prevalence + standing
among peer forks) x landscape saturation, with the anti-confirmation rule (a partial
landscape never yields GO). Fork-less reports fall back to the surfaced absolute policy
on the whole-report author count. The LLM rationale is best-effort and not asserted here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from metalworks.contract import (
    AudienceProfile,
    CandidateWedge,
    Competitor,
    CompetitorMap,
    Decision,
    DemandReport,
    EvidenceRef,
    ExistingSolution,
    Fork,
    Landscape,
    SegmentChoice,
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
        distinct_author_count=breadth,
        evidence=[EvidenceRef(kind="cluster", cluster_rank=1)],
    )


def _segment(name: str, authors: int) -> SegmentChoice:
    return SegmentChoice(
        name=name,
        profile=AudienceProfile(),
        distinct_author_count=authors,
        demand_score=float(authors),
    )


def _report(
    authors: int,
    *,
    wedges: list[CandidateWedge] | None = None,
    segments: list[SegmentChoice] | None = None,
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
        total_distinct_authors=authors,
        ranked_clusters=[],
        candidate_wedges=wedges or [],
        segments=segments or [],
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


# Whole-report fallback (no forks) — exercises the surfaced absolute policy on the count.


def test_strong_demand_open_landscape_is_go() -> None:
    a = run_assessment(_deps(), _report(150), _landscape(competitors=1))
    assert a.decision == Decision.GO
    assert a.pivot_target is None
    assert a.gap.demand_strength == SignalStrength.HIGH
    assert a.gap.landscape_saturation == SignalStrength.LOW


def test_moderate_demand_open_landscape_is_go() -> None:
    a = run_assessment(_deps(), _report(30), _landscape(competitors=1))
    assert a.decision == Decision.GO
    assert a.gap.demand_strength == SignalStrength.MEDIUM


def test_thin_demand_is_no_go() -> None:
    a = run_assessment(_deps(), _report(5), _landscape(competitors=1))
    assert a.decision == Decision.NO_GO
    assert a.gap.demand_strength == SignalStrength.LOW


def test_strong_demand_saturated_with_fork_is_pivot() -> None:
    # a real-breadth wedge (its OWN demand is what's scored now) in a crowded space → PIVOT to it.
    report = _report(150, wedges=[_wedge("narrow", 150)])
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
    # would be GO (strong fork, low supply) but the landscape is partial → PIVOT, never GO
    report = _report(150, wedges=[_wedge("w", 150)])
    a = run_assessment(_deps(), report, _landscape(competitors=1, partial=True))
    assert a.decision == Decision.PIVOT  # anti-confirmation guard
    assert a.partial is True
    assert a.caveat == "partial scan"


def test_partial_landscape_thin_demand_is_no_go() -> None:
    a = run_assessment(_deps(), _report(5), _landscape(partial=True))
    assert a.decision == Decision.NO_GO


def test_assessment_id_and_evidence_shape() -> None:
    a = run_assessment(_deps(), _report(150), _landscape(competitors=1))
    assert a.assessment_id.startswith("as:")
    assert a.report_id == "rpt-1"
    assert a.rationale  # falls back to the deterministic reasoning when no model rationale


# ── per-fork verdicts (the un-collapsed answer) ───────────────────────────────


def test_fork_verdicts_differentiate_by_relative_demand() -> None:
    # Two wedges in an OPEN space: the broad one clears MEDIUM (GO), the narrow one is LOW (NO-GO).
    report = _report(200, wedges=[_wedge("broad", 100), _wedge("narrow", 20)])
    a = run_assessment(_deps(), report, _landscape(competitors=1))
    assert a.decision == Decision.GO  # top-line = best fork
    by_label = {f.label: f for f in a.fork_verdicts}
    assert by_label["broad"].decision == Decision.GO
    assert by_label["narrow"].decision == Decision.NO_GO
    assert by_label["broad"].demand_percentile > by_label["narrow"].demand_percentile


def test_pivot_targets_the_strongest_fork_across_kinds() -> None:
    # Saturated space, no fork GOes; the strongest pivotable is a SEGMENT, not a wedge.
    report = _report(
        200, wedges=[_wedge("w", 30)], segments=[_segment("enterprise", 150), _segment("hobby", 5)]
    )
    a = run_assessment(_deps(), report, _landscape(competitors=6))
    assert a.decision == Decision.PIVOT
    assert a.pivot_target is not None
    assert a.pivot_target.kind == "segment"
    assert any(s.id == a.pivot_target.target_id for s in report.segments)


def test_confidence_is_low_on_a_band_edge() -> None:
    # Three forks: the middle sits exactly on the MEDIUM percentile cut → near-zero confidence.
    report = _report(60, wedges=[_wedge("hi", 30), _wedge("mid", 20), _wedge("lo", 10)])
    a = run_assessment(_deps(), report, _landscape(competitors=1))
    mid = next(f for f in a.fork_verdicts if f.label == "mid")
    assert mid.demand_percentile == 1 / 3  # exactly the medium cut
    assert mid.confidence < 0.1


def test_old_assessment_payload_validates() -> None:
    # Additive parity: a pre-fork Assessment (no fork_verdicts, no new gap fields) round-trips.
    from metalworks.contract import Assessment

    payload = {
        "assessment_id": "as:abc",
        "report_id": "rpt-1",
        "decision": "go",
        "rationale": "ship it",
        "gap": {
            "demand_strength": "high",
            "demand_summary": "Strong demand — 150 distinct voices.",
            "landscape_saturation": "low",
        },
        "generated_at": _CLOCK.isoformat(),
    }
    a = Assessment.model_validate(payload)
    assert a.fork_verdicts == []
    assert a.gap.confidence is None and a.gap.reference == ""


# ── MCP ───────────────────────────────────────────────────────────────────────


def test_mcp_assess_not_found(monkeypatch: Any) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.assess_from_report("nope")
    assert res["error"]["error_code"] == "not_found"
