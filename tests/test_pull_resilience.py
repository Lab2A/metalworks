"""A failing source window degrades the corpus, it never aborts the run (0.3.3).

The reported failure: a live Arctic Shift ``422 Timeout`` on one huge subreddit
killed the whole pull (and the run). `_pull_corpus` is now best-effort per
(source, subreddit) — a window that raises is recorded as a caveat and skipped,
and only an empty corpus stops the run. The 422 itself is now retried in the
reader (see test_arctic_api_reader.py); this guards the layer above it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

from metalworks.contract import ResearchBrief, TargetSubreddit, TriageThresholds
from metalworks.contract.corpus import CorpusRecord
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.arctic.api import ArcticShiftApiError
from metalworks.research.deps import CorpusReader, ResearchDeps
from metalworks.research.pipeline import _pull_corpus
from metalworks.research.sources import SourceWindow
from metalworks.research.types import MonthRef
from metalworks.stores import MemoryStores


class _GoodSource:
    """Yields one record per subreddit pulled."""

    source_id = "good"

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        yield CorpusRecord(
            id=f"{query}-1",
            source="good",
            source_id="1",
            title=f"post in {query}",
            text="body",
            engagement=3,
            extra={"subreddit": query},
        )


class _BoomSource:
    """Raises the way a live Arctic Shift 422 Timeout does, after its own retries."""

    source_id = "boom"

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        raise ArcticShiftApiError(
            f"422 Timeout on /posts/search: the Arctic Shift query for {query} was too heavy"
        )
        yield  # pragma: no cover — marks this a generator; body never reached


def _brief() -> ResearchBrief:
    return ResearchBrief(
        brief_id="b-resilience",
        question="q",
        decision_context="ctx",
        success_criteria=["x"],
        must_address=["y"],
        target_subreddits=[
            TargetSubreddit(name="Small", rationale="ok"),
            TargetSubreddit(name="Huge", rationale="times out"),
        ],
        web_research_directions=[],
        relevance_rubric="r",
        triage_thresholds=TriageThresholds(),
        time_window_months=1,
    )


def _deps(sources: list[object]) -> ResearchDeps:
    return ResearchDeps(
        chat=FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=cast(CorpusReader, object()),  # unused: the sources override bypasses it
        sources=cast("list", sources),
    )


def test_one_boom_source_is_skipped_others_pulled() -> None:
    """A source that raises on every window is skipped (caveat) — the good one still pulls."""
    deps = _deps([_GoodSource(), _BoomSource()])
    items, records, caveats = _pull_corpus(
        deps, _brief(), months=[MonthRef(2025, 1)], per_sub_limit=None
    )
    # The good source produced one record per subreddit; the boom source produced none.
    assert len(items) == 2
    assert {r.id for r in records.values()} == {"Small-1", "Huge-1"}
    # Two windows failed (boom over both Small and Huge); both surfaced as caveats.
    assert len(caveats) == 2
    assert all("boom/" in c and "422 Timeout" in c for c in caveats)


def test_total_failure_yields_empty_corpus_not_a_crash() -> None:
    """If every window fails, _pull_corpus returns empty + caveats — the caller stops cleanly."""
    deps = _deps([_BoomSource()])
    items, records, caveats = _pull_corpus(
        deps, _brief(), months=[MonthRef(2025, 1)], per_sub_limit=None
    )
    assert items == []
    assert records == {}
    assert len(caveats) == 2  # one per subreddit


def test_all_good_has_no_caveats() -> None:
    """The happy path is unchanged: no failures → no caveats."""
    deps = _deps([_GoodSource()])
    items, _records, caveats = _pull_corpus(
        deps, _brief(), months=[MonthRef(2025, 1)], per_sub_limit=None
    )
    assert len(items) == 2
    assert caveats == []
