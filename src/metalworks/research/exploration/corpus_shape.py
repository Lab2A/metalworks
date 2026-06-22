"""Assemble the ExplorationReport from the triage outputs.

The ExplorationReport is the contract field that surfaces the funnel to the
user: how many threads were pulled, auto-accepted by the hybrid score, sent to
the LLM, found relevant, etc. Showing the funnel honestly (60% rejected as
noise) is part of "a story of disciplined filtering, not a pile of leftovers".

This module is purely arithmetic on the upstream buckets + verdicts. It does NO
new LLM work or embedding.
"""

from __future__ import annotations

from collections import Counter

from metalworks.contract import ExplorationReport
from metalworks.research.types import ClassifierVerdict, TriageBuckets


def _percentile(values: list[float], p: float) -> float:
    """No numpy dependency — small dataset, linear interpolation OK."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def build_exploration_report(
    *,
    n_threads_pulled: int,
    buckets: TriageBuckets,
    middle_verdicts: dict[int, ClassifierVerdict],
    threads_synthesized: int = 0,
    false_reject: tuple[float, int] | None = None,
    dedup_merge_rate: float | None = None,
) -> ExplorationReport:
    """Compose the ExplorationReport contract field.

    Args:
        n_threads_pulled: the raw pull count BEFORE triage. Often larger than
            len(buckets.cosines) when the caller pre-filters (e.g. drops
            [removed] before embedding). Surfaced as `threads_pulled`.
        buckets: output of `triage_by_embedding`.
        middle_verdicts: output of `classify_middle`.
        threads_synthesized: filled by the downstream synthesis stage, after
            cluster dedup. Pass 0 from the triage step alone; the orchestrator
            overwrites this once synthesis completes.
        false_reject: optional `(rate, sample_size)` from the recall backstop
            (`estimate_false_reject_rate`) — the measured cost of the rank-only
            auto-reject band. None ⇒ backstop not run.
        dedup_merge_rate: optional embed_group near-dup merge rate, filled by the
            synthesis stage once it has run. None ⇒ synthesis hasn't run yet.
    """
    n_accepted = len(buckets.accepted)
    n_rejected = len(buckets.rejected)
    n_classified = len(middle_verdicts)
    middle_relevant = sum(1 for v in middle_verdicts.values() if v.relevant)

    threads_relevant = n_accepted + middle_relevant

    # noise_composition: count of each reason tag across REJECTED items. The
    # auto-rejected items don't have a verdict tag; we bucket them as
    # "low_cosine_match". The classifier-rejected items contribute their actual
    # reason tags.
    noise_counter: Counter[str] = Counter()
    if n_rejected:
        noise_counter["low_cosine_match"] = n_rejected
    for v in middle_verdicts.values():
        if not v.relevant:
            noise_counter[v.reason or "other"] += 1

    # similarity_percentiles: distribution of cosine scores across the full
    # pulled corpus — a sanity check on where the cosine floor landed.
    cos = buckets.cosines or []
    sim_percentiles: dict[str, float] = {}
    if cos:
        sim_percentiles = {
            "p10": round(_percentile(cos, 0.10), 4),
            "p25": round(_percentile(cos, 0.25), 4),
            "p50": round(_percentile(cos, 0.50), 4),
            "p75": round(_percentile(cos, 0.75), 4),
            "p90": round(_percentile(cos, 0.90), 4),
        }
    # hybrid_percentiles: the blended cosine + BM25 score that actually drives
    # the bucketing. Surfaced so the report can show whether the blend is
    # well-spread (good) or collapsed at one end (bad).
    hyb = buckets.hybrid_scores or []
    hybrid_percentiles: dict[str, float] = {}
    if hyb:
        hybrid_percentiles = {
            "p10": round(_percentile(hyb, 0.10), 4),
            "p25": round(_percentile(hyb, 0.25), 4),
            "p50": round(_percentile(hyb, 0.50), 4),
            "p75": round(_percentile(hyb, 0.75), 4),
            "p90": round(_percentile(hyb, 0.90), 4),
        }

    false_reject_rate = round(false_reject[0], 4) if false_reject is not None else None
    false_reject_sample_size = false_reject[1] if false_reject is not None else 0

    return ExplorationReport(
        threads_pulled=n_threads_pulled,
        threads_auto_accepted=n_accepted,
        threads_auto_rejected=n_rejected,
        threads_classified=n_classified,
        threads_relevant=threads_relevant,
        threads_synthesized=threads_synthesized,
        noise_composition=dict(noise_counter),
        false_reject_rate=false_reject_rate,
        false_reject_sample_size=false_reject_sample_size,
        dedup_merge_rate=(round(dedup_merge_rate, 4) if dedup_merge_rate is not None else None),
        similarity_percentiles=sim_percentiles,
        hybrid_percentiles=hybrid_percentiles,
    )
