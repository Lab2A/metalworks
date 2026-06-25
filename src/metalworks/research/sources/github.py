"""``GitHubItemSource`` — a keyless-with-optional-token :class:`ItemSource` over GitHub's REST API.

GitHub Issues capture a demand modality nothing else in the corpus reaches: a
**feature request or bug report filed against a shipping product** — "plugin X
doesn't support SSO, 340 👍" — i.e. quantified, attributed demand from the
developers and buyers of dev tooling. The issue is the record; its comments are
the quote-bearing sub-items; and the 👍 (``+1``) reaction count is a clean
**magnitude** of absolute endorsement volume (how many people upvoted the ask).

Shape (mirrors :mod:`metalworks.research.sources.stackexchange` — read that first)
---------------------------------------------------------------------------------
Two paged JSON endpoints carry the whole connector:

* ``GET /search/issues?q=<query>+created:<window>`` (``advanced_search=true``) —
  full-text issue search windowed by the ``created:`` qualifier, paged via
  ``page`` / ``per_page``, sorted by reactions so the candidate set leads with the
  most-endorsed asks. Each issue → :class:`CorpusRecord` (title, body, ``html_url``,
  author login pseudonymized).
* ``GET /repos/{owner}/{repo}/issues/{n}/comments`` — the comment thread under one
  issue, each → :class:`CorpusComment` (body + per-comment ``html_url`` permalink +
  author). The owner/repo/number triple is recovered from the issue's own
  ``repository_url`` + ``number`` (the search hit carries no repo object), stashed in
  the record's ``extra`` at pull time so ``comments_for`` can address the thread.

Signals — ``reactions`` (magnitude) + ``engagement`` (the comment count, social)
--------------------------------------------------------------------------------
The headline signal is ``reactions`` — the 👍 (``+1``) reaction count — a NEW kind
registered ``is_magnitude=True`` in :mod:`metalworks.research.synthesis.signals`
(this module imports that module so the kind is present whenever the connector is).
It is an absolute endorsement-volume number: it ranks (a 340-👍 ask sorts above a
5-👍 one, log-compressed) but never reaches the verdict band.

A magnitude-only grounding source is illegal UNLESS it is ``yields_units`` — and
GitHub is NOT a unit source (it has a real comment layer, so its breadth axis is
distinct authors, not distinct domains). The rule-5 conformance check therefore
requires a NON-magnitude signal too. The issue's **comment count** is that signal:
it is the native ``engagement`` int (registered non-magnitude), a genuine
participation signal distinct from the 👍 endorsement volume — no double-counting.
So a record emits ``{"reactions": <+1 count>, "engagement": <comment count>}`` and
the spec declares ``signals=("reactions", "engagement")``.

Auth — keyless, with an optional token (mirrors Stack Exchange's optional key)
------------------------------------------------------------------------------
The GitHub REST API works **unauthenticated** (60 req/hr/IP) but really wants a
token (``GITHUB_TOKEN``, 5000 req/hr). The token is passed as an ``Authorization:
Bearer`` header ONLY when present (explicit ``token=`` arg wins, else the env var),
and is **never required** — ``auth="key"``, ``access="open"`` (keyless works, just
slow). The keyless path sends no ``Authorization`` header at all (asserted in the
tests).

``query`` is a free-text search string. ``window.start`` / ``window.end`` drive the
``created:`` qualifier; GitHub is not month-partitioned, so ``window.months`` is
ignored.

Out of scope (per the issue): GraphQL Discussions (REST issues first) and any
per-repo deep crawl beyond the brief's search.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

# Importing the signals module registers the ``reactions`` kind (and every other
# built-in kind) at its module scope — so a bare ``import`` of this connector also
# guarantees ``reactions`` is in ``SIGNAL_SPECS`` for the scorer / conformance sweep.
import metalworks.research.synthesis.signals  # noqa: F401  # pyright: ignore[reportUnusedImport]
from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

DEFAULT_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT_S = 30.0
# GitHub caps ``per_page`` at 100 and the Search API at 1000 total results (10
# pages of 100). 50 keeps a single page cheap; we stop at the documented cap.
DEFAULT_PAGE_SIZE = 50
_MAX_SEARCH_RESULTS = 1000  # GitHub Search API hard cap (1000 across all pages).
_GITHUB_API_VERSION = "2022-11-28"
_ACCEPT = "application/vnd.github+json"


def _hash_author(login: Any, *, salt: str) -> str | None:
    """Stable, non-reversible author id from a GitHub user ``login``.

    GitHub attaches a ``user`` ``{login, id, ...}`` to each issue/comment. A
    ghosted/deleted author has no ``login`` (the ``user`` is ``None`` or the
    ``ghost`` placeholder); that collapses to a tombstone (``None``) HERE so
    nothing downstream re-derives GitHub specifics. We hash the stable ``login``.
    """
    if not isinstance(login, str) or not login or login == "ghost":
        return None
    h = hashlib.sha256(f"{salt}:{login}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _login_of(user: Any) -> str | None:
    """The ``login`` string from a GitHub ``user`` block, or ``None``.

    A deleted/ghost author is ``user: null`` (or carries no ``login``); both
    collapse to ``None`` here so the author tombstones cleanly downstream.
    """
    if not isinstance(user, dict):
        return None
    login: Any = cast("dict[str, Any]", user).get("login")
    return login if isinstance(login, str) else None


def _parse_dt(value: Any) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp (``2026-05-15T10:00:00Z``) to UTC, or ``None``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _thumbs_up(reactions: Any) -> int:
    """The 👍 (``+1``) reaction count from an issue's ``reactions`` block.

    GitHub returns ``reactions`` as ``{"+1": n, "-1": n, "total_count": n, ...}``.
    The 👍 (``+1``) count is the endorsement-volume magnitude — "340 people want
    this" — which is sharper than ``total_count`` (that mixes 👎 / 😄 / 👀). Absent
    or malformed → 0.
    """
    if not isinstance(reactions, dict):
        return 0
    value: Any = cast("dict[str, Any]", reactions).get("+1")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _build_query(query: str, window: SourceWindow) -> str:
    """Compose the GitHub search ``q``: terms + ``type:issue`` + the ``created:`` window.

    The ``created:`` qualifier takes ``YYYY-MM-DD`` bounds. A start-only window
    becomes ``created:>=start``, an end-only window ``created:<=end``, both a
    ``start..end`` range; an open window omits the qualifier entirely.
    """
    parts: list[str] = []
    if query:
        parts.append(query)
    parts.append("type:issue")
    start = window.start.date().isoformat() if window.start else None
    end = window.end.date().isoformat() if window.end else None
    if start and end:
        parts.append(f"created:{start}..{end}")
    elif start:
        parts.append(f"created:>={start}")
    elif end:
        parts.append(f"created:<={end}")
    return " ".join(parts)


def _owner_repo_from_url(repository_url: Any) -> tuple[str, str] | None:
    """Recover ``(owner, repo)`` from a search hit's ``repository_url``.

    A ``/search/issues`` hit carries no repo object, only
    ``repository_url = https://api.github.com/repos/{owner}/{repo}``. We split that
    so :meth:`comments_for` can address ``/repos/{owner}/{repo}/issues/{n}/comments``.
    Returns ``None`` when the URL is missing or malformed.
    """
    if not isinstance(repository_url, str) or not repository_url:
        return None
    path = urlsplit(repository_url).path.strip("/")
    parts = path.split("/")
    # .../repos/{owner}/{repo}
    if len(parts) >= 3 and parts[-3] == "repos" and parts[-2] and parts[-1]:
        return parts[-2], parts[-1]
    return None


class GitHubItemSource:
    """:class:`ItemSource` over the public GitHub REST API (issues + comments).

    ``token`` is the optional ``GITHUB_TOKEN`` (read from the env when not passed)
    that raises the rate limit from 60/hr to 5000/hr — never required (the keyless
    path sends no ``Authorization`` header). ``pull`` searches issues for the
    brief's terms over the ``created:`` window and yields each issue as a
    :class:`CorpusRecord` (👍 → ``reactions`` magnitude, comment count →
    ``engagement``); ``comments_for`` fetches each issue's comment thread.
    """

    source_id = "github"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        author_salt: str = "metalworks-local",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        page_size: int = DEFAULT_PAGE_SIZE,
        client: Any | None = None,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        # Optional token: explicit arg wins, else the env var, else keyless. No env
        # read at import time — only here, at construction.
        self._token = token or os.environ.get("GITHUB_TOKEN") or None
        self._salt = author_salt
        self._timeout_s = timeout_s
        self._page_size = max(1, min(page_size, 100))
        self._client = client
        # owner/repo addressing for each pulled issue id (populated at pull time so
        # ``comments_for`` can resolve a search hit, which carries no repo object).
        self._repo_by_id: dict[str, tuple[str, str, int]] = {}

    # ── HTTP plumbing (lazy httpx) ────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """The headers every request carries; ``Authorization`` ONLY when tokened.

        The keyless path omits ``Authorization`` entirely (no token leaked) — the
        optional ``GITHUB_TOKEN`` is sent as a Bearer credential only when present.
        """
        headers = {
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            "User-Agent": "metalworks-research/0.1 (+https://github.com)",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get(self, url: str, params: dict[str, Any] | None) -> Any:
        """One GET → parsed JSON. httpx is imported lazily (a bare ``import metalworks``
        must not need to construct a client)."""
        import httpx

        client = self._client
        headers = self._headers()
        if client is None:
            client = httpx.Client(timeout=self._timeout_s)
            try:
                resp = client.get(url, params=params, headers=headers)
            finally:
                client.close()
        else:
            resp = client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ── pull (issues → CorpusRecord) ──────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate issue records for ``query`` over ``window``.

        Pages ``/search/issues`` (with ``advanced_search=true``) for the brief's
        terms, scoped to ``type:issue`` and the ``created:<start>..<end>`` qualifier
        from ``window.start`` / ``window.end``, sorted by reactions so the candidate
        set leads with the most-endorsed asks. Stops at GitHub's 1000-result Search
        API cap (or ``limit``). ``window.months`` is ignored — GitHub is not
        month-partitioned.
        """
        url = f"{self._base_url}/search/issues"
        q = _build_query(query, window)
        seen: set[str] = set()
        emitted = 0
        page = 1
        while True:
            params: dict[str, Any] = {
                "q": q,
                "advanced_search": "true",
                "per_page": self._page_size,
                "page": page,
                "sort": "reactions",
                "order": "desc",
            }
            payload = self._get(url, params)
            items = self._items(payload)
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                record = self._record_from_issue(cast("dict[str, Any]", item))
                if record is None or record.id in seen:
                    continue
                seen.add(record.id)
                yield record
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            # GitHub Search has no ``has_more`` flag: a short page (fewer than
            # ``per_page`` hits) is the last one, and the API hard-caps at 1000 total
            # results across all pages. Either terminates the page loop.
            if len(items) < self._page_size:
                break
            page += 1
            if page * self._page_size > _MAX_SEARCH_RESULTS:
                break

    @staticmethod
    def _items(payload: Any) -> list[Any]:
        """The ``items`` array from a ``/search/issues`` payload (or ``[]``)."""
        if not isinstance(payload, dict):
            return []
        raw: Any = cast("dict[str, Any]", payload).get("items")
        return cast("list[Any]", raw) if isinstance(raw, list) else []

    def _record_from_issue(self, item: dict[str, Any]) -> CorpusRecord | None:
        """Map one ``/search/issues`` hit onto the source-neutral spine.

        Title/body/``html_url``/author login pseudonymized; the 👍 count →
        ``reactions`` magnitude, the comment count → ``engagement`` (social). The
        owner/repo/number triple is recovered from ``repository_url`` + ``number``
        and stashed in ``extra`` (and an internal map) so ``comments_for`` can
        address the thread.
        """
        issue_id = item.get("id")
        html_url = str(item.get("html_url") or "")
        if issue_id is None or not html_url:
            return None  # no id or permalink → not quotable; drop it.
        rid = str(issue_id)
        number_raw = item.get("number")
        number = int(number_raw) if isinstance(number_raw, int) else None
        owner_repo = _owner_repo_from_url(item.get("repository_url"))
        comment_count = int(item.get("comments") or 0)
        thumbs = _thumbs_up(item.get("reactions"))
        login = _login_of(item.get("user"))
        # reactions (👍 magnitude) + engagement (comment count, the rule-5 social
        # signal). Comment count is omitted as 0.0 only never — engagement of 0 is a
        # real "no discussion yet" value, so we always carry it.
        signals: dict[str, float] = {
            "reactions": float(thumbs),
            "engagement": float(comment_count),
        }
        if owner_repo is not None and number is not None:
            self._repo_by_id[rid] = (owner_repo[0], owner_repo[1], number)
        return CorpusRecord(
            id=f"github_{rid}",
            source="github",
            source_id=rid,
            url=html_url,
            title=str(item.get("title") or ""),
            text=str(item.get("body") or ""),
            author_hash=_hash_author(login, salt=self._salt),
            engagement=comment_count,  # the issue's native engagement = comment count.
            signals=signals,
            created_at=_parse_dt(item.get("created_at")),
            extra={
                "owner": owner_repo[0] if owner_repo else "",
                "repo": owner_repo[1] if owner_repo else "",
                "number": number,
                "reactions_plus1": thumbs,
                "comments": comment_count,
                "state": str(item.get("state") or ""),
                "html_url": html_url,
            },
        )

    # ── comments (issue comments → CorpusComment) ─────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one comment batch per issue id, from ``/repos/{owner}/{repo}/issues/{n}/comments``.

        GitHub issues have a real comment layer, so this never returns ``None`` (an
        empty list for a comment-less issue is correct, not "comment-less source").
        Ids whose owner/repo/number was not captured at pull time (e.g. asked for
        cold, without a preceding pull) yield an empty batch rather than erroring.
        """
        return self._iter_comments(record_ids)

    def _iter_comments(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        for rid in record_ids:
            native = rid[len("github_") :] if rid.startswith("github_") else rid
            addr = self._repo_by_id.get(native)
            if addr is None:
                yield []
                continue
            yield self._fetch_comments(*addr, parent_id=rid)

    def _fetch_comments(
        self, owner: str, repo: str, number: int, *, parent_id: str
    ) -> list[CorpusComment]:
        url = f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/comments"
        params: dict[str, Any] = {"per_page": 100, "page": 1}
        try:
            payload = self._get(url, params)
        except Exception:
            # A per-issue failure must not abort the batch; the affected issue simply
            # yields empty (no comments recovered), like Stack Exchange's per-chunk guard.
            return []
        items = cast("list[Any]", payload) if isinstance(payload, list) else []
        out: list[CorpusComment] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            comment = self._comment_from_item(cast("dict[str, Any]", item), parent_id=parent_id)
            if comment is not None:
                out.append(comment)
        return out

    def _comment_from_item(self, item: dict[str, Any], *, parent_id: str) -> CorpusComment | None:
        comment_id = item.get("id")
        body = str(item.get("body") or "")
        if comment_id is None or not body.strip():
            return None  # deleted/empty comment → drop, not a tombstone.
        login = _login_of(item.get("user"))
        thumbs = _thumbs_up(item.get("reactions"))
        return CorpusComment(
            id=str(comment_id),
            parent_id=parent_id,
            source="github",
            url=str(item.get("html_url") or ""),
            text=body,
            author_hash=_hash_author(login, salt=self._salt) or "",
            engagement=thumbs,
            signals={"reactions": float(thumbs)},
            created_at=_parse_dt(item.get("created_at")),
            extra={"reactions_plus1": thumbs},
        )

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """GitHub serves live data; the latest window ends now (open start).

        ``months`` is empty — GitHub windows by datetime span only.
        """
        return SourceWindow(end=datetime.now(tz=UTC))


def _factory(**kwargs: Any) -> GitHubItemSource:
    return GitHubItemSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors stackexchange.py).
# Keyless + open; the optional GITHUB_TOKEN only raises the rate limit, so auth is
# "key" but access stays "open" (keyless works, just slow). Signals: reactions (the
# NEW magnitude kind registered above) + engagement (the comment count, the
# non-magnitude social signal rule 5 requires — GitHub has a comment layer, so it is
# NOT a yields_units source). ``targeting="keyword"`` (the brief's terms drive the
# issue search), picked by the ``keyword`` target picker.
register_source(
    "github",
    _factory,
    spec=SourceSpec(
        source_id="github",
        lane="grounding",
        signals=("reactions", "engagement"),
        targeting="keyword",
        auth="key",
        env=("GITHUB_TOKEN",),
        access="open",
        relevance_hint=(
            "developers and the buyers of dev tooling filing feature requests and bug "
            "reports against shipping products — GitHub Issues (👍 = endorsement volume)"
        ),
    ),
)


__all__ = ["GitHubItemSource"]
