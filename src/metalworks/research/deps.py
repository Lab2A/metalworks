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
    from metalworks.contract import SourceSelection
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.research.discovery import DiscoveryProvider
    from metalworks.research.sources import ItemSource
    from metalworks.research.sources.magnitude import MagnitudeProvider
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
    discovery: DiscoveryProvider | None = None
    comments: CommentSource | None = None
    sources: list[ItemSource] | None = None
    magnitude_providers: list[MagnitudeProvider] | None = None
    clock: Callable[[], datetime] = default_clock
    emit: Callable[[str], None] = _noop_emit
    author_salt: str = "metalworks-local"

    @property
    def filter_model(self) -> ChatModel:
        """The cheap model for triage; falls back to the capable one."""
        return self.fast_chat if self.fast_chat is not None else self.chat

    def _arctic_default(self) -> list[ItemSource]:
        """The Reddit/Arctic floor, built from ``reader`` + ``comments``.

        Built here (not as a mutable dataclass default) so which-source-is-default
        stays configurable without touching this seam.
        """
        from metalworks.research.sources.arctic import ArcticItemSource

        return [
            ArcticItemSource(
                reader=self.reader,
                comments=self.comments,
                author_salt=self.author_salt,
            )
        ]

    def effective_sources(self, selection: SourceSelection | None = None) -> list[ItemSource]:
        """The connectors this run pulls from, in precedence order.

        Precedence (the override always wins, so default behavior is unchanged):

        1. **Explicit override** — ``self.sources`` set (CLI ``--source`` /
           ``[sources].enabled`` resolved by the caller). Returned verbatim. Every
           existing caller and the default path pass no ``selection``, so this and
           the floor below are byte-for-byte unchanged.
        2. **Selector output** — a ``selection`` from the brief-aware picker
           (on by default — #167; the pipeline computes one unless ``[sources].select``
           is ``false`` or an override is set). Its ``selected`` ids are constructed
           via the source registry, threading ``reader`` / ``comments`` to whichever
           factory accepts them.
        3. **Floor** — a single :class:`ArcticItemSource` (Reddit), so a run is
           never source-less.

        The selector itself can never reach (3) empty: its non-removable floor
        guarantees a non-empty ``selected`` (falling back to ``reddit``). This
        method's own floor is the belt-and-suspenders for a hand-built selection.
        """
        if self.sources is not None:
            return self.sources
        if selection is not None and selection.selected:
            built = [self._build_selected(sid) for sid in selection.selected]
            return built or self._arctic_default()
        return self._arctic_default()

    def _build_selected(self, source_id: str) -> ItemSource:
        """Construct one selected source via the registry, threading what it takes.

        Reddit/Arctic gets ``reader`` / ``comments`` / ``author_salt`` (the same
        wiring the floor uses); a keyless connector that takes none of them is
        constructed bare. We try the full kwarg set and fall back on ``TypeError``
        so an extra kwarg never breaks a source whose factory doesn't accept it.
        """
        from metalworks.research.sources import get_source

        kwargs = {
            "reader": self.reader,
            "comments": self.comments,
            "author_salt": self.author_salt,
        }
        try:
            return get_source(source_id, **kwargs)
        except TypeError:
            return get_source(source_id)

    def effective_magnitude_providers(self) -> list[MagnitudeProvider]:
        """The lane-② magnitude providers this run measures with, in order.

        Precedence mirrors :meth:`effective_sources`:

        1. **Explicit override** — ``self.magnitude_providers`` set (a test or a
           caller wiring providers directly). Returned verbatim.
        2. **Config** — the opt-in ``[sources].magnitude`` id list, each constructed
           from the :data:`~metalworks.research.sources.magnitude.MAGNITUDE_PROVIDERS`
           registry.
        3. **Empty** — the default. With nothing overridden and nothing configured,
           the magnitude hook is a no-op and the run is byte-for-byte unchanged.

        Magnitude is opt-in and OFF by default, so this returns ``[]`` unless a
        caller or config asks for it — the determinism / no-surprise posture.
        """
        if self.magnitude_providers is not None:
            return self.magnitude_providers
        from metalworks import config
        from metalworks.research.sources.magnitude import get_magnitude_provider

        return [get_magnitude_provider(pid) for pid in config.magnitude_provider_ids()]
