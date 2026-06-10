"""Cross-stream confidence weighting.

Adjusts cluster.signal based on whether the web stream agrees, is silent, or
disagrees. We treat the synthesis-derived signal as a FLOOR — we only DOWNGRADE
on disagreement; we don't promote based on web agreement alone (the underlying
corpus base-rate is still the authority).

Standalone module so it can be applied independently of the LLM triangulator
call — useful for unit tests and for replaying triangulation against adjusted
weights.
"""

from __future__ import annotations

import logging

from metalworks.contract import CrossReference, InsightCluster, SignalStrength

logger = logging.getLogger(__name__)


_SIGNAL_RANK = {
    SignalStrength.LOW: 0,
    SignalStrength.MEDIUM: 1,
    SignalStrength.HIGH: 2,
}
_RANK_SIGNAL = {v: k for k, v in _SIGNAL_RANK.items()}


def _min_signal(a: SignalStrength, b: SignalStrength) -> SignalStrength:
    return _RANK_SIGNAL[min(_SIGNAL_RANK[a], _SIGNAL_RANK[b])]


def apply_cross_stream_confidence(
    *,
    clusters: list[InsightCluster],
    cross_references: list[CrossReference],
) -> list[InsightCluster]:
    """Return a new list of clusters with .signal adjusted per cross-stream agreement.

    Logic:
      - agree         → signal unchanged (the corpus base-rate is the floor)
      - silent_web    → signal unchanged (Reddit-only insight; many real ones look like this)
      - silent_corpus → n/a (no cluster to adjust — these are orphan web findings)
      - disagree      → signal downgraded one step (HIGH→MEDIUM, MEDIUM→LOW), floor at LOW

    Important: we never UPGRADE a cluster's signal because web agreed.
    Cross-stream agreement is corroborating evidence, but the distinct-author
    count drives the underlying signal — overriding that on agreement alone would
    let the web stream artificially inflate weak Reddit themes.

    Returns NEW InsightCluster instances; does not mutate inputs.
    """
    cx_by_rank: dict[int, CrossReference] = {}
    for cx in cross_references:
        if cx.cluster_rank == 0:
            continue  # synthetic orphan-web bucket, no cluster to adjust
        cx_by_rank[cx.cluster_rank] = cx

    adjusted: list[InsightCluster] = []
    n_downgraded = 0
    for c in clusters:
        cx = cx_by_rank.get(c.rank)
        if cx is None or cx.agreement != "disagree":
            adjusted.append(c)
            continue
        # Downgrade one step on disagreement.
        new_signal = _min_signal(
            c.signal,
            SignalStrength.MEDIUM if c.signal == SignalStrength.HIGH else SignalStrength.LOW,
        )
        if new_signal != c.signal:
            n_downgraded += 1
        adjusted.append(c.model_copy(update={"signal": new_signal}))

    if n_downgraded:
        logger.info(
            "confidence_weighter: downgraded %d cluster(s) on cross-stream disagreement",
            n_downgraded,
        )
    return adjusted
