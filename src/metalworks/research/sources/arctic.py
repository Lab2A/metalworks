"""``ArcticItemSource`` — the reference :class:`ItemSource` (Reddit / Arctic).

Wraps the existing Arctic data layer — :class:`~metalworks.research.arctic.reader.ArcticReader`
(submissions, DuckDB-over-Parquet) and
:class:`~metalworks.research.arctic.api.ArcticShiftApiClient` (live comments) —
and yields the source-neutral corpus spine. Submission rows are built into
``RedditPost`` and comment dicts into ``RedditComment``, then mapped onto
:class:`~metalworks.contract.CorpusRecord` / :class:`~metalworks.contract.CorpusComment`
via the existing ``from_reddit_*`` mappers (reused, not reimplemented).

This is the DEFAULT source: it self-registers as ``SOURCES["reddit"]`` (alias
``"arctic"``) on import, so ``get_source("reddit")`` returns it and the pipeline
keeps Reddit as the default with no behavior change.

``query`` for Arctic is a subreddit name (the bulk reader pulls per-subreddit);
the pipeline drives one source instance per brief subreddit, which is what the
prior ``_pull_corpus`` loop did. Sentinel normalization (``[deleted]`` /
``[removed]``) happens at this boundary: authors are hashed (or tombstoned), so
nothing downstream re-derives Reddit specifics.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from metalworks.contract import CorpusComment, CorpusRecord, RedditComment, RedditPost
from metalworks.research.sources import SourceWindow, register_source
from metalworks.research.types import MonthRef

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from metalworks.research.deps import CommentSource, CorpusReader

# Columns the pull needs. Superset of the prior triage select — adds the
# fields hydration used to re-fetch (author/url/created_utc) so the record
# ingested during the pull is complete and no second submission fetch is needed.
_PULL_COLS = [
    "id",
    "title",
    "selftext",
    "subreddit",
    "score",
    "num_comments",
    "author",
    "url",
    "created_utc",
]


def _hash_author(author: str | None, *, salt: str) -> str | None:
    """Stable, non-reversible author id; removal sentinels → tombstone (None).

    This is the source-boundary normalization the spec moves out of the shared
    loader: ``[deleted]`` / ``[removed]`` collapse to ``None`` HERE, so the
    corpus spine never carries a raw Reddit sentinel.
    """
    if not author or author in ("[deleted]", "[removed]"):
        return None
    h = hashlib.sha256(f"{salt}:{author.lower()}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _ts_to_dt(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (ValueError, OSError, TypeError):
        return None


def _strip_prefix(rid: str | None, prefix: str) -> str | None:
    if not rid:
        return None
    return rid[len(prefix) :] if rid.startswith(prefix) else rid


class ArcticItemSource:
    """:class:`ItemSource` over Arctic Shift submissions + live comments."""

    source_id = "reddit"

    def __init__(
        self,
        *,
        reader: CorpusReader,
        comments: CommentSource | None = None,
        author_salt: str = "metalworks-local",
        content_type: str = "submissions",
    ) -> None:
        self._reader = reader
        self._comments = comments
        self._salt = author_salt
        self._content_type = content_type

    # ── pull (submissions → CorpusRecord) ────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate records for one subreddit (``query``) over ``window``.

        Builds ``RedditPost`` from each parquet row and maps it onto the
        source-neutral spine via ``CorpusRecord.from_reddit_post`` (reused 1b
        mapper). ``window.months`` drives the month-partitioned reader.
        """
        months = list(window.months)
        if not months:
            months = list(self.latest_window().months)
        rows = self._reader.pull_subreddit(
            subreddit=query,
            content_type=self._content_type,
            months=months,
            select_cols=_PULL_COLS,
            limit=limit,
        )
        for row in rows:
            post_id = row.get("id")
            if not post_id:
                continue
            subreddit = str(row.get("subreddit") or query)
            url = row.get("url") or (
                f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/" if subreddit else ""
            )
            post = RedditPost(
                post_id=str(post_id),
                subreddit=subreddit,
                title=str(row.get("title") or ""),
                selftext=str(row.get("selftext") or ""),
                url=str(url),
                author=_hash_author(row.get("author"), salt=self._salt),
                score=int(row.get("score") or 0),
                num_comments=int(row.get("num_comments") or 0),
                created_utc=_ts_to_dt(row.get("created_utc")),
            )
            yield CorpusRecord.from_reddit_post(post)

    # ── comments (live API → CorpusComment) ──────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Stream comment batches per record id via the live Arctic Shift API.

        Returns ``None`` when no comment source is configured (so the run is
        marked comment-less rather than failed).
        """
        if self._comments is None:
            return None
        return self._iter_comments(record_ids)

    def _iter_comments(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        ids = [rid for rid in record_ids if rid]
        if not ids:
            return
        assert self._comments is not None
        source = self._comments
        for link_id, thread in zip(ids, source.comments_for_links(ids), strict=False):
            batch: list[CorpusComment] = []
            for c in thread:
                comment_id = _strip_prefix(c.get("id") or c.get("name"), "t1_")
                if not comment_id:
                    continue
                subreddit = str(c.get("subreddit") or "")
                post_id = _strip_prefix(c.get("link_id"), "t3_") or link_id
                permalink = (
                    f"/r/{subreddit}/comments/{post_id}/_/{comment_id}/" if subreddit else ""
                )
                comment = RedditComment(
                    comment_id=str(comment_id),
                    post_id=str(post_id),
                    subreddit=subreddit,
                    body=str(c.get("body") or ""),
                    permalink=permalink,
                    author_hash=_hash_author(c.get("author"), salt=self._salt) or "",
                    score=int(c.get("score") or 0),
                    created_utc=_ts_to_dt(c.get("created_utc")),
                    parent_id=_strip_prefix(c.get("parent_id"), "t1_"),
                )
                batch.append(CorpusComment.from_reddit_comment(comment))
            yield batch

    # ── window ───────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        anchor: MonthRef = self._reader.latest_available_month(self._content_type)
        return SourceWindow(months=(anchor,))


def _factory(**kwargs: Any) -> ArcticItemSource:
    return ArcticItemSource(**kwargs)


# Self-register on import (append-friendly registry). Alias the legacy id too.
register_source("reddit", _factory)
register_source("arctic", _factory)


__all__ = ["ArcticItemSource"]
