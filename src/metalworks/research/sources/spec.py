"""``SourceSpec`` — per-source lane + auth + signal metadata (the chassis root).

Going wide on sources is only safe and cheap if every source *declares* what it
is: which **lane** it serves (``grounding`` evidence, raw ``magnitude``, or
``web`` context), which **signal** kinds it emits (each registered in
:mod:`metalworks.research.synthesis.signals`), how it's **targeted**, what
**auth** it needs, and whether it's reachable at all (**access**). The runtime
:data:`~metalworks.research.sources.SOURCES` factory registry carries none of
that, so the selector / catalog / conformance guardrail have nothing to read.
:class:`SourceSpec` is that parallel, append-only metadata layer, stored in
:data:`SOURCE_SPECS` and registered alongside the factory.

This is an INTERNAL contract — the selector and catalog read it, but it never
crosses the wire (it is *not* in ``scripts/gen_ts_types.py``). ``spec`` is
optional at registration time for runtime back-compat: a source that registers a
bare factory still works, defaulting to a grounding lane.

The validity matrix is enforced in :meth:`SourceSpec.__post_init__` so an
ill-declared source fails loudly at construction rather than silently mis-routing
in the selector:

* ``access == "blocked"`` ⇒ ``lane == "web"`` — a blocked source can only ever
  contribute web-style context, never first-class grounding/magnitude.
* ``auth in {key, oauth, paid}`` ⇒ ``env`` non-empty — an auth'd source must name
  the env var(s) it reads, so the catalog can tell the operator what to set.
* ``lane == "magnitude"`` is illegal here — an :class:`ItemSource` pulls discrete
  corpus items (grounding) or web context; a magnitude lane (search volume as a
  demand denominator) is a *different* source shape and does not register here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Lane = Literal["grounding", "magnitude", "web"]
Targeting = Literal["none", "subreddit", "instance", "slug", "keyword"]
Auth = Literal["none", "key", "oauth", "paid"]
Access = Literal["open", "free_key", "paid", "blocked"]

_AUTHED: frozenset[str] = frozenset({"key", "oauth", "paid"})


@dataclass(frozen=True)
class SourceSpec:
    """Declarative metadata for one registered source — the unit the selector reads.

    ``lane`` routes the source's contribution; ``signals`` names the kinds it
    emits (each must be registered in
    :mod:`metalworks.research.synthesis.signals`); ``targeting`` is the selector
    knob it varies on (a subreddit, a Lemmy instance, a Product Hunt slug, a
    keyword, or nothing); ``auth`` / ``env`` / ``access`` describe reachability;
    ``relevance_hint`` is the one line the selector ranks on; ``sunset`` flags an
    impending API deprecation (e.g. an Atlassian V2 cutover) for the catalog to
    surface. See the module docstring for the validity matrix.
    """

    source_id: str
    lane: Lane
    signals: tuple[str, ...]
    targeting: Targeting
    auth: Auth
    env: tuple[str, ...]
    access: Access
    relevance_hint: str
    sunset: date | None = None

    def __post_init__(self) -> None:
        if self.lane == "magnitude":
            raise ValueError(
                f"source {self.source_id!r}: lane 'magnitude' is illegal on an ItemSource "
                "(it pulls discrete grounding/web items, not a magnitude denominator)"
            )
        if self.access == "blocked" and self.lane != "web":
            raise ValueError(
                f"source {self.source_id!r}: access 'blocked' requires lane 'web' "
                f"(a blocked source contributes only context), got lane {self.lane!r}"
            )
        if self.auth in _AUTHED and not self.env:
            raise ValueError(
                f"source {self.source_id!r}: auth {self.auth!r} requires a non-empty 'env' "
                "naming the var(s) it reads"
            )


# ── append-only metadata registry (parallel to ``SOURCES``) ──────────────────
SOURCE_SPECS: dict[str, SourceSpec] = {}


def _grounding_default(source_id: str) -> SourceSpec:
    """The back-compat spec a source gets when it registers without one.

    A bare ``register_source(id, factory)`` (no ``spec=``) still works: it lands a
    minimal grounding-lane spec so the registry is uniform. Such a default spec is
    intentionally signal-less and hint-less — a real source is expected to declare
    its own, and the 0.5 conformance guardrail fails a source still on this stub.
    """
    return SourceSpec(
        source_id=source_id,
        lane="grounding",
        signals=(),
        targeting="none",
        auth="none",
        env=(),
        access="open",
        relevance_hint="",
    )


__all__ = [
    "SOURCE_SPECS",
    "Access",
    "Auth",
    "Lane",
    "SourceSpec",
    "Targeting",
    "_grounding_default",
]
