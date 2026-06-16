"""The validate loop — GO exits, PIVOT loops to the target, NO-GO terminates,
the cap holds, and a killed fork never reappears (semantic dedup). Offline: the four
stages are injected, so no real corpus pull.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from metalworks.contract import (
    Competitor,
    CompetitorMap,
    Decision,
    DemandReport,
    Fork,
    Landscape,
    SignalStrength,
)
from metalworks.contract.assess import Assessment, GapAnalysis
from metalworks.contract.ideate import IdeaSketch
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.validate import ValidationStep, validate
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
        generated_at=_CLOCK,
    )


def _landscape() -> Landscape:
    sq = Competitor(competitor_index=0, name="nothing", kind="status_quo", one_liner="x")
    cm = CompetitorMap(
        map_id="cm", report_id="rpt-1", status_quo_alternative=sq, generated_at=_CLOCK
    )
    return Landscape(landscape_id="ls", report_id="rpt-1", competitor_map=cm, generated_at=_CLOCK)


def _assessment(decision: Decision, *, open_wedge: str | None = None) -> Assessment:
    gap = GapAnalysis(
        demand_strength=SignalStrength.HIGH,
        demand_summary="strong",
        landscape_saturation=SignalStrength.LOW,
        open_wedge=open_wedge,
        reasoning="because",
    )
    return Assessment(
        assessment_id="as:1",
        report_id="rpt-1",
        decision=decision,
        rationale="r",
        gap=gap,
        generated_at=_CLOCK,
    )


def _ideate(_deps: Any, idea: str) -> IdeaSketch:
    return IdeaSketch(idea=idea, hypothesis=idea, provenance="idea-first")


def _stages(assess_fn: Any) -> dict[str, Any]:
    return {
        "ideate_fn": _ideate,
        "research_fn": lambda _d, _s: _report(),
        "landscape_fn": lambda _d, _r: _landscape(),
        "assess_fn": assess_fn,
    }


class _Scripted:
    """Returns a scripted (decision, open_wedge) per call, recording the ideas seen."""

    def __init__(self, script: list[tuple[Decision, str | None]]) -> None:
        self._script = script
        self.ideas_assessed: list[str] = []

    def __call__(self, _deps: Any, report: DemandReport, _landscape: Landscape) -> Assessment:
        decision, open_wedge = self._script.pop(0)
        return _assessment(decision, open_wedge=open_wedge)


def test_go_exits_first_round() -> None:
    result = validate(_deps(), "x", **_stages(_Scripted([(Decision.GO, None)])))
    assert result.outcome == "go"
    assert result.iterations == 1
    assert result.decision_log[0].decision == Decision.GO
    assert result.final_assessment is not None


def test_no_go_terminates() -> None:
    result = validate(_deps(), "x", **_stages(_Scripted([(Decision.NO_GO, None)])))
    assert result.outcome == "no_go"
    assert result.iterations == 1


def test_pivot_loops_to_target_then_go() -> None:
    seen_ideas: list[str] = []

    def assess(_d: Any, _r: DemandReport, _l: Landscape) -> Assessment:
        # round 1 → PIVOT to "idea2"; round 2 → GO
        return script.pop(0)

    script = [_assessment(Decision.PIVOT, open_wedge="idea2"), _assessment(Decision.GO)]

    def ideate(_d: Any, idea: str) -> IdeaSketch:
        seen_ideas.append(idea)
        return IdeaSketch(idea=idea, hypothesis=idea, provenance="idea-first")

    result = validate(
        _deps(),
        "idea1",
        ideate_fn=ideate,
        research_fn=lambda _d, _s: _report(),
        landscape_fn=lambda _d, _r: _landscape(),
        assess_fn=assess,
    )
    assert result.outcome == "go"
    assert result.iterations == 2
    assert seen_ideas == ["idea1", "idea2"]  # the loop pivoted to the target
    assert result.decision_log[0].decision == Decision.PIVOT
    assert result.decision_log[0].ruled_out == ["idea1"]


def test_max_iterations_cap_yields_exhausted() -> None:
    # always PIVOT to a fresh fork → never converges → cap → exhausted
    script = [
        (Decision.PIVOT, "a"),
        (Decision.PIVOT, "b"),
        (Decision.PIVOT, "c"),
    ]
    result = validate(_deps(), "start", max_iterations=2, **_stages(_Scripted(list(script))))
    assert result.outcome == "exhausted"
    assert result.iterations == 2  # stopped at the cap


def test_pivot_back_to_seen_fork_is_exhausted() -> None:
    # PIVOT points back at the starting idea → already seen → exhausted, not an infinite loop
    result = validate(_deps(), "x", **_stages(_Scripted([(Decision.PIVOT, "x")])))
    assert result.outcome == "exhausted"
    assert result.iterations == 1


def test_custom_decide_callback_overrides_recommendation() -> None:
    # assessment says GO, but the human callback says NO-GO — the human wins
    def human(_step: ValidationStep) -> Decision:
        return Decision.NO_GO

    result = validate(_deps(), "x", decide=human, **_stages(_Scripted([(Decision.GO, None)])))
    assert result.outcome == "no_go"
