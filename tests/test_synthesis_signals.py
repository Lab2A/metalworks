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
