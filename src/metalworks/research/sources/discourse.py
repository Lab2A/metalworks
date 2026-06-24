"""``DiscourseSource`` — a keyless :class:`ItemSource` over the Discourse JSON API.

Discourse is the highest *venues-per-build* source: thousands of branded community
forums — every ``community.X.com``, ``meta.*``, and vendor / dev / vertical board —
run the **same software** and expose the **same public JSON API** (append ``.json``
to almost any HTML route). One adapter, parameterized by ``instance`` (the forum
host, e.g. ``meta.discourse.org``), unlocks the long tail of pro / practitioner
communities that Reddit and Hacker News miss (support forums, power-user boards,
vendor communities). This is the connector that turns "Reddit research" into
"research over the forums where the actual users of a product already talk".

Shape (mirrors :mod:`metalworks.research.sources.hackernews` — read that first)
------------------------------------------------------------------------------
Two JSON endpoints carry the whole connector, both on the configured host:

* ``/search.json?q=<query>`` — full-text search, windowed in-query with Discourse's
  ``after:`` / ``before:`` date operators (``YYYY-MM-DD``). The response carries a
  ``topics`` list (the threads — title + view/like counts) and a parallel ``posts``
  list (search hits with a ``blurb`` excerpt). Each topic → :class:`CorpusRecord`,
  its first matching post's blurb supplying the quotable body.
* ``/t/<id>.json`` — one topic's ``post_stream.posts`` (the reply thread), each
  flattened to a :class:`CorpusComment` (``cooked`` HTML → text, a per-post
  permalink, a pseudonymized ``username``).

Auth is **keyless** for public forums (``auth="none"``, ``access="open"``). Some
hosts gate search behind a login and answer a public request with **403** (or a
login redirect); that is treated as **"skip this host"** — the affected pull yields
nothing rather than crashing the run, exactly the way the SE / HN connectors guard a
per-call failure. Sentinel normalization is the source's job: a deleted / anonymous
post carries no ``username`` (→ tombstone author) and empty ``cooked`` (→ dropped),
so the corpus spine never sees a Discourse-specific marker.

Signals
-------
``upvotes`` (social) carries the Discourse **like** count (``like_count``); ``views``
(magnitude) carries the topic **view** count. Both kinds are already registered in
:mod:`metalworks.research.synthesis.signals` — no ``register_signal`` here.

``query`` is a free-text search string. ``window.start`` / ``window.end`` drive the
``after:`` / ``before:`` operators; Discourse is not month-partitioned, so
``window.months`` is ignored. The host (default ``meta.discourse.org``) is the
``instance`` target — set it per source via ``instance=`` (the ``instance`` picker
maps a brief to candidate hosts).
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

DEFAULT_INSTANCE = "meta.discourse.org"
DEFAULT_TIMEOUT_S = 30.0
# Discourse search is page-bounded; a single page is plenty for a candidate set.
DEFAULT_MAX_TOPICS = 50

_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"\s*</?(?:p|br|div|li)\s*/?>\s*", re.IGNORECASE)
_MULTI_NL_RE = re.compile(r"\n{2,}")


def _hash_author(username: Any, *, salt: str) -> str | None:
    """Stable, non-reversible author id from a Discourse ``username``.

    A deleted / anonymous post carries no (or an empty) ``username``; that collapses
    to a tombstone (``None``) HERE so nothing downstream re-derives Discourse
    specifics. We hash the lowercased username (Discourse usernames are unique and
    case-insensitive within a host).
    """
    if not isinstance(username, str) or not username.strip():
        return None
    h = hashlib.sha256(f"{salt}:{username.strip().lower()}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _ts_to_dt(ts: Any) -> datetime | None:
    """Discourse timestamps are ISO-8601 strings (``created_at``)."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _clean_html(text: str | None) -> str:
    """Turn a Discourse ``cooked`` HTML body (or a search ``blurb``) into plain text.

    Cooked bodies are HTML: ``<p>`` paragraphs, ``<a href>`` links, ``<blockquote>``
    / ``<code>`` blocks, and HTML entities. We convert block tags to newlines, strip
    every other tag, collapse blank runs, then unescape entities.
    """
    if not text:
        return ""
    text = _PARA_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return html.unescape(text).strip()


class DiscourseSource:
    """:class:`ItemSource` over a public, keyless Discourse forum's JSON API.

    ``instance`` is the forum host (the ``instance`` target) — ``meta.discourse.org``
    by default, ``community.<vendor>.com`` / ``forum.<project>.org`` for branded
    boards. A host that gates its search behind a login (403 / redirect) is skipped
    gracefully: the pull yields nothing rather than raising.
    """

    source_id = "discourse"

    def __init__(
        self,
        *,
        instance: str = DEFAULT_INSTANCE,
        scheme: str = "https",
        author_salt: str = "metalworks-local",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_topics: int = DEFAULT_MAX_TOPICS,
        client: Any | None = None,
    ) -> None:
        # Accept a bare host or a full URL; normalize to scheme + host.
        host = (instance or DEFAULT_INSTANCE).strip()
        if "://" in host:
            scheme, _, host = host.partition("://")
        self._instance = host.rstrip("/")
        self._scheme = scheme or "https"
        self._base_url = f"{self._scheme}://{self._instance}"
        self._salt = author_salt
        self._timeout_s = timeout_s
        self._max_topics = max(1, max_topics)
        self._client = client

    # ── HTTP plumbing (lazy httpx) ────────────────────────────────────────────

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """One GET → parsed JSON dict, or ``None`` when the host gates the request.

        A 403 / 404 / login-redirect (the "this forum requires a login" shape) is
        swallowed to ``None`` so the caller can skip the host gracefully; any other
        transport / decode failure also collapses to ``None`` (a per-call guard,
        like HN's per-story ``except``). httpx is imported lazily (it is core, but a
        bare ``import metalworks`` should not construct a client).
        """
        import httpx

        client = self._client
        owns = client is None
        if owns:
            client = httpx.Client(
                timeout=self._timeout_s,
                follow_redirects=False,
                headers={"User-Agent": "metalworks-research/0.1 (+https://github.com)"},
            )
        try:
            resp = client.get(url, params=params)
            # A login-gated host answers public JSON with 403/404 or a redirect to
            # /login; treat any of those as "skip host", not an error.
            status = getattr(resp, "status_code", 200)
            if status in (401, 403, 404) or status in range(300, 400):
                return None
            resp.raise_for_status()
            payload: Any = resp.json()
        except Exception:
            return None
        finally:
            if owns:
                client.close()
        return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}

    # ── pull (topics → CorpusRecord) ──────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate topic records for ``query`` over ``window``.

        Queries ``/search.json`` once (Discourse search is relevance-ranked and
        page-bounded), with ``after:`` / ``before:`` date operators appended from
        ``window.start`` / ``window.end``. ``window.months`` is ignored — Discourse
        is not month-partitioned. A gated host (``_get`` → ``None``) yields nothing.
        """
        url = f"{self._base_url}/search.json"
        params = {"q": self._search_query(query, window)}
        payload = self._get(url, params)
        if payload is None:
            return  # gated / unreachable host → skip gracefully
        topics = _as_list(payload.get("topics"))
        blurbs = self._blurbs_by_topic(_as_list(payload.get("posts")))
        emitted = 0
        for topic in topics:
            if not isinstance(topic, dict):
                continue
            record = self._record_from_topic(cast("dict[str, Any]", topic), blurbs)
            if record is None:
                continue
            yield record
            emitted += 1
            if limit is not None and emitted >= limit:
                return
            if emitted >= self._max_topics:
                return

    def _search_query(self, query: str, window: SourceWindow) -> str:
        """Compose the Discourse ``q`` string: the text plus ``after:`` / ``before:``.

        Discourse expresses a date window with in-query operators (``after:YYYY-MM-DD``
        is inclusive of that day onward; ``before:`` up to that day), not separate
        params — so the window rides inside ``q``.
        """
        parts = [query.strip()]
        if window.start is not None:
            parts.append(f"after:{window.start.date().isoformat()}")
        if window.end is not None:
            parts.append(f"before:{window.end.date().isoformat()}")
        return " ".join(p for p in parts if p)

    def _blurbs_by_topic(self, posts: list[Any]) -> dict[int, str]:
        """First search-result ``blurb`` per ``topic_id`` (the quotable excerpt).

        Search returns a parallel ``posts`` list whose entries carry a ``blurb``
        (the matched-text excerpt) and a ``topic_id``. We keep the FIRST blurb seen
        per topic so a topic record has body text even before its full thread is
        fetched.
        """
        out: dict[int, str] = {}
        for post in posts:
            if not isinstance(post, dict):
                continue
            post_d = cast("dict[str, Any]", post)
            tid = _as_int(post_d.get("topic_id"))
            if tid is None or tid in out:
                continue
            blurb = _clean_html(post_d.get("blurb"))
            if blurb:
                out[tid] = blurb
        return out

    def _record_from_topic(
        self, topic: dict[str, Any], blurbs: dict[int, str]
    ) -> CorpusRecord | None:
        topic_id = _as_int(topic.get("id"))
        if topic_id is None:
            return None
        like_count = _as_int(topic.get("like_count")) or 0
        views = _as_int(topic.get("views")) or 0
        slug = str(topic.get("slug") or "")
        permalink = self._topic_url(topic_id, slug)
        return CorpusRecord(
            id=f"{self._instance}:{topic_id}",
            source="discourse",
            source_id=str(topic_id),
            url=permalink,
            title=html.unescape(str(topic.get("title") or topic.get("fancy_title") or "")),
            text=blurbs.get(topic_id, ""),
            author_hash=_hash_author(topic.get("last_poster_username"), salt=self._salt),
            engagement=like_count,
            # upvotes (social, the Discourse "like") + views (magnitude); both
            # registered upstream.
            signals={"upvotes": float(like_count), "views": float(views)},
            created_at=_ts_to_dt(topic.get("created_at")),
            extra={
                "instance": self._instance,
                "slug": slug,
                "like_count": like_count,
                "views": views,
                "posts_count": _as_int(topic.get("posts_count")) or 0,
                "category_id": topic.get("category_id"),
            },
        )

    def _topic_url(self, topic_id: int, slug: str, post_number: int | None = None) -> str:
        base = f"{self._base_url}/t/{slug}/{topic_id}" if slug else f"{self._base_url}/t/{topic_id}"
        return f"{base}/{post_number}" if post_number else base

    # ── comments (post stream → CorpusComment) ────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one post-stream batch per topic id, from ``/t/<id>.json``.

        Discourse always has a thread layer, so this never returns ``None`` (an
        empty list for a gated / single-post topic is correct, not "comment-less").
        Each id is the spine id (``<host>:<topic_id>``) or a bare native id; we
        recover the native topic id from either.
        """
        return self._iter_threads(record_ids)

    def _iter_threads(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        for rid in record_ids:
            native = self._native_topic_id(rid)
            if native is None:
                yield []
                continue
            payload = self._get(f"{self._base_url}/t/{native}.json")
            if payload is None:
                yield []  # gated topic → empty, not a crash
                continue
            yield self._comments_from_topic(payload, str(native))

    @staticmethod
    def _native_topic_id(rid: str) -> str | None:
        """Recover the native topic id from a spine id (``<host>:<id>``) or bare id."""
        if not rid:
            return None
        native = rid.rsplit(":", 1)[-1] if ":" in rid else rid
        return native or None

    def _comments_from_topic(self, payload: dict[str, Any], topic_id: str) -> list[CorpusComment]:
        stream = payload.get("post_stream")
        posts = (
            _as_list(cast("dict[str, Any]", stream).get("posts"))
            if isinstance(stream, dict)
            else []
        )
        slug = str(payload.get("slug") or "")
        out: list[CorpusComment] = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            comment = self._comment_from_post(
                cast("dict[str, Any]", post), topic_id=topic_id, slug=slug
            )
            if comment is not None:
                out.append(comment)
        return out

    def _comment_from_post(
        self, post: dict[str, Any], *, topic_id: str, slug: str
    ) -> CorpusComment | None:
        post_id = _as_int(post.get("id"))
        if post_id is None:
            return None
        text = _clean_html(post.get("cooked"))
        if not text:
            return None  # deleted / empty post → drop, not a tombstone.
        post_number = _as_int(post.get("post_number"))
        like_count = _as_int(post.get("like_count")) or 0
        tid = _as_int(topic_id) or 0
        return CorpusComment(
            id=f"{self._instance}:{post_id}",
            parent_id=f"{self._instance}:{topic_id}",
            source="discourse",
            url=self._topic_url(tid, slug, post_number),
            text=text,
            author_hash=_hash_author(post.get("username"), salt=self._salt) or "",
            engagement=like_count,
            signals={"upvotes": float(like_count)},
            created_at=_ts_to_dt(post.get("created_at")),
            extra={
                "instance": self._instance,
                "post_number": post_number,
                "like_count": like_count,
            },
        )

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """Discourse serves live data; the latest window ends now (open start).

        ``months`` is empty — Discourse windows by datetime span only.
        """
        return SourceWindow(end=datetime.now(tz=UTC))


def _as_list(value: Any) -> list[Any]:
    return cast("list[Any]", value) if isinstance(value, list) else []


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _factory(**kwargs: Any) -> DiscourseSource:
    return DiscourseSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors stackexchange.py).
# Keyless + open: a public Discourse forum needs no key; a login-gated host is
# skipped at pull time, not registered as authed. Signals: upvotes (social, the
# Discourse "like") + views (magnitude), both registered in synthesis.signals — no
# register_signal needed here.
register_source(
    "discourse",
    _factory,
    spec=SourceSpec(
        source_id="discourse",
        lane="grounding",
        signals=("upvotes", "views"),
        targeting="instance",
        auth="none",
        env=(),
        access="open",
        relevance_hint=(
            "branded product/vendor/vertical community forums (support, power users, practitioners)"
        ),
    ),
)


__all__ = ["DiscourseSource"]
