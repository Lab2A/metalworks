"""``HackerNewsSource`` — a keyless reference :class:`ItemSource` over Hacker News.

Where :mod:`metalworks.research.sources.arctic` wraps a private data layer (DuckDB
over a Parquet mirror plus a rate-limited comment API), this connector is the
*small, dependency-light* reference: it talks to the public **HN Algolia** search
API (``hn.algolia.com``) — keyless, no auth, no SDK — over the core ``httpx``
dependency. It is the connector to read first when writing your own (and the BYO
skeleton in :mod:`metalworks.research.sources.template` mirrors its shape).

Two endpoints carry the whole connector:

* ``/api/v1/search`` and ``/api/v1/search_by_date`` — full-text search for
  *stories*, the top-level items that become :class:`CorpusRecord`. We page with
  ``page`` / ``hitsPerPage`` and window with ``numericFilters=created_at_i>…``.
* ``/api/v1/items/{objectID}`` — one story's full comment *tree*, which we flatten
  depth-first into :class:`CorpusComment`s.

Sentinel normalization is the source's job (see the protocol docstring): HN marks
missing/removed content with ``null`` authors and ``[flagged]`` / ``[dead]`` /
``null`` text. We drop dead/empty comments here and hash authors at this boundary,
so the corpus spine downstream never sees an HN-specific tombstone.

``query`` is a free-text search string (unlike Arctic, where ``query`` is a single
subreddit). ``window.start`` / ``window.end`` drive the date filter; HN is not
month-partitioned, so ``window.months`` is ignored.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

DEFAULT_BASE_URL = "https://hn.algolia.com/api/v1"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_HITS_PER_PAGE = 50
# HN sentinels for missing / moderated content. None of these are quotable.
_DEAD_TEXT = ("[flagged]", "[dead]", "[deleted]", "[removed]")
_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"\s*</?p\s*/?>\s*", re.IGNORECASE)
_MULTI_NL_RE = re.compile(r"\n{2,}")


def _hash_author(author: str | None, *, salt: str) -> str | None:
    """Stable, non-reversible author id; HN's ``null`` author → tombstone (None).

    Mirrors the Arctic connector's boundary normalization: a missing author
    collapses to ``None`` HERE so nothing downstream re-derives HN specifics.
    """
    if not author:
        return None
    h = hashlib.sha256(f"{salt}:{author.lower()}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _ts_to_dt(ts: Any) -> datetime | None:
    """Algolia exposes ``created_at_i`` (epoch seconds); fall back to ISO ``created_at``."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _clean_html(text: str | None) -> str:
    """Turn HN's HTML comment body into plain text.

    HN comment text is HTML: ``<p>`` paragraph breaks, ``<a href>`` links,
    ``<i>``/``<code>`` inline tags, and HTML entities. We convert paragraph tags
    to newlines, strip every other tag, then unescape entities.
    """
    if not text:
        return ""
    text = _PARA_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return html.unescape(text).strip()


class HackerNewsSource:
    """:class:`ItemSource` over the public, keyless HN Algolia API."""

    source_id = "hackernews"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        author_salt: str = "metalworks-local",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        hits_per_page: int = DEFAULT_HITS_PER_PAGE,
        by_date: bool = False,
        client: Any | None = None,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._salt = author_salt
        self._timeout_s = timeout_s
        self._hits_per_page = hits_per_page
        # search_by_date is newest-first; search is relevance-ranked. The pull is
        # a candidate set the pipeline triages, so relevance ranking is the default.
        self._by_date = by_date
        self._client = client

    # ── HTTP plumbing (lazy httpx) ────────────────────────────────────────────

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One GET → parsed JSON dict. httpx is imported lazily (it is core, but
        a bare ``import metalworks`` should not need to construct a client)."""
        import httpx

        client = self._client
        if client is None:
            client = httpx.Client(
                timeout=self._timeout_s,
                headers={"User-Agent": "metalworks-research/0.1 (+https://github.com)"},
            )
            try:
                resp = client.get(url, params=params)
            finally:
                client.close()
        else:
            resp = client.get(url, params=params)
        resp.raise_for_status()
        payload: Any = resp.json()
        return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}

    # ── pull (stories → CorpusRecord) ─────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate story records for ``query`` over ``window``.

        Pages the Algolia search endpoint until exhausted (or ``limit`` is hit),
        filtering by ``tags=story`` and ``created_at_i`` numeric filters built from
        ``window.start`` / ``window.end``. ``window.months`` is ignored — HN is
        not month-partitioned.
        """
        endpoint = "search_by_date" if self._by_date else "search"
        url = f"{self._base_url}/{endpoint}"
        numeric = self._numeric_filters(window)
        emitted = 0
        page = 0
        while True:
            params: dict[str, Any] = {
                "query": query,
                "tags": "story",
                "page": page,
                "hitsPerPage": self._hits_per_page,
            }
            if numeric:
                params["numericFilters"] = numeric
            payload = self._get(url, params)
            raw_hits: Any = payload.get("hits")
            hits: list[Any] = cast("list[Any]", raw_hits) if isinstance(raw_hits, list) else []
            if not hits:
                break
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                record = self._record_from_hit(cast("dict[str, Any]", hit))
                if record is None:
                    continue
                yield record
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            nb_pages: Any = payload.get("nbPages")
            page += 1
            if isinstance(nb_pages, int) and page >= nb_pages:
                break
            if len(hits) < self._hits_per_page:
                break

    def _numeric_filters(self, window: SourceWindow) -> str:
        clauses: list[str] = []
        if window.start is not None:
            clauses.append(f"created_at_i>={int(window.start.timestamp())}")
        if window.end is not None:
            clauses.append(f"created_at_i<={int(window.end.timestamp())}")
        return ",".join(clauses)

    def _record_from_hit(self, hit: dict[str, Any]) -> CorpusRecord | None:
        object_id = hit.get("objectID")
        if not object_id:
            return None
        object_id = str(object_id)
        hn_url = f"https://news.ycombinator.com/item?id={object_id}"
        # A story is either text (Ask HN) or a link (story_url); prefer the body.
        story_text = _clean_html(hit.get("story_text"))
        link = str(hit.get("url") or "")
        text = story_text or link
        points = int(hit.get("points") or 0)
        num_comments = int(hit.get("num_comments") or 0)
        return CorpusRecord(
            id=object_id,
            source="hackernews",
            source_id=object_id,
            url=hn_url,
            title=str(hit.get("title") or ""),
            text=text,
            author_hash=_hash_author(hit.get("author"), salt=self._salt),
            engagement=points,
            created_at=_ts_to_dt(hit.get("created_at_i") or hit.get("created_at")),
            extra={
                "num_comments": num_comments,
                "points": points,
                "objectID": object_id,
            },
        )

    # ── comments (item tree → CorpusComment) ──────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one comment batch per record id, fetched from ``/items/{id}``.

        HN always has a comment layer, so this never returns ``None`` (an empty
        list for a story with no live comments is correct, not "comment-less").
        """
        return self._iter_comments(record_ids)

    def _iter_comments(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        for rid in record_ids:
            if not rid:
                yield []
                continue
            try:
                payload = self._get(f"{self._base_url}/items/{rid}")
            except Exception:
                # Per-story failure must not abort the batch; yield empty for it.
                yield []
                continue
            batch: list[CorpusComment] = []
            self._flatten_children(payload.get("children"), parent_record=str(rid), out=batch)
            yield batch

    def _flatten_children(
        self, children: Any, *, parent_record: str, out: list[CorpusComment]
    ) -> None:
        """Walk the recursive ``children`` tree of an ``/items/{id}`` payload.

        Each node is ``{id, type, author, text, created_at_i, children:[…]}``.
        Dead / empty comments are dropped (not emitted as tombstones); their
        children are still walked so a live reply under a dead parent survives.
        """
        if not isinstance(children, list):
            return
        nodes: list[Any] = cast("list[Any]", children)
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_d = cast("dict[str, Any]", node)
            comment = self._comment_from_node(node_d, parent_record=parent_record)
            if comment is not None:
                out.append(comment)
            self._flatten_children(node_d.get("children"), parent_record=parent_record, out=out)

    def _comment_from_node(
        self, node: dict[str, Any], *, parent_record: str
    ) -> CorpusComment | None:
        if node.get("type") not in (None, "comment"):
            return None
        comment_id = node.get("id")
        if comment_id is None:
            return None
        comment_id = str(comment_id)
        # HN dead/flagged comments carry null text or a sentinel; drop them.
        raw = node.get("text")
        if raw is None or (isinstance(raw, str) and raw.strip() in _DEAD_TEXT):
            return None
        text = _clean_html(raw)
        if not text or text in _DEAD_TEXT:
            return None
        return CorpusComment(
            id=comment_id,
            parent_id=parent_record,
            source="hackernews",
            url=f"https://news.ycombinator.com/item?id={comment_id}",
            text=text,
            author_hash=_hash_author(node.get("author"), salt=self._salt) or "",
            engagement=0,  # HN comments have no public score.
            created_at=_ts_to_dt(node.get("created_at_i") or node.get("created_at")),
            extra={"objectID": comment_id, "parent_id_native": node.get("parent_id")},
        )

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """HN has no fixed anchor (it serves live data); the latest window ends now.

        We return an end-bounded window anchored at the current instant; ``start``
        is ``None`` (open) so a caller that does not narrow it pulls the most
        recent matches. ``months`` is empty — HN windows by datetime span only.
        """
        return SourceWindow(end=datetime.now(tz=UTC))


def _factory(**kwargs: Any) -> HackerNewsSource:
    return HackerNewsSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors arctic.py).
# The Algolia HN Search API is open + keyless; HN points are its endorsement signal.
register_source(
    "hackernews",
    _factory,
    spec=SourceSpec(
        source_id="hackernews",
        lane="grounding",
        signals=("points",),
        targeting="keyword",
        auth="none",
        env=(),
        access="open",
        relevance_hint="builder/early-adopter demand for a topic on Hacker News",
    ),
)


__all__ = ["HackerNewsSource"]
