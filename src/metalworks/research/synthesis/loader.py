"""Load hydrated Reddit comments/posts from the corpus repo.

Synthesis works against the post-triage subset already persisted by the
hydration stage. This module is the one boundary between the synthesis core and
storage: every other synthesis module operates on the in-memory `LoadedComment`
/ `LoadedPost` shapes produced here.

We never keep `[deleted]` / `[removed]` / empty bodies — synthesis ranking on
those is meaningless and they'd just chew up LLM tokens.

DESIGN NOTE: an earlier internal version read Supabase tables directly
with a manual 200-id IN-chunk loop. Here we read through
`deps.corpus.get_posts(...)` / `deps.corpus.get_comments_for_posts(...)`, which
return contract `RedditPost` / `RedditComment` and already paginate to
exhaustion — so the manual `_ID_CHUNK` chunking is dropped. The contract rows
are MAPPED to the synthesis-local shapes: `RedditComment.score` →
`LoadedComment.upvotes`, `.permalink` → `permalink`. Posts have no `permalink`
on the contract, so `LoadedPost.permalink` is sourced from `RedditPost.url`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.research.types import LoadedComment, LoadedPost

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metalworks.research.deps import ResearchDeps

# Same upper bound the marketing pipeline used. Past this, the LLM synthesis
# call's input grows faster than its recall improves; the embed-group dedup
# stage gets the load down to a sane number anyway.
DEFAULT_COMMENT_CAP = 2000


def load_posts(deps: ResearchDeps, post_ids: Sequence[str]) -> list[LoadedPost]:
    """Pull post rows for the post-triage subset, mapped to LoadedPost."""
    if not post_ids:
        return []
    out: list[LoadedPost] = []
    seen: set[str] = set()
    for p in deps.corpus.get_posts(list(dict.fromkeys(post_ids))):
        if not p.post_id or p.post_id in seen:
            continue
        seen.add(p.post_id)
        subreddit = p.subreddit or ""
        permalink = p.url or ""
        out.append(
            LoadedPost(
                post_id=p.post_id,
                subreddit=subreddit,
                title=p.title or "",
                score=p.score,
                num_comments=p.num_comments,
                permalink=permalink,
                # Source-neutral display fields, derived from the Reddit row.
                source="reddit",
                source_label=f"r/{subreddit}" if subreddit else "",
                engagement=int(p.score or 0),
                engagement_unit="upvotes",
                source_url=permalink,
            )
        )
    return out


def load_comments(
    deps: ResearchDeps,
    post_ids: Sequence[str],
    cap: int = DEFAULT_COMMENT_CAP,
) -> list[LoadedComment]:
    """Pull comment rows for the post-triage subset, capped at `cap`.

    Filters out `[deleted]` / `[removed]` / empty bodies inline, maps
    `RedditComment.score` → `LoadedComment.upvotes`, and returns the
    highest-scoring comments first so the cap chops noise, not signal.
    """
    if not post_ids:
        return []
    out: list[LoadedComment] = []
    seen: set[str] = set()
    for c in deps.corpus.get_comments_for_posts(list(dict.fromkeys(post_ids))):
        body = (c.body or "").strip()
        if not body or body in ("[deleted]", "[removed]"):
            continue
        if not c.comment_id or c.comment_id in seen:
            continue
        seen.add(c.comment_id)
        subreddit = c.subreddit or ""
        permalink = c.permalink or ""
        upvotes = int(c.score or 0)
        out.append(
            LoadedComment(
                comment_id=c.comment_id,
                post_id=c.post_id or "",
                subreddit=subreddit,
                body=body,
                upvotes=upvotes,
                author_hash=c.author_hash or "",
                permalink=permalink,
                # Source-neutral display fields, derived from the Reddit row.
                source="reddit",
                source_label=f"r/{subreddit}" if subreddit else "",
                engagement=upvotes,
                engagement_unit="upvotes",
                source_url=permalink,
            )
        )

    # Highest-scoring first, then cap. Score-sort before cap is what keeps the
    # cap from silently dropping the strongest signal (a long-tail filter).
    out.sort(key=lambda c: c.upvotes, reverse=True)
    return out[:cap]
