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
    # A tied pair at the top lands at midrank 2/3 ≈ 0.667 — right on the HIGH cut
    # (0.66) — so its confidence is near zero even though the band itself is HIGH.
    report = _report(60, wedges=[_wedge("tieA", 30), _wedge("tieB", 30), _wedge("lo", 10)])
    a = run_assessment(_deps(), report, _landscape(competitors=1))
    tie = next(f for f in a.fork_verdicts if f.label == "tieA")
    assert tie.demand_percentile == 2 / 3  # sits on the 0.66 high cut
    assert tie.confidence < 0.1


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


# ── per-fork saturation gates the GO ──────────────────────────────────────────


def _tagged_landscape(comp_clusters: list[list[int]]) -> Landscape:
    comps = [
        Competitor(
            competitor_index=i,
            name=f"c{i}",
            kind="direct",
            one_liner="x",
            gaps=[],
            addresses_clusters=cl,
        )
        for i, cl in enumerate(comp_clusters, start=1)
    ]
    cm = CompetitorMap(
        map_id="cm:rpt-1",
        report_id="rpt-1",
        competitors=comps,
        status_quo_alternative=_status_quo(),
        generated_at=_CLOCK,
    )
    return Landscape(
        landscape_id="ls:rpt-1", report_id="rpt-1", competitor_map=cm, generated_at=_CLOCK
    )


def _wedge_on(label: str, breadth: int, clusters: list[int]) -> CandidateWedge:
    return CandidateWedge(
        label=label,
        pain=label,
        scope="minimal",
        breadth_count=breadth,
        distinct_author_count=breadth,
        cluster_ranks=clusters,
        evidence=[EvidenceRef(kind="cluster", cluster_rank=clusters[0])],
    )


def test_per_fork_saturation_diverges_by_cluster() -> None:
    # Two wedges on different clusters; ALL supply tags cluster 1 → wedge-1 crowded, wedge-2 open.
    report = _report(
        200,
        wedges=[_wedge_on("indie", 100, [1]), _wedge_on("enterprise", 100, [2])],
    )
    land = _tagged_landscape([[1]] * 6)  # 6 rivals, all on cluster 1
    a = run_assessment(_deps(), report, land)
    by = {f.label: f for f in a.fork_verdicts}
    assert by["indie"].landscape_saturation == SignalStrength.HIGH  # 6 rivals hit its cluster
    assert by["enterprise"].landscape_saturation == SignalStrength.LOW  # none hit cluster 2
    # the report-level gap still reports the GLOBAL (space-level) saturation.
    assert a.gap.landscape_saturation == SignalStrength.HIGH


def test_fork_in_open_niche_goes_while_global_is_crowded() -> None:
    # The headline #80 scenario: a fork open inside a CROWDED space can GO. Two
    # equally-broad wedges; all 6 rivals crowd cluster 1, so the space (global)
    # saturation is HIGH — yet the cluster-2 wedge's OWN saturation is LOW, so the
    # GO gate (now per-fork) lets it GO while the report-level gap reads crowded.
    report = _report(
        200,
        wedges=[_wedge_on("indie", 100, [1]), _wedge_on("enterprise", 100, [2])],
    )
    land = _tagged_landscape([[1]] * 6)  # 6 rivals, all on cluster 1 → global HIGH
    a = run_assessment(_deps(), report, land)
    by = {f.label: f for f in a.fork_verdicts}
    assert a.gap.landscape_saturation == SignalStrength.HIGH  # the space is crowded
    assert by["indie"].decision == Decision.NO_GO  # its own niche is crowded
    assert by["enterprise"].decision == Decision.GO  # but THIS niche is open → GO
    assert a.decision == Decision.GO  # a fork GOes → top-line GO


def test_untagged_landscape_falls_back_to_global_per_fork() -> None:
    # No competitor carries cluster tags → per-fork can't distinguish → each fork shows global.
    report = _report(200, wedges=[_wedge_on("a", 100, [1]), _wedge_on("b", 100, [2])])
    land = _tagged_landscape([[], [], []])  # 3 rivals, none tagged
    a = run_assessment(_deps(), report, land)
    glob = a.gap.landscape_saturation
    assert all(f.landscape_saturation == glob for f in a.fork_verdicts)
