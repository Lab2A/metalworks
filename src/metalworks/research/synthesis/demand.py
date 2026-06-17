"""Demand strength — relative, self-calibrating, the single source of truth.

The honest unit for "how wanted is this" is NOT an absolute distinct-author count
(100 authors is enormous in a niche, noise in r/all). It is *dimensionless*:

- **prevalence** — a fork's distinct authors as a fraction of the pulled crowd.
- **percentile** — where the fork's breadth sits among the *other forks* in the
  same report (self-calibrating against the run's own distribution).

The band (LOW/MEDIUM/HIGH) is derived from the percentile when there are >= 2
peer forks to calibrate against; below that there is no distribution, so it falls
back to the surfaced absolute policy on the author count. Every remaining number
lives in :class:`AssessPolicy` — documented, overridable, and (for the relative
cuts) dimensionless. The only irreducible absolutes are *validity gates*
(``min_authors`` / ``min_prevalence``), not verdict thresholds.

Consumed by both ``research.assess`` (the decision) and ``synthesis.verdict``
(the prose sentence), so the two can never disagree.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from metalworks.contract import SignalStrength

_RANK: dict[SignalStrength, int] = {
    SignalStrength.LOW: 0,
    SignalStrength.MEDIUM: 1,
    SignalStrength.HIGH: 2,
}
_LABEL: dict[SignalStrength, str] = {
    SignalStrength.HIGH: "Strong demand",
    SignalStrength.MEDIUM: "Moderate demand",
    SignalStrength.LOW: "Thin signal",
}


class AssessPolicy(BaseModel):
    """Every number the verdict rests on — surfaced, documented, overridable.

    The relative cuts are dimensionless percentiles of the run's own fork
    distribution. The absolute fields are used ONLY when there is no distribution
    to calibrate against (the degenerate <2-fork case) or as validity gates.
    """

    # Validity gates — the only irreducible absolutes (gates, not verdict thresholds).
    min_authors: int = Field(default=10, description="Below this the pull is too thin to trust.")
    min_prevalence: float = Field(
        default=0.05, description="A fork reaching <5% of the crowd is not a real slice."
    )
    # Self-calibrating band cuts — midrank percentiles of the PEER-fork distribution.
    # 0.66 so a 3-fork run reads cleanly as one HIGH / one MEDIUM / one LOW
    # (distinct top-of-3 midrank is 5/6 ≈ 0.83) AND a tied pair at the top both
    # clear it (a top tie of two scores 2/3 ≈ 0.667).
    high_percentile: float = 0.66
    medium_percentile: float = 0.33
    # Degenerate <2-fork fallback ONLY (surfaced + overridable; no longer hidden).
    whole_report_strong: int = 100
    whole_report_moderate: int = 25
    # Saturation supply cuts (moved out of assess.py module constants).
    saturated_supply: int = 6
    some_supply: int = 3


DEFAULT_POLICY = AssessPolicy()


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def prevalence(distinct_authors: int, total_distinct_authors: int) -> float:
    """This fork's distinct authors as a fraction of the pulled crowd — dimensionless, [0, 1]."""
    if total_distinct_authors <= 0:
        return 0.0
    return _clamp01(distinct_authors / total_distinct_authors)


def percentile_rank(value: int, population: list[int]) -> float:
    """Midrank percentile of ``value`` among its peers — fraction below plus half
    the ties, in [0, 1].

    Counting half the ties keeps equal peers symmetric. With a plain
    strictly-below count, a tie at the top is demoted: two equally-broad forks in
    ``[50, 50, 10]`` each score 1/3 and miss the HIGH cut, so the report reads
    "Moderate demand" while a distinct ``[60, 30, 10]`` of the same shape reads
    "Strong". Midrank scores that tied pair 2/3, so the strongest forks set the
    band regardless of ties. Empty population → 0.0.
    """
    if not population:
        return 0.0
    below = sum(1 for x in population if x < value)
    ties = sum(1 for x in population if x == value)
    return (below + 0.5 * ties) / len(population)


def rank(band: SignalStrength) -> int:
    """Ordinal rank of a band (LOW=0, MEDIUM=1, HIGH=2) — for sorting forks."""
    return _RANK[band]


def meets_medium(band: SignalStrength) -> bool:
    """True when the band clears the MEDIUM bar (the demand floor for a GO)."""
    return _RANK[band] >= _RANK[SignalStrength.MEDIUM]


def stronger(a: SignalStrength, b: SignalStrength) -> SignalStrength:
    return a if _RANK[a] >= _RANK[b] else b


def label_for(band: SignalStrength) -> str:
    """The prose strength label for a band (the words ``derive_verdict`` prints)."""
    return _LABEL[band]


def strength(
    rank_value: int,
    distinct_authors: int,
    total_distinct_authors: int,
    peers: list[int],
    *,
    policy: AssessPolicy = DEFAULT_POLICY,
) -> tuple[SignalStrength, float, float, float, str]:
    """Score one fork. Returns ``(band, prevalence, percentile, confidence, reference)``.

    ``rank_value`` is the breadth used to rank against ``peers`` (other forks);
    ``distinct_authors`` is the subset count used for prevalence. With >= 2 peers
    the band is the percentile relative to them; otherwise it falls back to the
    surfaced absolute policy on the author count.
    """
    prev = prevalence(distinct_authors, total_distinct_authors)
    thin = total_distinct_authors < policy.min_authors

    if len(peers) >= 2:
        pct = percentile_rank(rank_value, peers)
        if prev < policy.min_prevalence:
            band = SignalStrength.LOW
            reference = f"below the {policy.min_prevalence:.0%} prevalence floor"
        elif pct >= policy.high_percentile:
            band = SignalStrength.HIGH
            reference = f"top of {len(peers)} forks (pct {pct:.0%}, {prev:.0%} of the pull)"
        elif pct >= policy.medium_percentile:
            band = SignalStrength.MEDIUM
            reference = f"mid of {len(peers)} forks (pct {pct:.0%}, {prev:.0%} of the pull)"
        else:
            band = SignalStrength.LOW
            reference = f"bottom of {len(peers)} forks (pct {pct:.0%}, {prev:.0%} of the pull)"
        cuts = (policy.medium_percentile, policy.high_percentile)
        width = max(policy.high_percentile - policy.medium_percentile, 1e-6)
        confidence = _clamp01(min(abs(pct - c) for c in cuts) / width)
    else:
        pct = 0.0
        n = rank_value
        if n >= policy.whole_report_strong:
            band = SignalStrength.HIGH
        elif n >= policy.whole_report_moderate:
            band = SignalStrength.MEDIUM
        else:
            band = SignalStrength.LOW
        reference = f"{n} authors (no peer distribution — absolute policy)"
        cuts_n = (policy.whole_report_moderate, policy.whole_report_strong)
        edge = max(policy.whole_report_moderate, 1)
        confidence = _clamp01(min(abs(n - c) for c in cuts_n) / edge)

    if thin:
        confidence *= 0.5
        reference += "; thin pull"
    return band, prev, pct, confidence, reference


def report_demand_label(
    wedge_breadths: list[int],
    segment_authors: list[int],
    total_distinct_authors: int,
    *,
    policy: AssessPolicy = DEFAULT_POLICY,
) -> str:
    """The report-level strength label — the strongest fork's band (consistent with the
    top-line verdict). Falls back to the absolute policy on the total when there are no forks."""
    best = SignalStrength.LOW
    found = False
    for b in wedge_breadths:
        band, *_ = strength(b, b, total_distinct_authors, wedge_breadths, policy=policy)
        best = stronger(best, band)
        found = True
    for a in segment_authors:
        band, *_ = strength(a, a, total_distinct_authors, segment_authors, policy=policy)
        best = stronger(best, band)
        found = True
    if found:
        return label_for(best)
    # No forks: absolute fallback on the whole-report author count.
    band, *_ = strength(
        total_distinct_authors, total_distinct_authors, total_distinct_authors, [], policy=policy
    )
    return label_for(band)
