"""The validate loop (light-by-default).

GO exits, NO-GO terminates, the cap holds, and — the headline — a PIVOT to a fork the
report already surfaced REUSES the corpus (no re-pull): research runs once. A pivot that
leaves the corpus triggers a fresh pull. The four stages are injected, so no real pull.
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
    Fork,
    Landscape,
    SignalStrength,
)
from metalworks.contract.assess import Assessment, GapAnalysis, PivotTarget
from metalworks.contract.ideate import IdeaSketch
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.validate import ValidationStep, validate
from metalworks.stores import MemoryStores

_CLOCK = datetime(2026, 2, 2, tzinfo=UTC)
_W1 = CandidateWedge(label="wedge one", pain="pain one", scope="minimal", breadth_count=30)
_W2 = CandidateWedge(label="wedge two", pain="pain two", scope="broad", breadth_count=20)


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


def _report() -> DemandReport:
    return DemandReport(
        report_id="rpt-1",
        query="q",
        fork=Fork.BOTH,
        pinned_axis="",
        optimized_axis="",
        date_range_start=_CLOCK,
        date_range_end=_CLOCK,
        total_threads=1,
        total_distinct_authors=50,
        ranked_clusters=[],
        candidate_wedges=[_W1, _W2],
        generated_at=_CLOCK,
    )


def _landscape() -> Landscape:
    sq = Competitor(competitor_index=0, name="nothing", kind="status_quo", one_liner="x")
    cm = CompetitorMap(
        map_id="cm", report_id="rpt-1", status_quo_alternative=sq, generated_at=_CLOCK
    )
    return Landscape(landscape_id="ls", report_id="rpt-1", competitor_map=cm, generated_at=_CLOCK)


def _assessment(decision: Decision, *, pivot_to: str | None = None) -> Assessment:
    pt = PivotTarget(kind="wedge", target_id=pivot_to, why="aim narrower") if pivot_to else None
    gap = GapAnalysis(
        demand_strength=SignalStrength.HIGH,
        demand_summary="strong",
        landscape_saturation=SignalStrength.LOW,
        reasoning="because",
    )
    return Assessment(
        assessment_id="as:1",
        report_id="rpt-1",
        decision=decision,
        rationale="r",
        gap=gap,
        pivot_target=pt,
        generated_at=_CLOCK,
    )


def _ideate(_deps: Any, idea: str) -> IdeaSketch:
    return IdeaSketch(idea=idea, hypothesis=idea, provenance="idea-first")


def _run(
    script: list[Assessment], *, max_iterations: int = 4, decide: Any = None
) -> tuple[Any, dict[str, int]]:
    """Drive validate with a scripted assess sequence; count fresh research pulls."""
    counts = {"research": 0}

    def research_fn(_d: Any, _s: Any) -> DemandReport:
        counts["research"] += 1
        return _report()

    seq = list(script)

    def assess_fn(_d: Any, _r: DemandReport, _l: Landscape) -> Assessment:
        return seq.pop(0)

    result = validate(
        _deps(),
        "idea",
        decide=decide,
        max_iterations=max_iterations,
        ideate_fn=_ideate,
        research_fn=research_fn,
        landscape_fn=lambda _d, _r: _landscape(),
        assess_fn=assess_fn,
    )
    return result, counts


def test_go_exits_first_round() -> None:
    result, counts = _run([_assessment(Decision.GO)])
    assert result.outcome == "go"
    assert result.iterations == 1
    assert counts["research"] == 1
    assert result.decision_log[0].fresh_pull is True


def test_no_go_terminates() -> None:
    result, counts = _run([_assessment(Decision.NO_GO)])
    assert result.outcome == "no_go"
    assert counts["research"] == 1


def test_in_corpus_pivot_reuses_corpus_then_go() -> None:
    # round 1 PIVOT to a fork ALREADY in the report → reuse (no re-pull); round 2 GO
    result, counts = _run([_assessment(Decision.PIVOT, pivot_to=_W1.id), _assessment(Decision.GO)])
    assert result.outcome == "go"
    assert result.iterations == 2
    assert counts["research"] == 1  # the headline: corpus reused, NOT re-pulled
    assert result.decision_log[0].decision == Decision.PIVOT
    assert result.decision_log[0].fresh_pull is True  # round 1 = the one pull
    assert result.decision_log[1].fresh_pull is False  # round 2 reused the corpus


def test_out_of_corpus_pivot_triggers_fresh_pull() -> None:
    # PIVOT to an id NOT in the report → the loop must re-pull
    result, counts = _run(
        [_assessment(Decision.PIVOT, pivot_to="w:not-in-report"), _assessment(Decision.GO)]
    )
    assert result.outcome == "go"
    assert counts["research"] == 2  # a fresh pull happened
    assert result.decision_log[1].fresh_pull is True


def test_pivot_with_no_target_is_exhausted() -> None:
    result, counts = _run([_assessment(Decision.PIVOT, pivot_to=None)])
    assert result.outcome == "exhausted"
    assert counts["research"] == 1


def test_max_iterations_cap_yields_exhausted() -> None:
    # keep pivoting to in-corpus forks → never converges → cap → exhausted, still ONE pull
    result, counts = _run([_assessment(Decision.PIVOT, pivot_to=_W1.id)] * 3, max_iterations=2)
    assert result.outcome == "exhausted"
    assert result.iterations == 2
    assert counts["research"] == 1  # all reuse, no re-pulls


def test_custom_decide_overrides_recommendation() -> None:
    def human(_step: ValidationStep) -> Decision:
        return Decision.NO_GO

    result, _ = _run([_assessment(Decision.GO)], decide=human)
    assert result.outcome == "no_go"
