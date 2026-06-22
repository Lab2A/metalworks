"""Pillar D — build-spec generation (the grounded half).

``build_spec_from_report(deps, report, positioning, surface, *, stack) -> BuildSpec``
turns a finished report into an evidence-grounded :class:`~metalworks.contract.build.BuildSpec`
for the user's OWN Claude Code to build against (metalworks is not a coding agent).

Grounding is DETERMINISTIC, not embedding-fuzzy: one LLM call maps demand
clusters to candidate features, each tagged with the ``source_cluster_rank`` it
derives from; the builder then attaches THAT cluster's verified quotes as the
feature's evidence. A feature whose source cluster is invalid or quote-less is
dropped (no-cite-no-feature) — the LLM cannot smuggle in an un-grounded feature.
Personas are derived from the report's segments (each tied to the top demand
cluster's voice); pricing tiers are copied through from the report's price
evidence, never recomputed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    BuildPersona,
    BuildSpec,
    DemandReport,
    EvidenceRef,
    FeatureSpec,
    InsightCluster,
    PositioningBrief,
    PricingTier,
)
from metalworks.contract.surface import SurfaceKind

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

_MAX_FEATURES = 8
_MAX_PERSONAS = 3
_QUOTES_PER_FEATURE = 2
_MAX_TOKENS = 2048
# Sort key for a feature whose source-cluster rank is missing/malformed (≤ 0):
# push it to the end of the build order rather than ahead of rank-1 demand.
_RANK_LAST = 10_000


# ── LLM I/O (private) ────────────────────────────────────────────────────────


class _FeatureDraft(BaseModel):
    feature_id: str = Field(description="kebab-case slug, e.g. 'fade-tracker'.")
    title: str = Field(description="The feature in a few words.")
    rationale: str = Field(description="Which consumer pain it serves.")
    source_cluster_rank: int = Field(description="1-based InsightCluster.rank this derives from.")


class _BuildPhrasing(BaseModel):
    features: list[_FeatureDraft] = Field(default_factory=list[_FeatureDraft])


# ── helpers ──────────────────────────────────────────────────────────────────


def _cluster_by_rank(report: DemandReport) -> dict[int, InsightCluster]:
    # Keep-first on a duplicate rank: a malformed/hand-edited report could carry
    # two clusters at the same rank, and a plain comprehension would silently let
    # the later one win — attaching the WRONG cluster's quotes to a feature.
    by_rank: dict[int, InsightCluster] = {}
    for c in report.ranked_clusters:
        by_rank.setdefault(c.rank, c)
    return by_rank


def _first_quote_ref(report: DemandReport) -> list[EvidenceRef]:
    """A ref to the first real Reddit voice in the report (any cluster), or []."""
    for cluster in report.ranked_clusters:
        if cluster.quotes:
            return [EvidenceRef(evidence_id=cluster.quotes[0].id, kind="quote")]
    return []


def _personas(report: DemandReport) -> list[BuildPersona]:
    """ICPs derived from the report's segments, each tied to a real voice.

    A persona MUST carry a resolvable ref (no-cite-no-claim). When the report has
    no quote anywhere, no persona can be grounded, so none are emitted.
    """
    quote_ref = _first_quote_ref(report)
    if not quote_ref:
        return []
    out: list[BuildPersona] = []
    for seg in report.segments[:_MAX_PERSONAS]:
        prefs = "; ".join(seg.preferences[:3]) if seg.preferences else "unspecified preferences"
        out.append(
            BuildPersona(
                name=seg.name,
                description=f"{seg.name} — wants {prefs}.",
                evidence=list(quote_ref),
            )
        )
    if not out:
        # No segments — derive one persona from the strongest grounded cluster.
        anchor = next(c for c in report.ranked_clusters if c.quotes)
        out.append(
            BuildPersona(
                name="Core user",
                description=f"The audience behind: {anchor.claim}",
                evidence=list(quote_ref),
            )
        )
    return out


def _pricing_tiers(report: DemandReport) -> list[PricingTier]:
    """Tiers copied through from the report's price evidence (never recomputed).

    No-cite-no-claim applies to price too: with no price evidence to cite, no
    tier is emitted — a price the report can't back never ships.
    """
    pf = report.price_finding
    if pf is None or pf.insufficient_signal or not pf.evidence:
        return []
    refs = [EvidenceRef(evidence_id=p.id, kind="price") for p in pf.evidence]
    tiers: list[PricingTier] = []
    if pf.low is not None:
        tiers.append(
            PricingTier(
                name="Starter",
                price=pf.low,
                currency=pf.currency,
                rationale="The low end of observed willingness to pay.",
                evidence=list(refs),
            )
        )
    if pf.high is not None and pf.high != pf.low:
        tiers.append(
            PricingTier(
                name="Pro",
                price=pf.high,
                currency=pf.currency,
                rationale="The high end of observed willingness to pay.",
                evidence=list(refs),
            )
        )
    return tiers


def _ground_features(report: DemandReport, drafts: list[_FeatureDraft]) -> list[FeatureSpec]:
    """Attach each feature's source cluster's quotes; drop the un-grounded ones.

    The result is ordered as the BUILD ORDER — strongest validated demand first
    (by the source cluster's rank) — then capped, so the cap keeps the highest-
    demand features rather than whatever order the LLM happened to draft. This is
    the deterministic, grounded residue of the build-blueprint exploration: the
    sequence comes from real demand, and ``features[0]`` is the spine to build
    first. No new LLM call — the rank is already on each draft.
    """
    by_rank = _cluster_by_rank(report)
    seen: set[str] = set()
    out: list[FeatureSpec] = []
    for d in drafts:
        cluster = by_rank.get(d.source_cluster_rank)
        if cluster is None or not cluster.quotes:
            continue  # no-cite-no-feature
        fid = d.feature_id.strip() or f"feature-{d.source_cluster_rank}"
        if fid in seen:
            continue
        seen.add(fid)
        refs = [
            EvidenceRef(evidence_id=q.id, kind="quote")
            for q in cluster.quotes[:_QUOTES_PER_FEATURE]
        ]
        out.append(
            FeatureSpec(
                feature_id=fid,
                title=d.title.strip(),
                rationale=d.rationale.strip(),
                evidence=refs,
                source_cluster_rank=d.source_cluster_rank,
            )
        )
    # Order by grounded demand (rank 1 first), then cap. Stable sort preserves the
    # LLM's relative order within a single cluster. Ties on rank are rare (features
    # usually map to distinct clusters); a malformed rank ≤ 0 sorts last.
    out.sort(key=lambda f: f.source_cluster_rank if f.source_cluster_rank > 0 else _RANK_LAST)
    return out[:_MAX_FEATURES]


# ── public entry ─────────────────────────────────────────────────────────────


def build_spec_from_report(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None = None,
    surface: SurfaceKind = "web",
    *,
    stack: str = "empty",
) -> BuildSpec:
    """Derive an evidence-grounded :class:`BuildSpec` from a finished report."""
    wedge = (
        positioning.wedge.unique_attribute
        if positioning is not None and positioning.wedge is not None
        else "(no positioning wedge)"
    )
    pains = "\n".join(
        f"- [cluster {c.rank}] {c.claim}" for c in report.ranked_clusters[:_MAX_FEATURES]
    )
    system = (
        "You turn validated consumer demand into a SHORT product feature list for a founder to "
        "build. Each feature must derive from ONE of the numbered demand clusters below — set "
        "source_cluster_rank to that cluster's number. Do not invent features with no cluster "
        f"behind them; a feature with no real cluster will be discarded. Keep it to the core "
        f"features that deliver the positioning wedge (at most {_MAX_FEATURES})."
    )
    user = (
        f"Product idea: {report.query}\nSurface: {surface}\nPositioning wedge: {wedge}\n\n"
        f"Validated demand clusters:\n{pains}\n\nList the core features."
    )
    # No try/except: an infra error (404/auth/network) must propagate so the
    # caller sees a real failure, not a spec silently mislabelled "thin demand".
    # The only honest `partial` is a successful call whose features all fail to
    # ground — `_ground_features` already returns [] in that case.
    phrasing = deps.chat.complete_structured(
        system=system,
        user=user,
        output_model=_BuildPhrasing,
        max_tokens=_MAX_TOKENS,
        temperature=0.3,
    )
    features = _ground_features(report, phrasing.features)

    personas = _personas(report)
    pricing = _pricing_tiers(report)
    partial = not features
    caveat = (
        "No evidence-grounded feature survived (the LLM mapping produced none tied to a real "
        "demand cluster) — treat this spec as a stub, not a buildable plan."
        if partial
        else None
    )
    return BuildSpec(
        spec_id=f"spec:{report.report_id}",
        report_id=report.report_id,
        surface=surface,
        stack=stack,
        features=features,
        personas=personas,
        pricing_tiers=pricing,
        partial=partial,
        caveat=caveat,
    )
