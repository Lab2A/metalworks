"""Source-declared demand signals — the open vector + typed-spec registry.

These pin the de-Reddit'd scoring: a source emits an open ``signals`` dict, the
deterministic scorer reads known kinds via the SignalSpec registry, unknown kinds
are context-only, and a single-source (Reddit) run scores bit-for-bit as it did
when ``engagement`` was the only signal — the back-compat invariant.
"""

from __future__ import annotations

import math

from metalworks.research.synthesis import cluster_ranker, signals
from metalworks.research.synthesis.signals import (
    SignalSpec,
    aggregate_signals,
    native_kind,
    register_signal,
    score_signals,
)


def test_known_kind_scores_log_by_default() -> None:
    # Built-in social kinds are log / weight 1.
    assert score_signals({"upvotes": 5}) == math.log1p(5)
    assert score_signals({"points": 200}) == math.log1p(200)


def test_unknown_kind_is_context_only() -> None:
    # A kind with no registered spec never scores — it rides harmlessly.
    assert score_signals({"made_up_kind": 9999}) == 0.0
    # …and doesn't perturb a known kind summed alongside it.
    assert score_signals({"upvotes": 5, "made_up_kind": 9999}) == math.log1p(5)


def test_multiple_known_kinds_sum_independently() -> None:
    # Each currency contributes its own transform — NOT summed-then-logged.
    assert score_signals({"upvotes": 4, "points": 9}) == math.log1p(4) + math.log1p(9)


def test_compute_demand_score_back_compat_int_equals_upvotes_vector() -> None:
    # The legacy positional int and the explicit {"upvotes": n} vector agree…
    assert cluster_ranker.compute_demand_score(12, 30) == cluster_ranker.compute_demand_score(
        12, {"upvotes": 30}
    )
    # …and both reproduce the pre-signals formula exactly.
    assert cluster_ranker.compute_demand_score(12, 30) == (
        12 * cluster_ranker.AUTHOR_WEIGHT + math.log1p(30)
    )


def test_compute_demand_score_breadth_outranks_virality() -> None:
    # The original invariant survives the rewrite (50x2 outranks 1x200).
    assert cluster_ranker.compute_demand_score(
        50, {"upvotes": 2}
    ) > cluster_ranker.compute_demand_score(1, {"upvotes": 200})


def test_native_kind_maps_sources_to_their_engagement_currency() -> None:
    assert native_kind("reddit") == "upvotes"
    assert native_kind("hackernews") == "points"
    assert native_kind("producthunt") == "votes"
    assert native_kind("some_new_source") == "engagement"  # safe fallback


def test_aggregate_signals_sums_each_kind_across_members() -> None:
    class _M:
        def __init__(self, sig: dict[str, float]) -> None:
            self.signals = sig

    members = [_M({"upvotes": 2}), _M({"upvotes": 3, "points": 1}), _M({})]
    assert aggregate_signals(members) == {"upvotes": 5.0, "points": 1.0}


def test_register_signal_adds_a_new_scored_kind() -> None:
    # A new source registering a new kind teaches the scorer to read it — with
    # zero contract change. Linear transform so the math is unambiguous here.
    try:
        register_signal(SignalSpec(kind="test_helpful", weight=0.5, transform="linear"))
        assert score_signals({"test_helpful": 10}) == 5.0
    finally:
        signals.SIGNAL_SPECS.pop("test_helpful", None)


# ── 0.2a: magnitude kinds contribute to RANKING (the sort key only) ──────────
def test_magnitude_kinds_are_registered_and_flagged() -> None:
    # The deferred magnitude specs are now live, and flagged is_magnitude so a
    # future band rewire (0.2b) can tell them apart from social endorsement.
    for kind in ("search_volume", "installs", "downloads", "views", "funding", "rfp_budget"):
        spec = signals.get_spec(kind)
        assert spec is not None, kind
        assert spec.is_magnitude is True, kind
    # rating is polarity-capable but NOT yet a magnitude kind; polarity stays inert.
    rating = signals.get_spec("rating")
    assert rating is not None
    assert rating.is_magnitude is False


def test_search_volume_contributes_to_score() -> None:
    # A magnitude kind scores additively via its spec (log / weight 1), exactly
    # like every other registered kind — no special path.
    assert score_signals({"search_volume": 5000}) == math.log1p(5000)
    # …and rides alongside a social kind without perturbing it.
    assert score_signals({"upvotes": 5, "search_volume": 5000}) == (
        math.log1p(5) + math.log1p(5000)
    )


def test_high_search_volume_outranks_equal_breadth_cluster() -> None:
    # AC#1: same breadth, but the cluster carrying search_volume sorts higher.
    with_volume = cluster_ranker.compute_demand_score(20, {"upvotes": 10, "search_volume": 40000})
    without = cluster_ranker.compute_demand_score(20, {"upvotes": 10})
    assert with_volume > without


def test_reddit_only_ordering_is_byte_identical_to_pre_magnitude() -> None:
    # AC#2 (invariance): a Reddit-only run carries only {"upvotes": n} — no
    # magnitude kinds present — so every cluster score, and thus the ordering, is
    # bit-for-bit the pre-signals formula. Pin both the scores and the sort.
    reddit_clusters = [
        ("thin", 8, {"upvotes": 3}),
        ("broad", 50, {"upvotes": 120}),
        ("mid", 22, {"upvotes": 60}),
    ]
    scored = [
        (name, cluster_ranker.compute_demand_score(breadth, sig))
        for name, breadth, sig in reddit_clusters
    ]
    # Each score is exactly breadth*AUTHOR_WEIGHT + log1p(upvotes) — the pre-signals law.
    for (_name, breadth, sig), (_n, score) in zip(reddit_clusters, scored, strict=True):
        assert score == breadth * cluster_ranker.AUTHOR_WEIGHT + math.log1p(sig["upvotes"])
    order = [name for name, _ in sorted(scored, key=lambda it: it[1], reverse=True)]
    assert order == ["broad", "mid", "thin"]
