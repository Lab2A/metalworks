"""Resume + progress: per-stage checkpoints, the fresh-run-unchanged invariant,
resume-skips-completed-stages, and the progress heartbeat.

Fully offline (no duckdb): a hand-rolled counting CorpusReader + FakeComments +
FakeEmbedding + MemoryStores + a scripted FakeChatModel, so these run in both the
all-extras and the bare matrix.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import (
    ResearchBrief,
    RunSummary,
    TargetSubreddit,
    TriageThresholds,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel, GroundedResult, GroundingChunk, GroundingSupport
from metalworks.research import run_research
from metalworks.research.checkpoints import (
    PIPELINE_STAGES,
    AnalyzingCheckpoint,
    HydratingCheckpoint,
    PlanningCheckpoint,
    PullingCheckpoint,
    TriagingCheckpoint,
    TriangulatingCheckpoint,
)
from metalworks.research.deps import ResearchDeps
from metalworks.research.exploration.llm_classifier import _BatchVerdicts, _Verdict
from metalworks.research.planner.subreddit_picker import _PickerOutput
from metalworks.research.synthesis.cluster_ranker import _CandidateCluster, _SynthesisOutput
from metalworks.research.triangulate.triangulator import (
    _LLMCrossReference,
    _LLMOutput,
    _LLMResolution,
)
from metalworks.research.types import MonthRef
from metalworks.stores import MemoryStores

# The full pipeline (triage's BM25) needs the [research] extra; the bare matrix
# (`.[dev]` only) lacks it, so pipeline-running tests skip there — the pure
# contract / emit / envelope-surface tests still run in both matrices.
needs_research = pytest.mark.skipif(
    importlib.util.find_spec("rank_bm25") is None,
    reason="needs the [research] extra (rank-bm25) for the triage stage",
)

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_CREATED = _NOW.timestamp()

_SUBMISSIONS: dict[str, list[dict[str, Any]]] = {
    "Supplements": [
        {"id": "p1", "title": "focus blend review", "selftext": "citicoline stack works"},
        {"id": "p2", "title": "afternoon crash help", "selftext": "anything for the 3pm crash"},
        {"id": "p3", "title": "stim free options", "selftext": "stim-free focus, caffeine bad"},
    ],
    "Nootropics": [
        {"id": "p4", "title": "l-theanine combo", "selftext": "l-theanine plus caffeine"},
        {"id": "p5", "title": "budget stacks", "selftext": "good budget nootropic under 30"},
    ],
}


class CountingReader:
    """A minimal CorpusReader over an in-memory submission table; counts pulls."""

    def __init__(self) -> None:
        self.pull_calls = 0

    def latest_available_month(self, content_type: str = "submissions") -> MonthRef:
        return MonthRef(2026, 6)

    def pull_subreddit(
        self, *, subreddit: str, content_type: str, months: Any, **_kw: Any
    ) -> Iterator[dict[str, Any]]:
        self.pull_calls += 1
        for row in _SUBMISSIONS.get(subreddit, []):
            yield {
                "id": row["id"],
                "title": row["title"],
                "selftext": row["selftext"],
                "subreddit": subreddit,
                "score": 10,
                "num_comments": 4,
                "author": f"user_{row['id']}",
                "url": f"https://reddit.com/r/{subreddit}/comments/{row['id']}/",
                "created_utc": _CREATED,
            }

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Iterator[dict[str, Any]]:
        return iter(())

    def close(self) -> None:
        return None


class FakeComments:
    """CommentSource yielding two distinct comments per relevant post."""

    def comments_for_links(self, link_ids: Any) -> Iterator[list[dict[str, Any]]]:
        for lid in link_ids:
            yield [
                {
                    "id": f"c_{lid}_a",
                    "link_id": f"t3_{lid}",
                    "subreddit": "Supplements",
                    "body": f"top comment on {lid}: the strongest signal here",
                    "author": f"commenter_{lid}_a",
                    "score": 40,
                    "created_utc": _CREATED,
                },
                {
                    "id": f"c_{lid}_b",
                    "link_id": f"t3_{lid}",
                    "subreddit": "Supplements",
                    "body": f"second comment on {lid}: a quieter but real opinion",
                    "author": f"commenter_{lid}_b",
                    "score": 10,
                    "created_utc": _CREATED,
                },
            ]


def _brief() -> ResearchBrief:
    return ResearchBrief(
        brief_id="b-resume",
        question="what do people want in a focus supplement",
        decision_context="deciding whether to launch a stim-free focus product",
        success_criteria=["clear top demand themes"],
        must_address=["is stim-free demand real"],
        target_subreddits=[
            TargetSubreddit(name="Supplements", rationale="core"),
            TargetSubreddit(name="Nootropics", rationale="adjacent"),
        ],
        web_research_directions=["market size"],
        relevance_rubric="relevant if about focus, energy, or nootropic supplements",
        triage_thresholds=TriageThresholds(),
        time_window_months=1,
    )


def _scripted_chat() -> FakeChatModel:
    chat = FakeChatModel(grounded=True)
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
                    claim="people want stim-free focus that does not wreck sleep",
                    member_comment_indices=[0, 1],
                    quote_comment_indices=[0, 1],
                )
            ]
        ),
    )
    chat.script(
        _LLMOutput,
        _LLMOutput(
            cross_references=[
                _LLMCrossReference(
                    cluster_id="cluster:1",
                    web_finding_ids=["web:1"],
                    agreement="agree",
                    note="both streams show stim-free demand",
                )
            ],
            must_address_resolutions=[
                _LLMResolution(
                    must_address_item="is stim-free demand real", resolved_by="cluster:1"
                )
            ],
        ),
    )
    text = "1. CLAIM: the focus supplement market is growing\n   SPECIFICS: +18% in 2025\n"
    chat.grounded_results.append(
        GroundedResult(
            text=text,
            chunks=(GroundingChunk(uri="https://example.com/report", title="Market Report"),),
            supports=(GroundingSupport(start_char=0, end_char=len(text), chunk_indices=(0,)),),
        )
    )
    return chat


def _deps(
    *, reader: CountingReader | None = None, corpus: MemoryStores | None = None
) -> ResearchDeps:
    return ResearchDeps(
        chat=_scripted_chat(),
        embeddings=FakeEmbedding(),
        corpus=corpus if corpus is not None else MemoryStores(),
        reader=reader if reader is not None else CountingReader(),
        comments=FakeComments(),
        author_salt="test-salt",
        clock=lambda: _NOW,
    )


# ── Contract: additive round-trip ───────────────────────────────────────────


def test_runsummary_additive_old_payload_validates() -> None:
    """A payload WITHOUT the new progress fields still validates (additive)."""
    old = {
        "report_id": "r1",
        "query": "q",
        "status": "queued",
        "created_at": _NOW.isoformat(),
    }
    run = RunSummary.model_validate(old)
    assert run.stage is None
    assert run.stage_index is None
    assert run.stage_total is None
    assert run.updated_at is None


def test_runsummary_progress_roundtrip() -> None:
    run = RunSummary(
        report_id="r1",
        query="q",
        status="analyzing_relevant",
        stage="analyzing",
        stage_index=4,
        stage_total=6,
        created_at=_NOW,
        updated_at=_NOW,
    )
    back = RunSummary.model_validate_json(run.model_dump_json())
    assert back.stage == "analyzing"
    assert back.stage_index == 4
    assert back.stage_total == 6
    assert back.updated_at == _NOW


# ── The critical invariant: fresh run identical with/without a checkpoint store ─


@needs_research
def test_fresh_run_unchanged_with_and_without_checkpoints() -> None:
    """Same run_id, one run with a checkpoint store and one without → byte-identical
    reports. The checkpoint-or-compute wrapper is a transparent pass-through when no
    checkpoint exists."""
    rid = "fixed-run-id"
    report_no_cp = run_research(_deps(), brief=_brief(), run_id=rid, checkpoints=None)
    store = MemoryStores()
    report_cp = run_research(_deps(corpus=store), brief=_brief(), run_id=rid, checkpoints=store)
    assert report_no_cp.report_id == rid == report_cp.report_id
    assert report_no_cp.model_dump_json() == report_cp.model_dump_json()


@needs_research
def test_run_id_is_report_id_and_default_generates() -> None:
    report = run_research(_deps(), brief=_brief(), run_id="abc-123")
    assert report.report_id == "abc-123"
    gen = run_research(_deps(), brief=_brief())  # no run_id → fresh uuid, no checkpoints
    assert gen.report_id and gen.report_id != "abc-123"


# ── Per-stage serializer round-trips (on real run data) ──────────────────────

_STAGE_MODELS = {
    "planning": PlanningCheckpoint,
    "pulling": PullingCheckpoint,
    "triaging": TriagingCheckpoint,
    "hydrating": HydratingCheckpoint,
    "analyzing": AnalyzingCheckpoint,
    "triangulating": TriangulatingCheckpoint,
}


@needs_research
def test_each_stage_checkpoint_roundtrips_losslessly() -> None:
    store = MemoryStores()
    run_research(_deps(corpus=store), brief=_brief(), run_id="rt", checkpoints=store)
    for stage, model_cls in _STAGE_MODELS.items():
        raw = store.get_checkpoint("rt", stage)
        assert raw is not None, f"missing checkpoint for {stage}"
        parsed = model_cls.model_validate_json(raw)
        # Re-serializing the parsed envelope is byte-identical → lossless.
        assert parsed.model_dump_json() == raw


# ── Resume skips completed stages ────────────────────────────────────────────


@needs_research
def test_resume_skips_completed_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure in `analyzing` keeps the ≤hydrating checkpoints; resume re-runs
    only from analyzing — the corpus pull and subreddit pick are NOT redone."""
    import metalworks.research.pipeline as pipe

    store = MemoryStores()
    reader = CountingReader()

    # Spy: count subreddit-pick calls (planning) through the pipeline's binding.
    pick_calls = {"n": 0}
    real_pick = pipe.pick_target_subreddits

    def _spy_pick(*a: Any, **k: Any) -> Any:
        pick_calls["n"] += 1
        return real_pick(*a, **k)

    monkeypatch.setattr(pipe, "pick_target_subreddits", _spy_pick)

    # Make synthesize raise on the FIRST attempt only (fails in `analyzing`).
    real_synth = pipe.synthesize
    synth_calls = {"n": 0}

    def _flaky_synth(*a: Any, **k: Any) -> Any:
        synth_calls["n"] += 1
        if synth_calls["n"] == 1:
            raise RuntimeError("boom in synthesis")
        return real_synth(*a, **k)

    monkeypatch.setattr(pipe, "synthesize", _flaky_synth)

    deps1 = _deps(reader=reader, corpus=store)
    with pytest.raises(RuntimeError, match="boom in synthesis"):
        run_research(deps1, brief=_brief(), run_id="resume-1", checkpoints=store)

    # Stages up to and including hydrating are checkpointed; analyzing is not.
    for stage in ("planning", "pulling", "triaging", "hydrating"):
        assert store.get_checkpoint("resume-1", stage) is not None, stage
    assert store.get_checkpoint("resume-1", "analyzing") is None
    pulls_before = reader.pull_calls
    picks_before = pick_calls["n"]
    assert pulls_before > 0 and picks_before == 1

    # Resume: same run_id, fresh deps (fresh reader so a re-pull would be visible).
    reader2 = CountingReader()
    deps2 = _deps(reader=reader2, corpus=store)
    report = run_research(deps2, brief=_brief(), run_id="resume-1", checkpoints=store)

    # The completed stages were loaded — the new reader was NOT pulled, and the
    # subreddit picker (planning) was NOT called again.
    assert reader2.pull_calls == 0, "resume must not re-pull the corpus"
    assert pick_calls["n"] == picks_before, "resume must not re-pick subreddits"
    assert report.report_id == "resume-1"
    assert report.ranked_clusters, "resumed run still produces a real report"


@needs_research
def test_resume_reuses_planning_not_a_fresh_llm_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    """The non-determinism capture: on resume, the checkpointed planning is reused,
    so pick_target_subreddits is not called again."""
    import metalworks.research.pipeline as pipe

    store = MemoryStores()
    run_research(_deps(corpus=store), brief=_brief(), run_id="nd", checkpoints=store)
    assert store.get_checkpoint("nd", "planning") is not None

    calls = {"n": 0}

    def _boom_pick(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        raise AssertionError("pick_target_subreddits must not run on resume")

    monkeypatch.setattr(pipe, "pick_target_subreddits", _boom_pick)
    # Re-run the same id: every stage is checkpointed, so planning is loaded.
    report = run_research(_deps(corpus=store), brief=_brief(), run_id="nd", checkpoints=store)
    assert calls["n"] == 0
    assert report.report_id == "nd"


@needs_research
def test_resume_produces_same_report_id_and_clusters() -> None:
    store = MemoryStores()
    first = run_research(_deps(corpus=store), brief=_brief(), run_id="same", checkpoints=store)
    # A full re-run with all checkpoints present loads everything.
    again = run_research(_deps(corpus=store), brief=_brief(), run_id="same", checkpoints=store)
    assert first.report_id == again.report_id == "same"
    assert [c.claim for c in first.ranked_clusters] == [c.claim for c in again.ranked_clusters]
    assert again.model_dump_json() == first.model_dump_json()


# ── Progress heartbeat ───────────────────────────────────────────────────────


def test_emit_sink_updates_runsummary_stage_fields() -> None:
    from metalworks.mcp.jobs import _make_emit

    runs = MemoryStores()
    brief = _brief()
    emit = _make_emit(run_id="job-1", brief=brief, runs=runs, created_at=_NOW)
    emit("analyzing")
    run = runs.get_run("job-1")
    assert run is not None
    assert run.status == "analyzing_relevant"
    assert run.stage == "analyzing"
    assert run.stage_index == PIPELINE_STAGES.index("analyzing") + 1 == 4
    assert run.stage_total == len(PIPELINE_STAGES) == 6
    assert run.updated_at is not None


def test_emit_sink_swallows_save_errors() -> None:
    from metalworks.mcp.jobs import _make_emit

    class _Boom:
        def save_run(self, _run: RunSummary) -> None:
            raise RuntimeError("store down")

    emit = _make_emit(run_id="x", brief=_brief(), runs=_Boom(), created_at=_NOW)  # type: ignore[arg-type]
    emit("pulling")  # must not raise


# ── MCP / facade surfaces ────────────────────────────────────────────────────


def test_research_resume_mcp_not_found_envelope() -> None:
    from metalworks.mcp import tools

    res = tools.research_resume("does-not-exist", store_path=":memory:")
    assert "error" in res
    assert res["error"]["error_code"] == "not_found"


@needs_research
def test_research_resume_mcp_returns_report_when_complete(tmp_path: Any) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    db = str(tmp_path / "store.db")
    store = config.default_store(db)
    report = run_research(_deps(corpus=store), brief=_brief(), run_id="done-1", checkpoints=store)
    store.save_report(report)
    store.save_run(RunSummary.from_report(report, question="q"))
    res = tools.research_resume("done-1", store_path=db)
    assert "report" in res
    assert res["report"]["report_id"] == "done-1"


@needs_research
def test_facade_research_resume_returns_completed_report() -> None:
    from metalworks import Metalworks

    store = MemoryStores()
    report = run_research(_deps(corpus=store), brief=_brief(), run_id="fac-1", checkpoints=store)
    store.save_report(report)
    store.save_run(RunSummary.from_report(report, question="q"))
    m = Metalworks(store=store)
    bundle = m.research_resume("fac-1")
    assert bundle.demand.report_id == "fac-1"


def test_facade_research_resume_missing_brief_raises() -> None:
    from metalworks import Metalworks

    m = Metalworks(store=MemoryStores())
    with pytest.raises(KeyError):
        m.research_resume("nope")
