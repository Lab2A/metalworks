"""Public testing utilities — verify YOUR adapters and backends.

Implement a repo backend or a ChatModel adapter, then run metalworks' own
conformance checks against it:

    from metalworks.testing import FakeChatModel, FakeEmbedding, check_all_repos

    def test_my_backend_conforms():
        check_all_repos(MyBackend())

`check_all_repos` runs the same semantic assertions metalworks holds its
built-in backends to — including the >1000-rows-behind-one-filter case that
catches silently-truncating paginated backends.

Source connectors have their own conformance check — implement an
:class:`~metalworks.research.sources.ItemSource` and verify it against the
published contract before you ship it:

    from metalworks.testing import check_item_source

    def test_my_source_conforms():
        check_item_source(MySource())

`check_item_source` asserts the protocol contract: `pull` yields `CorpusRecord`s
with stable, non-empty ids, a re-pull is idempotent (same id set), `comments_for`
returns `CorpusComment`s parented to pulled record ids (or `None`), and
`latest_window` returns a `SourceWindow`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from metalworks.contract import (
    CorpusComment,
    CorpusRecord,
    InboxItem,
    Opportunity,
    RedditComment,
    RedditPost,
    ResearchBrief,
    RunSummary,
    TargetSubreddit,
)
from metalworks.embeddings import FakeEmbedding, IndexIdentity
from metalworks.errors import EmbeddingModelMismatch, StyleAuditUnsupported
from metalworks.llm.fake import FakeChatModel
from metalworks.render import ComputedStyle, PageRenderer, RenderedPage, RendererCapabilities
from metalworks.render.fake import FakeRenderer
from metalworks.research.sources import ItemSource, SourceWindow
from metalworks.stores.repos import (
    AccountRepo,
    BriefRepo,
    CorpusRepo,
    InboxRepo,
    OpportunityRepo,
    RunRepo,
    StoredRedditAccount,
)

if TYPE_CHECKING:
    pass


class AllRepos(BriefRepo, RunRepo, CorpusRepo, AccountRepo, OpportunityRepo, InboxRepo, Protocol):
    """Intersection protocol: a backend that implements every metalworks repo."""


def _post(i: int) -> RedditPost:
    return RedditPost(
        post_id=f"mwtest-p{i}",
        subreddit="Supplements",
        title=f"Post {i}",
        url=f"https://reddit.com/r/Supplements/comments/mwtest-p{i}/",
    )


def _comment(i: int, post_id: str) -> RedditComment:
    return RedditComment(
        comment_id=f"mwtest-c{i}",
        post_id=post_id,
        subreddit="Supplements",
        body=f"comment body {i}",
        permalink=f"https://reddit.com/r/Supplements/comments/{post_id}/mwtest-c{i}/",
        author_hash=f"author{i % 7}",
    )


def check_brief_repo(repo: BriefRepo) -> None:
    brief = ResearchBrief(
        brief_id="mwtest-b1",
        question="q",
        decision_context="d",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core")],
        web_research_directions=[],
        relevance_rubric="r",
    )
    repo.save_brief(brief)
    got = repo.get_brief("mwtest-b1")
    assert got is not None and got.question == "q", "brief round-trip failed"
    assert repo.get_brief("mwtest-missing") is None, "missing brief must return None"
    assert any(b.brief_id == "mwtest-b1" for b in repo.list_briefs()), "list_briefs missed brief"


def check_run_repo(repo: RunRepo) -> None:
    run = RunSummary(
        report_id="mwtest-r1",
        brief_id="mwtest-b1",
        query="q",
        status="queued",
        created_at=datetime(2026, 6, 9, tzinfo=UTC),
    )
    repo.save_run(run)
    repo.save_run(run.model_copy(update={"status": "complete"}))
    got = repo.get_run("mwtest-r1")
    assert got is not None and got.status == "complete", "save_run must upsert by report_id"
    assert [r.report_id for r in repo.list_runs(brief_id="mwtest-b1")] == ["mwtest-r1"]


def check_corpus_repo(repo: CorpusRepo, *, rows: int = 1500) -> None:
    """The big one: a paginating backend that silently truncates fails here."""
    posts = [_post(i) for i in range(3)]
    repo.upsert_posts(posts)
    comments = [_comment(i, posts[i % 3].post_id) for i in range(rows)]
    repo.upsert_comments(comments)
    repo.upsert_comments(comments[:50])  # idempotent re-upsert must not duplicate

    got = repo.get_comments_for_posts([p.post_id for p in posts])
    assert len(got) == rows, (
        f"get_comments_for_posts returned {len(got)} of {rows} rows — "
        "backend is truncating (paginate to exhaustion!)"
    )
    got_posts = repo.get_posts(["mwtest-p0", "mwtest-p2", "mwtest-missing"])
    assert {p.post_id for p in got_posts} == {"mwtest-p0", "mwtest-p2"}
    _check_corpus_embeddings(repo)


def _check_corpus_embeddings(repo: CorpusRepo) -> None:
    """Vector storage round-trip + cosine search + model-mismatch guard.

    Storage (upsert) is always exercised; the cosine search needs the ``[research]``
    extra (numpy), so it is skipped when numpy is absent — keeping the bare CI
    matrix green while still proving the write path on every backend.
    """
    import importlib.util

    identity = IndexIdentity(embedding_model_id="mwtest-embed", dim=4)
    repo.upsert_embeddings(
        {"mwtest-c0": [1.0, 0.0, 0.0, 0.0], "mwtest-c1": [0.0, 1.0, 0.0, 0.0]},
        identity=identity,
    )

    # get_embeddings (the cache-read path) — numpy-free, always exercised.
    fetched = repo.get_embeddings(["mwtest-c0", "mwtest-absent"], identity=identity)
    assert set(fetched) == {"mwtest-c0"}, "get_embeddings must return only stored ids"
    assert fetched["mwtest-c0"][0] == 1.0
    wrong_model = IndexIdentity(embedding_model_id="mwtest-other", dim=4)
    assert repo.get_embeddings(["mwtest-c0"], identity=wrong_model) == {}, (
        "get_embeddings must miss when the index was built with a different model"
    )

    if importlib.util.find_spec("numpy") is None:
        return  # search needs the [research] extra; the write path is already proven

    nearest = repo.search_embeddings([0.9, 0.1, 0.0, 0.0], k=1, identity=identity)
    assert nearest and nearest[0][0] == "mwtest-c0", "cosine search missed the nearest vector"

    other_model = IndexIdentity(embedding_model_id="mwtest-other", dim=4)
    try:
        repo.search_embeddings([1.0, 0.0, 0.0, 0.0], k=1, identity=other_model)
    except EmbeddingModelMismatch:
        pass
    else:
        raise AssertionError("search must reject a mismatched embedding model")


def check_account_repo(repo: AccountRepo) -> None:
    acct = StoredRedditAccount(username="mwtest-user", encrypted_access_token="ct")
    repo.save_account(acct)
    got = repo.get_account("mwtest-user")
    assert got is not None and got.encrypted_access_token == "ct"
    repo.delete_account("mwtest-user")
    assert repo.get_account("mwtest-user") is None


def check_opportunity_repo(repo: OpportunityRepo) -> None:
    opp = Opportunity(opportunity_id="mwtest-o1", post=_post(900), draft_reply="d")
    repo.save_opportunities([opp])
    assert repo.opportunity_exists(_post(900).url) is True, "dedup gate failed"
    assert repo.opportunity_exists("https://reddit.com/r/none/") is False
    repo.update_opportunity_status("mwtest-o1", "approved")
    assert [o.opportunity_id for o in repo.list_opportunities(status="approved")] == ["mwtest-o1"]


def check_inbox_repo(repo: InboxRepo) -> None:
    repo.upsert_inbox_items([InboxItem(message_id="mwtest-m1", kind="dm", body="hi")])
    assert len(repo.list_inbox_items(unread_only=True)) >= 1
    repo.mark_inbox_read("mwtest-m1")
    assert all(i.message_id != "mwtest-m1" for i in repo.list_inbox_items(unread_only=True))


def check_item_source(
    source: ItemSource,
    *,
    query: str = "test",
    window: SourceWindow | None = None,
    limit: int | None = 25,
) -> None:
    """Assert that ``source`` honors the :class:`ItemSource` contract.

    A third-party connector self-verifies with this BEFORE shipping. It runs a
    small live pull against the source and checks the contract every downstream
    stage relies on:

    * ``source.source_id`` is a non-empty string.
    * ``latest_window()`` returns a :class:`SourceWindow`.
    * ``pull()`` yields :class:`CorpusRecord`s, each with a non-empty ``id``,
      ``source`` matching ``source_id``, and ``source_id`` set.
    * ids are UNIQUE within a pull and STABLE across a re-pull (idempotency — the
      same query/window yields the same id set, so upsert-by-id never duplicates).
    * ``comments_for()`` returns ``None`` (comment-less source) OR yields
      :class:`CorpusComment`s, each parented (``parent_id``) to a pulled record id.

    Pass a ``window`` for sources that require one; otherwise ``latest_window()``
    is used. ``limit`` keeps the probe small — give the source a fixture with at
    least one record so the assertions have something to bite on.
    """
    assert isinstance(source.source_id, str) and source.source_id, (
        "source_id must be a non-empty string"
    )

    win = window if window is not None else source.latest_window()
    assert isinstance(win, SourceWindow), "latest_window() must return a SourceWindow"

    records = list(source.pull(query=query, window=win, limit=limit))
    assert records, "pull() yielded no records — give check_item_source a fixture/window with data"

    ids: list[str] = []
    for r in records:
        assert isinstance(r, CorpusRecord), f"pull() must yield CorpusRecord, got {type(r)!r}"
        assert r.id, "every pulled record must have a non-empty, stable id"
        assert r.source == source.source_id, (
            f"record.source ({r.source!r}) must equal source_id ({source.source_id!r})"
        )
        assert r.source_id, "record.source_id (native id) must be set"
        ids.append(r.id)

    assert len(set(ids)) == len(ids), "pulled record ids must be unique within a pull"

    # Idempotency: a re-pull over the same query/window yields the same id set.
    again = [r.id for r in source.pull(query=query, window=win, limit=limit)]
    assert set(again) == set(ids), (
        "pull() is not idempotent: re-pulling the same query/window changed the id "
        "set — record ids must be stable (the corpus upserts by id)"
    )

    # Comments: None (comment-less) is legal; otherwise every comment must be a
    # CorpusComment parented to one of the pulled records.
    batches = source.comments_for(ids)
    if batches is not None:
        pulled = set(ids)
        for batch in batches:
            for c in batch:
                assert isinstance(c, CorpusComment), (
                    f"comments_for() must yield CorpusComment, got {type(c)!r}"
                )
                assert c.id, "every comment must have a non-empty id"
                assert c.parent_id in pulled, (
                    f"comment.parent_id ({c.parent_id!r}) is not one of the pulled record ids"
                )
                assert c.source == source.source_id, (
                    f"comment.source ({c.source!r}) must equal source_id ({source.source_id!r})"
                )


def check_all_repos(backend: AllRepos, *, corpus_rows: int = 1500) -> None:
    """Run every repo conformance check against one backend instance.

    Use a fresh/empty backend — the checks write `mwtest-` prefixed rows.
    """
    check_brief_repo(backend)
    check_run_repo(backend)
    check_corpus_repo(backend, rows=corpus_rows)
    check_account_repo(backend)
    check_opportunity_repo(backend)
    check_inbox_repo(backend)


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def check_page_renderer(renderer: PageRenderer, *, url: str = "https://example.com") -> None:
    """Assert that ``renderer`` honors the :class:`~metalworks.render.PageRenderer` contract.

    A renderer adapter self-verifies with this before shipping. Point it at a
    reachable ``url`` (a real page for Playwright/Firecrawl, anything for the
    Fake). It checks the surface every consumer relies on:

    * ``renderer_id`` is a non-empty string and ``capabilities`` is a
      :class:`~metalworks.render.RendererCapabilities`.
    * ``render()`` returns a :class:`~metalworks.render.RenderedPage` whose
      ``screenshot`` is PNG bytes (or empty), ``html`` is a string, and
      ``final_url`` is set.
    * if ``capabilities.supports_style_audit``: ``extract_computed_styles()``
      yields :class:`~metalworks.render.ComputedStyle`; otherwise it raises
      :class:`~metalworks.errors.StyleAuditUnsupported`.
    """
    assert isinstance(renderer.renderer_id, str) and renderer.renderer_id, (
        "renderer_id must be a non-empty string"
    )
    assert isinstance(renderer.capabilities, RendererCapabilities), (
        "capabilities must be a RendererCapabilities"
    )

    page = renderer.render(url)
    assert isinstance(page, RenderedPage), f"render() must return RenderedPage, got {type(page)!r}"
    assert isinstance(page.screenshot, bytes), "screenshot must be bytes"
    assert page.screenshot[:8] == _PNG_MAGIC or page.screenshot == b"", (
        "screenshot must be PNG bytes (or empty when the backend couldn't capture)"
    )
    assert isinstance(page.html, str), "html must be a string"
    assert page.final_url, "final_url must be set (resolved URL after redirects)"

    if renderer.capabilities.supports_style_audit:
        styles = renderer.extract_computed_styles(url, ["body"])
        assert all(isinstance(s, ComputedStyle) for s in styles), (
            "extract_computed_styles() must yield ComputedStyle"
        )
    else:
        raised = False
        try:
            renderer.extract_computed_styles(url, ["body"])
        except StyleAuditUnsupported:
            raised = True
        assert raised, (
            "a screenshot-only renderer (supports_style_audit=False) must raise "
            "StyleAuditUnsupported from extract_computed_styles()"
        )


__all__ = [
    "AllRepos",
    "FakeChatModel",
    "FakeEmbedding",
    "FakeRenderer",
    "check_account_repo",
    "check_all_repos",
    "check_brief_repo",
    "check_corpus_repo",
    "check_inbox_repo",
    "check_item_source",
    "check_opportunity_repo",
    "check_page_renderer",
    "check_run_repo",
]
