"""Exa SearchProvider adapter (``metalworks[exa]``, exa-py SDK).

Mapping notes:

- ``recency_days`` → ``start_published_date`` (ISO date ``recency_days`` ago).
- ``search_and_contents`` is used so results carry text; snippets are the
  first 500 chars of each result's text.
"""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from metalworks.errors import MissingExtraError, MissingKeyError
from metalworks.search import PROTOCOL_VERSION, SearchResult

_SNIPPET_CHARS = 500


class ExaSearch:
    """SearchProvider over the Exa search-and-contents API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "exa"

    def __init__(self, *, api_key: str | None = None) -> None:
        try:
            exa_py = importlib.import_module("exa_py")
        except ImportError as exc:
            raise MissingExtraError("exa", package="exa-py") from exc
        key = api_key or os.environ.get("EXA_API_KEY")
        if not key:
            raise MissingKeyError("EXA_API_KEY", provider="Exa")
        self._client: Any = exa_py.Exa(api_key=key)

    def search(
        self,
        *,
        query: str,
        max_results: int = 10,
        recency_days: int | None = None,
    ) -> list[SearchResult]:
        kwargs: dict[str, Any] = {}
        if recency_days is not None:
            start = datetime.now(UTC) - timedelta(days=recency_days)
            kwargs["start_published_date"] = start.strftime("%Y-%m-%d")
        response = self._client.search_and_contents(
            query, num_results=max_results, text=True, **kwargs
        )
        results: list[SearchResult] = []
        items: list[Any] = list(getattr(response, "results", None) or [])
        for item in items:
            text: str = getattr(item, "text", None) or ""
            results.append(
                SearchResult(
                    url=getattr(item, "url", None) or "",
                    title=getattr(item, "title", None) or "",
                    snippet=text[:_SNIPPET_CHARS],
                    published_at=getattr(item, "published_date", None),
                    raw=item,
                )
            )
        return results
