"""Deterministic one-line viability verdict.

The verdict is derived from real signals (distinct-author breadth is the honest
base rate), never an LLM flourish. Thin-evidence runs read as thin — never a
fake green light.
"""

from __future__ import annotations

from metalworks.contract import MarketSizing, PriceFinding

_STRONG = 100
_MODERATE = 25


def derive_verdict(
    *,
    total_distinct_authors: int,
    market: MarketSizing | None = None,
    price: PriceFinding | None = None,
) -> str:
    if total_distinct_authors >= _STRONG:
        strength = "Strong demand"
    elif total_distinct_authors >= _MODERATE:
        strength = "Moderate demand"
    else:
        strength = "Thin signal"

    parts = [f"{strength} — {total_distinct_authors} distinct voices"]
    if market is not None:
        parts.append(
            f"~{market.reddit_floor:,} reachable on Reddit, "
            f"~{market.addressable_market:,} addressable"
        )
    if price is not None:
        if price.insufficient_signal:
            parts.append("not enough price signal to recommend a price")
        elif price.low is not None and price.high is not None:
            parts.append(
                # en-dash renders the price range in the report
                f"willingness to pay ~{price.currency} {price.low:g}–{price.high:g}"  # noqa: RUF001
            )

    tail = ". Treat as exploratory." if total_distinct_authors < _MODERATE else "."
    return "; ".join(parts) + tail
