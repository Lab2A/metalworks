"""Source connectors: the ``ItemSource`` protocol + an append-friendly registry.

This is the seam that turns "Reddit research" into "research over any source".
A connector implements :class:`ItemSource` — it knows how to *pull* top-level
items (:class:`~metalworks.contract.CorpusRecord`) and their comments
(:class:`~metalworks.contract.CorpusComment`) for a query over a time window,
yielding the source-neutral corpus spine. The pipeline never speaks Reddit (or
HN, or reviews) directly; it speaks ``ItemSource`` and lets
:func:`~metalworks.research.sources.ingest.ingest_source` write the pulled
records into the durable corpus.

Window neutrality
-----------------
The bulk corpus is month-partitioned, so the existing reader speaks
:class:`~metalworks.research.types.MonthRef`. :class:`SourceWindow` neutralizes
that: it carries the resolved ``months`` (what Arctic needs) plus a
source-agnostic ``[start, end]`` datetime span (what a date-ranged API source
needs). A connector reads whichever it understands; the pipeline only ever holds
an opaque ``SourceWindow``.

Append-friendly registry
-------------------------
:data:`SOURCES` is a module-level ``dict[str, factory]``. A new connector
(e.g. a concurrent Hacker News stream) self-registers on import by calling
:func:`register_source` at module scope — it never has to edit a shared list
inline, so two connector streams can land without colliding on this file. The
built-in Arctic connector registers itself when
:mod:`metalworks.research.sources.arctic` is imported (which :func:`get_source`
triggers lazily for the ``"reddit"`` / ``"arctic"`` ids).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from metalworks.research.sources.spec import (
    SOURCE_SPECS,
    Access,
    Auth,
    Lane,
    SourceSpec,
    Targeting,
    _grounding_default,
)

if TYPE_CHECKING:
    from metalworks.contract import CorpusComment, CorpusRecord
    from metalworks.research.types import MonthRef


@dataclass(frozen=True)
class SourceWindow:
    """A source-neutral time window over the corpus.

    ``months`` is the month-partition list the bulk (Arctic) reader needs;
    ``start`` / ``end`` are the equivalent absolute span for a date-ranged API
    source. A connector reads whichever representation it understands. Empty
    ``months`` is legal for a source that only windows by datetime span.
    """

    months: Sequence[MonthRef] = field(default_factory=tuple)
    start: datetime | None = None
    end: datetime | None = None


@runtime_checkable
class ItemSource(Protocol):
    """A connector that pulls source-neutral corpus items for a query/window.

    Implementations yield :class:`~metalworks.contract.CorpusRecord` (top-level
    items) and, when the source has them, :class:`~metalworks.contract.CorpusComment`
    (quote-bearing sub-items). A source with no comment layer returns ``None``
    from :meth:`comments_for` — the ingest path then records the run as
    comment-less rather than treating it as an error.

    Sentinel normalization (Reddit's ``[deleted]`` / ``[removed]`` author and
    body markers) is the SOURCE's job: by the time records/comments cross this
    boundary they carry tombstones (``author_hash=None`` / empty body), not raw
    sentinels. The shared synthesis loader no longer special-cases them.

    Optional ``yields_units = True`` (class attribute, default ``False`` when
    absent) marks a source whose records are SELF-REPRESENTING: each record's own
    text is a synthesis unit, because the source has no comment layer (e.g. web
    pages). Synthesis then clusters the records themselves and the ranker measures
    their breadth by distinct domain instead of distinct author. This is an
    explicit opt-in, NOT inferred from :meth:`comments_for` returning ``None`` — a
    comment-bearing source whose comment client simply isn't wired also returns
    ``None`` but is not a unit source.
    """

    source_id: str

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate :class:`CorpusRecord`s for ``query`` over ``window``.

        ``limit`` is a per-pull dev guard (``None`` in production). The pull is
        the *candidate* set; the pipeline triages it for relevance before any
        expensive comment fetch.
        """
        ...

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one comment batch per record id, in input order.

        Returns ``None`` when the source has no comment layer at all (so the
        caller marks the run comment-less, not failed). A source WITH comments
        yields a (possibly empty) ``list[CorpusComment]`` per id.
        """
        ...

    def latest_window(self) -> SourceWindow:
        """The most recent window this source can serve (its anchor)."""
        ...


# ── Append-friendly registry ─────────────────────────────────────────────────

SourceFactory = Callable[..., ItemSource]

# Module-level registry. Connectors self-register here on import via
# ``register_source`` — never by editing a shared inline list — so concurrent
# connector streams (e.g. a Hacker News adapter) can land without colliding.
SOURCES: dict[str, SourceFactory] = {}


def register_source(
    source_id: str, factory: SourceFactory, *, spec: SourceSpec | None = None
) -> None:
    """Register ``factory`` under ``source_id`` (idempotent on re-import).

    Re-registering the same id overwrites — module re-imports under pytest must
    not raise, and a downstream override of a built-in is intentional.

    ``spec`` declares the source's lane / auth / signal metadata in the parallel
    :data:`SOURCE_SPECS` registry. It is optional for runtime back-compat: a bare
    ``register_source(id, factory)`` still works and lands a minimal grounding
    default (signal-less, which the 0.5 conformance guardrail then flags). A
    passed ``spec.source_id`` must match ``source_id``.
    """
    if spec is not None and spec.source_id != source_id:
        raise ValueError(
            f"spec.source_id {spec.source_id!r} does not match register id {source_id!r}"
        )
    SOURCES[source_id] = factory
    SOURCE_SPECS[source_id] = spec if spec is not None else _grounding_default(source_id)


def get_source(source_id: str, **kwargs: object) -> ItemSource:
    """Construct the registered source for ``source_id``.

    Triggers a lazy import of a built-in connector for known ids so a bare
    ``import`` of this package stays free of ``duckdb`` / ``httpx``: the Arctic
    connector for ``"reddit"`` / ``"arctic"``, the Hacker News connector for
    ``"hackernews"``, the web-search connector for ``"web"``. Unknown ids raise
    ``KeyError``.
    """
    _BUILTIN_MODULES = {
        "ats": "metalworks.research.sources.ats",
        "reddit": "metalworks.research.sources.arctic",
        "arctic": "metalworks.research.sources.arctic",
        "hackernews": "metalworks.research.sources.hackernews",
        "hackernews_archive": "metalworks.research.sources.hn_archive",
        "hn_archive": "metalworks.research.sources.hn_archive",
        "producthunt": "metalworks.research.sources.producthunt",
        "stackexchange": "metalworks.research.sources.stackexchange",
        "web": "metalworks.research.sources.web",
    }
    if source_id not in SOURCES and source_id in _BUILTIN_MODULES:
        # Lazy self-registration: importing the module runs its register_source.
        import importlib

        importlib.import_module(_BUILTIN_MODULES[source_id])
    try:
        factory = SOURCES[source_id]
    except KeyError as exc:
        raise KeyError(f"unknown source {source_id!r}; registered: {sorted(SOURCES)}") from exc
    return factory(**kwargs)


__all__ = [
    "SOURCES",
    "SOURCE_SPECS",
    "Access",
    "Auth",
    "ItemSource",
    "Lane",
    "SourceFactory",
    "SourceSpec",
    "SourceWindow",
    "Targeting",
    "get_source",
    "register_source",
]
