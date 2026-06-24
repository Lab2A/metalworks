"""Source-neutral corpus records: the spine of the corpus-as-core re-architecture.

`RedditPost` / `RedditComment` are the live, Reddit-specific contract. This
module adds a source-NEUTRAL pair — `CorpusRecord` (a top-level item: a Reddit
post, an HN story, a product review) and `CorpusComment` (a quote-bearing
sub-item: a Reddit comment, an HN comment, a review-as-text) — so the synthesis
layer can rank and quote evidence without knowing where it came from.

The shape is a small, stable SPINE (`id`, `source`, `url`, `text`, …) plus an
open `extra: dict` tail for source-specific fields that don't deserve a column
(Reddit's `subreddit`, a review's star rating, …). Mappers translate the Reddit
contract into this shape; new sources add their own mappers without touching the
spine.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from metalworks.contract.reddit import RedditComment, RedditPost


class CorpusRecord(BaseModel):
    """A source-neutral top-level item (Reddit post / HN story / review).

    The `id` is the corpus-wide identity; `source` + `source_id` recover the
    origin. Source-specific fields (e.g. a subreddit) live in `extra`.
    """

    id: str = Field(description="Corpus-wide identity for this record.")
    source: str = Field(description="Origin source, e.g. 'reddit', 'hackernews', 'reviews'.")
    source_id: str = Field(description="Native id within the source (e.g. Reddit base36 post id).")
    url: str = Field(default="", description="Resolvable link to the item.")
    title: str = Field(default="", description="Item title/headline.")
    text: str = Field(default="", description="Body text; empty for link-only items.")
    author_hash: str | None = Field(
        default=None, description="Salted pseudonymous author id, when available."
    )
    engagement: int = Field(
        default=0, description="Source-native engagement signal (Reddit score, HN points, …)."
    )
    signals: dict[str, float] = Field(
        default_factory=dict,
        description="Open, source-declared demand signals keyed by kind (e.g. "
        "{'upvotes': 12} for Reddit, {'rating': 1, 'verified_purchase': 1} for a "
        "review). The deterministic scorer reads known kinds via the SignalSpec "
        "registry; unknown kinds are context-only. Empty ⇒ synthesized from "
        "`engagement` at load (the back-compat path).",
    )
    created_at: datetime | None = None
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Source-specific fields that don't earn a spine column."
    )

    @classmethod
    def from_reddit_post(cls, post: RedditPost) -> CorpusRecord:
        """Map a Reddit `RedditPost` onto the source-neutral spine."""
        return cls(
            id=post.post_id,
            source="reddit",
            source_id=post.post_id,
            url=post.url,
            title=post.title,
            text=post.selftext,
            author_hash=None,
            engagement=post.score,
            signals={"upvotes": float(post.score)},
            created_at=post.created_utc,
            extra={
                "subreddit": post.subreddit,
                "num_comments": post.num_comments,
                "flair": post.flair,
                "author": post.author,
            },
        )


class CorpusComment(BaseModel):
    """A source-neutral quote-bearing sub-item (Reddit comment / HN comment / review).

    Always belongs to a `CorpusRecord` via `parent_id`. `url` must resolve to the
    quote in context (the provenance link the structural-provenance contract
    depends on).
    """

    id: str = Field(description="Corpus-wide identity for this comment.")
    parent_id: str = Field(description="Id of the CorpusRecord this belongs to.")
    source: str = Field(description="Origin source, e.g. 'reddit', 'hackernews', 'reviews'.")
    url: str = Field(default="", description="Resolvable link to the quote in context.")
    text: str = Field(default="", description="Verbatim comment/quote text.")
    author_hash: str = Field(
        default="", description="Salted pseudonymous author id — for distinct-author counting."
    )
    engagement: int = Field(
        default=0, description="Source-native engagement signal (Reddit upvotes, HN points, …)."
    )
    signals: dict[str, float] = Field(
        default_factory=dict,
        description="Open, source-declared demand signals keyed by kind (see "
        "`CorpusRecord.signals`). Empty ⇒ synthesized from `engagement` at load.",
    )
    created_at: datetime | None = None
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Source-specific fields that don't earn a spine column."
    )

    @classmethod
    def from_reddit_comment(cls, comment: RedditComment) -> CorpusComment:
        """Map a Reddit `RedditComment` onto the source-neutral spine."""
        return cls(
            id=comment.comment_id,
            parent_id=comment.post_id,
            source="reddit",
            url=comment.permalink,
            text=comment.body,
            author_hash=comment.author_hash,
            engagement=comment.score,
            signals={"upvotes": float(comment.score)},
            created_at=comment.created_utc,
            extra={
                "subreddit": comment.subreddit,
                "parent_id_native": comment.parent_id,
            },
        )
