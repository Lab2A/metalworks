"""Three-bucket exploration triage tests.

Offline only — FakeEmbedding drives the hybrid score, a FakeChatModel scripted
per output_model stands in for the middle-bucket classifier. No network, no real
LLM (pytest-socket blocks sockets via --disable-socket).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import pytest

from metalworks.contract import TriageThresholds
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.exploration import (
    classify_middle,
    run_exploration_triage,
    triage_by_embedding,
)
from metalworks.research.exploration.llm_classifier import _BatchVerdicts, _Verdict
from metalworks.research.types import ExplorationItem
from metalworks.stores import MemoryStores, SqliteStores


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions"):
        raise NotImplementedError

    def pull_subreddit(self, **_kw: object):
        raise NotImplementedError

    def fetch_submissions_by_ids(self, _ids: object, _months: object):
        raise NotImplementedError

    def close(self) -> None:
        return None


class _RaisingChat(FakeChatModel):
    """A FakeChatModel whose structured calls always raise — used to exercise
    the per-batch failure → reason='other' demotion path."""

    def complete_structured(self, **_kw: Any) -> Any:
        raise RuntimeError("classifier down")


def _deps(chat: FakeChatModel | None = None, *, fast_chat: FakeChatModel | None = None):
    return ResearchDeps(
        chat=chat or FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        fast_chat=fast_chat,
    )


def _items(n: int) -> list[ExplorationItem]:
    return [
        ExplorationItem(idx=i, post_id=f"p{i}", title=f"thread {i}", selftext=f"body {i}")
        for i in range(n)
    ]


# ── triage_by_embedding ─────────────────────────────────────────────────────


def test_triage_three_bucket_split_disjoint_and_complete() -> None:
    pytest.importorskip("rank_bm25")  # triage needs the [research] extra
    deps = _deps()
    items = _items(10)
    thresholds = TriageThresholds(auto_accept_pct=0.2, auto_reject_pct=0.5)
    buckets = triage_by_embedding(deps, question="thread 3", items=items, thresholds=thresholds)

    # Disjoint + complete partition of every input index.
    union = set(buckets.accepted) | set(buckets.rejected) | set(buckets.middle)
    assert union == set(range(10))
    assert len(buckets.accepted) + len(buckets.rejected) + len(buckets.middle) == 10
    # Percentage-driven counts (round(10*0.2)=2 accept, round(10*0.5)=5 reject).
    assert len(buckets.accepted) == 2
    assert len(buckets.rejected) == 5
    assert len(buckets.middle) == 3
    # Dense score vectors, one per item.
    assert len(buckets.cosines) == 10
    assert len(buckets.hybrid_scores) == 10
    assert len(buckets.bm25_scores) == 10


def test_triage_empty_items_returns_empty_buckets() -> None:
    deps = _deps()
    buckets = triage_by_embedding(deps, question="q", items=[], thresholds=TriageThresholds())
    assert buckets.accepted == []
    assert buckets.rejected == []
    assert buckets.middle == []


class _CountingEmbedding:
    """Deterministic FakeEmbedding that counts how many texts it embedded."""

    protocol_version = "test"

    def __init__(self, *, dim: int = 8) -> None:
        self._fake = FakeEmbedding(dim=dim)
        self.model_id = self._fake.model_id
        self.dim = dim
        self.texts_embedded = 0

    def embed(
        self, texts: Sequence[str], *, task: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        self.texts_embedded += len(texts)
        return self._fake.embed(texts, task=task)


def test_triage_reuses_persisted_item_vectors_across_runs(tmp_path: Path) -> None:
    pytest.importorskip("rank_bm25")  # triage needs the [research] extra
    store = SqliteStores(tmp_path / "corpus.db")
    emb = _CountingEmbedding()
    deps = ResearchDeps(chat=FakeChatModel(), embeddings=emb, corpus=store, reader=_NullReader())
    items = _items(6)
    thresholds = TriageThresholds(auto_accept_pct=0.2, auto_reject_pct=0.5)

    triage_by_embedding(deps, question="thread 3", items=items, thresholds=thresholds)
    assert emb.texts_embedded == 1 + 6  # the query + every item

    emb.texts_embedded = 0
    triage_by_embedding(deps, question="thread 3", items=items, thresholds=thresholds)
    assert emb.texts_embedded == 1  # items reused from corpus.db; only the query re-embeds
    store.close()


def test_triage_accept_plus_reject_over_n_squeezes_middle() -> None:
    pytest.importorskip("rank_bm25")  # triage needs the [research] extra
    deps = _deps()
    items = _items(4)
    # 0.8 + 0.8 = 1.6 > 1.0 → middle squeezed to zero, no overlap.
    thresholds = TriageThresholds(auto_accept_pct=0.8, auto_reject_pct=0.8)
    buckets = triage_by_embedding(deps, question="q", items=items, thresholds=thresholds)
    assert buckets.middle == []
    assert len(buckets.accepted) + len(buckets.rejected) == 4
    assert not (set(buckets.accepted) & set(buckets.rejected))


# ── classify_middle ─────────────────────────────────────────────────────────


def test_classify_middle_maps_batch_index_to_global_idx() -> None:
    chat = FakeChatModel()
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(
            verdicts=[
                _Verdict(batch_index=0, relevant=True, reason="on_topic"),
                _Verdict(batch_index=1, relevant=False, reason="off_topic"),
            ]
        ),
    )
    deps = _deps(fast_chat=chat)
    items = _items(5)
    verdicts = classify_middle(
        deps,
        question="q",
        relevance_rubric="r",
        items=items,
        middle_indices=[2, 4],
    )
    # batch_index 0 → global idx 2, batch_index 1 → global idx 4.
    assert verdicts[2].relevant is True
    assert verdicts[2].reason == "on_topic"
    assert verdicts[4].relevant is False
    assert verdicts[4].reason == "off_topic"


def test_classify_middle_unknown_reason_coerced_to_other() -> None:
    chat = FakeChatModel()
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(verdicts=[_Verdict(batch_index=0, relevant=True, reason="WILD_GUESS")]),
    )
    deps = _deps(fast_chat=chat)
    verdicts = classify_middle(
        deps, question="q", relevance_rubric="r", items=_items(1), middle_indices=[0]
    )
    assert verdicts[0].reason == "other"


def test_classify_middle_batch_failure_demotes_to_other() -> None:
    deps = _deps(fast_chat=_RaisingChat())
    items = _items(3)
    verdicts = classify_middle(
        deps, question="q", relevance_rubric="r", items=items, middle_indices=[0, 1, 2]
    )
    # Whole batch failed → every member rejected with reason='other'.
    assert set(verdicts.keys()) == {0, 1, 2}
    assert all(not v.relevant and v.reason == "other" for v in verdicts.values())


def test_classify_middle_missing_verdict_backfilled_as_other() -> None:
    chat = FakeChatModel()
    # Only one of two middle items gets a verdict; the other must backfill.
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(verdicts=[_Verdict(batch_index=0, relevant=True, reason="on_topic")]),
    )
    deps = _deps(fast_chat=chat)
    verdicts = classify_middle(
        deps, question="q", relevance_rubric="r", items=_items(3), middle_indices=[0, 1]
    )
    assert verdicts[0].relevant is True
    assert verdicts[1].relevant is False
    assert verdicts[1].reason == "other"


def test_classify_middle_empty_indices_returns_empty() -> None:
    deps = _deps()
    out = classify_middle(deps, question="q", relevance_rubric="r", items=[], middle_indices=[])
    assert out == {}


# ── run_exploration_triage (orchestrator) ───────────────────────────────────


def test_run_exploration_triage_returns_indices_and_report() -> None:
    pytest.importorskip("rank_bm25")  # triage needs the [research] extra
    chat = FakeChatModel()
    chat.script(_BatchVerdicts, _BatchVerdicts(verdicts=[]))  # middle all backfill→other
    deps = _deps(fast_chat=chat)
    items = _items(10)
    thresholds = TriageThresholds(auto_accept_pct=0.2, auto_reject_pct=0.5)
    relevant, report = run_exploration_triage(
        deps,
        question="thread 3",
        relevance_rubric="r",
        items=items,
        thresholds=thresholds,
    )
    # Accepted bucket always counts as relevant; middle all 'other' → rejected.
    assert len(relevant) == 2
    assert report.threads_pulled == 10
    assert report.threads_auto_accepted == 2
    assert report.threads_auto_rejected == 5
    assert report.threads_classified == 3
    assert report.threads_relevant == 2
    # Funnel composition is surfaced honestly.
    assert report.noise_composition.get("low_cosine_match") == 5


def test_run_exploration_triage_empty_items() -> None:
    deps = _deps()
    relevant, report = run_exploration_triage(
        deps, question="q", relevance_rubric="r", items=[], thresholds=TriageThresholds()
    )
    assert relevant == []
    assert report.threads_pulled == 0


# ── recall backstop + cosine_ceiling safety valve (issue #82) ───────────────


class _MapEmbedding:
    """Embedding stub: known texts → fixed vectors, others → an orthogonal vector.

    Lets a test pin the EXACT cosine of one 'trap' thread to the question, so the
    cosine_ceiling rescue path is exercised deterministically.
    """

    protocol_version = "test"
    model_id = "map/embedding"
    dim = 3

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed(
        self, texts: Sequence[str], *, task: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        return [self._vectors.get(t, [0.0, 0.0, 1.0]) for t in texts]


def test_cosine_ceiling_has_non_none_default() -> None:
    # Issue #82: the safety valve must be ON by default so a high-cosine thread
    # can't be silently auto-rejected on percentile alone.
    assert TriageThresholds().cosine_ceiling == 0.50
    assert TriageThresholds().cosine_ceiling is not None


def test_high_cosine_item_in_reject_band_is_rescued_to_middle() -> None:
    pytest.importorskip("rank_bm25")
    # The trap thread shares the question's vector (cosine 1.0) but carries NO
    # lexical overlap. Bucketing on BM25 only (alpha=0) ranks it into the bottom
    # band; the non-None cosine_ceiling must RESCUE it back to the middle.
    question = "alpha beta gamma delta unique"
    trap = "zzz"  # cosine 1.0 to the question, but shares no tokens → BM25 0
    vectors = {question: [1.0, 0.0, 0.0], trap: [1.0, 0.0, 0.0]}
    items = [
        ExplorationItem(idx=0, post_id="p0", title=question, selftext=""),  # lexical top
        ExplorationItem(idx=1, post_id="p1", title="alpha beta gamma", selftext=""),
        ExplorationItem(idx=2, post_id="p2", title="alpha beta", selftext=""),
        ExplorationItem(idx=3, post_id="p3", title="alpha", selftext=""),
        ExplorationItem(idx=4, post_id="p4", title=trap, selftext=""),  # cosine 1.0, BM25 0
    ]
    deps = ResearchDeps(
        chat=FakeChatModel(),
        embeddings=_MapEmbedding(vectors),
        corpus=MemoryStores(),
        reader=_NullReader(),
    )
    # No ceiling → the trap is auto-rejected on rank alone (the old silent-drop bug).
    no_valve = triage_by_embedding(
        deps,
        question=question,
        items=items,
        thresholds=TriageThresholds(auto_accept_pct=0.2, auto_reject_pct=0.4, cosine_ceiling=None),
        hybrid_alpha=0.0,
    )
    assert 4 in no_valve.rejected
    assert 4 not in no_valve.middle

    # With the default-on ceiling (0.50) the high-cosine trap is rescued to middle.
    rescued = triage_by_embedding(
        deps,
        question=question,
        items=items,
        thresholds=TriageThresholds(auto_accept_pct=0.2, auto_reject_pct=0.4, cosine_ceiling=0.50),
        hybrid_alpha=0.0,
    )
    assert 4 in rescued.middle
    assert 4 not in rescued.rejected
    assert (rescued.band_percentile_disagreement or 0.0) > 0.0


def test_estimate_false_reject_rate_measures_rejected_band() -> None:
    # The backstop samples the reject band and runs it through the SAME classifier;
    # the kept fraction IS the false-reject-rate estimate. Here the scripted
    # classifier keeps everything it sees → rate 1.0.
    chat = FakeChatModel()
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(verdicts=[_Verdict(batch_index=0, relevant=True, reason="on_topic")]),
    )
    deps = _deps(fast_chat=chat)
    from metalworks.research.exploration import estimate_false_reject_rate

    out = estimate_false_reject_rate(
        deps,
        question="q",
        relevance_rubric="r",
        items=_items(5),
        rejected_indices=[3],
        sample_size=20,
    )
    assert out is not None
    rate, n = out
    assert rate == 1.0  # classifier kept the one sampled reject
    assert n == 1


def test_estimate_false_reject_rate_none_when_band_empty_or_disabled() -> None:
    deps = _deps()
    assert estimate_false_reject_rate_proxy(deps, rejected=[], n=20) is None  # empty band
    assert estimate_false_reject_rate_proxy(deps, rejected=[1, 2], n=0) is None  # disabled


def estimate_false_reject_rate_proxy(deps: Any, *, rejected: list[int], n: int):
    from metalworks.research.exploration import estimate_false_reject_rate

    return estimate_false_reject_rate(
        deps,
        question="q",
        relevance_rubric="r",
        items=_items(5),
        rejected_indices=rejected,
        sample_size=n,
    )


def test_run_exploration_triage_emits_false_reject_rate() -> None:
    pytest.importorskip("rank_bm25")
    # The orchestrator runs the backstop and surfaces the estimate on corpus_shape.
    chat = FakeChatModel()
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(
            verdicts=[_Verdict(batch_index=i, relevant=True, reason="on_topic") for i in range(50)]
        ),
    )
    deps = _deps(fast_chat=chat)
    items = _items(10)
    thresholds = TriageThresholds(auto_accept_pct=0.2, auto_reject_pct=0.5, backstop_sample_size=20)
    _relevant, report = run_exploration_triage(
        deps, question="thread 3", relevance_rubric="r", items=items, thresholds=thresholds
    )
    # 5 rejected, all sampled, classifier keeps all → false_reject_rate 1.0.
    assert report.false_reject_rate == 1.0
    assert report.false_reject_sample_size == 5


def test_run_exploration_triage_no_backstop_when_disabled() -> None:
    pytest.importorskip("rank_bm25")
    chat = FakeChatModel()
    chat.script(_BatchVerdicts, _BatchVerdicts(verdicts=[]))
    deps = _deps(fast_chat=chat)
    thresholds = TriageThresholds(auto_accept_pct=0.2, auto_reject_pct=0.5, backstop_sample_size=0)
    _relevant, report = run_exploration_triage(
        deps, question="thread 3", relevance_rubric="r", items=_items(10), thresholds=thresholds
    )
    assert report.false_reject_rate is None
    assert report.false_reject_sample_size == 0
