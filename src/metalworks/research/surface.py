"""Pillar C — Surface decision + UX skeleton (Design stage).

Two grounded artifacts from the demand + positioning evidence:

- ``decide_surface(deps, report, positioning) -> SurfaceRecommendation`` — picks
  the surface to build against a FIXED five-dimension rubric. One LLM call
  phrases each dimension's finding + the chosen surface + trade-offs; the service
  then GROUNDS each dimension by cosine-matching its finding to the report's real
  evidence (cluster quotes / web findings). A dimension with no match is marked
  ``is_assumption``; ``confidence`` is service-assigned from how many dimensions
  are actually grounded. Thin grounding → ``partial`` (a labelled hypothesis).
- ``build_ux_skeleton(deps, report, positioning, surface) -> UxSkeleton`` — a 3-5
  screen skeleton. Each screen is grounded the same way; a screen with no backing
  voice ships ``validated=False`` (an explicit hypothesis), never silently.

Highest grounding risk of any pillar: the DECISION grounds, aesthetics do not.
This module ships text + structure only — no pixels — and the design handoff
(:class:`~metalworks.contract.surface.DesignBrief`) is explicitly ungrounded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    DemandReport,
    EvidenceRef,
    PositioningBrief,
    RubricDimension,
    Screen,
    SignalStrength,
    SurfaceRecommendation,
    TradeOff,
    UxSkeleton,
)
from metalworks.contract.surface import RubricName, SurfaceKind

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

# Cosine floor for grounding a finding to a real complaint. Deliberately strict:
# real embeddings score loosely related text ~0.5-0.6, and over-attributing a
# "no signal" rubric finding to a quote would inflate confidence on the
# highest-grounding-risk pillar. Under-claim (more honest assumptions) instead.
_MATCH_THRESHOLD = 0.7
_MAX_REFS = 2
_RUBRIC_ORDER: tuple[RubricName, ...] = (
    "where_are_the_users",
    "technical_sophistication",
    "usage_frequency",
    "realtime_or_hardware",
    "distribution",
)
_MAX_TOKENS = 1536


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _RubricItem(BaseModel):
    name: RubricName
    finding: str = Field(description="What the evidence implies for this dimension.")


class _SurfacePhrasing(BaseModel):
    chosen: SurfaceKind = Field(description="The recommended surface.")
    runner_up: SurfaceKind | None = Field(default=None)
    rationale: str = Field(description="One short paragraph on why the chosen surface.")
    rubric: list[_RubricItem] = Field(default_factory=list[_RubricItem])
    trade_offs: list[str] = Field(default_factory=list[str])


class _ScreenItem(BaseModel):
    name: str
    purpose: str
    primary_action: str
    serves_wedge: bool = False


class _UxPhrasing(BaseModel):
    screens: list[_ScreenItem] = Field(default_factory=list[_ScreenItem])


# ── grounding (cosine-match findings to real evidence) ───────────────────────


def _evidence_texts(report: DemandReport) -> tuple[dict[str, str], dict[str, str]]:
    """(id → text, id → kind) over the report's quotes + web findings."""
    texts: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for c in report.ranked_clusters:
        for q in c.quotes:
            texts[q.id] = q.text
            kinds[q.id] = "quote"
    for w in report.web_findings:
        texts[w.id] = w.claim
        kinds[w.id] = "web"
    return texts, kinds


def _match_refs(
    deps: ResearchDeps,
    claim_texts: list[str],
    evidence_texts: dict[str, str],
    kinds: dict[str, str],
) -> dict[int, list[EvidenceRef]]:
    """Map each claim (by index) to up to _MAX_REFS resolvable refs above threshold."""
    if not claim_texts or not evidence_texts:
        return {}
    from metalworks.stores.vectors import cosine_topk

    ids = list(evidence_texts)
    try:
        ev_vecs = deps.embeddings.embed([evidence_texts[i] for i in ids], task="document")
        claim_vecs = deps.embeddings.embed(claim_texts, task="document")
        vectors = {ids[i]: ev_vecs[i] for i in range(len(ids))}
        tops = [cosine_topk(cv, vectors, _MAX_REFS) for cv in claim_vecs]
    except Exception:  # embeddings down or numpy ([research] extra) absent → no grounding
        return {}
    out: dict[int, list[EvidenceRef]] = {}
    for ci, hits in enumerate(tops):
        refs = [
            EvidenceRef(evidence_id=ev_id, kind=kinds[ev_id])  # type: ignore[arg-type]
            for ev_id, score in hits
            if score >= _MATCH_THRESHOLD and ev_id in kinds
        ]
        if refs:
            out[ci] = refs
    return out


def _confidence(grounded_dims: int, total_dims: int) -> SignalStrength:
    if total_dims and grounded_dims >= max(4, total_dims - 1):
        return SignalStrength.HIGH
    if grounded_dims >= 2:
        return SignalStrength.MEDIUM
    return SignalStrength.LOW


# ── stage 1: surface recommendation ──────────────────────────────────────────


def _surface_context(report: DemandReport, positioning: PositioningBrief) -> str:
    segs = ", ".join(s.name for s in report.segments[:3]) or "unspecified"
    pains = "\n".join(f"- {c.claim}" for c in report.ranked_clusters[:5])
    wedge = positioning.wedge.unique_attribute if positioning.wedge else "(no wedge)"
    return (
        f"Product idea: {report.query}\n"
        f"Audience segments: {segs}\n"
        f"Positioning wedge: {wedge}\n"
        f"Top consumer pains:\n{pains}"
    )


def decide_surface(
    deps: ResearchDeps, report: DemandReport, positioning: PositioningBrief
) -> SurfaceRecommendation:
    """Recommend the surface to build, with a grounded rubric + trade-offs."""
    ctx = _surface_context(report, positioning)
    system = (
        "You recommend ONE product surface (sdk, web, mobile, cli, browser_extension, api, "
        "desktop) for a founder, judged on a fixed rubric: where_are_the_users, "
        "technical_sophistication, usage_frequency, realtime_or_hardware, distribution. For each "
        "rubric dimension write a one-line finding grounded in the evidence below. Then choose the "
        "surface, a runner_up, a short rationale, and 2-3 trade-offs. Do not invent user facts; if "
        "a dimension has no signal, say so plainly (it will be marked an assumption)."
    )
    try:
        phrasing = deps.chat.complete_structured(
            system=system,
            user=ctx,
            output_model=_SurfacePhrasing,
            max_tokens=_MAX_TOKENS,
            temperature=0.3,
        )
    except Exception as exc:
        return SurfaceRecommendation(
            report_id=report.report_id,
            chosen="web",
            rationale=f"Surface synthesis unavailable ({type(exc).__name__}).",
            confidence=SignalStrength.LOW,
            generated_at=deps.clock(),
            partial=True,
            caveat="Recommendation unavailable; defaulting to web as a placeholder hypothesis.",
        )

    ev_texts, kinds = _evidence_texts(report)
    # Keep only the fixed dimensions, in canonical order; ground each.
    by_name = {item.name: item for item in phrasing.rubric}
    findings: list[tuple[RubricName, str]] = [
        (name, by_name[name].finding) for name in _RUBRIC_ORDER if name in by_name
    ]
    matched = _match_refs(deps, [f for _, f in findings], ev_texts, kinds)
    rubric: list[RubricDimension] = []
    grounded = 0
    for i, (name, finding) in enumerate(findings):
        refs = matched.get(i, [])
        if refs:
            grounded += 1
        rubric.append(
            RubricDimension(name=name, finding=finding, evidence_refs=refs, is_assumption=not refs)
        )

    trade_matched = _match_refs(deps, phrasing.trade_offs, ev_texts, kinds)
    trade_offs = [
        TradeOff(text=t, evidence_refs=trade_matched.get(i, []))
        for i, t in enumerate(phrasing.trade_offs)
        if t.strip()
    ]

    confidence = _confidence(grounded, len(_RUBRIC_ORDER))
    partial = grounded < 2
    caveat = (
        "Thin grounding: fewer than two rubric dimensions are evidence-backed — treat the "
        "surface pick as a hypothesis, not a finding."
        if partial
        else None
    )
    return SurfaceRecommendation(
        report_id=report.report_id,
        chosen=phrasing.chosen,
        runner_up=phrasing.runner_up,
        rationale=phrasing.rationale.strip(),
        rubric=rubric,
        trade_offs=trade_offs,
        confidence=confidence,
        generated_at=deps.clock(),
        partial=partial,
        caveat=caveat,
    )


# ── stage 2: UX skeleton ─────────────────────────────────────────────────────


def build_ux_skeleton(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief,
    surface: SurfaceKind,
) -> UxSkeleton:
    """A 3-5 screen skeleton for ``surface``; unbacked screens ship as hypotheses."""
    wedge = positioning.wedge.unique_attribute if positioning.wedge else "(no wedge)"
    pains = "\n".join(f"- {c.claim}" for c in report.ranked_clusters[:5])
    system = (
        "You sketch a 3-5 screen skeleton for the chosen product surface. Each screen has a name, "
        "a one-line purpose, and a single primary_action. Mark serves_wedge true when the screen "
        "directly delivers the positioning wedge. Text only — no visual design. Ground screens in "
        "the real pains; do not invent demand for a screen."
    )
    user = (
        f"Surface: {surface}\nPositioning wedge: {wedge}\n"
        f"Top consumer pains:\n{pains}\n\nSketch the screens."
    )
    try:
        phrasing = deps.chat.complete_structured(
            system=system,
            user=user,
            output_model=_UxPhrasing,
            max_tokens=_MAX_TOKENS,
            temperature=0.3,
        )
    except Exception as exc:
        return UxSkeleton(
            report_id=report.report_id,
            surface=surface,
            generated_at=deps.clock(),
            partial=True,
            caveat=f"UX synthesis unavailable ({type(exc).__name__}).",
        )

    ev_texts, kinds = _evidence_texts(report)
    matched = _match_refs(deps, [s.purpose for s in phrasing.screens], ev_texts, kinds)
    screens: list[Screen] = []
    for i, s in enumerate(phrasing.screens[:5]):
        refs = matched.get(i, [])
        screens.append(
            Screen(
                name=s.name,
                purpose=s.purpose,
                primary_action=s.primary_action,
                serves_wedge=s.serves_wedge,
                evidence_refs=refs,
                validated=bool(refs),
            )
        )
    unvalidated = sum(1 for s in screens if not s.validated)
    caveat = (
        f"{unvalidated} of {len(screens)} screens are unvalidated (no backing voice) — "
        "treat those as hypotheses to test."
        if unvalidated
        else None
    )
    return UxSkeleton(
        report_id=report.report_id,
        surface=surface,
        screens=screens,
        generated_at=deps.clock(),
        partial=bool(unvalidated),
        caveat=caveat,
    )
