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

**Scoring is signal-aware additive** (the chosen scope). Every shipped spec is
positive-additive (``weight * transform(total)``). As of 0.2a the ``is_magnitude``
kinds (``search_volume`` / ``installs`` / ``downloads`` / ``views`` / ``funding``
/ ``rfp_budget``) are registered and contribute to the RANKING score the same
additive way every other kind does — a high-volume theme sorts higher. This moves
the sort key ONLY (``compute_demand_score`` → clusters/wedges/segments); it does
NOT touch the verdict band (``demand.strength`` reads breadth/author counts and
never sees the signal vector). ``polarity`` remains carried-but-inert: a
polarity-capable ``rating`` spec is registered, but the scorer does not yet read
its sign (negative-polarity reviews are 0.2b). ``is_breadth`` is likewise
reserved.

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

    ``weight`` and ``transform`` are the active knobs (additive contribution).
    ``is_magnitude`` marks an absolute-volume kind (search volume, installs); as of
    0.2a these contribute to the RANKING score additively like any other kind (they
    re-order clusters), but they are deliberately NOT read by the verdict band —
    ``demand.strength`` never sees the signal vector, so a high-magnitude theme
    sorts higher without moving the GO/NO-GO call (that rewire is 0.2b).
    ``polarity`` / ``is_breadth`` stay carried-but-inert: a polarity-capable rating
    spec reserves the shape for signed signals (a 1-star review is demand FOR a
    better thing) without a future contract change.
    """

    kind: str
    weight: float = 1.0
    transform: str = "log"  # "log" | "linear" | "bounded"
    polarity: float = 1.0  # reserved: +1 demand-for, -1 demand-against (0.2b)
    is_breadth: bool = False  # reserved: counts as a distinct voice (a verified buyer does)
    is_magnitude: bool = False  # an absolute volume kind (search_volume); ranks, never bands

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
# are the only kinds the Reddit/HN/PH path emits; a Reddit-only run's vector is
# {"upvotes": sum}, so its cluster ordering is byte-identical to pre-magnitude.
for _kind in ("upvotes", "points", "votes", "engagement"):
    register_signal(SignalSpec(kind=_kind, weight=1.0, transform="log"))


# Magnitude kinds (0.2a) — absolute-volume signals a source can declare. They
# contribute to the RANKING score additively (log-compressed, weight 1, so a theme
# carrying high search volume sorts above an equal-breadth one) but are flagged
# ``is_magnitude`` and are NEVER read by the verdict band (``demand.strength`` does
# not see the signal vector). The log keeps a single huge magnitude from dwarfing
# the breadth axis — ranking still favors breadth of voices over raw volume.
for _kind in ("search_volume", "installs", "downloads", "views", "funding", "rfp_budget"):
    register_signal(SignalSpec(kind=_kind, weight=1.0, transform="log", is_magnitude=True))


# A polarity-capable review-rating kind. Registered so a rating contributes to
# ranking, but ``polarity`` is NOT consumed yet — a low rating is "demand for a
# better thing", which is the signed 0.2b axis, deferred here.
register_signal(SignalSpec(kind="rating", weight=1.0, transform="log", polarity=1.0))


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
