"""The relative demand scorer — prevalence, self-calibrating bands, sufficiency floor.

Pure functions, no deps. These pin the unit change behind assess: demand is
dimensionless (prevalence + percentile-among-peers), the bands self-calibrate off
the run's own fork distribution, and the only absolutes are validity gates.
"""

from __future__ import annotations

from metalworks.contract import SignalStrength
from metalworks.research.synthesis import demand
from metalworks.research.synthesis.demand import DEFAULT_POLICY, AssessPolicy


def test_prevalence_is_a_clamped_fraction() -> None:
    assert demand.prevalence(50, 200) == 0.25
    assert demand.prevalence(0, 200) == 0.0
    assert demand.prevalence(300, 200) == 1.0  # clamped — never > 1
    assert demand.prevalence(5, 0) == 0.0  # no corpus → no signal


def test_percentile_rank_self_calibrates() -> None:
    pop = [10, 20, 30]
    assert demand.percentile_rank(30, pop) == 2 / 3  # top of three
    assert demand.percentile_rank(10, pop) == 0.0  # bottom
    assert demand.percentile_rank(5, []) == 0.0


def test_relative_path_uses_peers_not_absolute_count() -> None:
    # 3 peers → relative bands. The biggest is HIGH, the smallest LOW — regardless
    # of the absolute author count (the whole point: domain-portable).
    peers = [40, 20, 10]
    big, prev, pct, _conf, ref = demand.strength(40, 40, 100, peers)
    small, *_ = demand.strength(10, 10, 100, peers)
    assert big == SignalStrength.HIGH
    assert small == SignalStrength.LOW
    assert prev == 0.40 and pct == 2 / 3
    assert "forks" in ref  # self-calibration note mentions the peer set


def test_absolute_fallback_below_two_peers() -> None:
    # <2 peers → no distribution → surfaced absolute policy on the author count.
    band, _prev, pct, _conf, ref = demand.strength(150, 150, 150, [150])
    assert band == SignalStrength.HIGH and pct == 0.0
    assert "absolute policy" in ref
    assert demand.strength(30, 30, 30, [])[0] == SignalStrength.MEDIUM
    assert demand.strength(5, 5, 5, [])[0] == SignalStrength.LOW


def test_min_prevalence_caps_a_tiny_fork() -> None:
    # A fork that ranks high among peers but reaches almost nobody is still LOW.
    peers = [3, 2, 1]
    band, prev, *_ = demand.strength(3, 3, 100_000, peers)
    assert prev < DEFAULT_POLICY.min_prevalence
    assert band == SignalStrength.LOW


def test_thin_pull_halves_confidence_and_caveats() -> None:
    thin = AssessPolicy(min_authors=100)
    _band, _prev, _pct, conf_thin, ref = demand.strength(150, 150, 50, [150], policy=thin)
    _b2, _p2, _pct2, conf_ok, _r2 = demand.strength(150, 150, 5000, [150], policy=thin)
    assert conf_thin == conf_ok * 0.5
    assert "thin pull" in ref


def test_report_label_is_the_strongest_fork() -> None:
    # report-level label = the best fork's band (so report.verdict and assess agree).
    label = demand.report_demand_label([40, 20, 10], [], 100)
    assert label == "Strong demand"
    assert demand.report_demand_label([], [], 5) == "Thin signal"  # no forks → absolute fallback
