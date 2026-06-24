"""Source-declared demand signals — the de-Reddit'd replacement for ``engagement``.

The corpus spine already generalized *identity* (``source`` / ``source_url``) and
*a voice* (``cluster_breadth`` counts authors OR domains). What stayed flat was
the **signal**: every source's notion of "how much does this matter" was crushed
into one ``engagement: int`` (Reddit upvotes, HN points), and the demand scorer
read only that. An Amazon verified-purchase, a 1-star rating, a search volume, a
crowdfunding pledge — all collapsed to "an int" the scorer treated like upvotes.

This module is the fix, in two halves:

* **An open signal vector.** A source emits ``signals: dict[str, float]`` — any
  named kind it has. The contract spine never changes when a new source adds a
  new signal. That is the "super flexible" half.

* **A typed semantics registry** — :class:`SignalSpec` + :func:`register_signal`,
  mirroring ``register_source``. This is the ONE seam where flexibility meets
  determinism: the pure scorer reads how to weight each *known* kind from this
  table. An UNKNOWN signal degrades to context-only (never scored, never crashes,
  never silently distorts) — exactly today's ``extra: dict`` behavior. Decisions
  stay deterministic: scoring is a pure function of ``(breadth, signals, specs)``.

**v1 is signal-aware additive only** (the chosen scope). Every shipped spec is
positive-additive (``weight * transform(total)``); the ``polarity`` /
``is_breadth`` / ``is_magnitude`` fields are carried on the spec so the later
steps (negative-polarity reviews, a search-volume magnitude axis) are pure
additions, but the v1 scorer does NOT consume them yet.

**Back-compat invariant.** Every shipped social-endorsement kind (``upvotes`` /
``points`` / ``votes`` / ``engagement``) is ``log`` / ``weight=1``, so a
single-source run scores bit-for-bit as before: a Reddit-only cluster's
aggregated vector is ``{"upvotes": sum}`` and ``score_signals`` returns
``log1p(sum)`` — identical to the old ``log1p(sum(m.upvotes))``. (Mixed-source
clusters differ slightly: we no longer add unlike currencies before the log,
which is strictly more correct. Every default run is single-source.)
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SignalSpec:
    """How the deterministic scorer reads one named signal kind.

    ``weight`` and ``transform`` are the v1-active knobs (additive contribution).
    ``polarity`` / ``is_breadth`` / ``is_magnitude`` are carried but NOT consumed
    in v1 — they reserve the shape for the magnitude axis (search volume as a
    demand denominator) and signed signals (a 1-star review is demand FOR a better
    thing) without a future contract change.
    """

    kind: str
    weight: float = 1.0
    transform: str = "log"  # "log" | "linear" | "bounded"
    polarity: float = 1.0  # v2: +1 demand-for, -1 demand-against
    is_breadth: bool = False  # v2: counts as a distinct voice (a verified buyer does)
    is_magnitude: bool = False  # v2: an absolute volume denominator (search_volume)

    def _transform(self, total: float) -> float:
        t = max(total, 0.0)  # v1 additive-only: clamp; polarity/sign is v2
        if self.transform == "log":
            return math.log1p(t)
        # "linear" and "bounded" are identity here — a bounded kind (e.g. a 0-1
        # rating) is expected pre-normalized by its source. Both reserved for v2.
        return t

    def contribution(self, total: float) -> float:
        """Additive score contribution of ``total`` units of this kind (v1)."""
        return self.weight * self._transform(total)


# ── registry (mirrors register_source) ───────────────────────────────────────
SIGNAL_SPECS: dict[str, SignalSpec] = {}


def register_signal(spec: SignalSpec) -> None:
    """Register ``spec`` under ``spec.kind`` (idempotent; re-register overwrites).

    The open-vocabulary counterpart to ``register_source``: a source that emits a
    new named signal registers its semantics here so the pure scorer can read it.
    A kind with no registered spec is scored as zero (context-only) — never an
    error, so an unknown signal can ride in the corpus spine harmlessly.
    """
    SIGNAL_SPECS[spec.kind] = spec


def get_spec(kind: str) -> SignalSpec | None:
    """The registered spec for ``kind``, or ``None`` (unknown → context-only)."""
    return SIGNAL_SPECS.get(kind)


# Built-in social-endorsement kinds — all log / weight 1 so any SINGLE-source run
# scores exactly as the pre-signals code did (the back-compat invariant). These
# are the only kinds any v1 source emits; review/search/crowdfunding specs land
# with their connectors (and turn on polarity / magnitude then).
for _kind in ("upvotes", "points", "votes", "engagement"):
    register_signal(SignalSpec(kind=_kind, weight=1.0, transform="log"))


# Native signal kind a source's bare ``engagement`` int means, for back-compat
# synthesis when a record carries no explicit ``signals`` (older mappers / new
# sources not yet emitting a vector). Unknown sources fall back to "engagement".
_NATIVE_KIND: dict[str, str] = {
    "reddit": "upvotes",
    "arctic": "upvotes",
    "hackernews": "points",
    "hackernews_archive": "points",
    "hn_archive": "points",
    "producthunt": "votes",
}


def native_kind(source: str) -> str:
    """The signal kind a ``source``'s native ``engagement`` int represents."""
    return _NATIVE_KIND.get(source, "engagement")


# ── pure scoring ─────────────────────────────────────────────────────────────
def score_signals(
    signals: Mapping[str, float], *, specs: Mapping[str, SignalSpec] = SIGNAL_SPECS
) -> float:
    """Spec-weighted additive score of a signal vector. Unknown kinds contribute 0."""
    total = 0.0
    for kind, value in signals.items():
        spec = specs.get(kind)
        if spec is not None:
            total += spec.contribution(value)
    return total


class _HasSignals(Protocol):
    signals: dict[str, float]


def aggregate_signals(members: Iterable[_HasSignals]) -> dict[str, float]:
    """Sum each named signal across a cluster's members into one vector."""
    agg: dict[str, float] = {}
    for m in members:
        for kind, value in m.signals.items():
            agg[kind] = agg.get(kind, 0.0) + value
    return agg
