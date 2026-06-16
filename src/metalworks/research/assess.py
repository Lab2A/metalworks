"""Assess — the GO / PIVOT / NO-GO gap verdict (the heart of the validate loop).

``run_assessment(deps, report, landscape) -> Assessment``. The **decision is a
pure, deterministic function** of demand strength x landscape saturation — so it
is defensible and unit-testable; the LLM only writes the human-facing rationale.

Demand strength comes from distinct-author breadth (the same bands as
``derive_verdict``). Saturation is computed from what the code actually has:
the supply count (named competitors + empirically-found existing solutions),
NOT a "dropped-gap" measure that the competitor map can't produce. The
anti-confirmation rule is enforced in code: a ``partial`` landscape can never
yield a hard GO.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.contract import DemandReport, EvidenceRef, Landscape, SignalStrength
from metalworks.contract.assess import Assessment, Decision, GapAnalysis, PivotTarget
from metalworks.research.synthesis.verdict import derive_verdict

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

_STRONG_AUTHORS = 100
_MODERATE_AUTHORS = 25
_SATURATED_SUPPLY = 6
_SOME_SUPPLY = 3
_MAX_RATIONALE_TOKENS = 512


def _demand_strength(n: int) -> tuple[SignalStrength, str]:
    if n >= _STRONG_AUTHORS:
        return SignalStrength.HIGH, "strong"
    if n >= _MODERATE_AUTHORS:
        return SignalStrength.MEDIUM, "moderate"
    return SignalStrength.LOW, "thin"


def _saturation(landscape: Landscape) -> SignalStrength:
    """How crowded the supply is, from what we actually found — named competitors
    plus empirically-pulled existing solutions. HIGH-severity gaps are openings, so
    their presence holds saturation down even when supply is large."""
    cm = landscape.competitor_map
    supply = len(landscape.existing_solutions) + len(cm.competitors)
    openings = any(g.severity == SignalStrength.HIGH for c in cm.competitors for g in c.gaps)
    if supply >= _SATURATED_SUPPLY and not openings:
        return SignalStrength.HIGH
    if supply >= _SOME_SUPPLY:
        return SignalStrength.MEDIUM
    return SignalStrength.LOW


def _decide(
    report: DemandReport, landscape: Landscape
) -> tuple[Decision, SignalStrength, SignalStrength, PivotTarget | None, str | None, str]:
    """The pure verdict function. Returns
    (decision, demand_strength, saturation, pivot_target, open_label, reasoning)."""
    # Demand: when the run is narrowed to a chosen wedge (a PIVOT round), evaluate
    # THAT wedge's breadth, not the whole report — so a narrowed re-assess reflects
    # the fork actually under consideration.
    active = report.active_wedge if report.chosen_wedge_id else None
    n = (
        (active.breadth_count or active.distinct_author_count)
        if active
        else report.total_distinct_authors
    )
    demand, demand_word = _demand_strength(n)
    saturation = _saturation(landscape)
    moderate_plus = demand in (SignalStrength.MEDIUM, SignalStrength.HIGH)

    # The fork to pivot to: the strongest wedge we are NOT already focused on, else
    # the strongest (not-yet-chosen) segment. Excluding the active fork lets the loop
    # explore a genuinely new angle each PIVOT — and terminate when it runs out.
    pivot_wedge = max(
        (w for w in report.candidate_wedges if w.id != report.chosen_wedge_id),
        key=lambda w: w.breadth_count,
        default=None,
    )
    seg = report.default_segment
    if pivot_wedge is not None:
        fork_kind, fork_id, open_label = "wedge", pivot_wedge.id, pivot_wedge.label
    elif seg is not None and seg.id != report.chosen_segment_id:
        fork_kind, fork_id, open_label = "segment", seg.id, seg.name
    else:
        fork_kind, fork_id, open_label = None, None, None
    has_pivot = fork_id is not None

    if landscape.partial:
        # Anti-confirmation: never GO off partial grounding (absence of evidence
        # is not absence of competition).
        if moderate_plus and has_pivot:
            decision = Decision.PIVOT
            reasoning = (
                "Demand is real, but the landscape grounding was partial — pivot to the "
                "narrowest under-served fork rather than commit on incomplete supply data."
            )
        else:
            decision = Decision.NO_GO
            reasoning = (
                "Landscape grounding was partial and demand is thin or there is no fork to "
                "pivot to — not enough to commit."
            )
    elif moderate_plus and saturation == SignalStrength.LOW:
        decision = Decision.GO
        reasoning = f"{demand_word.capitalize()} demand and little exists today — an open lane."
    elif moderate_plus and has_pivot:
        decision = Decision.PIVOT
        reasoning = (
            f"{demand_word.capitalize()} demand, but the obvious space is crowded — aim at the "
            "under-served fork instead of competing head-on."
        )
    else:
        decision = Decision.NO_GO
        reasoning = (
            "Thin demand — treat as exploratory."
            if not moderate_plus
            else "Crowded supply with no open fork to pivot to."
        )

    pivot_target = None
    if decision == Decision.PIVOT and fork_kind is not None and fork_id is not None:
        pivot_target = PivotTarget(kind=fork_kind, target_id=fork_id, why=reasoning)
    return decision, demand, saturation, pivot_target, open_label, reasoning


def _rationale(
    deps: ResearchDeps, report: DemandReport, decision: Decision, gap: GapAnalysis
) -> str | None:
    pains = "\n".join(f"- {c.claim}" for c in report.ranked_clusters[:3])
    system = (
        "You are a blunt startup advisor. In 2-3 sentences, argue the given GO/PIVOT/NO-GO "
        "verdict honestly — cite the demand strength and what already exists. Do not hedge, "
        "do not invent evidence, do not soften a NO-GO."
    )
    user = (
        f"Idea: {report.query}\n"
        f"Verdict: {decision.value}\n"
        f"Demand: {gap.demand_summary}\n"
        f"Landscape saturation: {gap.landscape_saturation.value}\n"
        f"Top pains:\n{pains}"
    )
    try:
        result = deps.chat.complete_text(system=system, user=user, max_tokens=_MAX_RATIONALE_TOKENS)
        return (result.text or "").strip() or None
    except Exception:
        return None


def run_assessment(deps: ResearchDeps, report: DemandReport, landscape: Landscape) -> Assessment:
    """Compute the GO / PIVOT / NO-GO verdict for a report over its landscape."""
    decision, demand, saturation, pivot_target, open_label, reasoning = _decide(report, landscape)
    demand_summary = derive_verdict(
        total_distinct_authors=report.total_distinct_authors,
        market=report.market_sizing,
        price=report.price_finding,
    )
    gap = GapAnalysis(
        demand_strength=demand,
        demand_summary=demand_summary,
        landscape_saturation=saturation,
        open_wedge=open_label,
        reasoning=reasoning,
    )
    top = sorted(report.ranked_clusters, key=lambda c: c.demand_score, reverse=True)[:3]
    evidence = [EvidenceRef(kind="cluster", cluster_rank=c.rank) for c in top]
    rationale = _rationale(deps, report, decision, gap) or reasoning
    return Assessment(
        assessment_id=Assessment.make_id(report.report_id),
        report_id=report.report_id,
        decision=decision,
        rationale=rationale,
        gap=gap,
        pivot_target=pivot_target,
        evidence=evidence,
        partial=landscape.partial,
        caveat=landscape.caveat if landscape.partial else None,
        generated_at=deps.clock(),
    )
