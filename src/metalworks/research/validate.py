"""The validate loop — ideate → demand → landscape → assess, looping on PIVOT.

``validate(deps, idea, *, decide=...)`` runs the discovery loop headlessly. Each
round produces a GO/PIVOT/NO-GO verdict; the ``decide`` callback chooses the lane
(default ``--auto``: take the assessment's own deterministic recommendation). GO
exits, NO-GO terminates, PIVOT loops toward the under-served fork — accumulating a
decision log and refusing to re-propose a killed idea (semantic dedup on the idea
text, NOT a hash id, since content-addressed ids recompute every round).

The interactive, human-gated loop lives in the ``validate`` skill, which drives
the discrete ideate / landscape / assess tools and lets the human be the callback;
this SDK orchestrator is the headless ``--auto`` path (review fix #8).

The four stages are injectable so the loop is unit-testable offline without a
real corpus pull.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from metalworks.contract import Assessment, DemandReport, Landscape
from metalworks.contract.assess import Decision
from metalworks.contract.ideate import IdeaSketch
from metalworks.contract.validate import DecisionLogEntry, ValidationResult
from metalworks.research.assess import run_assessment
from metalworks.research.ideate import ideate_from_idea
from metalworks.research.landscape import run_landscape

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps


@dataclass(frozen=True)
class ValidationStep:
    """What the ``decide`` callback sees each round."""

    iteration: int
    idea: str
    report: DemandReport
    landscape: Landscape
    assessment: Assessment


DecideFn = Callable[[ValidationStep], Decision]
IdeateFn = Callable[["ResearchDeps", str], IdeaSketch]
ResearchFn = Callable[["ResearchDeps", IdeaSketch], DemandReport]
LandscapeFn = Callable[["ResearchDeps", DemandReport], Landscape]
AssessFn = Callable[["ResearchDeps", DemandReport, Landscape], Assessment]


def _default_research(deps: ResearchDeps, sketch: IdeaSketch) -> DemandReport:
    from metalworks.research.pipeline import run_research

    brief = sketch.brief
    if brief is None:
        from metalworks.research.planner import brief_from_question

        brief = brief_from_question(deps, sketch.idea)
    return run_research(deps, brief=brief)


def _auto(step: ValidationStep) -> Decision:
    """The headless default: take the round's own deterministic recommendation."""
    return step.assessment.decision


def validate(
    deps: ResearchDeps,
    idea: str,
    *,
    decide: DecideFn | None = None,
    max_iterations: int = 4,
    ideate_fn: IdeateFn | None = None,
    research_fn: ResearchFn | None = None,
    landscape_fn: LandscapeFn | None = None,
    assess_fn: AssessFn | None = None,
) -> ValidationResult:
    """Run the discovery loop from ``idea``. Returns where it landed + the decision log."""
    do_ideate = ideate_fn or ideate_from_idea
    do_research = research_fn or _default_research
    do_landscape = landscape_fn or run_landscape
    do_assess = assess_fn or run_assessment
    choose = decide or _auto

    seen: set[str] = set()
    log: list[DecisionLogEntry] = []
    current = idea
    final: Assessment | None = None
    outcome: str = "exhausted"

    for i in range(1, max_iterations + 1):
        norm = current.strip().lower()
        if norm in seen:  # circled back to a fork we already tried → done
            outcome = "exhausted"
            break
        seen.add(norm)

        sketch = do_ideate(deps, current)
        report = do_research(deps, sketch)
        landscape = do_landscape(deps, report)
        assessment = do_assess(deps, report, landscape)
        final = assessment
        decision = choose(
            ValidationStep(
                iteration=i, idea=current, report=report, landscape=landscape, assessment=assessment
            )
        )

        if decision is Decision.GO:
            log.append(_entry(i, current, decision, [], assessment))
            outcome = "go"
            break
        if decision is Decision.NO_GO:
            log.append(_entry(i, current, decision, [current], assessment))
            outcome = "no_go"
            break

        # PIVOT — aim at the under-served fork next round (its label is the seed).
        nxt = assessment.gap.open_wedge
        log.append(_entry(i, current, decision, [current], assessment))
        if not nxt or nxt.strip().lower() in seen:
            outcome = "exhausted"  # nothing new to pivot to
            break
        current = nxt

    return ValidationResult(
        outcome=outcome,  # type: ignore[arg-type]
        final_assessment=final,
        decision_log=log,
        iterations=len(log),
    )


def _entry(
    i: int, idea: str, decision: Decision, ruled_out: list[str], a: Assessment
) -> DecisionLogEntry:
    return DecisionLogEntry(
        iteration=i, idea=idea, decision=decision, ruled_out=ruled_out, why=a.gap.reasoning
    )
