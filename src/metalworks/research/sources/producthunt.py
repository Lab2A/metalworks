"""``ProductHuntSource`` — an :class:`ItemSource` over the Product Hunt API v2.

Product Hunt is launched products + the discussion around them — strongest for the
*competitive landscape* (what already exists, how it landed) and validating a
space, a complement to the unmet-need signal on Reddit / Hacker News.

The v2 API is **GraphQL** (``https://api.producthunt.com/v2/api/graphql``) and is
**token-gated**: a free, non-expiring *developer token* from the Product Hunt API
dashboard, sent as ``Authorization: Bearer <token>``. Set it as
``PRODUCT_HUNT_TOKEN`` (or pass ``token=``); without it, a pull raises a clear
error.

There is **no full-text search** of posts, so a research *question* does not map
to a query. This connector pulls the top posts (by votes) in the time window and
lets metalworks' relevance triage filter them — the same "pull candidates, triage"
shape as the other archive sources. Because Product Hunt's complexity rate limit
is real, the pull is capped (``DEFAULT_MAX_POSTS``) and the window result is cached
per instance so the pipeline's per-subreddit loop doesn't re-fetch it.

The GraphQL query strings live as module constants so they are easy to adjust
against the live schema. Mapping: a **Post** → :class:`CorpusRecord`
(``votesCount`` → engagement, ``name`` + ``tagline`` → title, ``description`` →
text, hunter → author); a **Comment** → :class:`CorpusComment` parented to its
post. Product Hunt has comments, so this is not a unit source.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from metalworks.research.types import MonthRef

ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_PAGE_SIZE = 50
# Cap a single pull — Product Hunt's rate limit is complexity-based, and pulling
# a whole multi-month window unbounded would blow through it. Top-by-votes keeps
# the highest-signal posts under the cap; triage narrows from there.
DEFAULT_MAX_POSTS = 500
DEFAULT_MAX_COMMENTS_PER_POST = 200

_POSTS_QUERY = """
query Posts($first: Int!, $after: String, $postedAfter: DateTime, $postedBefore: DateTime) {
  posts(first: $first, after: $after, order: VOTES,
        postedAfter: $postedAfter, postedBefore: $postedBefore) {
    edges {
      node {
        id name tagline description slug url votesCount commentsCount createdAt
        topics(first: 5) { edges { node { name } } }
        user { id name username }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_COMMENTS_QUERY = """
query Comments($id: ID!, $first: Int!, $after: String) {
  post(id: $id) {
    comments(first: $first, after: $after, order: VOTES_COUNT) {
      edges {
        node {
          id body votesCount createdAt url
          user { id name username }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


_TAG_RE = re.compile(r"<[^>]+>")
_BR_P_RE = re.compile(r"\s*<\s*(?:br|/p|p)\s*/?\s*>\s*", re.IGNORECASE)
_MULTI_NL_RE = re.compile(r"\n{2,}")


def _clean_html(text: str | None) -> str:
    """Product Hunt comment/description bodies are HTML — convert ``<p>``/``<br>``
    to newlines, strip other tags, unescape entities."""
    if not text:
        return ""
    text = _BR_P_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return html.unescape(text).strip()


def _hash_author(handle: str | None, *, salt: str) -> str | None:
    if not handle:
        return None
    h = hashlib.sha256(f"{salt}:{handle.lower()}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _ts_to_dt(ts: Any) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_dict(x: Any) -> dict[str, Any]:
    """Narrow an untyped JSON value to a string-keyed dict (or empty)."""
    return cast("dict[str, Any]", x) if isinstance(x, dict) else {}


class ProductHuntSource:
    """:class:`ItemSource` over the Product Hunt GraphQL API v2 (token-gated)."""

    source_id = "producthunt"

    def __init__(
        self,
        *,
        token: str | None = None,
        author_salt: str = "metalworks-local",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_posts: int = DEFAULT_MAX_POSTS,
        client: Any | None = None,
    ) -> None:
        self._token = (
            token
            or os.environ.get("PRODUCT_HUNT_TOKEN")
            or os.environ.get("PRODUCT_HUNT_DEVELOPER_TOKEN")
        )
        self._salt = author_salt
        self._timeout_s = timeout_s
        self._max_posts = max_posts
        self._client = client
        # Window pull is the same for every per-subreddit call the pipeline makes;
        # cache it so a token-limited API isn't re-hit once per brief subreddit.
        self._cache: dict[tuple[str | None, str | None, int | None], list[CorpusRecord]] = {}

    # ── GraphQL plumbing ───────────────────────────────────────────────────────

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            raise RuntimeError(
                "ProductHuntSource needs a Product Hunt developer token. Get a free one at "
                "the Product Hunt API dashboard and set PRODUCT_HUNT_TOKEN."
            )
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "metalworks-research/0.1",
        }
        payload = {"query": query, "variables": variables}
        client = self._client
        if client is None:
            import httpx

            client = httpx.Client(timeout=self._timeout_s, headers=headers)
            try:
                resp = client.post(ENDPOINT, json=payload)
            finally:
                client.close()
        else:
            resp = client.post(ENDPOINT, json=payload, headers=headers)
        resp.raise_for_status()
        body: Any = resp.json()
        if not isinstance(body, dict):
            return {}
        body_d = cast("dict[str, Any]", body)
        errors = body_d.get("errors")
        if errors:
            raise RuntimeError(f"Product Hunt GraphQL error: {errors}")
        data = body_d.get("data")
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}

    @staticmethod
    def _nodes(connection: Any) -> list[dict[str, Any]]:
        edges = _as_dict(connection).get("edges")
        out: list[dict[str, Any]] = []
        if isinstance(edges, list):
            for e in cast("list[Any]", edges):
                node = _as_dict(e).get("node")
                if isinstance(node, dict):
                    out.append(_as_dict(node))
        return out

    @staticmethod
    def _page_info(connection: Any) -> tuple[bool, str | None]:
        pi = _as_dict(_as_dict(connection).get("pageInfo"))
        cursor = pi.get("endCursor")
        return bool(pi.get("hasNextPage")), (str(cursor) if cursor else None)

    # ── pull (posts → CorpusRecord) ────────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield the top posts (by votes) in ``window``. ``query`` is ignored —
        Product Hunt has no full-text search, so relevance is the triage stage's
        job (see the module docstring)."""
        start, end = self._window_bounds(window)
        cap = min(self._max_posts, limit) if limit else self._max_posts
        key = (_iso(start), _iso(end), cap)
        if key not in self._cache:
            self._cache[key] = self._fetch_posts(start, end, cap)
        yield from self._cache[key]

    def _window_bounds(self, window: SourceWindow) -> tuple[datetime | None, datetime | None]:
        if window.start or window.end:
            return window.start, window.end
        months: tuple[MonthRef, ...] = tuple(window.months)
        if months:
            ms = sorted(months, key=lambda m: (m.year, m.month))
            start = datetime(ms[0].year, ms[0].month, 1, tzinfo=UTC)
            ly, lm = ms[-1].year, ms[-1].month
            ny, nm = (ly + 1, 1) if lm == 12 else (ly, lm + 1)
            end = datetime(ny, nm, 1, tzinfo=UTC)
            return start, end
        return None, None

    def _fetch_posts(
        self, start: datetime | None, end: datetime | None, cap: int
    ) -> list[CorpusRecord]:
        out: list[CorpusRecord] = []
        after: str | None = None
        while len(out) < cap:
            data = self._post(
                _POSTS_QUERY,
                {
                    "first": min(DEFAULT_PAGE_SIZE, cap - len(out)),
                    "after": after,
                    "postedAfter": _iso(start),
                    "postedBefore": _iso(end),
                },
            )
            conn = data.get("posts")
            nodes = self._nodes(conn)
            if not nodes:
                break
            for node in nodes:
                rec = self._record_from_post(node)
                if rec is not None:
                    out.append(rec)
                if len(out) >= cap:
                    break
            has_next, after = self._page_info(conn)
            if not has_next or not after:
                break
        return out

    def _record_from_post(self, node: dict[str, Any]) -> CorpusRecord | None:
        pid = node.get("id")
        if not pid:
            return None
        pid = str(pid)
        name = str(node.get("name") or "")
        tagline = str(node.get("tagline") or "")
        title = f"{name} — {tagline}".strip(" —") if tagline else name
        votes = int(node.get("votesCount") or 0)
        user = _as_dict(node.get("user"))
        topics = [
            str(n.get("name") or "") for n in self._nodes(node.get("topics")) if n.get("name")
        ]
        return CorpusRecord(
            id=pid,
            source="producthunt",
            source_id=pid,
            url=str(
                node.get("url") or f"https://www.producthunt.com/posts/{node.get('slug') or pid}"
            ),
            title=title,
            text=_clean_html(str(node.get("description") or "")) or tagline,
            author_hash=_hash_author(user.get("username") or user.get("id"), salt=self._salt),
            engagement=votes,
            created_at=_ts_to_dt(node.get("createdAt")),
            extra={
                "tagline": tagline,
                "topics": topics,
                "num_comments": int(node.get("commentsCount") or 0),
                "votes": votes,
            },
        )

    # ── comments (post comments → CorpusComment) ───────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one comment batch per post id (Product Hunt always has a comment
        layer, so this never returns ``None``)."""
        return self._iter_comments(record_ids)

    def _iter_comments(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        for rid in record_ids:
            if not rid:
                yield []
                continue
            try:
                yield self._fetch_comments(str(rid))
            except Exception:
                # A per-post failure must not abort the batch.
                yield []

    def _fetch_comments(self, post_id: str) -> list[CorpusComment]:
        out: list[CorpusComment] = []
        after: str | None = None
        while len(out) < DEFAULT_MAX_COMMENTS_PER_POST:
            data = self._post(
                _COMMENTS_QUERY,
                {"id": post_id, "first": DEFAULT_PAGE_SIZE, "after": after},
            )
            conn = _as_dict(data.get("post")).get("comments")
            nodes = self._nodes(conn)
            if not nodes:
                break
            for node in nodes:
                c = self._comment_from_node(node, parent_record=post_id)
                if c is not None:
                    out.append(c)
            has_next, after = self._page_info(conn)
            if not has_next or not after:
                break
        return out

    def _comment_from_node(
        self, node: dict[str, Any], *, parent_record: str
    ) -> CorpusComment | None:
        cid = node.get("id")
        body = _clean_html(str(node.get("body") or ""))
        if not cid or not body:
            return None
        cid = str(cid)
        user = _as_dict(node.get("user"))
        return CorpusComment(
            id=cid,
            parent_id=parent_record,
            source="producthunt",
            url=str(node.get("url") or f"https://www.producthunt.com/posts/{parent_record}"),
            text=body,
            author_hash=_hash_author(user.get("username") or user.get("id"), salt=self._salt) or "",
            engagement=int(node.get("votesCount") or 0),
            created_at=_ts_to_dt(node.get("createdAt")),
            extra={"votes": int(node.get("votesCount") or 0)},
        )

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """Product Hunt is live; the latest window ends now (open start)."""
        return SourceWindow(end=datetime.now(tz=UTC))


def _factory(**kwargs: Any) -> ProductHuntSource:
    return ProductHuntSource(**kwargs)


# The Product Hunt GraphQL API needs a developer token (free to obtain), read from
# PRODUCT_HUNT_TOKEN — so auth "key" / access "free_key" / env names the var. Votes
# are the supply-side endorsement signal.
register_source(
    "producthunt",
    _factory,
    spec=SourceSpec(
        source_id="producthunt",
        lane="grounding",
        signals=("votes",),
        targeting="slug",
        auth="key",
        env=("PRODUCT_HUNT_TOKEN",),
        access="free_key",
        relevance_hint="shipped products in the category and how much traction they got",
    ),
)


__all__ = ["ProductHuntSource"]
