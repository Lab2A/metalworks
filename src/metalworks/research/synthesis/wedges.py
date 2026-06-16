"""Candidate wedges — the buildable forks the engine surfaces (PR2).

``build_wedges(clusters, segments)`` turns the ranked demand clusters into a few
:class:`~metalworks.contract.research.CandidateWedge` options the surfaces can
offer instead of the pipeline silently picking one:

- a **minimal** wedge per top cluster (the narrowest thing that kills one pain);
- one **broad** wedge combining the top clusters (the platform bet).

Fully deterministic and grounded: every wedge carries the cluster ranks it draws
on and a ``cluster`` :class:`EvidenceRef` — no cluster, no wedge. ``segment_id``
links a wedge to the segment that owns its cluster, when one does. (A future
``lateral`` reframe can be added behind a best-effort LLM call; omitted here to
keep every emitted wedge grounded.)
"""

from __future__ import annotations

from metalworks.contract import CandidateWedge, EvidenceRef, InsightCluster, SegmentChoice

_MAX_MINIMAL = 3
_BROAD_N = 3


def _short(text: str, words: int = 7) -> str:
    parts = text.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _breadth(c: InsightCluster) -> int:
    return c.breadth_count or c.distinct_author_count


def build_wedges(
    clusters: list[InsightCluster], segments: list[SegmentChoice]
) -> list[CandidateWedge]:
    """Surface the buildable forks from the ranked clusters. Empty in → empty out."""
    if not clusters:
        return []
    ranked = sorted(clusters, key=lambda c: c.demand_score, reverse=True)

    # cluster rank → the id of the first segment that owns it (for segment_id linkage)
    seg_for_rank: dict[int, str] = {}
    for seg in segments:
        for ref in seg.evidence:
            if ref.cluster_rank is not None:
                seg_for_rank.setdefault(ref.cluster_rank, seg.id)

    wedges: list[CandidateWedge] = []

    # minimal: the narrowest thing that kills one top pain
    for c in ranked[:_MAX_MINIMAL]:
        wedges.append(
            CandidateWedge(
                label=_short(c.claim),
                pain=c.claim,
                scope="minimal",
                segment_id=seg_for_rank.get(c.rank),
                rationale=f"The narrowest thing someone would pay for that kills: {c.claim}",
                cluster_ranks=[c.rank],
                breadth_count=_breadth(c),
                distinct_author_count=c.distinct_author_count,
                signal=c.signal,
                evidence=[EvidenceRef(kind="cluster", cluster_rank=c.rank)],
            )
        )

    # broad: address the top pains together as one product
    if len(ranked) >= 2:
        top = ranked[:_BROAD_N]
        wedges.append(
            CandidateWedge(
                label="Platform play",
                pain="; ".join(c.claim for c in top),
                scope="broad",
                rationale="Address the top pains together as one product (more scope, more risk).",
                cluster_ranks=[c.rank for c in top],
                breadth_count=sum(_breadth(c) for c in top),
                distinct_author_count=sum(c.distinct_author_count for c in top),
                signal=top[0].signal,
                evidence=[EvidenceRef(kind="cluster", cluster_rank=c.rank) for c in top],
            )
        )

    return wedges
