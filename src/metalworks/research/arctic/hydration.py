"""Post-triage hydration: persist the small relevant Reddit subset.

Corpus hydration. The pipeline triages
millions of Parquet rows against the brief (~thousands relevant) and only that
subset is hydrated; the raw corpus stays in object storage.

Two stages, deliberately separate so they can be parallelized or skipped:

1. :func:`hydrate_submissions` — pulls matching rows via
   ``deps.reader.fetch_submissions_by_ids`` (the new PUBLIC reader method) and
   upserts ``RedditPost`` rows through ``deps.corpus``.

2. :func:`hydrate_comments` — fans out to the live Arctic Shift API via
   ``deps.comments.comments_for_links`` (the HF comment tree is stale) and
   upserts ``RedditComment`` rows.

Port changes vs. the source:

- Writes go through ``deps.corpus.upsert_posts`` / ``.upsert_comments`` against
  the contract models, not Supabase tables.
- Author hashing uses ``deps.author_salt`` (NOT a hardcoded constant); Reddit's
  ``[deleted]`` / ``[removed]`` sentinels are preserved.
- ``HydrationResult.skipped`` / ``.errors`` are populated from the API client's
  per-link failure accumulation so a run that lost most of its corpus to 5xx
  can flag itself partial.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from metalworks.contract import RedditComment, RedditPost
from metalworks.research.types import HydrationResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.types import MonthRef

SOURCE = "arctic_shift"


# ── Helpers ─────────────────────────────────────────────────────────────


def _hash_author(author: str | None, *, salt: str) -> str | None:
    """Stable, non-reversible author identifier.

    Reddit's ``[deleted]`` / ``[removed]`` sentinels are preserved as-is so the
    pipeline can reason about them; real usernames are sha256-truncated.
    """
    if not author or author in ("[deleted]", "[removed]"):
        return author or None
    h = hashlib.sha256(f"{salt}:{author.lower()}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _ts_to_dt(ts: Any) -> datetime | None:
    """Reddit emits ``created_utc`` as a unix-epoch float; contract wants
    ``datetime``."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (ValueError, OSError, TypeError):
        return None


def _strip_prefix(rid: str | None, prefix: str) -> str | None:
    """Strip Reddit's ``t1_`` / ``t3_`` fullname prefix to the bare id."""
    if not rid:
        return None
    return rid[len(prefix) :] if rid.startswith(prefix) else rid


# ── Public surface ──────────────────────────────────────────────────────


def hydrate_submissions(
    deps: ResearchDeps,
    *,
    post_ids: Sequence[str],
    months: Sequence[MonthRef],
) -> HydrationResult:
    """Persist a post-triage subset of submissions as ``RedditPost`` rows.

    ``post_ids`` are bare Reddit submission ids (no ``t3_`` prefix) — the
    triage-relevant set, not the full pull. ``months`` constrains the Parquet
    scan to the partitions the ids fall under.
    """
    t0 = time.monotonic()
    ids = [pid for pid in post_ids if pid]
    requested = len(ids)
    if not requested:
        return HydrationResult(0, 0, 0, 0.0, SOURCE)
    if not months:
        raise ValueError("hydrate_submissions: months window required")

    salt = deps.author_salt
    posts: list[RedditPost] = []
    fetched = 0
    for row in deps.reader.fetch_submissions_by_ids(ids, list(months)):
        post_id = row.get("id")
        if not post_id:
            continue
        fetched += 1
        subreddit = row.get("subreddit") or ""
        url = row.get("url") or (
            f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/" if subreddit else ""
        )
        posts.append(
            RedditPost(
                post_id=str(post_id),
                subreddit=str(subreddit),
                title=str(row.get("title") or ""),
                selftext=str(row.get("selftext") or ""),
                url=str(url),
                author=_hash_author(row.get("author"), salt=salt),
                score=int(row.get("score") or 0),
                num_comments=int(row.get("num_comments") or 0),
                created_utc=_ts_to_dt(row.get("created_utc")),
            )
        )

    deps.corpus.upsert_posts(posts)
    return HydrationResult(
        requested=requested,
        fetched=fetched,
        upserted=len(posts),
        elapsed_s=time.monotonic() - t0,
        source=SOURCE,
    )


def hydrate_comments(
    deps: ResearchDeps,
    *,
    link_ids: Sequence[str],
) -> HydrationResult:
    """Persist comments for a list of submissions as ``RedditComment`` rows.

    Uses ``deps.comments`` (the live Arctic Shift API) because the HF comment
    tree is stale. Per-link failures from the comment source are folded into
    ``HydrationResult.skipped`` / ``.errors``.
    """
    t0 = time.monotonic()
    ids = [lid for lid in link_ids if lid]
    requested = len(ids)
    if not requested:
        return HydrationResult(0, 0, 0, 0.0, SOURCE)
    if deps.comments is None:
        raise ValueError("hydrate_comments: deps.comments (CommentSource) is required")

    salt = deps.author_salt
    source = deps.comments
    comments: list[RedditComment] = []
    fetched = 0
    for link_id, thread in zip(ids, source.comments_for_links(ids), strict=False):
        fetched += len(thread)
        for c in thread:
            comment_id = _strip_prefix(c.get("id") or c.get("name"), "t1_")
            if not comment_id:
                continue
            subreddit = c.get("subreddit") or ""
            post_id = _strip_prefix(c.get("link_id"), "t3_") or link_id
            permalink = f"/r/{subreddit}/comments/{post_id}/_/{comment_id}/" if subreddit else ""
            comments.append(
                RedditComment(
                    comment_id=str(comment_id),
                    post_id=str(post_id),
                    subreddit=str(subreddit),
                    body=str(c.get("body") or ""),
                    permalink=permalink,
                    author_hash=_hash_author(c.get("author"), salt=salt) or "",
                    score=int(c.get("score") or 0),
                    created_utc=_ts_to_dt(c.get("created_utc")),
                    parent_id=_strip_prefix(c.get("parent_id"), "t1_"),
                )
            )

    deps.corpus.upsert_comments(comments)

    # Pull the per-link failure accumulation off the client if it exposes it.
    skipped = int(getattr(source, "last_skipped", 0) or 0)
    errors_attr: Any = getattr(source, "last_errors", None)
    errors_seq: list[Any] = cast("list[Any]", errors_attr) if isinstance(errors_attr, list) else []
    errors: list[str] = [str(e) for e in errors_seq]

    return HydrationResult(
        requested=requested,
        fetched=fetched,
        upserted=len(comments),
        elapsed_s=time.monotonic() - t0,
        source=SOURCE,
        skipped=skipped,
        errors=errors,
    )
