"""``StackExchangeSource`` — a keyless :class:`ItemSource` over the Stack Exchange API.

Stack Exchange is the highest-leverage de-Reddit'ing source: one keyless API
(``api.stackexchange.com/2.3``) fronts 170+ topical Q&A sites — Server Fault, DBA,
Security, Salesforce, the ``aws`` / ``devops`` / ``serverfault`` neighbourhoods —
i.e. the B2B / sysadmin / cloud-pro voices Reddit underweights. It also adds a real
**magnitude** signal Reddit upvotes cannot express: ``view_count`` ("47k views, no
accepted answer" = *quantified, unmet* demand). The connector emits both
``{"votes": score, "views": view_count}`` — ``votes`` social, ``views`` magnitude —
each already registered in :mod:`metalworks.research.synthesis.signals` (no new
``register_signal`` here).

CC BY-SA framing — evidence retrieval, NOT training ingestion
-------------------------------------------------------------
Stack Exchange user content is licensed **CC BY-SA**: re-use *requires* attribution
to the original post and author. That is exactly metalworks' cite-or-die posture —
every record carries the question's canonical permalink (``link``) and a
pseudonymized author derived from the SE profile, so a downstream quote always
resolves back to its source and its author. This connector is therefore framed as
**evidence retrieval / quoting under CC BY-SA**, NOT corpus ingestion for model
training (the free API ToS forbids AI-training use). We pull the minimum needed to
quote-with-attribution; we do not bulk-mirror SE for a model.

Shape (mirrors :mod:`metalworks.research.sources.hackernews` — read that first)
------------------------------------------------------------------------------
Two paged JSON endpoints carry the whole connector:

* ``/search/advanced`` — full-text question search for one ``site`` (the
  ``instance``), windowed by ``fromdate`` / ``todate`` (epoch seconds), paged via
  ``page`` / ``pagesize``, with a ``filter`` that includes question **body** +
  ``view_count`` + ``score``. Each question → :class:`CorpusRecord`.
* ``/questions/{ids}/answers`` — the answers under a batch of question ids (SE
  semicolon-joins up to ~100 ids per call), each → :class:`CorpusComment`. Answers
  are the quote-bearing sub-items (the Q&A analogue of a comment thread).

Auth is **keyless** (300 req/day/IP). A free, non-expiring app key raises the quota
to 10k/day; it is passed through when ``STACKEXCHANGE_KEY`` is set (or ``key=``) but
is **never required** — ``auth="none"``, ``access="open"``. Sentinel normalization
is the source's job: SE marks a deleted owner with no ``user_id`` and an empty /
absent body, which collapse to a tombstone author / dropped item here, so the
corpus spine never sees an SE-specific marker.

``query`` is a free-text search string. ``window.start`` / ``window.end`` drive the
date filter; SE is not month-partitioned, so ``window.months`` is ignored. The SE
``site`` (default ``stackoverflow``) is the ``instance`` target — set it per source
via ``site=`` (the ``instance`` picker maps a brief to candidate sites).
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

DEFAULT_BASE_URL = "https://api.stackexchange.com/2.3"
DEFAULT_SITE = "stackoverflow"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_PAGE_SIZE = 50  # SE caps pagesize at 100; 50 keeps a single page cheap.
# SE semicolon-joins ids in a vectorized route; it caps a request at ~100 ids.
_MAX_IDS_PER_CALL = 100
# A filter that adds the (HTML) body to the default question/answer projections
# while keeping score + view_count. This is SE's well-known "withbody" filter.
_FILTER_WITHBODY = "withbody"

_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"\s*</?(?:p|br|div|li)\s*/?>\s*", re.IGNORECASE)
_MULTI_NL_RE = re.compile(r"\n{2,}")


def _hash_author(owner: Any, *, salt: str) -> str | None:
    """Stable, non-reversible author id from an SE ``owner`` block.

    SE attaches an ``owner`` ``{user_id, display_name, link, ...}`` to each item.
    A deleted/anonymous owner has no ``user_id``; that collapses to a tombstone
    (``None``) HERE so nothing downstream re-derives SE specifics. We hash the
    stable numeric ``user_id`` (not the mutable display name) when present.
    """
    if not isinstance(owner, dict):
        return None
    user_id: Any = cast("dict[str, Any]", owner).get("user_id")
    if user_id is None:
        return None
    h = hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _ts_to_dt(ts: Any) -> datetime | None:
    """SE timestamps are epoch seconds (``creation_date``)."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    return None


def _clean_html(text: str | None) -> str:
    """Turn an SE HTML body into plain text.

    SE bodies are HTML: ``<p>`` paragraphs, ``<a href>`` links, ``<code>`` /
    ``<pre>`` blocks, and HTML entities. We convert block tags to newlines, strip
    every other tag, collapse blank runs, then unescape entities.
    """
    if not text:
        return ""
    text = _PARA_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return html.unescape(text).strip()


class StackExchangeSource:
    """:class:`ItemSource` over the public, keyless Stack Exchange API 2.3.

    ``site`` is the SE instance (the ``instance`` target) — ``stackoverflow`` by
    default, ``serverfault`` / ``dba`` / ``security`` / ``salesforce`` for B2B
    roles. ``key`` is the optional free app key (read from ``STACKEXCHANGE_KEY``
    when not passed) that raises the quota — never required.
    """

    source_id = "stackexchange"

    def __init__(
        self,
        *,
        site: str = DEFAULT_SITE,
        base_url: str | None = None,
        key: str | None = None,
        author_salt: str = "metalworks-local",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        page_size: int = DEFAULT_PAGE_SIZE,
        client: Any | None = None,
    ) -> None:
        self._site = site or DEFAULT_SITE
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        # Optional quota key: explicit arg wins, else the env var, else keyless.
        self._key = key or os.environ.get("STACKEXCHANGE_KEY") or None
        self._salt = author_salt
        self._timeout_s = timeout_s
        self._page_size = max(1, min(page_size, 100))
        self._client = client

    # ── HTTP plumbing (lazy httpx) ────────────────────────────────────────────

    def _common_params(self) -> dict[str, Any]:
        """The ``site`` (+ optional ``key``) every SE request carries."""
        params: dict[str, Any] = {"site": self._site}
        if self._key:
            params["key"] = self._key
        return params

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """One GET → parsed JSON dict. httpx is imported lazily (it is core, but a
        bare ``import metalworks`` should not need to construct a client)."""
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

    # ── pull (questions → CorpusRecord) ───────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate question records for ``query`` over ``window``.

        Pages ``/search/advanced`` for the configured ``site`` until SE reports no
        more pages (or ``limit`` is hit), windowed by ``fromdate`` / ``todate``
        from ``window.start`` / ``window.end``. ``window.months`` is ignored — SE
        is not month-partitioned. Sorted by votes so the candidate set leads with
        the highest-signal questions.
        """
        url = f"{self._base_url}/search/advanced"
        emitted = 0
        page = 1
        while True:
            params = self._common_params()
            params.update(
                {
                    "q": query,
                    "page": page,
                    "pagesize": self._page_size,
                    "order": "desc",
                    "sort": "votes",
                    "filter": _FILTER_WITHBODY,
                }
            )
            self._apply_window(params, window)
            payload = self._get(url, params)
            raw_items: Any = payload.get("items")
            items: list[Any] = cast("list[Any]", raw_items) if isinstance(raw_items, list) else []
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                record = self._record_from_question(cast("dict[str, Any]", item))
                if record is None:
                    continue
                yield record
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            if not payload.get("has_more"):
                break
            page += 1

    def _apply_window(self, params: dict[str, Any], window: SourceWindow) -> None:
        if window.start is not None:
            params["fromdate"] = int(window.start.timestamp())
        if window.end is not None:
            params["todate"] = int(window.end.timestamp())

    def _record_from_question(self, item: dict[str, Any]) -> CorpusRecord | None:
        question_id = item.get("question_id")
        if question_id is None:
            return None
        question_id = str(question_id)
        score = int(item.get("score") or 0)
        view_count = int(item.get("view_count") or 0)
        link = str(item.get("link") or "")
        return CorpusRecord(
            id=question_id,
            source="stackexchange",
            source_id=question_id,
            url=link,
            title=html.unescape(str(item.get("title") or "")),
            text=_clean_html(item.get("body")),
            author_hash=_hash_author(item.get("owner"), salt=self._salt),
            engagement=score,
            # votes (social) + views (magnitude); both registered upstream.
            signals={"votes": float(score), "views": float(view_count)},
            created_at=_ts_to_dt(item.get("creation_date")),
            extra={
                "site": self._site,
                "score": score,
                "view_count": view_count,
                "answer_count": int(item.get("answer_count") or 0),
                "is_answered": bool(item.get("is_answered")),
                "tags": list(item.get("tags") or []),
            },
        )

    # ── comments (answers → CorpusComment) ────────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one answer batch per question id, from ``/questions/{ids}/answers``.

        SE always has an answer layer, so this never returns ``None`` (an empty
        list for a question with no answers is correct, not "comment-less"). We
        batch ids into vectorized calls (SE semicolon-joins up to ~100 per request)
        then redistribute the answers back to per-id batches IN INPUT ORDER.
        """
        return self._iter_answers(record_ids)

    def _iter_answers(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        by_question: dict[str, list[CorpusComment]] = {}
        ids = [rid for rid in record_ids if rid]
        for start in range(0, len(ids), _MAX_IDS_PER_CALL):
            chunk = ids[start : start + _MAX_IDS_PER_CALL]
            self._fetch_answer_chunk(chunk, by_question)
        for rid in record_ids:
            yield by_question.get(rid, [])

    def _fetch_answer_chunk(
        self, chunk: Sequence[str], out: dict[str, list[CorpusComment]]
    ) -> None:
        joined = ";".join(chunk)
        url = f"{self._base_url}/questions/{joined}/answers"
        params = self._common_params()
        params.update(
            {
                "page": 1,
                "pagesize": 100,
                "order": "desc",
                "sort": "votes",
                "filter": _FILTER_WITHBODY,
            }
        )
        try:
            payload = self._get(url, params)
        except Exception:
            # A per-chunk failure must not abort the batch; the affected questions
            # simply yield empty (no answers recovered), like HN's per-story guard.
            return
        raw_items: Any = payload.get("items")
        items: list[Any] = cast("list[Any]", raw_items) if isinstance(raw_items, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            comment = self._comment_from_answer(cast("dict[str, Any]", item))
            if comment is None:
                continue
            out.setdefault(comment.parent_id, []).append(comment)

    def _comment_from_answer(self, item: dict[str, Any]) -> CorpusComment | None:
        answer_id = item.get("answer_id")
        question_id = item.get("question_id")
        if answer_id is None or question_id is None:
            return None
        text = _clean_html(item.get("body"))
        if not text:
            return None  # deleted/empty answer → drop, not a tombstone.
        score = int(item.get("score") or 0)
        link = str(item.get("link") or "")
        return CorpusComment(
            id=str(answer_id),
            parent_id=str(question_id),
            source="stackexchange",
            url=link,
            text=text,
            author_hash=_hash_author(item.get("owner"), salt=self._salt) or "",
            engagement=score,
            signals={"votes": float(score)},
            created_at=_ts_to_dt(item.get("creation_date")),
            extra={
                "site": self._site,
                "score": score,
                "is_accepted": bool(item.get("is_accepted")),
            },
        )

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """SE serves live data; the latest window ends now (open start).

        ``months`` is empty — SE windows by datetime span only.
        """
        return SourceWindow(end=datetime.now(tz=UTC))


def _factory(**kwargs: Any) -> StackExchangeSource:
    return StackExchangeSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors hackernews.py).
# Keyless + open; the optional STACKEXCHANGE_KEY only raises the quota (so auth
# stays "none" / access "open"). Signals: votes (social) + views (magnitude),
# both registered in synthesis.signals — no register_signal needed here.
register_source(
    "stackexchange",
    _factory,
    spec=SourceSpec(
        source_id="stackexchange",
        lane="grounding",
        signals=("votes", "views"),
        targeting="instance",
        auth="none",
        env=(),
        access="open",
        relevance_hint=(
            "developers, sysadmins, DBAs, security & cloud/SaaS pros across 170+ "
            "Stack Exchange sites"
        ),
    ),
)


__all__ = ["StackExchangeSource"]
