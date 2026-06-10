"""External web-search providers (the model-agnostic half of web research).

Internal (model-native) grounding lives on ChatModel adapters as
`complete_grounded` — see metalworks.llm.protocol. The research web stream
prefers internal grounding when `capabilities.native_grounding` is true and
falls back to an external SearchProvider + structured synthesis.

Note for research consumers: different search backends literally see
different webs — provider choice changes results, so it is explicit and
logged, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable

PROTOCOL_VERSION = "1.0"


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    published_at: str | None = None  # ISO 8601 when the provider exposes it
    raw: Any = None


@runtime_checkable
class SearchProvider(Protocol):
    """External search (Exa, Tavily, ...). Adapters live behind extras."""

    protocol_version: ClassVar[str]
    provider_id: str

    def search(
        self,
        *,
        query: str,
        max_results: int = 10,
        recency_days: int | None = None,
    ) -> list[SearchResult]: ...


__all__ = ["PROTOCOL_VERSION", "SearchProvider", "SearchResult"]
