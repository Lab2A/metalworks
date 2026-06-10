"""DiscoveryDeps — the injectable seam the discovery loop speaks through.

Mirrors `ResearchDeps`: one container threaded through `run_discovery`, so the
loop runs offline with fakes and against any provider with real adapters.

The two-model split matches the source's discovery pipeline: `chat` is the
capable "generate" model (voice-matched reply generation, LLM compliance
judge); `fast_chat` is the cheap "filter" model (relevance triage). When only
`chat` is supplied, `fast_chat` falls back to it via `.filter_model`.

The MEMORY system is deliberately NOT a dependency here (v0.1). Voice
guidelines, winning examples, pinned notes, and avoid lists all come from
`context` (a `DiscoveryContext`) — the public seam a caller (a memory system,
or a hand-maintained config) renders its knowledge into. Personas likewise
live on `context.personas`.

Two optional callbacks decouple the metrics-writeback the source baked into
Supabase tables:
- `query_performance(query) -> float` ranks/prioritizes caller-supplied
  queries (the karma/success-rate boost, with no opinion on where the score
  comes from).
- `on_query_result(query, posts_found, posts_kept)` is called once per query
  so a caller can persist per-query metrics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from metalworks.contract import DiscoveryContext

if TYPE_CHECKING:
    from metalworks.llm import ChatModel
    from metalworks.reddit import RedditSearch
    from metalworks.stores.repos import OpportunityRepo


def default_clock() -> datetime:
    return datetime.now(UTC)


def _noop_emit(_stage: str) -> None:
    return None


@dataclass
class DiscoveryDeps:
    """Everything the discovery loop needs, injected once and threaded through.

    Required: `chat`, `search`, `opportunities`. Everything else has a sensible
    default so the smallest call is
    `DiscoveryDeps(chat=..., search=..., opportunities=...)`.
    """

    chat: ChatModel
    search: RedditSearch
    opportunities: OpportunityRepo
    fast_chat: ChatModel | None = None
    context: DiscoveryContext = field(default_factory=DiscoveryContext)
    clock: Callable[[], datetime] = default_clock
    emit: Callable[[str], None] = _noop_emit
    query_performance: Callable[[str], float] | None = None
    on_query_result: Callable[[str, int, int], None] | None = None

    @property
    def filter_model(self) -> ChatModel:
        """The cheap model for triage + the LLM judge; falls back to the capable one."""
        return self.fast_chat if self.fast_chat is not None else self.chat
