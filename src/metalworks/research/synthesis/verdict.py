"""Deterministic one-line viability verdict — a pure formatter.

The strength is computed once in :mod:`metalworks.research.synthesis.demand`
(relative, self-calibrating) and handed in as ``strength_label`` so the prose
sentence and the ``assess`` decision can never disagree. This module only
formats — it owns no thresholds.
"""

from __future__ import annotations

from metalworks.contract import MarketSizing, PriceFinding


def derive_verdict(
    *,
    strength_label: str,
    total_distinct_authors: int,
    market: MarketSizing | None = None,
    price: PriceFinding | None = None,
) -> str:
    parts = [f"{strength_label} — {total_distinct_authors} distinct voices"]
    if market is not None:
        parts.append(f"~{market.reddit_floor:,} reachable on Reddit")
    if price is not None:
        if price.insufficient_signal:
            parts.append("not enough price signal to recommend a price")
        elif price.low is not None and price.high is not None:
            parts.append(
                # en-dash renders the price range in the report
                f"willingness to pay ~{price.currency} {price.low:g}–{price.high:g}"  # noqa: RUF001
            )

    tail = ". Treat as exploratory." if strength_label == "Thin signal" else "."
    return "; ".join(parts) + tail
