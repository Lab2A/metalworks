"""``WebItemSource`` — an :class:`ItemSource` over an external web search provider.

Where :mod:`metalworks.research.sources.hackernews` wraps a single keyless REST
API, this connector wraps the *already-shipped* search abstraction: a
:class:`~metalworks.search.SearchProvider` (Exa / Tavily / Parallel / Firecrawl,
resolved by :func:`metalworks.config.resolve_search`). It maps each
:class:`~metalworks.search.SearchResult` onto the source-neutral spine so the open
web becomes one more peer corpus alongside Reddit and HN — flat priority, not a
weighted overlay. (The future web-ranking branch reads ``extra["domain"]`` to
score breadth by distinct domain; populating that field is this connector's only
nod to it — the ranking itself is out of scope here.)

Identity. The web has no native item id, so a record's ``id`` is a stable SHA-1
of its *normalized* URL (lowercased scheme/host, no fragment, no trailing slash).
The same page therefore upserts to the same row across pulls — the idempotency the
corpus and the conformance check require.

Authorless by design. A web page has no single quotable author and no native
engagement signal, so ``author_hash`` is ``""`` and ``engagement`` is ``0`` — we
do NOT fabricate either. There is likewise no comment layer, so
:meth:`comments_for` returns ``None`` (the ingest path records the run as
comment-less rather than failing, exactly as the protocol allows).

``query`` is a free-text search string. ``window.start`` / ``window.end`` drive a
``recency_days`` hint passed to the provider (the search APIs window by recency,
not an absolute span); ``window.months`` is ignored — the web is not partitioned.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from metalworks.contract import CorpusRecord
from metalworks.research.sources import SourceWindow, register_source

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from metalworks.contract import CorpusComment
    from metalworks.search import SearchProvider

# Per-page search fan-out. The pull is a candidate set the pipeline triages, so a
# generous default keeps breadth high without a config knob.
DEFAULT_MAX_RESULTS = 25


def _normalize_url(url: str) -> str:
    """Canonicalize a URL for stable identity: lowercase scheme/host, drop the
    fragment, and strip a lone trailing slash so ``/a`` and ``/a/`` (and
    ``/A#x``) collapse to one id."""
    split = urlsplit(url.strip())
    scheme = split.scheme.lower()
    netloc = split.netloc.lower()
    path = split.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, split.query, ""))


def _stable_id(url: str) -> str:
    """A stable, collision-resistant id from the normalized URL (SHA-1 hex)."""
    return f"web_{hashlib.sha1(_normalize_url(url).encode()).hexdigest()[:16]}"


def _registrable_domain(url: str) -> str:
    """The hostname without a leading ``www.`` — the field web-ranking counts.

    Deliberately NOT a public-suffix split (no ``tldextract`` dependency): the
    host is precise enough for distinct-domain breadth, and a bare host keeps the
    connector dependency-free. Empty when the URL has no host.
    """
    host = urlsplit(url.strip()).netloc.lower()
    if "@" in host:  # strip any userinfo
        host = host.rsplit("@", 1)[-1]
    if ":" in host:  # strip a port
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _parse_published(published_at: str | None) -> datetime | None:
    """Parse a provider's ISO-8601 ``published_at`` into a UTC datetime, or ``None``."""
    if not published_at:
        return None
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _recency_days(window: SourceWindow, *, now: datetime) -> int | None:
    """Translate a ``[start, end]`` span into the providers' ``recency_days`` hint.

    The search APIs window by "results newer than N days", not by an absolute
    range, so we approximate the span as the days from ``window.start`` to now
    (rounded up). No ``start`` → ``None`` (unbounded), matching the providers'
    "search everything" default.
    """
    if window.start is None:
        return None
    delta = now - window.start
    days = math.ceil(delta.total_seconds() / 86400.0)
    return days if days > 0 else 1


class WebItemSource:
    """:class:`ItemSource` mapping web-search results onto the corpus spine.

    The :class:`~metalworks.search.SearchProvider` is injected for testability
    (constructor injection with a lazy default, mirroring the other connectors):
    pass a ``provider`` explicitly, or leave it ``None`` to resolve one from the
    environment via :func:`metalworks.config.resolve_search` on first pull.
    """

    source_id = "web"
    # Web has no comment layer: each record (a page) is a self-representing
    # synthesis unit — its own text is the demand signal. The pipeline reads this
    # opt-in flag to promote web records to units and rank them by domain breadth.
    yields_units = True

    def __init__(
        self,
        *,
        provider: SearchProvider | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        clock: Any | None = None,
    ) -> None:
        self._provider = provider
        self._max_results = max_results
        # Injectable clock for deterministic windows/timestamps in tests; defaults
        # to wall-clock UTC (library runtime code, so a bare datetime.now is fine).
        self._clock = clock

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else datetime.now(tz=UTC)

    def _resolved_provider(self) -> SearchProvider:
        """Lazily resolve a provider from the environment when none was injected.

        Resolution costs nothing until first pull (so a bare ``import`` is free),
        and :func:`resolve_search` returns ``None`` when no search key is set —
        which we surface as a clear error rather than a silent empty pull.
        """
        if self._provider is None:
            from metalworks.config import resolve_search

            resolved = resolve_search()
            if resolved is None:
                raise RuntimeError(
                    "WebItemSource has no SearchProvider: set a search key "
                    "(EXA_API_KEY / TAVILY_API_KEY / PARALLEL_API_KEY / "
                    "FIRECRAWL_API_KEY) or pass provider= explicitly."
                )
            self._provider = resolved
        return self._provider

    # ── pull (search results → CorpusRecord) ──────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate web records for ``query`` over ``window``.

        Runs ONE provider search (capped by ``limit`` and ``max_results``) and
        maps each result to a :class:`CorpusRecord`. ``window`` is translated to a
        ``recency_days`` hint; ``window.months`` is ignored — the web is not
        month-partitioned. The pull is the candidate set the pipeline triages, so
        a URL seen twice in one search is de-duplicated by its stable id here.
        """
        provider = self._resolved_provider()
        now = self._now()
        cap = self._max_results if limit is None else min(self._max_results, limit)
        if cap <= 0:
            return
        results = provider.search(
            query=query,
            max_results=cap,
            recency_days=_recency_days(window, now=now),
        )
        seen: set[str] = set()
        emitted = 0
        for result in results:
            url = (result.url or "").strip()
            if not url:
                continue
            record_id = _stable_id(url)
            if record_id in seen:
                continue
            seen.add(record_id)
            yield CorpusRecord(
                id=record_id,
                source="web",
                source_id=record_id,
                url=url,
                title=result.title or "",
                text=result.snippet or "",
                author_hash="",  # the web is authorless — expected, not a gap
                engagement=0,  # the web has no native engagement; do not fabricate
                created_at=_parse_published(result.published_at) or now,
                extra={
                    "domain": _registrable_domain(url),
                    "provider": provider.provider_id,
                },
            )
            emitted += 1
            if limit is not None and emitted >= limit:
                return

    # ── comments (web has none) ───────────────────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """The web has no comment layer → return ``None``.

        Per the protocol, ``None`` (not an empty iterator) marks the source as
        comment-less, so the ingest path records the run that way instead of
        treating it as a failure.
        """
        _ = record_ids
        return None

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """The web has no archive horizon; the latest window ends now.

        ``start`` is ``None`` (open) so an un-narrowed pull searches everything;
        ``months`` is empty — the web windows by recency only.
        """
        return SourceWindow(end=self._now())


def _factory(**kwargs: Any) -> WebItemSource:
    return WebItemSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors hackernews.py).
register_source("web", _factory)


__all__ = ["WebItemSource"]
