"""Public testing utilities — verify YOUR adapters and backends.

Implement a repo backend or a ChatModel adapter, then run metalworks' own
conformance checks against it:

    from metalworks.testing import FakeChatModel, FakeEmbedding, check_all_repos

    def test_my_backend_conforms():
        check_all_repos(MyBackend())

`check_all_repos` runs the same semantic assertions metalworks holds its
built-in backends to — including the >1000-rows-behind-one-filter case that
catches silently-truncating paginated backends.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from metalworks.contract import (
    InboxItem,
    Opportunity,
    RedditComment,
    RedditPost,
    ResearchBrief,
    RunSummary,
    TargetSubreddit,
)
from metalworks.embeddings import FakeEmbedding, IndexIdentity
from metalworks.errors import EmbeddingModelMismatch
from metalworks.llm.fake import FakeChatModel
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


__all__ = [
    "AllRepos",
    "FakeChatModel",
    "FakeEmbedding",
    "check_account_repo",
    "check_all_repos",
    "check_brief_repo",
    "check_corpus_repo",
    "check_inbox_repo",
    "check_opportunity_repo",
    "check_run_repo",
]
