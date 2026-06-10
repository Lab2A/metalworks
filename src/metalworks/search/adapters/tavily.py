"""Tavily SearchProvider adapter (``metalworks[tavily]``, tavily-python SDK).

Mapping notes:

- ``recency_days`` → Tavily's ``days`` parameter when provided.
- Tavily returns plain dicts (``url`` / ``title`` / ``content``); snippets
  are the first 500 chars of ``content``.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, ClassVar

from metalworks.errors import MissingExtraError, MissingKeyError
from metalworks.search import PROTOCOL_VERSION, SearchResult

_SNIPPET_CHARS = 500


class TavilySearch:
    """SearchProvider over the Tavily search API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "tavily"

    def __init__(self, *, api_key: str | None = None) -> None:
        try:
            tavily = importlib.import_module("tavily")
        except ImportError as exc:
            raise MissingExtraError("tavily", package="tavily-python") from exc
        key = api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise MissingKeyError("TAVILY_API_KEY", provider="Tavily")
        self._client: Any = tavily.TavilyClient(api_key=key)

    def search(
        self,
        *,
        query: str,
        max_results: int = 10,
        recency_days: int | None = None,
    ) -> list[SearchResult]:
        kwargs: dict[str, Any] = {}
        if recency_days is not None:
            kwargs["days"] = recency_days
        response = self._client.search(query, max_results=max_results, **kwargs)
        results: list[SearchResult] = []
        raw: dict[str, Any] = response or {}
        items: list[dict[str, Any]] = list(raw.get("results") or [])
        for item in items:
            content = str(item.get("content", "") or "")
            results.append(
                SearchResult(
                    url=str(item.get("url", "") or ""),
                    title=str(item.get("title", "") or ""),
                    snippet=content[:_SNIPPET_CHARS],
                    published_at=item.get("published_date"),
                    raw=item,
                )
            )
        return results
