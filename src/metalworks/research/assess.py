"""Assess — the GO / PIVOT / NO-GO gap verdict (the heart of the validate loop).

``run_assessment(deps, report, landscape) -> Assessment``. The **decision is a
pure, deterministic function** of demand x landscape saturation — defensible and
unit-testable; the LLM only writes the human-facing rationale.

Demand is **relative**, not an absolute author count: each fork is scored by its
prevalence and its standing among the report's other forks (see
``synthesis.demand``), so the verdict is domain-portable. The decision is computed
**per fork** (``fork_verdicts``) and synthesized into the three-lane top-line:
any fork GOes -> GO; real demand in a crowded space -> PIVOT to the under-served
fork; else NO_GO. Saturation is the supply count (competitors + existing
solutions); each fork's GO gate uses its OWN per-fork saturation (a fork in an
open niche can GO inside a crowded space), while the report-level gap reports the
space-wide value. Anti-confirmation is enforced in code: a ``partial`` landscape
can never yield a hard GO.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metalworks.contract import DemandReport, EvidenceRef, Landscape, SignalStrength
from metalworks.contract.assess import (
    Assessment,
    Decision,
    ForkVerdict,
    GapAnalysis,
    PivotTarget,
)
from metalworks.research.synthesis import demand
from metalworks.research.synthesis.demand import DEFAULT_POLICY, AssessPolicy
from metalworks.research.synthesis.verdict import derive_verdict

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

_MAX_RATIONALE_TOKENS = 512


@dataclass(frozen=True)
class _Verdict:
    """The pure verdict result — top-line decision plus the un-collapsed per-fork answer."""

    decision: Decision
    demand_strength: SignalStrength
    saturation: SignalStrength
    demand_prevalence: float
    demand_percentile: float | None
    confidence: float
    reference: str
    open_wedge: str | None
    reasoning: str
    pivot_target: PivotTarget | None
    fork_verdicts: list[ForkVerdict]


def _saturation(landscape: Landscape, policy: AssessPolicy) -> SignalStrength:
    """How crowded the supply is, from what we actually found — named competitors
    plus empirically-pulled existing solutions. HIGH-severity gaps are openings, so
    their presence holds saturation down even when supply is large. Space-level — the
    report's headline saturation; the GO gate uses per-fork saturation
    (see ``_fork_saturation`` / ForkVerdict.landscape_saturation)."""
    cm = landscape.competitor_map
    supply = len(landscape.existing_solutions) + len(cm.competitors)
    openings = any(g.severity == SignalStrength.HIGH for c in cm.competitors for g in c.gaps)
    if supply >= policy.saturated_supply and not openings:
        return SignalStrength.HIGH
    if supply >= policy.some_supply:
        return SignalStrength.MEDIUM
    return SignalStrength.LOW


def _fork_saturation(
    fork_clusters: set[int],
    landscape: Landscape,
    policy: AssessPolicy,
    fallback: SignalStrength,
) -> SignalStrength:
    """Saturation for ONE fork — supply (competitors + existing solutions) whose addressed clusters
    intersect this fork's clusters. This GATES the fork's GO decision. Pure ints in, so the scorer
    never imports landscape types. Falls back to the global value when this fork has no cluster
    tags, or when nothing in the landscape is tagged at all (can't distinguish forks → don't pretend
    to), which makes gating on it strictly better than gating on global, never worse. status_quo is
    the do-nothing baseline, never counted as supply."""
    if not fork_clusters:
        return fallback
    cm = landscape.competitor_map
    comp = [c for c in cm.competitors if set(c.addresses_clusters) & fork_clusters]
    sols = [s for s in landscape.existing_solutions if set(s.addresses_clusters) & fork_clusters]
    supply = len(comp) + len(sols)
    if supply == 0:
        any_tagged = any(c.addresses_clusters for c in cm.competitors) or any(
            s.addresses_clusters for s in landscape.existing_solutions
        )
        # tagged landscape, none hits this fork → genuinely open; untagged → can't tell, fall back.
        return SignalStrength.LOW if any_tagged else fallback
    openings = any(g.severity == SignalStrength.HIGH for c in comp for g in c.gaps)
    if supply >= policy.saturated_supply and not openings:
        return SignalStrength.HIGH
    if supply >= policy.some_supply:
        return SignalStrength.MEDIUM
    return SignalStrength.LOW


def _segment_clusters(seg: object) -> set[int]:
    return {e.cluster_rank for e in getattr(seg, "evidence", []) if e.cluster_rank}


def _score_forks(
    report: DemandReport, landscape: Landscape, partial: bool, policy: AssessPolicy
) -> tuple[list[ForkVerdict], dict[str, str], SignalStrength]:
    """A GO/NO-GO verdict per candidate wedge AND segment, with relative demand.

    A fork GOes iff its (relative, self-calibrating) demand clears MEDIUM and ITS OWN slice of the
    space is open (the fork's ``landscape_saturation`` is LOW, and grounding isn't partial). Gating
    on per-fork saturation lets a fork in an open niche GO even when the whole space is crowded;
    ``_fork_saturation`` falls back to the global value when it can't distinguish the fork, so this
    is strictly better, never worse. Returns the verdicts, the self-calibration notes (keyed by fork
    id), and the global saturation (still used for the report-level ``gap.landscape_saturation``).
    """
    global_sat = _saturation(landscape, policy)
    forks: list[ForkVerdict] = []
    refs: dict[str, str] = {}
    wedge_breadths = [w.breadth_count for w in report.candidate_wedges]
    for w in report.candidate_wedges:
        band, prev, pct, conf, ref = demand.strength(
            w.breadth_count,
            w.distinct_author_count or w.breadth_count,
            report.total_distinct_authors,
            wedge_breadths,
            policy=policy,
        )
        fork_sat = _fork_saturation(set(w.cluster_ranks), landscape, policy, global_sat)
        go = demand.meets_medium(band) and fork_sat == SignalStrength.LOW and not partial
        forks.append(
            ForkVerdict(
                kind="wedge",
                fork_id=w.id,
                label=w.label,
                decision=Decision.GO if go else Decision.NO_GO,
                demand_strength=band,
                landscape_saturation=fork_sat,
                demand_prevalence=prev,
                demand_percentile=pct,
                confidence=conf,
                distinct_author_count=w.distinct_author_count,
            )
        )
        refs[w.id] = ref
    seg_authors = [s.distinct_author_count for s in report.segments]
    for s in report.segments:
        band, prev, pct, conf, ref = demand.strength(
            s.distinct_author_count,
            s.distinct_author_count,
            report.total_distinct_authors,
            seg_authors,
            policy=policy,
        )
        fork_sat = _fork_saturation(_segment_clusters(s), landscape, policy, global_sat)
        go = demand.meets_medium(band) and fork_sat == SignalStrength.LOW and not partial
        forks.append(
            ForkVerdict(
                kind="segment",
                fork_id=s.id,
                label=s.name,
                decision=Decision.GO if go else Decision.NO_GO,
                demand_strength=band,
                landscape_saturation=fork_sat,
                demand_prevalence=prev,
                demand_percentile=pct,
                confidence=conf,
                distinct_author_count=s.distinct_author_count,
            )
        )
        refs[s.id] = ref
    return forks, refs, global_sat


def _decide(report: DemandReport, landscape: Landscape, policy: AssessPolicy) -> _Verdict:
    """The pure verdict: score every fork, then synthesize the three-lane report decision.

    Each fork's GO gate uses ITS OWN ``landscape_saturation`` (per-fork); the report-level
    ``gap.landscape_saturation`` still reports the GLOBAL saturation of the space.
    """
    partial = landscape.partial
    forks, refs, saturation = _score_forks(report, landscape, partial, policy)
    # The fork the loop already narrowed to (a PIVOT round) — never pivot back to it.
    active_id = report.chosen_wedge_id or report.chosen_segment_id

    # No forks: whole-report fallback on the absolute policy (preserves single-report behavior).
    if not forks:
        band, prev, _pct, conf, reference = demand.strength(
            report.total_distinct_authors,
            report.total_distinct_authors,
            report.total_distinct_authors,
            [],
            policy=policy,
        )
        moderate_plus = demand.meets_medium(band)
        if partial:
            decision, reasoning = (
                Decision.NO_GO,
                "Landscape grounding was partial and there is no fork to pivot to.",
            )
        elif moderate_plus and saturation == SignalStrength.LOW:
            decision = Decision.GO
            reasoning = f"{demand.label_for(band)} and little exists today — an open lane."
        else:
            decision = Decision.NO_GO
            reasoning = (
                "Thin demand — treat as exploratory."
                if not moderate_plus
                else "Crowded supply with no open fork to pivot to."
            )
        return _Verdict(
            decision, band, saturation, prev, None, conf, reference, None, reasoning, None, []
        )

    # Forks present: the report's reported demand is the active (narrowed) fork, else the best.
    top = max(
        forks, key=lambda f: (demand.rank(f.demand_strength), f.confidence, f.demand_prevalence)
    )
    anchor = next((f for f in forks if f.fork_id == active_id), None) or top

    go_forks = [f for f in forks if f.decision is Decision.GO]
    open_wedge: str | None = None
    pivot_target: PivotTarget | None = None
    if go_forks:
        best = max(
            go_forks,
            key=lambda f: (demand.rank(f.demand_strength), f.confidence, f.demand_prevalence),
        )
        decision = Decision.GO
        reasoning = f"{demand.label_for(best.demand_strength)} on '{best.label}' — an open lane."
    else:
        pivotables = [
            f for f in forks if demand.meets_medium(f.demand_strength) and f.fork_id != active_id
        ]
        if pivotables:
            target = max(
                pivotables,
                key=lambda f: (demand.rank(f.demand_strength), f.confidence, f.demand_prevalence),
            )
            decision = Decision.PIVOT
            open_wedge = target.label
            reasoning = (
                "Demand is real but the landscape grounding was partial — aim at the under-served "
                f"'{target.label}' rather than commit on incomplete supply data."
                if partial
                else f"Real demand, but the obvious space is crowded — aim at '{target.label}'."
            )
            pivot_target = PivotTarget(kind=target.kind, target_id=target.fork_id, why=reasoning)
        else:
            decision = Decision.NO_GO
            any_strong = any(demand.meets_medium(f.demand_strength) for f in forks)
            reasoning = (
                "Crowded supply with no open fork to pivot to."
                if any_strong
                else "Thin demand across every fork — treat as exploratory."
            )

    return _Verdict(
        decision=decision,
        demand_strength=anchor.demand_strength,
        saturation=saturation,
        demand_prevalence=anchor.demand_prevalence,
        demand_percentile=anchor.demand_percentile,
        confidence=anchor.confidence,
        reference=refs.get(anchor.fork_id, ""),
        open_wedge=open_wedge,
        reasoning=reasoning,
        pivot_target=pivot_target,
        fork_verdicts=forks,
    )


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


def run_assessment(
    deps: ResearchDeps,
    report: DemandReport,
    landscape: Landscape,
    *,
    policy: AssessPolicy = DEFAULT_POLICY,
) -> Assessment:
    """Compute the GO / PIVOT / NO-GO verdict for a report over its landscape.

    The decision is a pure, deterministic function of relative demand x landscape
    saturation, computed per fork and synthesized into the three-lane verdict;
    ``fork_verdicts`` carries the un-collapsed per-fork answer. ``policy`` surfaces
    every threshold (defaulted) — see :class:`AssessPolicy`.
    """
    v = _decide(report, landscape, policy)
    demand_summary = derive_verdict(
        strength_label=demand.label_for(v.demand_strength),
        total_distinct_authors=report.total_distinct_authors,
        market=report.market_sizing,
        price=report.price_finding,
    )
    gap = GapAnalysis(
        demand_strength=v.demand_strength,
        demand_summary=demand_summary,
        landscape_saturation=v.saturation,
        open_wedge=v.open_wedge,
        reasoning=v.reasoning,
        demand_prevalence=v.demand_prevalence,
        demand_percentile=v.demand_percentile,
        confidence=v.confidence,
        reference=v.reference,
    )
    top = sorted(report.ranked_clusters, key=lambda c: c.demand_score, reverse=True)[:3]
    evidence = [EvidenceRef(kind="cluster", cluster_rank=c.rank) for c in top]
    rationale = _rationale(deps, report, v.decision, gap) or v.reasoning
    return Assessment(
        assessment_id=Assessment.make_id(report.report_id),
        report_id=report.report_id,
        decision=v.decision,
        rationale=rationale,
        gap=gap,
        pivot_target=v.pivot_target,
        fork_verdicts=v.fork_verdicts,
        evidence=evidence,
        partial=landscape.partial,
        caveat=landscape.caveat if landscape.partial else None,
        generated_at=deps.clock(),
    )
