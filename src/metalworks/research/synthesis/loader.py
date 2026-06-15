"""Load the hydrated corpus subset from the corpus repo.

Synthesis works against the post-triage subset already persisted by the
hydration stage. This module is the one boundary between the synthesis core and
storage: every other synthesis module operates on the in-memory `LoadedComment`
/ `LoadedPost` shapes produced here.

We never keep `[deleted]` / `[removed]` / empty bodies — synthesis ranking on
those is meaningless and they'd just chew up LLM tokens.

DESIGN NOTE: we read the source-neutral corpus through
`deps.corpus.get_records(...)` / `deps.corpus.get_comments_for_records(...)`,
which return generic `CorpusRecord` / `CorpusComment` and already paginate to
exhaustion. The generic spine populates the synthesis-local shapes directly:
`CorpusRecord.engagement` → `LoadedPost`/`LoadedComment` engagement,
`CorpusComment.url` → `permalink`/`source_url`. The Reddit-only `subreddit`
display field is read from the record's `extra` tail (set at ingest). Posts have
no permalink of their own, so `LoadedPost.permalink` is sourced from the record
`url`. New sources populate the same fields from their own spine values.
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


def _source_label(source: str, subreddit: str) -> str:
    """A human-readable origin label for the synthesis display fields.

    Reddit renders `r/<sub>`; other sources render their own label (currently a
    titlecased source name — a source adapter will own this once a second source
    lands)."""
    if source == "reddit":
        return f"r/{subreddit}" if subreddit else ""
    return source.replace("_", " ").title()


def _engagement_unit(source: str) -> str:
    """Source-native engagement unit for display (Reddit: upvotes)."""
    return "upvotes" if source == "reddit" else "engagements"


def load_posts(deps: ResearchDeps, post_ids: Sequence[str]) -> list[LoadedPost]:
    """Pull record rows for the post-triage subset, mapped to LoadedPost."""
    if not post_ids:
        return []
    out: list[LoadedPost] = []
    seen: set[str] = set()
    for r in deps.corpus.get_records(list(dict.fromkeys(post_ids))):
        if not r.id or r.id in seen:
            continue
        seen.add(r.id)
        # `subreddit` is a Reddit-only display field carried in the record tail.
        subreddit = str(r.extra.get("subreddit") or "")
        num_comments = int(r.extra.get("num_comments") or 0)
        permalink = r.url or ""
        engagement = int(r.engagement or 0)
        out.append(
            LoadedPost(
                post_id=r.id,
                subreddit=subreddit,
                title=r.title or "",
                score=engagement,
                num_comments=num_comments,
                permalink=permalink,
                # Source-neutral display fields, derived from the generic spine.
                source=r.source,
                source_label=_source_label(r.source, subreddit),
                engagement=engagement,
                engagement_unit=_engagement_unit(r.source),
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

    Filters out `[deleted]` / `[removed]` / empty bodies inline, maps the generic
    `CorpusComment.engagement` → `LoadedComment.upvotes`, and returns the
    highest-engagement comments first so the cap chops noise, not signal.
    """
    if not post_ids:
        return []
    out: list[LoadedComment] = []
    seen: set[str] = set()
    for c in deps.corpus.get_comments_for_records(list(dict.fromkeys(post_ids))):
        body = (c.text or "").strip()
        if not body or body in ("[deleted]", "[removed]"):
            continue
        if not c.id or c.id in seen:
            continue
        seen.add(c.id)
        # `subreddit` is a Reddit-only display field carried in the comment tail.
        subreddit = str(c.extra.get("subreddit") or "")
        permalink = c.url or ""
        upvotes = int(c.engagement or 0)
        out.append(
            LoadedComment(
                comment_id=c.id,
                post_id=c.parent_id or "",
                subreddit=subreddit,
                body=body,
                upvotes=upvotes,
                author_hash=c.author_hash or "",
                permalink=permalink,
                # Source-neutral display fields, derived from the generic spine.
                source=c.source,
                source_label=_source_label(c.source, subreddit),
                engagement=upvotes,
                engagement_unit=_engagement_unit(c.source),
                source_url=permalink,
            )
        )

    # Highest-engagement first, then cap. Sort before cap is what keeps the
    # cap from silently dropping the strongest signal (a long-tail filter).
    out.sort(key=lambda c: c.upvotes, reverse=True)
    return out[:cap]
