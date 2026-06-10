"""Market sizing.

Pure + deterministic. Two numbers, both honest:

  - `reddit_floor`        — total distinct authors across the synthesized corpus
                            (a real count of distinct people talking about this
                            on Reddit).
  - `addressable_market`  — `reddit_floor x DEFAULT_REACH_MULTIPLIER`, a STATED,
                            editable assumption (most people lurk — posters are
                            ~1% of the addressable population).

Neither number is LLM-emitted. The reach multiplier is the editable assumption
that keeps this honest, never a fabricated market size.
"""

from __future__ import annotations

from metalworks.contract import MarketSizing

# Authors who POST about a topic are a small slice of the interested population
# (most lurk). 100x = posters are ~1% of the addressable market.
DEFAULT_REACH_MULTIPLIER = 100.0
DEFAULT_PENETRATION = {"conservative": 0.01, "expected": 0.03, "good": 0.06}


def build_market_sizing(
    total_distinct_authors: int,
    *,
    reach_multiplier: float = DEFAULT_REACH_MULTIPLIER,
    penetration: dict[str, float] | None = None,
) -> MarketSizing:
    floor = max(0, int(total_distinct_authors))
    multiplier = max(1.0, reach_multiplier)
    addressable = round(floor * multiplier) if floor > 0 else 0
    return MarketSizing(
        reddit_floor=floor,
        addressable_market=max(floor, addressable),
        penetration=dict(penetration or DEFAULT_PENETRATION),
    )
