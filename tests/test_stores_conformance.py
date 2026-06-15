"""Repo conformance suite — every backend must behave identically.

Includes the two review-mandated cases:
- >1000 rows behind one filter (the PostgREST silent-truncation killer; a
  downstream hosted/PostgREST backend reuses this same parametrized suite)
- concurrent writes + reads on SQLite under a thread pool (the pipeline's
  actual access pattern)
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pytest

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
from metalworks.stores import (
    AccountRepo,
    BriefRepo,
    CorpusRepo,
    InboxRepo,
    MemoryStores,
    OpportunityRepo,
    RunRepo,
    SqliteStores,
    StoredRedditAccount,
)


class AllRepos(BriefRepo, RunRepo, CorpusRepo, AccountRepo, OpportunityRepo, InboxRepo, Protocol):
    """Intersection type for backends that implement every repo."""


@pytest.fixture(params=["memory", "sqlite"])
def stores(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[AllRepos]:
    if request.param == "memory":
        yield MemoryStores()
    else:
        backend = SqliteStores(tmp_path / "test.db")
        yield backend
        backend.close()


def _post(i: int) -> RedditPost:
    return RedditPost(
        post_id=f"p{i}",
        subreddit="Supplements",
        title=f"Post {i}",
        url=f"https://reddit.com/r/Supplements/comments/p{i}/",
    )


def _comment(i: int, post_id: str) -> RedditComment:
    return RedditComment(
        comment_id=f"c{i}",
        post_id=post_id,
        subreddit="Supplements",
        body=f"comment body {i}",
        permalink=f"https://reddit.com/r/Supplements/comments/{post_id}/c{i}/",
        author_hash=f"author{i % 7}",
    )


def _brief(brief_id: str, version: int = 1) -> ResearchBrief:
    return ResearchBrief(
        brief_id=brief_id,
        version=version,
        question="q",
        decision_context="d",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core")],
        web_research_directions=[],
        relevance_rubric="r",
    )


def _opportunity(i: int) -> Opportunity:
    return Opportunity(opportunity_id=f"o{i}", post=_post(i), draft_reply=f"draft {i}")


# ── Briefs ──


def test_brief_round_trip_and_listing(stores: AllRepos) -> None:
    stores.save_brief(_brief("b1"))
    stores.save_brief(_brief("b2", version=2))
    got = stores.get_brief("b1")
    assert got is not None and got.question == "q"
    assert stores.get_brief("missing") is None
    listed = stores.list_briefs()
    assert [b.brief_id for b in listed] == ["b2", "b1"]  # newest version first
    assert stores.list_briefs(workspace_id="other") == []


# ── Runs + reports ──


def test_run_lifecycle(stores: AllRepos) -> None:
    t0 = datetime(2026, 6, 9, tzinfo=UTC)
    run = RunSummary(report_id="r1", brief_id="b1", query="q", status="queued", created_at=t0)
    stores.save_run(run)
    stores.save_run(run.model_copy(update={"status": "complete"}))  # upsert overwrites
    got = stores.get_run("r1")
    assert got is not None and got.status == "complete"
    assert [r.report_id for r in stores.list_runs(brief_id="b1")] == ["r1"]
    assert stores.list_runs(brief_id="nope") == []


# ── Corpus: the >1000-row truncation case ──


def test_corpus_returns_all_rows_beyond_1000(stores: AllRepos) -> None:
    """1,500 comments behind 3 post ids — a backend that truncates at 1000
    (PostgREST max-rows default) MUST fail this test."""
    posts = [_post(i) for i in range(3)]
    stores.upsert_posts(posts)
    comments = [_comment(i, posts[i % 3].post_id) for i in range(1500)]
    stores.upsert_comments(comments)
    # Idempotent re-upsert must not duplicate.
    stores.upsert_comments(comments[:100])

    got = stores.get_comments_for_posts([p.post_id for p in posts])
    assert len(got) == 1500
    assert {c.comment_id for c in got} == {f"c{i}" for i in range(1500)}

    got_posts = stores.get_posts(["p0", "p2", "missing"])
    assert {p.post_id for p in got_posts} == {"p0", "p2"}


def test_reddit_shims_round_trip_through_generic_spine(stores: AllRepos) -> None:
    """The Reddit-named shims map onto the generic CorpusRecord/CorpusComment
    store and reconstruct the Reddit contract on read — every Reddit field that
    matters survives the trip through the spine + `extra` tail."""
    post = RedditPost(
        post_id="px",
        subreddit="Supplements",
        title="t",
        selftext="body",
        url="https://reddit.com/r/Supplements/comments/px/",
        author="u_hash",
        score=99,
        num_comments=7,
        flair="Discussion",
    )
    stores.upsert_posts([post])
    got = stores.get_posts(["px"])
    assert len(got) == 1
    p = got[0]
    assert (p.post_id, p.subreddit, p.selftext, p.score, p.num_comments, p.flair, p.author) == (
        "px",
        "Supplements",
        "body",
        99,
        7,
        "Discussion",
        "u_hash",
    )

    comment = RedditComment(
        comment_id="cx",
        post_id="px",
        subreddit="Supplements",
        body="signal",
        permalink="https://reddit.com/r/Supplements/comments/px/_/cx/",
        author_hash="ah",
        score=12,
        parent_id="t1_parent",
    )
    stores.upsert_comments([comment])
    cgot = stores.get_comments_for_posts(["px"])
    assert len(cgot) == 1
    c = cgot[0]
    assert (c.comment_id, c.post_id, c.subreddit, c.body, c.score, c.parent_id) == (
        "cx",
        "px",
        "Supplements",
        "signal",
        12,
        "t1_parent",
    )


def test_generic_corpus_surface_round_trips(stores: AllRepos) -> None:
    """The authoritative generic surface stores a non-Reddit record + comment."""
    rec = CorpusRecord(
        id="hn1",
        source="hackernews",
        source_id="40001",
        url="https://news.ycombinator.com/item?id=40001",
        title="Show HN",
        text="built it",
        engagement=88,
        extra={"site": "example.com"},
    )
    cc = CorpusComment(
        id="hnc1",
        parent_id="hn1",
        source="hackernews",
        url="https://news.ycombinator.com/item?id=50001",
        text="we churned after the price hike",
        author_hash="hn_a",
        engagement=20,
    )
    stores.upsert_records([rec])
    stores.upsert_corpus_comments([cc])

    recs = stores.get_records(["hn1", "missing"])
    assert [r.id for r in recs] == ["hn1"]
    assert recs[0].source == "hackernews" and recs[0].extra["site"] == "example.com"

    cmts = stores.get_comments_for_records(["hn1"])
    assert [c.id for c in cmts] == ["hnc1"]
    assert cmts[0].source == "hackernews"


# ── Accounts ──


def test_account_round_trip(stores: AllRepos) -> None:
    acct = StoredRedditAccount(
        username="brand_founder",
        encrypted_access_token="gAAAA-ciphertext",
        encrypted_refresh_token="gAAAA-refresh",
        scopes=["submit", "read"],
        token_expires_at=1750000000.0,
        metadata={"karma": "1200"},
    )
    stores.save_account(acct)
    got = stores.get_account("brand_founder")
    assert got is not None and got.scopes == ["submit", "read"]
    assert len(stores.list_accounts()) == 1
    stores.delete_account("brand_founder")
    assert stores.get_account("brand_founder") is None


# ── Opportunities: dedup gate + status transitions ──


def test_opportunity_dedup_and_status(stores: AllRepos) -> None:
    stores.save_opportunities([_opportunity(1), _opportunity(2)])
    assert stores.opportunity_exists(_post(1).url) is True
    assert stores.opportunity_exists("https://reddit.com/r/other/xyz/") is False

    stores.update_opportunity_status("o1", "approved")
    approved = stores.list_opportunities(status="approved")
    assert [o.opportunity_id for o in approved] == ["o1"]
    assert len(stores.list_opportunities()) == 2
    stores.update_opportunity_status("missing", "approved")  # no-op, no raise


# ── Inbox ──


def test_inbox_upsert_and_read_flags(stores: AllRepos) -> None:
    items = [
        InboxItem(message_id="m1", kind="comment_reply", body="hi"),
        InboxItem(message_id="m2", kind="dm", body="yo"),
    ]
    stores.upsert_inbox_items(items)
    assert len(stores.list_inbox_items(unread_only=True)) == 2
    stores.mark_inbox_read("m1")
    unread = stores.list_inbox_items(unread_only=True)
    assert [i.message_id for i in unread] == ["m2"]
    assert len(stores.list_inbox_items()) == 2


# ── Backend equivalence: same script, same observable results ──


def _run_script(s: AllRepos) -> tuple[int, bool, int]:
    s.upsert_posts([_post(i) for i in range(5)])
    s.upsert_comments([_comment(i, f"p{i % 5}") for i in range(50)])
    s.save_opportunities([_opportunity(9)])
    return (
        len(s.get_comments_for_posts(["p0", "p1", "p2", "p3", "p4"])),
        s.opportunity_exists(_post(9).url),
        len(s.get_posts(["p0", "p1"])),
    )


def test_memory_and_sqlite_equivalent(tmp_path: Path) -> None:
    sqlite_backend = SqliteStores(tmp_path / "eq.db")
    try:
        assert _run_script(MemoryStores()) == _run_script(sqlite_backend)
    finally:
        sqlite_backend.close()


# ── SQLite concurrency: the pipeline's real access pattern ──


def test_sqlite_concurrent_writes_and_reads(tmp_path: Path) -> None:
    backend = SqliteStores(tmp_path / "conc.db")
    try:

        def write_batch(batch: int) -> None:
            backend.upsert_comments([_comment(batch * 100 + i, f"p{batch}") for i in range(100)])

        def read_batch(batch: int) -> int:
            return len(backend.get_comments_for_posts([f"p{batch}"]))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write_batch, range(8)))
            counts = list(pool.map(read_batch, range(8)))
        assert counts == [100] * 8

        # Interleaved write+read storm must not raise "database is locked".
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures: list[Callable[[], object]] = []
            for batch in range(8, 16):
                futures.append(pool.submit(write_batch, batch).result)
                futures.append(pool.submit(read_batch, batch % 8).result)
            for f in futures:
                f()
        assert len(backend.get_comments_for_posts([f"p{b}" for b in range(16)])) == 1600
    finally:
        backend.close()
