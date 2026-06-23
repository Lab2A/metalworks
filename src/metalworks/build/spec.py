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

The build spec also OWNS the product shape (this used to be a separate, orphaned
pillar). With ``surface="auto"`` the SAME feature-mapping call also returns the
chosen surface + a one-line rationale (no extra call — it already has the query,
wedge, and pains in scope); a pinned surface skips the pick. Screens are then
sketched AFTER the features exist, so each :class:`~metalworks.contract.surface.Screen`
maps to real ``feature_id``s (the old skeleton was blind to the features it was
meant to serve). Shell screens (auth/settings) are flagged as scaffolding, not
demand hypotheses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, get_args

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
    Screen,
)
from metalworks.contract.surface import SurfaceKind

if TYPE_CHECKING:
    from metalworks.contract import (
        ConversionSurfaceRequirement,
        LoopRequirement,
    )
    from metalworks.research.deps import ResearchDeps

# The distribution→build requirements (D3) shape: the tuple
# ``distribution_requirements(channels)`` returns — embedded-loop requirements +
# the conversion-surface requirement(s) — fed into the spec so it records the
# build requirements distribution decided.
DistributionRequirements = tuple["list[LoopRequirement]", "list[ConversionSurfaceRequirement]"]

_MAX_FEATURES = 8
_MAX_PERSONAS = 3
_MAX_SCREENS = 6
_QUOTES_PER_FEATURE = 2
_QUOTES_PER_SCREEN = 1
_MAX_TOKENS = 2048
_DEFAULT_SURFACE: SurfaceKind = "web"
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
    # Only consulted when surface="auto"; pinned callers ignore these two.
    chosen_surface: SurfaceKind = Field(
        default=_DEFAULT_SURFACE, description="The surface to build (used iff surface='auto')."
    )
    surface_rationale: str = Field(
        default="", description="One line on why that surface (used iff surface='auto')."
    )


class _ScreenDraft(BaseModel):
    name: str = Field(description="Screen name.")
    purpose: str = Field(description="What this screen is for, one line.")
    primary_action: str = Field(description="The single primary action on this screen.")
    feature_ids: list[str] = Field(
        default_factory=list[str],
        description="feature_id(s) from the list below that this screen serves. [] for shells.",
    )
    serves_wedge: bool = Field(default=False)
    scaffolding: bool = Field(
        default=False, description="True for shell screens (auth/settings) every product needs."
    )


class _ScreenPhrasing(BaseModel):
    screens: list[_ScreenDraft] = Field(default_factory=list[_ScreenDraft])


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


def _build_screens(
    deps: ResearchDeps,
    report: DemandReport,
    surface: SurfaceKind,
    wedge: str,
    features: list[FeatureSpec],
) -> list[Screen]:
    """Sketch screens AFTER the features exist, so each maps to real feature ids.

    One LLM call that sees the grounded feature list; the service then keeps only
    the ``feature_ids`` that resolve to a real feature (the LLM cannot map a screen
    to a feature that does not exist), inherits that feature's evidence as the
    screen's grounding, and marks ``validated`` accordingly. Shell screens
    (auth/settings) carry no feature and ship ``scaffolding=True`` — needed by every
    product, not a demand hypothesis. An infra failure degrades to no screens (the
    rest of the spec still ships), never propagating as a fake "partial demand".
    """
    if not features:
        return []
    by_id = {f.feature_id: f for f in features}
    feature_lines = "\n".join(f"- {f.feature_id}: {f.title}" for f in features)
    system = (
        "You sketch the 3-5 core screens (plus any auth/settings shells) for the chosen product "
        "surface. Each screen has a name, a one-line purpose, and a single primary_action, and "
        "lists the feature_id(s) BELOW that it serves — use only ids from the list, never invent "
        "one. A shell screen (sign-in, settings) serves no feature: leave feature_ids empty and "
        "set scaffolding=true. Mark serves_wedge when the screen directly delivers the wedge. "
        "Text and structure only — no visual design."
    )
    user = (
        f"Surface: {surface}\nPositioning wedge: {wedge}\n\n"
        f"Features to build (the screens must cover these):\n{feature_lines}\n\nSketch the screens."
    )
    try:
        phrasing = deps.chat.complete_structured(
            system=system,
            user=user,
            output_model=_ScreenPhrasing,
            max_tokens=_MAX_TOKENS,
            temperature=0.3,
        )
    except Exception:
        return []
    screens: list[Screen] = []
    for s in phrasing.screens[:_MAX_SCREENS]:
        # Keep only ids that resolve to a real feature — drops any the LLM invented.
        valid_ids = [fid for fid in s.feature_ids if fid in by_id]
        refs: list[EvidenceRef] = []
        for fid in valid_ids:
            refs.extend(by_id[fid].evidence[:_QUOTES_PER_SCREEN])
        screens.append(
            Screen(
                name=s.name.strip(),
                purpose=s.purpose.strip(),
                primary_action=s.primary_action.strip(),
                feature_ids=valid_ids,
                serves_wedge=s.serves_wedge,
                scaffolding=s.scaffolding and not valid_ids,
                evidence_refs=refs,
                validated=bool(refs),
            )
        )
    return screens


# ── public entry ─────────────────────────────────────────────────────────────


def build_spec_from_report(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None = None,
    surface: SurfaceKind | Literal["auto"] = "auto",
    *,
    stack: str = "empty",
    distribution_requirements: DistributionRequirements | None = None,
) -> BuildSpec:
    """Derive an evidence-grounded :class:`BuildSpec` from a finished report.

    ``surface="auto"`` (the default) lets the feature-mapping call also pick the
    surface + a one-line rationale; pinning ``surface`` (e.g. ``"cli"``) honors it
    and skips the pick. Screens are sketched after the features so each maps to a
    real ``feature_id``.

    ``distribution_requirements`` (D3) is the
    ``(loop_requirements, conversion_surface_requirements)`` tuple from
    :func:`metalworks.research.distribution_requirements` — the embedded-loop +
    conversion-surface build requirements distribution decided. When supplied, the
    spec RECORDS them (``loop_requirements`` / ``conversion_surface_requirements``);
    the default ``None`` leaves both empty, so behavior is byte-for-byte unchanged.
    """
    auto_surface = surface == "auto"
    wedge = (
        positioning.wedge.unique_attribute
        if positioning is not None and positioning.wedge is not None
        else "(no positioning wedge)"
    )
    pains = "\n".join(
        f"- [cluster {c.rank}] {c.claim}" for c in report.ranked_clusters[:_MAX_FEATURES]
    )
    surface_kinds = ", ".join(get_args(SurfaceKind))
    surface_instruction = (
        "Also choose the ONE product surface that best fits where these users are and how "
        f"technical they are — one of: {surface_kinds} — and set chosen_surface + a one-line "
        "surface_rationale grounded in the demand below."
        if auto_surface
        else f"The surface is fixed to '{surface}'; build the features for that surface."
    )
    system = (
        "You turn validated consumer demand into a SHORT product feature list for a founder to "
        "build. Each feature must derive from ONE of the numbered demand clusters below — set "
        "source_cluster_rank to that cluster's number. Do not invent features with no cluster "
        "behind them; a feature with no real cluster will be discarded. Keep it to the core "
        f"features that deliver the positioning wedge (at most {_MAX_FEATURES}). "
        f"{surface_instruction}"
    )
    pinned = "auto (you choose)" if auto_surface else surface
    user = (
        f"Product idea: {report.query}\nSurface: {pinned}\nPositioning wedge: {wedge}\n\n"
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

    if auto_surface:
        chosen_surface: SurfaceKind = phrasing.chosen_surface
        surface_rationale = phrasing.surface_rationale.strip() or None
    else:
        chosen_surface = surface
        surface_rationale = None

    screens = _build_screens(deps, report, chosen_surface, wedge, features)

    personas = _personas(report)
    pricing = _pricing_tiers(report)
    partial = not features
    caveat = (
        "No evidence-grounded feature survived (the LLM mapping produced none tied to a real "
        "demand cluster) — treat this spec as a stub, not a buildable plan."
        if partial
        else None
    )
    loop_reqs, conversion_reqs = (
        distribution_requirements if distribution_requirements is not None else ([], [])
    )
    return BuildSpec(
        spec_id=f"spec:{report.report_id}",
        report_id=report.report_id,
        surface=chosen_surface,
        stack=stack,
        surface_rationale=surface_rationale,
        features=features,
        personas=personas,
        pricing_tiers=pricing,
        screens=screens,
        loop_requirements=list(loop_reqs),
        conversion_surface_requirements=list(conversion_reqs),
        partial=partial,
        caveat=caveat,
    )
