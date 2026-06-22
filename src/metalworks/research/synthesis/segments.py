"""Audience segmentation: group ranked InsightClusters into sub-audiences.

The LLM only proposes NAMES + which existing cluster ranks belong to each
segment + a few preference paraphrases. Every quantitative field is computed
deterministically:

  - `distinct_author_count` — the UNION of the segment's clusters' author sets
    (an author in two of the segment's clusters counts once).
  - `demand_score` — the sum of the segment's clusters' demand_scores.

The per-segment audience-profile rebuild is dropped for now — each segment
carries the report-level profile by default. Best-effort: returns [] on LLM
failure, never raises.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    AudienceProfile,
    AudienceSegment,
    EvidenceRef,
    InsightCluster,
    SignalStrength,
)
from metalworks.research.synthesis.demand import relative_band

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

MAX_SEGMENTS = 4
LLM_RETRIES = 3


class _SegmentProposal(BaseModel):
    name: str
    preferences: list[str] = Field(default_factory=list[str])
    cluster_ranks: list[int] = Field(
        default_factory=list[int],
        description="1-based ranks of the clusters in this segment.",
    )


class _SegmentPlan(BaseModel):
    segments: list[_SegmentProposal] = Field(default_factory=list["_SegmentProposal"])


def build_segments(
    deps: ResearchDeps,
    clusters: list[InsightCluster],
    cluster_authors: list[set[str]],
    fallback_profile: AudienceProfile | None,
) -> list[AudienceSegment]:
    """Group ranked clusters into named sub-audiences.

    `cluster_authors[i]` is the set of author_hashes for `clusters[i]`.
    `fallback_profile` is the report-level audience profile (used as each
    segment's profile until a per-segment refinement is wired in). Returns []
    when there's nothing to segment or the LLM proposes no valid grouping.
    """
    if len(clusters) < 2:
        return []  # nothing meaningful to segment
    try:
        plan = _default_propose(deps, clusters)
    except Exception:  # best-effort secondary call, never fail the report
        return []
    by_rank = {c.rank: i for i, c in enumerate(clusters)}

    segments: list[AudienceSegment] = []
    seg_authors: list[set[str]] = []  # parallel to `segments`, for the overlap pass
    for prop in plan.segments[:MAX_SEGMENTS]:
        idxs = [by_rank[r] for r in dict.fromkeys(prop.cluster_ranks) if r in by_rank]
        if not idxs or not (prop.name or "").strip():
            continue

        authors: set[str] = set()
        demand = 0.0
        for i in idxs:
            authors |= cluster_authors[i] if i < len(cluster_authors) else set()
            demand += clusters[i].demand_score

        profile = fallback_profile or AudienceProfile(
            caveat="No demographic signal for this segment's communities; preferences only."
        )
        segments.append(
            AudienceSegment(
                name=prop.name.strip(),
                profile=profile,
                preferences=[p.strip() for p in prop.preferences if (p or "").strip()][:6],
                demand_score=round(demand, 4),
                distinct_author_count=len(authors),
                # Provisional — re-banded relative to ALL segments below, once the
                # report's full segment distribution is known.
                signal=SignalStrength.LOW,
                evidence=[EvidenceRef(kind="cluster", cluster_rank=clusters[i].rank) for i in idxs],
            )
        )
        seg_authors.append(authors)

    # Confidence is RELATIVE: band each segment's author count against the author
    # counts ACROSS this report's segments (top third → HIGH), not a fixed cutoff.
    seg_population = [s.distinct_author_count for s in segments]

    # Overlap pass (the anti-fake-fork guard): author-set Jaccard vs every other
    # segment, keyed by id. Near 1.0 ⇒ not a distinct audience; the surface suppresses it.
    enriched: list[AudienceSegment] = []
    for i, seg in enumerate(segments):
        overlap: dict[str, float] = {}
        for j, other in enumerate(segments):
            if i == j:
                continue
            a, b = seg_authors[i], seg_authors[j]
            union = a | b
            overlap[other.id] = round(len(a & b) / len(union), 4) if union else 0.0
        enriched.append(
            seg.model_copy(
                update={
                    "overlap": overlap,
                    "signal": relative_band(seg.distinct_author_count, seg_population),
                }
            )
        )

    enriched.sort(key=lambda s: s.demand_score, reverse=True)
    return enriched


def _default_propose(deps: ResearchDeps, clusters: list[InsightCluster]) -> _SegmentPlan:
    listing = "\n".join(
        f'{c.rank}. "{c.claim}" — {c.distinct_author_count} distinct voices' for c in clusters
    )
    system = (
        "You group consumer-insight clusters into a few distinct sub-audiences (segments). Each "
        "segment is a coherent kind of person with shared preferences, defined by the clusters "
        "belong to it (by rank). A cluster may belong to one segment or none. Do not invent "
        "audiences the clusters don't support; prefer 2-3 strong segments over many thin ones. "
        "Preferences must paraphrase the clusters' claims, not add new facts."
    )
    user = (
        "Insight clusters (rank. claim — distinct voices):\n"
        f"{listing}\n\n"
        "Group them into sub-audiences. For each: a short name, 2-4 preferences, and the "
        "cluster ranks that define it."
    )
    last_err: Exception | None = None
    for attempt in range(LLM_RETRIES):
        try:
            return deps.filter_model.complete_structured(
                system=system,
                user=user,
                output_model=_SegmentPlan,
                max_tokens=3072,
                temperature=0.3,
            )
        except Exception as e:  # surfaced after retries
            last_err = e
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"Segmentation LLM failed after {LLM_RETRIES} attempts: {last_err}")
