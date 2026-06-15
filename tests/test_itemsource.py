"""ItemSource + ingest + auto-ingest pipeline tests.

A `FakeSource` (source="fake") implements the `ItemSource` protocol and yields a
couple `CorpusRecord` / `CorpusComment` items. We prove:

1. `ingest_source` upserts records + comments and is idempotent (re-ingest →
   no duplicates).
2. `run_research`, given `deps.sources = [FakeSource()]`, ingests-then-
   synthesizes in ONE call on an EMPTY corpus and returns a report (the
   auto-ingest invariant — ingestion is a side effect of the run, not a
   separate step).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import pytest

from metalworks.contract import (
    CorpusComment,
    CorpusRecord,
    ResearchBrief,
    TargetSubreddit,
    TriageThresholds,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.exploration.llm_classifier import _BatchVerdicts, _Verdict
from metalworks.research.pipeline import run_research
from metalworks.research.planner.subreddit_picker import _PickerOutput
from metalworks.research.sources import ItemSource, SourceWindow, get_source, register_source
from metalworks.research.sources.ingest import ingest_source
from metalworks.research.synthesis.cluster_ranker import _CandidateCluster, _SynthesisOutput
from metalworks.research.triangulate.triangulator import _LLMOutput
from metalworks.stores import MemoryStores

_NOW = datetime(2026, 6, 1, tzinfo=UTC)

# Records, each with two comments, all source="fake". Distinct text → distinct
# FakeEmbedding vectors (no dedup collapse), mirroring the e2e fixture.
_RECORDS = [
    ("f1", "people want a stim-free focus aid that does not wreck sleep", 50),
    ("f2", "afternoon crash help, anything that is not caffeine", 30),
    ("f3", "stim free focus options, caffeine wrecks my sleep", 20),
    ("f4", "l-theanine plus caffeine to concentrate at work", 80),
    ("f5", "good budget nootropic stack under thirty a month", 15),
]


class FakeSource:
    """An ItemSource that yields a couple fake records + their comments."""

    source_id = "fake"

    def __init__(self, *, include_sentinel: bool = False) -> None:
        self._include_sentinel = include_sentinel

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        for rid, text, score in _RECORDS:
            yield CorpusRecord(
                id=rid,
                source="fake",
                source_id=rid,
                url=f"https://fake.test/{rid}",
                title=text,
                text=text,
                engagement=score,
                created_at=_NOW,
                extra={"subreddit": "fakeland", "num_comments": 2},
            )

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        return self._iter(record_ids)

    def _iter(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        for rid in record_ids:
            batch = [
                CorpusComment(
                    id=f"{rid}_c1",
                    parent_id=rid,
                    source="fake",
                    url=f"https://fake.test/{rid}/c1",
                    text=f"top comment on {rid}: strongest signal here",
                    author_hash="a1",
                    engagement=20,
                    created_at=_NOW,
                ),
                CorpusComment(
                    id=f"{rid}_c2",
                    parent_id=rid,
                    source="fake",
                    url=f"https://fake.test/{rid}/c2",
                    text=f"second comment on {rid}: quieter but real",
                    author_hash="a2",
                    engagement=5,
                    created_at=_NOW,
                ),
            ]
            if self._include_sentinel:
                # A removal-sentinel comment that ingest must drop.
                batch.append(
                    CorpusComment(
                        id=f"{rid}_c3",
                        parent_id=rid,
                        source="fake",
                        url=f"https://fake.test/{rid}/c3",
                        text="[deleted]",
                        author_hash="[deleted]",
                        engagement=0,
                    )
                )
            yield batch

    def latest_window(self) -> SourceWindow:
        return SourceWindow(start=_NOW, end=_NOW)


def test_fakesource_satisfies_protocol() -> None:
    assert isinstance(FakeSource(), ItemSource)


def test_registry_is_append_friendly() -> None:
    # A connector self-registers without editing a shared inline list.
    register_source("fake", lambda **_: FakeSource())
    src = get_source("fake")
    assert isinstance(src, FakeSource)

    # The built-in Reddit/Arctic connector self-registers on its import — the
    # registry is a shared dict, so a new connector and a built-in coexist with
    # no edit to a shared inline list.
    import metalworks.research.sources.arctic  # noqa: F401
    from metalworks.research.sources import SOURCES

    assert "fake" in SOURCES
    assert "reddit" in SOURCES
    assert "arctic" in SOURCES


def test_ingest_source_is_idempotent() -> None:
    corpus = MemoryStores()
    src = FakeSource(include_sentinel=True)
    window = SourceWindow(start=_NOW, end=_NOW)
    ids = [rid for rid, _, _ in _RECORDS]
    n = len(_RECORDS)

    r1 = ingest_source(corpus, src, query="focus", window=window)
    assert r1.records == n
    # Two real comments per record; the [deleted] sentinel comment is dropped.
    assert r1.comments == 2 * n
    assert r1.has_comments is True

    assert len(corpus.get_records(ids)) == n
    assert len(corpus.get_comments_for_records(ids)) == 2 * n

    # Re-ingest the same window → no duplicates (upsert keyed on id).
    ingest_source(corpus, src, query="focus", window=window)
    assert len(corpus.get_records(ids)) == n
    assert len(corpus.get_comments_for_records(ids)) == 2 * n


def _brief() -> ResearchBrief:
    return ResearchBrief(
        brief_id="b-fake",
        question="what do people want in a focus supplement",
        decision_context="deciding whether to launch a stim-free focus product",
        success_criteria=["clear top demand themes"],
        must_address=["is stim-free demand real"],
        target_subreddits=[TargetSubreddit(name="fakeland", rationale="core")],
        web_research_directions=[],
        relevance_rubric="relevant if about focus",
        triage_thresholds=TriageThresholds(),
        time_window_months=1,
    )


def _scripted_chat() -> FakeChatModel:
    chat = FakeChatModel(grounded=False)
    chat.script(_PickerOutput, _PickerOutput(suggestions=[]))
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(
            verdicts=[_Verdict(batch_index=i, relevant=True, reason="on_topic") for i in range(50)]
        ),
    )
    chat.script(
        _SynthesisOutput,
        _SynthesisOutput(
            clusters=[
                _CandidateCluster(
                    claim="people want stim-free focus",
                    member_comment_indices=[0, 1],
                    quote_comment_indices=[0, 1],
                )
            ]
        ),
    )
    chat.script(_LLMOutput, _LLMOutput(cross_references=[], must_address_resolutions=[]))
    return chat


def _deps(sources: list[ItemSource], corpus: MemoryStores) -> ResearchDeps:
    return ResearchDeps(
        chat=_scripted_chat(),
        embeddings=FakeEmbedding(),
        corpus=corpus,
        reader=_NullReader(),
        sources=sources,
        clock=lambda: _NOW,
    )


class _NullReader:
    """A CorpusReader stub the fake-source path never reads from (sources own
    the pull), but `_window_months` calls `latest_available_month`."""

    def latest_available_month(self, content_type: str = "submissions"):  # type: ignore[no-untyped-def]
        from metalworks.research.types import MonthRef

        return MonthRef(2026, 6)

    def pull_subreddit(self, **_):  # type: ignore[no-untyped-def]
        return iter(())

    def fetch_submissions_by_ids(self, *_):  # type: ignore[no-untyped-def]
        return iter(())

    def close(self) -> None:
        return None


def test_run_research_over_fake_source_one_call_auto_ingest() -> None:
    # EMPTY corpus + research() in ONE call → report (auto-ingest invariant).
    # Runs the full pipeline, which needs the [research] extra (rank-bm25/numpy).
    pytest.importorskip("rank_bm25")
    pytest.importorskip("numpy")
    corpus = MemoryStores()
    all_ids = [rid for rid, _, _ in _RECORDS]
    assert corpus.get_records(all_ids) == []  # truly empty to start

    report = run_research(_deps([FakeSource()], corpus), brief=_brief())

    # A report came back over the fake source's corpus.
    assert report.report_id
    n_relevant = report.total_threads
    assert n_relevant >= 2
    assert len(report.ranked_clusters) == 1

    # Ingestion happened as a SIDE EFFECT of the run: the durable corpus is now
    # populated (the triage-relevant subset) even though we never called ingest
    # separately — the auto-ingest invariant.
    persisted = corpus.get_records(all_ids)
    assert len(persisted) == n_relevant
    assert all(r.source == "fake" for r in persisted)
    comments = corpus.get_comments_for_records(all_ids)
    assert len(comments) == 2 * n_relevant

    # The synthesized cluster's quotes resolve into the fake corpus.
    cluster = report.ranked_clusters[0]
    assert cluster.quotes
    bodies = {c.text for c in comments}
    for q in cluster.quotes:
        assert q.text in bodies
        assert q.source == "fake"
