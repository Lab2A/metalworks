"""Firecrawl SearchProvider adapter (``metalworks[firecrawl]``).

Firecrawl is primarily a scraper/crawler; its deeper scrape + crawl role
belongs to a *later* phase. Here it is a **thin SearchProvider shim** only — it
calls Firecrawl's ``/v2/search`` endpoint, which combines a web search with
optional per-result scraping.

Integration approach — **httpx against the REST endpoint**, not the SDK call
surface. The ``firecrawl-py`` search method shape has churned across v1/v2, so
we hit the documented ``/v2/search`` REST contract directly (``httpx`` is a core
metalworks dependency). We still lazy-import the ``firecrawl`` package inside
``__init__`` purely to gate the ``firecrawl`` extra (raising
:class:`MissingExtraError` when it is absent), matching Exa/Tavily.

Mapping notes:

- ``recency_days`` → Firecrawl's ``tbs`` time-based filter (``qdr:d/w/m/y``,
  the coarsest bucket that covers the window).
- Results live under ``data.web``; each has ``url`` / ``title`` /
  ``description`` and, when ``scrapeOptions`` is set, ``markdown``. The snippet
  is the first ~500 chars of ``markdown`` if present, else ``description``.

REST reference (verified 2026-06): ``POST https://api.firecrawl.dev/v2/search``
with a ``Bearer`` token.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, ClassVar

import httpx

from metalworks.errors import MissingExtraError, MissingKeyError
from metalworks.search import PROTOCOL_VERSION, SearchResult

_SNIPPET_CHARS = 500
_ENDPOINT = "https://api.firecrawl.dev/v2/search"
_TIMEOUT_S = 60.0


def _tbs_for_days(recency_days: int) -> str:
    """Map a day window to Firecrawl's coarsest covering ``tbs`` bucket."""
    if recency_days <= 1:
        return "qdr:d"
    if recency_days <= 7:
        return "qdr:w"
    if recency_days <= 31:
        return "qdr:m"
    return "qdr:y"


class FirecrawlSearch:
    """SearchProvider over the Firecrawl ``/v2/search`` API (thin shim)."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "firecrawl"

    def __init__(self, *, api_key: str | None = None) -> None:
        # Gate the `firecrawl` extra. We call the REST endpoint over httpx (see
        # module docstring); the import keeps the MissingExtraError contract
        # identical to the SDK-backed adapters.
        try:
            importlib.import_module("firecrawl")
        except ImportError as exc:
            raise MissingExtraError("firecrawl", package="firecrawl-py") from exc
        key = api_key or os.environ.get("FIRECRAWL_API_KEY")
        if not key:
            raise MissingKeyError("FIRECRAWL_API_KEY", provider="Firecrawl")
        self._api_key: str = key

    def search(
        self,
        *,
        query: str,
        max_results: int = 10,
        recency_days: int | None = None,
    ) -> list[SearchResult]:
        body: dict[str, Any] = {
            "query": query,
            "limit": max_results,
            "scrapeOptions": {"formats": ["markdown"]},
        }
        if recency_days is not None:
            body["tbs"] = _tbs_for_days(recency_days)
        headers = {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }
        response = httpx.post(_ENDPOINT, json=body, headers=headers, timeout=_TIMEOUT_S)
        response.raise_for_status()
        payload: dict[str, Any] = response.json() or {}
        data: dict[str, Any] = payload.get("data") or {}
        items: list[dict[str, Any]] = list(data.get("web") or [])
        results: list[SearchResult] = []
        for item in items:
            markdown = str(item.get("markdown", "") or "")
            description = str(item.get("description", "") or "")
            snippet = (markdown or description)[:_SNIPPET_CHARS]
            results.append(
                SearchResult(
                    url=str(item.get("url", "") or ""),
                    title=str(item.get("title", "") or ""),
                    snippet=snippet,
                    published_at=None,
                    raw=item,
                )
            )
        return results
