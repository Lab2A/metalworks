"""Load the hydrated corpus subset from the corpus repo.

Synthesis works against the post-triage subset already persisted by the
hydration stage. This module is the one boundary between the synthesis core and
storage: every other synthesis module operates on the in-memory `LoadedComment`
/ `LoadedPost` shapes produced here.

Removal-sentinel normalization (`[deleted]` / `[removed]`) now happens at the
SOURCE/ingest boundary (`research/sources/ingest.py`), not here — the corpus the
loader reads is already free of them, so this module stays source-neutral. We
still drop empty bodies defensively (a blank comment carries no quotable signal).

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

from metalworks.contract import SynthesisThresholds
from metalworks.research.types import LoadedComment, LoadedPost

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metalworks.research.deps import ResearchDeps

# Same upper bound the marketing pipeline used. Past this, the LLM synthesis
# call's input grows faster than its recall improves; the embed-group dedup
# stage gets the load down to a sane number anyway. Surfaced as
# ``SynthesisThresholds.comment_cap`` (issue #82); this constant mirrors that
# documented default for callers that don't thread a policy through.
DEFAULT_COMMENT_CAP = SynthesisThresholds.model_fields["comment_cap"].default


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

    Removal sentinels are already normalized away at ingest; here we just drop
    empty bodies defensively, map the generic `CorpusComment.engagement` →
    `LoadedComment.upvotes`, and return the highest-engagement comments first so
    the cap chops noise, not signal.
    """
    if not post_ids:
        return []
    out: list[LoadedComment] = []
    seen: set[str] = set()
    for c in deps.corpus.get_comments_for_records(list(dict.fromkeys(post_ids))):
        body = (c.text or "").strip()
        if not body:
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


def load_commentless_records_as_units(
    deps: ResearchDeps,
    post_ids: Sequence[str],
    *,
    exclude_ids: set[str],
) -> list[LoadedComment]:
    """Records from a comment-less source contribute their OWN text as a unit.

    A web page has no comment thread — the page text itself IS the unit of demand
    signal. We map each such record to a `LoadedComment` so it flows through the
    existing embed-group + cluster pipeline unchanged.

    The discriminator is the ``extra["is_unit"]`` flag the hydration stage sets
    on records whose SOURCE has no comment layer (``comments_for`` returned
    ``None``). This is deliberately a per-source property, not "any record with
    zero comments": a comment-bearing source (Reddit, HN) carries its signal in
    comments, so a Reddit post with zero comments in a run stays excluded
    (unchanged behavior), while a web record is always promoted. ``exclude_ids``
    are record ids that DO have comments — a guard against double-counting.

    Authorless units carry ``author_hash=""``; the breadth ranker counts them by
    distinct domain instead of distinct author, so they rank comparably rather
    than scoring zero for having no author.
    """
    if not post_ids:
        return []
    out: list[LoadedComment] = []
    seen: set[str] = set()
    for r in deps.corpus.get_records(list(dict.fromkeys(post_ids))):
        if not r.id or r.id in exclude_ids or r.id in seen:
            continue
        # Only records a comment-less source flagged at ingest become units; a
        # comment-bearing source's posts are represented by their comments.
        if not r.extra.get("is_unit"):
            continue
        seen.add(r.id)
        # The page/story text is the signal; fall back to the title for link-only
        # records whose body is empty.
        body = (r.text or r.title or "").strip()
        if not body:
            continue
        subreddit = str(r.extra.get("subreddit") or "")
        engagement = int(r.engagement or 0)
        url = r.url or ""
        out.append(
            LoadedComment(
                comment_id=r.id,
                post_id=r.id,
                subreddit=subreddit,
                body=body,
                upvotes=engagement,
                author_hash=r.author_hash or "",
                permalink=url,
                source=r.source,
                source_label=_source_label(r.source, subreddit),
                engagement=engagement,
                engagement_unit=_engagement_unit(r.source),
                source_url=url,
            )
        )
    return out
