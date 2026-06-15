"""WebItemSource tests — OFFLINE (pytest-socket blocks real network).

A ``FakeSearchProvider`` returns canned :class:`SearchResult`s (no network). We
assert the connector satisfies the :class:`ItemSource` protocol, maps results to
authorless :class:`CorpusRecord`s with a populated ``extra["domain"]``, respects
``limit``, returns ``None`` from ``comments_for`` (web has no comment layer),
ingests end-to-end idempotently, and resolves through the registry.

The connector imports only the core stack (stdlib + the ``SearchProvider``
protocol), so this whole module runs on the bare CI variant — no optional-dep
imports to guard. (The end-to-end ingest uses ``MemoryStores`` + ``ingest_source``,
both core.)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from metalworks.contract import CorpusRecord
from metalworks.research.sources import ItemSource, SourceWindow, get_source
from metalworks.research.sources.ingest import ingest_source
from metalworks.research.sources.web import (
    WebItemSource,
    _normalize_url,
    _recency_days,
    _registrable_domain,
    _stable_id,
)
from metalworks.search import PROTOCOL_VERSION, SearchResult
from metalworks.stores import MemoryStores
from metalworks.testing import check_item_source

_NOW = datetime(2026, 6, 1, tzinfo=UTC)

# Canned results: distinct domains, one with a published date, one link-only
# (no snippet), plus a duplicate URL (different casing/trailing slash) that must
# collapse to the same stable id, and an empty-URL row that must be skipped.
_RESULTS = [
    SearchResult(
        url="https://www.example.com/focus-aids",
        title="Best stim-free focus aids",
        snippet="People want focus without the caffeine crash.",
        published_at="2026-05-20T00:00:00Z",
    ),
    SearchResult(
        url="https://nootropics.io/stacks",
        title="Nootropic stacks that work",
        snippet="L-theanine plus caffeine is the classic combo.",
        published_at=None,
    ),
    SearchResult(
        url="https://blog.acme.dev/no-crash",
        title="No-crash energy",
        snippet="",  # snippet-less result still maps (text falls back to "")
        published_at=None,
    ),
    # Same page as result[0], different casing + trailing slash → de-duplicated.
    SearchResult(
        url="https://WWW.example.com/focus-aids/",
        title="dup",
        snippet="dup",
    ),
    # Empty URL → skipped.
    SearchResult(url="", title="ghost", snippet="x"),
]


class FakeSearchProvider:
    """A canned :class:`SearchProvider` — no network. Records its last call."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "fake"

    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self._results = results if results is not None else _RESULTS
        self.calls: list[tuple[str, int, int | None]] = []

    def search(
        self,
        *,
        query: str,
        max_results: int = 10,
        recency_days: int | None = None,
    ) -> list[SearchResult]:
        self.calls.append((query, max_results, recency_days))
        return list(self._results[:max_results])


def _source(**kwargs: object) -> WebItemSource:
    provider = kwargs.pop("provider", FakeSearchProvider())
    return WebItemSource(provider=provider, clock=lambda: _NOW, **kwargs)  # type: ignore[arg-type]


# ── Helper-level mapping ──────────────────────────────────────────────────────


def test_normalize_url_collapses_casing_fragment_and_slash() -> None:
    a = _normalize_url("https://WWW.Example.com/Path/#frag")
    b = _normalize_url("https://www.example.com/Path")
    assert a == b == "https://www.example.com/Path"
    assert _stable_id("https://x.com/a/") == _stable_id("https://x.com/a")


def test_registrable_domain_strips_www_and_port() -> None:
    assert _registrable_domain("https://www.example.com/x") == "example.com"
    assert _registrable_domain("https://blog.acme.dev:8443/y") == "blog.acme.dev"
    assert _registrable_domain("https://user:pw@host.io/z") == "host.io"


def test_recency_days_from_window_span() -> None:
    assert _recency_days(SourceWindow(), now=_NOW) is None  # open start → unbounded
    window = SourceWindow(start=datetime(2026, 5, 22, tzinfo=UTC))
    assert _recency_days(window, now=_NOW) == 10


# ── Protocol + pull mapping ───────────────────────────────────────────────────


def test_web_satisfies_protocol() -> None:
    assert isinstance(_source(), ItemSource)


def test_pull_maps_results_to_records() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))

    # Empty-URL row skipped; the duplicate URL collapses → three distinct records.
    assert [r.url for r in records] == [
        "https://www.example.com/focus-aids",
        "https://nootropics.io/stacks",
        "https://blog.acme.dev/no-crash",
    ]

    r0 = records[0]
    assert isinstance(r0, CorpusRecord)
    assert r0.source == "web"
    assert r0.source_id == r0.id == _stable_id("https://www.example.com/focus-aids")
    assert r0.title == "Best stim-free focus aids"
    assert r0.text == "People want focus without the caffeine crash."
    # Authorless, no fabricated engagement.
    assert r0.author_hash == ""
    assert r0.engagement == 0
    # extra carries the domain (web-ranking breadth field) + provider id.
    assert r0.extra == {"domain": "example.com", "provider": "fake"}
    # Published date is parsed; the link-only result falls back to the pull time.
    assert r0.created_at == datetime(2026, 5, 20, tzinfo=UTC)
    assert records[1].created_at == _NOW
    assert records[1].extra["domain"] == "nootropics.io"


def test_pull_honors_limit() -> None:
    provider = FakeSearchProvider()
    src = _source(provider=provider)
    records = list(src.pull(query="focus", window=SourceWindow(), limit=1))
    assert len(records) == 1
    # The provider was capped at the limit (no over-fetch).
    assert provider.calls[0][1] == 1


def test_pull_passes_recency_hint_from_window() -> None:
    provider = FakeSearchProvider()
    src = _source(provider=provider)
    window = SourceWindow(start=datetime(2026, 5, 25, tzinfo=UTC))
    list(src.pull(query="focus", window=window, limit=5))
    query, max_results, recency_days = provider.calls[0]
    assert query == "focus"
    assert max_results == 5
    assert recency_days == 7


# ── Comments + window ─────────────────────────────────────────────────────────


def test_comments_for_returns_none() -> None:
    # Web has no comment layer → None (so the run is recorded comment-less).
    assert _source().comments_for(["web_abc", "web_def"]) is None


def test_latest_window_returns_source_window() -> None:
    win = _source().latest_window()
    assert isinstance(win, SourceWindow)
    assert win.end == _NOW
    assert win.start is None


# ── Conformance + registry ────────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    check_item_source(_source(), query="focus", window=SourceWindow(), limit=None)


def test_get_source_resolves_web() -> None:
    # Registry integration: the id resolves (lazy import self-registers).
    src = get_source("web", provider=FakeSearchProvider())
    assert isinstance(src, WebItemSource)
    assert src.source_id == "web"


def test_web_registers_in_sources() -> None:
    import metalworks.research.sources.web  # noqa: F401
    from metalworks.research.sources import SOURCES

    assert "web" in SOURCES


# ── End-to-end ingest (idempotent) ────────────────────────────────────────────


def test_ingest_source_is_idempotent() -> None:
    corpus = MemoryStores()
    src = WebItemSource(provider=FakeSearchProvider(), clock=lambda: _NOW)
    window = SourceWindow()
    n = 3  # three distinct records after URL de-dup + empty-URL skip

    r1 = ingest_source(corpus, src, query="focus", window=window)
    assert r1.records == n
    # Web has no comments → comment-less run, zero comments.
    assert r1.comments == 0
    assert r1.has_comments is False

    ids = [r.id for r in src.pull(query="focus", window=window)]
    assert len(corpus.get_records(ids)) == n
    assert corpus.get_comments_for_records(ids) == []

    # Re-ingest the same window → no duplicates (upsert keyed on the stable id).
    ingest_source(corpus, src, query="focus", window=window)
    assert len(corpus.get_records(ids)) == n
    persisted = corpus.get_records(ids)
    assert all(r.source == "web" for r in persisted)
    assert all(r.extra.get("domain") for r in persisted)
