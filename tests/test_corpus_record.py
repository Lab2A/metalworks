"""Source-neutral corpus record mappers + synthesis source-neutrality.

Covers Phase 1a of the corpus-as-core re-architecture:

  1. `CorpusRecord.from_reddit_post` / `CorpusComment.from_reddit_comment`
     round-trip the Reddit contract onto the source-neutral spine.
  2. The cluster_ranker prompt formatter is source-NEUTRAL: a non-Reddit
     `LoadedComment` renders `(<label>, N <unit>)` with nothing Reddit-specific
     (`r/...`, `upvotes`) leaking.
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import CorpusComment, CorpusRecord, RedditComment, RedditPost
from metalworks.research.synthesis.cluster_ranker import _format_numbered_comment
from metalworks.research.types import LoadedComment

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def test_corpus_record_from_reddit_post_round_trips() -> None:
    post = RedditPost(
        post_id="abc123",
        subreddit="Supplements",
        title="focus blend review",
        selftext="citicoline stack works for me",
        url="https://reddit.com/r/Supplements/comments/abc123/",
        author="user_x",
        score=50,
        num_comments=12,
        created_utc=_NOW,
        flair="Discussion",
    )

    rec = CorpusRecord.from_reddit_post(post)

    assert rec.id == "abc123"
    assert rec.source == "reddit"
    assert rec.source_id == "abc123"
    assert rec.url == "https://reddit.com/r/Supplements/comments/abc123/"
    assert rec.title == "focus blend review"
    assert rec.text == "citicoline stack works for me"
    assert rec.engagement == 50
    assert rec.created_at == _NOW
    # Reddit-specific fields live in the open tail, not the spine.
    assert rec.extra["subreddit"] == "Supplements"
    assert rec.extra["num_comments"] == 12
    assert rec.extra["flair"] == "Discussion"
    assert rec.extra["author"] == "user_x"


def test_corpus_comment_from_reddit_comment_round_trips() -> None:
    comment = RedditComment(
        comment_id="cmt9",
        post_id="abc123",
        subreddit="Supplements",
        body="this is the strongest signal here",
        permalink="https://reddit.com/r/Supplements/comments/abc123/_/cmt9/",
        author_hash="hash_deadbeef",
        score=40,
        created_utc=_NOW,
        parent_id="t1_parent",
    )

    cc = CorpusComment.from_reddit_comment(comment)

    assert cc.id == "cmt9"
    assert cc.parent_id == "abc123"
    assert cc.source == "reddit"
    assert cc.url == "https://reddit.com/r/Supplements/comments/abc123/_/cmt9/"
    assert cc.text == "this is the strongest signal here"
    assert cc.author_hash == "hash_deadbeef"
    assert cc.engagement == 40
    assert cc.created_at == _NOW
    assert cc.extra["subreddit"] == "Supplements"
    assert cc.extra["parent_id_native"] == "t1_parent"


def test_prompt_formatter_is_source_neutral_for_non_reddit() -> None:
    """A Hacker News comment must render its own label/unit, not Reddit's."""
    hn = LoadedComment(
        comment_id="hn1",
        post_id="story1",
        subreddit="",  # never a subreddit for HN
        body="we switched off this tool after the pricing change",
        author_hash="hn_author",
        source="hackernews",
        source_label="Hacker News",
        engagement=42,
        engagement_unit="points",
        source_url="https://news.ycombinator.com/item?id=1",
    )

    line = _format_numbered_comment(3, hn)

    assert line == (
        "[3] (Hacker News, 42 points) we switched off this tool after the pricing change"
    )
    # Nothing Reddit-specific may leak when the source isn't Reddit.
    assert "r/" not in line
    assert "upvotes" not in line


def test_prompt_formatter_reddit_path_unchanged() -> None:
    """The Reddit display fields still render the legacy `(r/<sub>, N upvotes)`."""
    reddit = LoadedComment(
        comment_id="c1",
        post_id="p1",
        subreddit="Supplements",
        body="stim-free focus is what I want",
        upvotes=40,
        author_hash="a",
        permalink="https://reddit.com/x",
        source="reddit",
        source_label="r/Supplements",
        engagement=40,
        engagement_unit="upvotes",
        source_url="https://reddit.com/x",
    )

    line = _format_numbered_comment(0, reddit)

    assert line == "[0] (r/Supplements, 40 upvotes) stim-free focus is what I want"
