"""Reddit ↔ source-neutral corpus mapping used by the CorpusRepo shims.

The corpus store holds the generic :class:`CorpusRecord` / :class:`CorpusComment`
spine (Phase 1b). The forward mappers (Reddit → spine) live on the contract
(``CorpusRecord.from_reddit_post`` etc.). The REVERSE mappers — reconstructing
the Reddit contract from the spine plus its ``extra`` tail — live here, in the
storage layer, because they are a backend concern (the Reddit-named shims on
``CorpusRepo``), not part of the source-neutral contract.

Everything Reddit needs is recoverable: the spine carries the id/url/title/text/
engagement/created_at, and ``extra`` carries the Reddit-only fields
(``subreddit``, ``num_comments``, ``flair``, ``author`` for posts;
``subreddit``, ``parent_id_native`` for comments).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.contract import CorpusComment, CorpusRecord, RedditComment, RedditPost

if TYPE_CHECKING:
    from collections.abc import Sequence


def records_from_reddit_posts(posts: Sequence[RedditPost]) -> list[CorpusRecord]:
    return [CorpusRecord.from_reddit_post(p) for p in posts]


def corpus_comments_from_reddit_comments(
    comments: Sequence[RedditComment],
) -> list[CorpusComment]:
    return [CorpusComment.from_reddit_comment(c) for c in comments]


def reddit_post_from_record(rec: CorpusRecord) -> RedditPost:
    """Rebuild a Reddit ``RedditPost`` from the source-neutral spine + ``extra``."""
    extra = rec.extra
    num_comments = extra.get("num_comments", 0)
    return RedditPost(
        post_id=rec.source_id or rec.id,
        subreddit=str(extra.get("subreddit") or ""),
        title=rec.title,
        selftext=rec.text,
        url=rec.url,
        author=extra.get("author"),
        score=rec.engagement,
        num_comments=int(num_comments) if num_comments is not None else 0,
        created_utc=rec.created_at,
        flair=extra.get("flair"),
    )


def reddit_comment_from_corpus_comment(cc: CorpusComment) -> RedditComment:
    """Rebuild a Reddit ``RedditComment`` from the source-neutral spine + ``extra``."""
    extra = cc.extra
    return RedditComment(
        comment_id=cc.id,
        post_id=cc.parent_id,
        subreddit=str(extra.get("subreddit") or ""),
        body=cc.text,
        permalink=cc.url,
        author_hash=cc.author_hash,
        score=cc.engagement,
        created_utc=cc.created_at,
        parent_id=extra.get("parent_id_native"),
    )


__all__ = [
    "corpus_comments_from_reddit_comments",
    "records_from_reddit_posts",
    "reddit_comment_from_corpus_comment",
    "reddit_post_from_record",
]
