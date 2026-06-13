"""Pillar B — Market Positioning.

Turn a finished :class:`~metalworks.contract.research.DemandReport` into a
grounded Dunford wedge + price hypothesis (a
:class:`~metalworks.contract.positioning.PositioningBrief`).

The defensible-by-construction move: wedge SELECTION is deterministic. A wedge
only stands on an ``InsightCluster`` that the web stream is ``silent_web`` or
``disagree`` on (a real pain competitors miss) at ≥ MEDIUM signal — ranked by
``demand_score``. No such cluster → an honest null brief (``partial``), never an
invented angle. Exactly ONE LLM call phrases the three free-text slots
(``unique_attribute`` / ``value`` / ``market_category``) constrained to a Dunford
template; a second cheap pass verifies each authored clause is entailed by the
cited quotes and marks the brief ``partial`` if not. The price band is copied
through from the report's ``PriceFinding`` — never recomputed.

``build_positioning_brief(deps, report)`` is the reusable core behind the
``metalworks position`` CLI and the ``positioning_from_report`` MCP tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    DemandReport,
    EvidenceRef,
    InsightCluster,
    SignalStrength,
    WebFinding,
)
from metalworks.contract.positioning import (
    PositioningBrief,
    PriceHypothesis,
    WedgeClaim,
)

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

# Web-stream relations that mark genuine white space (a pain competitors miss).
_WHITESPACE = frozenset({"silent_web", "disagree"})
_SIGNAL_RANK = {SignalStrength.LOW: 1, SignalStrength.MEDIUM: 2, SignalStrength.HIGH: 3}
_MIN_SIGNAL = _SIGNAL_RANK[SignalStrength.MEDIUM]

_NULL_STATEMENT = (
    "No differentiated wedge: every strong demand cluster is echoed by the web "
    "(no silent-web or disagree signal at ≥ MEDIUM). A defensible position needs an "
    "angle competitors miss — none surfaced in this report."
)
_NULL_CAVEAT = (
    "Honest null: positioning needs at least one MEDIUM+ cluster the web stream is "
    "silent on or disagrees with. Re-run with broader web research, or treat the "
    "market as commoditized on the current evidence."
)


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _WedgePhrasing(BaseModel):
    """The only LLM-authored slots, constrained to a Dunford template."""

    competitive_alternative: str = Field(
        description="What the audience uses today (ground in the web findings / cluster)."
    )
    unique_attribute: str = Field(
        description="A verb-led capability clause completing 'the <category> that ___' — e.g. "
        "'fades post-acne marks without irritation'. NOT a noun phrase. Entailed by the quotes."
    )
    value: str = Field(
        description="A benefit clause completing 'so they ___' — e.g. 'get clearer skin in weeks'. "
        "Entailed by the quotes."
    )
    market_category: str = Field(description="The frame of reference (e.g. 'focus supplement').")


class _Entailment(BaseModel):
    unique_attribute_supported: bool = Field(
        description="True only if the cited quotes actually support the unique_attribute claim."
    )
    value_supported: bool = Field(
        description="True only if the cited quotes actually support the value claim."
    )
    note: str = Field(default="", description="One line on any unsupported clause.")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _price_hypothesis(report: DemandReport) -> PriceHypothesis | None:
    """Copy the report's PriceFinding through as a hypothesis (never recompute)."""
    pf = report.price_finding
    if pf is None:
        return None
    refs = [EvidenceRef(evidence_id=p.id, kind="price") for p in pf.evidence]
    if pf.insufficient_signal or pf.low is None or pf.high is None:
        return PriceHypothesis(
            framing="Insufficient price signal to recommend a band.",
            evidence=refs,
            insufficient_signal=True,
        )
    framing = (
        f"Van Westendorp-shaped band from {len(pf.evidence)} price mention(s): "
        f"PMC ≈ {pf.currency} {pf.low:g}, PME ≈ {pf.currency} {pf.high:g}."
    )
    return PriceHypothesis(
        low=pf.low, high=pf.high, currency=pf.currency, framing=framing, evidence=refs
    )


def _whitespace_clusters(report: DemandReport) -> list[InsightCluster]:
    """Clusters the web is silent on / disagrees with, ≥ MEDIUM, by demand_score."""
    ranks = {
        cr.cluster_rank for cr in report.cross_references if cr.agreement in _WHITESPACE
    }
    candidates = [
        c
        for c in report.ranked_clusters
        if c.rank in ranks and _SIGNAL_RANK.get(c.signal, 0) >= _MIN_SIGNAL
    ]
    return sorted(candidates, key=lambda c: c.demand_score, reverse=True)


def _cluster_web_findings(
    report: DemandReport, cluster: InsightCluster
) -> list[WebFinding]:
    """Web findings cross-referenced to this cluster (the competitive context)."""
    indices: set[int] = set()
    for cr in report.cross_references:
        if cr.cluster_rank == cluster.rank and cr.agreement in _WHITESPACE:
            indices.update(cr.web_finding_indices)
    return [w for w in report.web_findings if w.finding_index in indices]


def _beachhead(report: DemandReport) -> str:
    """The narrow first audience — deterministic, from segments/audience."""
    if report.segments:
        return report.segments[0].name
    ap = report.audience_profile
    if ap is not None and ap.age_range is not None and ap.age_range.estimate:
        return f"{ap.age_range.estimate} buyers in this niche"
    return "early adopters in this niche"


def _wedge_evidence(cluster: InsightCluster, webs: list[WebFinding]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = [EvidenceRef(kind="cluster", cluster_rank=cluster.rank)]
    refs += [EvidenceRef(evidence_id=q.id, kind="quote") for q in cluster.quotes]
    refs += [EvidenceRef(evidence_id=w.id, kind="web") for w in webs]
    return refs


def _statement(wedge: WedgeClaim) -> str:
    return (
        f"For {wedge.beachhead} who currently rely on {wedge.competitive_alternative}, "
        f"this is the {wedge.market_category} that {wedge.unique_attribute} — "
        f"so they {wedge.value}."
    )


# ── LLM passes (private) ─────────────────────────────────────────────────────


def _phrase_wedge(
    deps: ResearchDeps, cluster: InsightCluster, webs: list[WebFinding]
) -> _WedgePhrasing:
    quotes = "\n".join(f'- "{q.text}"' for q in cluster.quotes[:3])
    web_ctx = (
        "\n".join(f"- {w.claim}: {w.specifics}" for w in webs[:4])
        if webs
        else "(the web stream is SILENT on this pain — competitors don't address it)"
    )
    system = (
        "You phrase a Dunford positioning wedge from ALREADY-VERIFIED demand evidence, to drop "
        "into this exact sentence: 'For <audience> who rely on <competitive_alternative>, this is "
        "the <market_category> that <unique_attribute> — so they <value>.' So unique_attribute "
        "MUST be a verb-led clause (e.g. 'fades marks without irritation') and value MUST complete "
        "'so they ___' (e.g. 'get clearer skin in weeks'). Do not invent capabilities or "
        "audiences; if the quotes only describe a pain, phrase the attribute as solving exactly "
        "that pain, nothing more. Keep each field to one tight clause."
    )
    user = (
        f"Consumer demand cluster (the white space competitors miss):\n{cluster.claim}\n\n"
        f"Verbatim quotes backing it:\n{quotes}\n\n"
        f"What the web/market currently offers:\n{web_ctx}\n\n"
        "Phrase the wedge to fit the template: competitive_alternative (what they use today), "
        "unique_attribute (verb-led, entailed by the quotes), value (completes 'so they ___'), "
        "market_category (the everyday frame a buyer uses)."
    )
    return deps.chat.complete_structured(
        system=system,
        user=user,
        output_model=_WedgePhrasing,
        max_tokens=1024,
        temperature=0.3,
    )


def _verify_entailment(
    deps: ResearchDeps, cluster: InsightCluster, phrasing: _WedgePhrasing
) -> _Entailment:
    quotes = "\n".join(f'- "{q.text}"' for q in cluster.quotes[:3])
    model = deps.filter_model  # cheap model when configured, else the main chat
    system = (
        "You are a strict entailment checker. A claim is supported ONLY if the quotes below "
        "directly back it; do not give the benefit of the doubt. Plausible-but-unstated is "
        "NOT supported."
    )
    user = (
        f"Quotes:\n{quotes}\n\n"
        f"unique_attribute claim: {phrasing.unique_attribute}\n"
        f"value claim: {phrasing.value}\n\n"
        "For each claim, is it entailed by the quotes?"
    )
    return model.complete_structured(
        system=system,
        user=user,
        output_model=_Entailment,
        max_tokens=512,
        temperature=0.0,
    )


# ── Public entry ─────────────────────────────────────────────────────────────


def build_positioning_brief(deps: ResearchDeps, report: DemandReport) -> PositioningBrief:
    """Derive a grounded :class:`PositioningBrief` from a finished report.

    Deterministic wedge selection + one phrasing call + an entailment check. On
    no white space, or if phrasing fails, returns an honest ``partial`` brief
    (never an invented wedge). The price band is copied through from the report.
    """
    price = _price_hypothesis(report)
    candidates = _whitespace_clusters(report)
    if not candidates:
        return PositioningBrief(
            report_id=report.report_id,
            positioning_statement=_NULL_STATEMENT,
            wedge=None,
            price_hypothesis=price,
            partial=True,
            caveat=_NULL_CAVEAT,
        )

    cluster = candidates[0]
    webs = _cluster_web_findings(report, cluster)
    try:
        phrasing = _phrase_wedge(deps, cluster, webs)
    except Exception as exc:  # phrasing failed — return an honest partial, not a crash
        return PositioningBrief(
            report_id=report.report_id,
            positioning_statement=_NULL_STATEMENT,
            wedge=None,
            price_hypothesis=price,
            partial=True,
            caveat=f"Positioning synthesis unavailable ({type(exc).__name__}); wedge not phrased.",
        )

    wedge = WedgeClaim(
        competitive_alternative=phrasing.competitive_alternative.strip(),
        unique_attribute=phrasing.unique_attribute.strip(),
        value=phrasing.value.strip(),
        beachhead=_beachhead(report),
        market_category=phrasing.market_category.strip(),
        source_cluster_rank=cluster.rank,
        evidence=_wedge_evidence(cluster, webs),
    )

    # Entailment verification — the no-cite-no-claim generalization for free text.
    partial = False
    caveat: str | None = None
    try:
        check = _verify_entailment(deps, cluster, phrasing)
        unsupported: list[str] = []
        if not check.unique_attribute_supported:
            unsupported.append("unique_attribute")
        if not check.value_supported:
            unsupported.append("value")
        if unsupported:
            partial = True
            caveat = (
                f"Unverified clause(s) {', '.join(unsupported)}: not entailed by the cited "
                f"quotes ({check.note or 'no support found'}). Treat the wedge as a hypothesis."
            )
    except Exception:  # verification is best-effort — unverified, not fatal
        partial = True
        caveat = "Entailment check unavailable; wedge is unverified — treat as a hypothesis."

    return PositioningBrief(
        report_id=report.report_id,
        positioning_statement=_statement(wedge),
        wedge=wedge,
        price_hypothesis=price,
        partial=partial,
        caveat=caveat,
    )
