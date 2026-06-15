"""Offline end-to-end pipeline test — the M2 capstone.

Runs the FULL research pipeline (reader → triage → hydration → synthesis ‖
web → triangulate → assembly) with zero network: a local DuckDB-written
parquet corpus, a fake comment source, FakeEmbedding, MemoryStores, and a
scripted FakeChatModel. Proves the wiring holds and the structural-provenance
contract survives the whole pipeline (every ResolvedCitation resolves into the
hydrated corpus).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from metalworks.contract import (
    DemandReport,
    ResearchBrief,
    TargetSubreddit,
    TriageThresholds,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel, GroundedResult, GroundingChunk, GroundingSupport
from metalworks.research.arctic.reader import ArcticReader
from metalworks.research.deps import ResearchDeps
from metalworks.research.exploration.llm_classifier import _BatchVerdicts, _Verdict
from metalworks.research.pipeline import run_research
from metalworks.research.planner.subreddit_picker import _PickerOutput
from metalworks.research.synthesis.cluster_ranker import _CandidateCluster, _SynthesisOutput
from metalworks.research.triangulate.triangulator import (
    _LLMCrossReference,
    _LLMOutput,
    _LLMResolution,
)
from metalworks.stores import MemoryStores

# DuckDB ([arctic]/[all] extra) writes the local parquet fixture; skip without it.
duckdb = pytest.importorskip("duckdb")

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_CREATED = _NOW.timestamp()

# Distinct text per submission so FakeEmbedding gives distinct vectors (no
# dedup collapse). Columns: id, subreddit, title, selftext, score, num_comments.
_SUBMISSIONS = [
    ("p1", "Supplements", "focus blend review", "citicoline stack works for me", 50, 12),
    ("p2", "Supplements", "afternoon crash help", "anything for the 3pm crash not caffeine", 30, 8),
    ("p3", "Supplements", "stim free options", "stim-free focus, caffeine wrecks my sleep", 20, 5),
    ("p4", "Nootropics", "l-theanine combo", "l-theanine plus caffeine to concentrate", 80, 20),
    ("p5", "Nootropics", "budget stacks", "good budget nootropic stack under 30 a month", 15, 3),
]


def _write_corpus(root: Path, *, year: int, month: int) -> None:
    """Write the submissions parquet at {root}/submissions/YYYY/MM/data.parquet."""
    out_dir = root / "submissions" / f"{year:04d}" / f"{month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        values = ",\n".join(
            "('{id}', '{author}', '{sub}', '{title}', '{body}', {score}, {nc}, "
            "'https://reddit.com/r/{sub}/comments/{id}/', {created})".format(
                id=sid,
                author=f"user_{sid}",
                sub=sub,
                title=title.replace("'", "''"),
                body=body.replace("'", "''"),
                score=score,
                nc=nc,
                created=_CREATED,
            )
            for sid, sub, title, body, score, nc in _SUBMISSIONS
        )
        con.execute(
            f"COPY (SELECT * FROM (VALUES\n{values}\n) AS t("
            "id, author, subreddit, title, selftext, score, num_comments, url, created_utc"
            f")) TO '{out_dir / 'data.parquet'}' (FORMAT PARQUET)"
        )
    finally:
        con.close()


class _FakeComments:
    """CommentSource yielding two distinct comments per relevant post."""

    def comments_for_links(self, link_ids: Any) -> Iterator[list[dict[str, Any]]]:
        for lid in link_ids:
            yield [
                {
                    "id": f"c_{lid}_a",
                    "link_id": f"t3_{lid}",
                    "subreddit": "Supplements",
                    "body": f"top comment on {lid}: this is the strongest signal here",
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
        brief_id="b-e2e",
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
    # Subreddit picker: add nothing (keep the corpus deterministic).
    chat.script(_PickerOutput, _PickerOutput(suggestions=[]))
    # Triage classifier (middle bucket): mark every batch position relevant so
    # the whole pulled corpus survives to hydration. Covers any batch size.
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(
            verdicts=[_Verdict(batch_index=i, relevant=True, reason="on_topic") for i in range(50)]
        ),
    )
    # Cluster synthesis: one theme citing representatives 0 and 1 (top-2 by
    # upvotes). Quotes are index-based, so ResolvedCitation.text IS a real
    # comment body — resolves into the corpus by construction.
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
    # Triangulation: cluster 1 agrees with web finding 1; resolve the
    # must_address item to the cluster.
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
    # Web (internal grounded path): one finding grounded in one source.
    text = "1. CLAIM: the focus supplement market is growing\n   SPECIFICS: +18% in 2025\n"
    chat.grounded_results.append(
        GroundedResult(
            text=text,
            chunks=(GroundingChunk(uri="https://example.com/report", title="Market Report"),),
            supports=(GroundingSupport(start_char=0, end_char=len(text), chunk_indices=(0,)),),
        )
    )
    return chat


def test_pipeline_end_to_end_offline(tmp_path: Path) -> None:
    _write_corpus(tmp_path, year=_NOW.year, month=_NOW.month)
    reader = ArcticReader(data_root=str(tmp_path), probe_sleep_s=0.0)
    store = MemoryStores()
    chat = _scripted_chat()
    deps = ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=store,
        reader=reader,
        comments=_FakeComments(),
        author_salt="test-salt",
        clock=lambda: _NOW,
    )

    report = run_research(deps, brief=_brief())

    # 1. A valid report came back, anchored to the corpus window.
    assert report.report_id
    assert report.query == "what do people want in a focus supplement"
    # Triage is deterministic: top bucket accepted + middle classified relevant,
    # bottom percentile auto-rejected. At least the accepted+middle survive.
    n_relevant = report.total_threads
    assert n_relevant >= 2
    assert report.generated_at == _NOW

    # 2. The relevant subset was hydrated into the repo (posts + 2 comments each).
    all_ids = [s[0] for s in _SUBMISSIONS]
    posts = store.get_posts(all_ids)
    assert len(posts) == n_relevant
    comments = store.get_comments_for_posts(all_ids)
    assert len(comments) == 2 * n_relevant

    # 3. The triage funnel ran and is internally consistent.
    assert report.corpus_shape is not None
    assert report.corpus_shape.threads_pulled == 5
    assert report.corpus_shape.threads_relevant == n_relevant

    # 4. A cluster was synthesized with verified, corpus-resolving quotes.
    assert len(report.ranked_clusters) == 1
    cluster = report.ranked_clusters[0]
    assert cluster.quotes, "cluster must carry at least one verified quote"
    corpus_bodies = {c.body for c in comments}
    for q in cluster.quotes:
        assert q.text in corpus_bodies, "every ResolvedCitation must resolve into the corpus"
        assert q.source_url  # provenance link present
        # Citations are the materialized, source-neutral form: generic source
        # fields are populated (Reddit maps onto them), Reddit-named fields gone.
        assert q.source == "reddit"
        assert q.source_name.startswith("r/")
        assert not hasattr(q, "permalink")
        assert not hasattr(q, "subreddit")

    # 4b. Portability (clean-break golden): the report serializes and reloads
    # with NO corpus present, and is SEMANTICALLY equivalent — same clusters,
    # claims, scores, and citation text+url (now under generic field names).
    detached = DemandReport.model_validate_json(report.model_dump_json())
    assert [c.claim for c in detached.ranked_clusters] == [c.claim for c in report.ranked_clusters]
    assert [c.demand_score for c in detached.ranked_clusters] == [
        c.demand_score for c in report.ranked_clusters
    ]
    orig_citations = [(q.text, q.source_url) for c in report.ranked_clusters for q in c.quotes]
    reloaded_citations = [
        (q.text, q.source_url) for c in detached.ranked_clusters for q in c.quotes
    ]
    assert reloaded_citations == orig_citations  # text + url survive detached round-trip
    assert {r.id for r in detached.evidence} == {r.id for r in report.evidence}

    # 5. Web stream produced a grounded finding (claim from LLM, URL from metadata).
    assert len(report.web_findings) == 1
    assert report.web_findings[0].source_url == "https://example.com/report"
    assert report.web_findings[0].claim == "the focus supplement market is growing"

    # 6. Triangulation resolved the must_address item and cross-referenced.
    assert report.must_address_resolution.get("is stim-free demand real") == "cluster:1"
    assert len(report.cross_references) == 1

    # 7. No stage degraded → complete report.
    assert report.partial is False

    reader.close()


def test_pipeline_empty_corpus_is_partial(tmp_path: Path) -> None:
    """A subreddit with no matching parquet rows → partial report, not empty success."""
    _write_corpus(tmp_path, year=_NOW.year, month=_NOW.month)
    reader = ArcticReader(data_root=str(tmp_path), probe_sleep_s=0.0)
    chat = _scripted_chat()
    brief = _brief().model_copy(
        update={"target_subreddits": [TargetSubreddit(name="EmptySubNoRows", rationale="x")]}
    )
    deps = ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=reader,
        comments=_FakeComments(),
        clock=lambda: _NOW,
    )
    report = run_research(deps, brief=brief)
    assert report.partial is True
    assert report.total_threads == 0
    assert report.caveat is not None and "No threads" in report.caveat
    reader.close()
