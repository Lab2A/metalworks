"""ResearchDeps — the injectable seam every pipeline stage speaks through.

Replaces the source's module-level llm_client / embeddings / supabase
singletons. One container, threaded through every stage, so the pipeline runs
offline with fakes and against any provider with real adapters.

The two ChatModels mirror the source's two-model split: `chat` is the capable
"generate" model (synthesis, triangulation, planning, grounded web research);
`fast_chat` is the cheap "filter" model (middle-bucket triage classification).
When only `chat` is supplied, `fast_chat` falls back to it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.research.sources import ItemSource
    from metalworks.research.types import MonthRef
    from metalworks.search import SearchProvider
    from metalworks.stores.repos import CorpusRepo


@runtime_checkable
class CorpusReader(Protocol):
    """The submissions corpus reader (Arctic Shift over DuckDB, or a fake).

    Submissions come from here; comments come from `CommentSource` (the live
    API), because the bulk archive's comment tree lags by years.
    """

    def latest_available_month(self, content_type: str = "submissions") -> MonthRef: ...

    def pull_subreddit(
        self,
        *,
        subreddit: str,
        content_type: str,
        months: Sequence[MonthRef],
        select_cols: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def fetch_submissions_by_ids(
        self, post_ids: Sequence[str], months: Sequence[MonthRef]
    ) -> Iterator[dict[str, Any]]:
        """Public hydration read — replaces the source's reach into reader
        privates (`_con` / `_resolve_patterns`)."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class CommentSource(Protocol):
    """Per-link comment fetch (the live Arctic Shift API, or a fake)."""

    def comments_for_links(self, link_ids: Sequence[str]) -> Iterator[list[dict[str, Any]]]: ...


def default_clock() -> datetime:
    return datetime.now(UTC)


def _noop_emit(_stage: str) -> None:
    return None


@dataclass
class ResearchDeps:
    """Everything the pipeline needs, injected once and threaded through.

    Required: `chat`, `embeddings`, `corpus`, `reader`. Everything else has a
    sensible default so the smallest call is `ResearchDeps(chat=..., ...)`.
    """

    chat: ChatModel
    embeddings: EmbeddingProvider
    corpus: CorpusRepo
    reader: CorpusReader
    fast_chat: ChatModel | None = None
    search: SearchProvider | None = None
    comments: CommentSource | None = None
    sources: list[ItemSource] | None = None
    clock: Callable[[], datetime] = default_clock
    emit: Callable[[str], None] = _noop_emit
    author_salt: str = "metalworks-local"

    @property
    def filter_model(self) -> ChatModel:
        """The cheap model for triage; falls back to the capable one."""
        return self.fast_chat if self.fast_chat is not None else self.chat

    def effective_sources(self) -> list[ItemSource]:
        """The configured connectors, defaulting to Reddit/Arctic.

        When ``sources`` is unset (the common case, and every existing caller),
        derive a single :class:`ArcticItemSource` from ``reader`` + ``comments``
        so behavior is unchanged: research still ingests-then-synthesizes Reddit
        in one call. The default is deliberately built here, NOT hardcoded as a
        mutable dataclass default — which-source-is-default stays configurable by
        a later ``[sources]`` config stream without touching this seam.
        """
        if self.sources is not None:
            return self.sources
        from metalworks.research.sources.arctic import ArcticItemSource

        return [
            ArcticItemSource(
                reader=self.reader,
                comments=self.comments,
                author_salt=self.author_salt,
            )
        ]
