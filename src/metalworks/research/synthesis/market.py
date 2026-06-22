"""Market sizing.

Pure + deterministic. Only honest numbers ship:

  - `reddit_floor`   — total distinct authors across the synthesized corpus
                       (a real count of distinct people talking about this on
                       Reddit).
  - `penetration`    — already-labeled scenario bands (conservative / expected /
                       good), never a fabricated market size.

Neither number is LLM-emitted.
"""

from __future__ import annotations

from metalworks.contract import MarketSizing

DEFAULT_PENETRATION = {"conservative": 0.01, "expected": 0.03, "good": 0.06}


def build_market_sizing(
    total_distinct_authors: int,
    *,
    penetration: dict[str, float] | None = None,
) -> MarketSizing:
    floor = max(0, int(total_distinct_authors))
    return MarketSizing(
        reddit_floor=floor,
        penetration=dict(penetration or DEFAULT_PENETRATION),
    )
