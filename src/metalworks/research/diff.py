"""Diffing two versions of a report lineage.

A `DemandReport` is a live view over the corpus; a ``research refresh``
re-synthesizes against the now-larger corpus and pins a new version. This module
computes the :class:`~metalworks.contract.ReportDiff` between two versions so a
founder can see *what moved* — new demand themes, themes that faded, demand that
grew or shrank, sources that entered.

Two layers, by design (see `ReportDiff`):

- **Deterministic** — thread/author/cluster counts and source distribution, read
  straight from each report's own fields. Ground truth.
- **Advisory** — cluster identity across versions. Rank is positional and
  renumbered every run, so it can't be an id; instead clusters are matched by
  nearest-neighbor on their claim embedding. Synthesis is non-deterministic, so
  a claim's *wording* can drift between runs even when the theme is stable —
  hence advisory. The matching is greedy over descending similarity with stable
  tie-breaks, so it is itself deterministic given deterministic embeddings: a
  report diffed against an identical re-synthesis yields ``is_empty``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from metalworks.contract import ClusterDelta, ReportDiff

if TYPE_CHECKING:
    from metalworks.contract import CorpusStats, DemandReport, InsightCluster
    from metalworks.embeddings import EmbeddingProvider

# Cosine above which two claim embeddings are taken to be the same theme. Set so
# verbatim-identical claims (cosine 1.0) always match and unrelated claims
# (cosine ~0 for hash/real embeddings) never do, while real-embedding
# paraphrases (~0.9) still match.
CLAIM_MATCH_THRESHOLD = 0.85

# Demand-score movement below this is treated as no change (float-noise guard).
_SCORE_EPS = 1e-9


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _source_distribution(stats: CorpusStats | None) -> dict[str, int]:
    """Source label → threads examined, from a report's corpus stats."""
    if stats is None:
        return {}
    dist: dict[str, int] = {}
    for entry in stats.subreddit_distribution:
        label = entry.source or entry.subreddit or "(unknown)"
        dist[label] = dist.get(label, 0) + entry.threads_examined
    return dist


def _match_clusters(
    old: list[InsightCluster],
    new: list[InsightCluster],
    embeddings: EmbeddingProvider,
) -> tuple[list[ClusterDelta], int, list[str], list[str]]:
    """Match clusters across versions by claim-embedding nearest-neighbor.

    Returns ``(changed, unchanged_count, added_claims, dropped_claims)``. Greedy
    over descending similarity with ``(old_idx, new_idx)`` tie-breaks → fully
    deterministic for deterministic embeddings.
    """
    if not old and not new:
        return [], 0, [], []
    if not old:
        return [], 0, [c.claim for c in new], []
    if not new:
        return [], 0, [], [c.claim for c in old]

    old_vecs = embeddings.embed([c.claim for c in old], task="document")
    new_vecs = embeddings.embed([c.claim for c in new], task="document")

    # All candidate pairs above threshold, sorted strongest-first (stable
    # tie-break on indices keeps the match deterministic).
    pairs: list[tuple[float, int, int]] = []
    for i in range(len(old)):
        for j in range(len(new)):
            sim = _cosine(old_vecs[i], new_vecs[j])
            if sim >= CLAIM_MATCH_THRESHOLD:
                pairs.append((sim, i, j))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))

    matched_old: dict[int, int] = {}  # old_idx → new_idx
    matched_new: set[int] = set()
    sims: dict[int, float] = {}
    for sim, i, j in pairs:
        if i in matched_old or j in matched_new:
            continue
        matched_old[i] = j
        matched_new.add(j)
        sims[i] = sim

    changed: list[ClusterDelta] = []
    unchanged = 0
    for i, j in matched_old.items():
        oc, nc = old[i], new[j]
        moved = (
            abs(oc.demand_score - nc.demand_score) > _SCORE_EPS
            or oc.distinct_author_count != nc.distinct_author_count
        )
        if moved:
            changed.append(
                ClusterDelta(
                    claim_before=oc.claim,
                    claim_after=nc.claim,
                    similarity=round(sims[i], 6),
                    demand_score_before=oc.demand_score,
                    demand_score_after=nc.demand_score,
                    distinct_authors_before=oc.distinct_author_count,
                    distinct_authors_after=nc.distinct_author_count,
                )
            )
        else:
            unchanged += 1

    added = [new[j].claim for j in range(len(new)) if j not in matched_new]
    dropped = [old[i].claim for i in range(len(old)) if i not in matched_old]
    # Order changed deltas by strongest movement first for a readable summary.
    changed.sort(key=lambda d: (-abs(d.demand_score_delta), d.claim_after))
    return changed, unchanged, added, dropped


def diff_reports(
    old: DemandReport,
    new: DemandReport,
    *,
    embeddings: EmbeddingProvider,
) -> ReportDiff:
    """Compute the :class:`ReportDiff` from ``old`` to ``new``.

    ``embeddings`` is used only for the advisory cluster matching; the
    deterministic count layer is read straight off the two reports. The two
    reports are normally consecutive versions of one lineage, but the function
    is total — it will diff any two reports.
    """
    changed, unchanged, added, dropped = _match_clusters(
        old.ranked_clusters, new.ranked_clusters, embeddings
    )
    return ReportDiff(
        lineage_id=new.effective_lineage_id,
        from_report_id=old.report_id,
        to_report_id=new.report_id,
        from_version=old.version,
        to_version=new.version,
        total_threads_before=old.total_threads,
        total_threads_after=new.total_threads,
        total_distinct_authors_before=old.total_distinct_authors,
        total_distinct_authors_after=new.total_distinct_authors,
        cluster_count_before=len(old.ranked_clusters),
        cluster_count_after=len(new.ranked_clusters),
        source_distribution_before=_source_distribution(old.corpus_stats),
        source_distribution_after=_source_distribution(new.corpus_stats),
        clusters_added=added,
        clusters_dropped=dropped,
        clusters_changed=changed,
        clusters_unchanged=unchanged,
    )


__all__ = ["CLAIM_MATCH_THRESHOLD", "diff_reports"]
