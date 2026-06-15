"""Parallel (parallel.ai) SearchProvider adapter (``metalworks[parallel]``).

Integration approach — **httpx against the REST endpoint**, not the SDK call
surface. The ``parallel-web`` SDK's search method namespace is still in beta and
has shifted (``client.search`` vs ``client.beta.search``) between releases, so
pinning to it is fragile. The REST contract at ``/v1beta/search`` is stable and
documented, and ``httpx`` is already a core metalworks dependency. We still
lazy-import the ``parallel`` package inside ``__init__`` purely to gate the
``parallel`` extra (raising :class:`MissingExtraError` when it is absent), so the
install story matches Exa/Tavily exactly.

Mapping notes:

- The query is sent as the Parallel ``objective`` (the API's natural-language
  research goal); ``search_queries`` is left to auto-generation.
- ``recency_days`` → ``source_policy.after_date`` (ISO date ``recency_days`` ago).
- Each result carries an ``excerpts`` list (LLM-optimized snippets); the snippet
  is the first ~500 chars of the joined excerpts. ``publish_date`` → ``published_at``.

REST reference (verified 2026-06): ``POST https://api.parallel.ai/v1beta/search``
with headers ``x-api-key`` + ``parallel-beta: search-extract-2025-10-10``.
"""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx

from metalworks.errors import MissingExtraError, MissingKeyError
from metalworks.search import PROTOCOL_VERSION, SearchResult

_SNIPPET_CHARS = 500
_ENDPOINT = "https://api.parallel.ai/v1beta/search"
_BETA_HEADER = "search-extract-2025-10-10"
_TIMEOUT_S = 60.0


class ParallelSearch:
    """SearchProvider over the Parallel (parallel.ai) Search API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "parallel"

    def __init__(self, *, api_key: str | None = None) -> None:
        # Gate the `parallel` extra. We call the REST endpoint over httpx (see
        # module docstring), but the import keeps the MissingExtraError contract
        # identical to the SDK-backed adapters.
        try:
            importlib.import_module("parallel")
        except ImportError as exc:
            raise MissingExtraError("parallel", package="parallel-web") from exc
        key = api_key or os.environ.get("PARALLEL_API_KEY")
        if not key:
            raise MissingKeyError("PARALLEL_API_KEY", provider="Parallel")
        self._api_key: str = key

    def search(
        self,
        *,
        query: str,
        max_results: int = 10,
        recency_days: int | None = None,
    ) -> list[SearchResult]:
        body: dict[str, Any] = {
            "objective": query,
            "max_results": max_results,
            "excerpts": {"max_chars_per_result": 2000},
        }
        if recency_days is not None:
            after = datetime.now(UTC) - timedelta(days=recency_days)
            body["source_policy"] = {"after_date": after.strftime("%Y-%m-%d")}
        headers = {
            "x-api-key": self._api_key,
            "parallel-beta": _BETA_HEADER,
            "content-type": "application/json",
        }
        response = httpx.post(_ENDPOINT, json=body, headers=headers, timeout=_TIMEOUT_S)
        response.raise_for_status()
        payload: dict[str, Any] = response.json() or {}
        results: list[SearchResult] = []
        items: list[dict[str, Any]] = list(payload.get("results") or [])
        for item in items:
            excerpts: list[Any] = list(item.get("excerpts") or [])
            joined = "\n".join(str(e) for e in excerpts)
            results.append(
                SearchResult(
                    url=str(item.get("url", "") or ""),
                    title=str(item.get("title", "") or ""),
                    snippet=joined[:_SNIPPET_CHARS],
                    published_at=item.get("publish_date"),
                    raw=item,
                )
            )
        return results
