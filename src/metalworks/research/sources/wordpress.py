"""``WordPressSource`` — a keyless :class:`ItemSource` over the WordPress.org plugin directory.

The WordPress.org plugin directory is the one marketplace that is **fully open AND
carries both quotable reviews and a deployment-magnitude** (``active_installs``):
a keyless JSON search API fronts the whole directory, and every plugin's reviews are
public, verbatim, authored, and permalinked. It reaches site admins / agencies /
freelancers — the SMB long-tail B2B layer Reddit and HN underweight. This is a
Phase-3 grounding singleton (the review/marketplace shape).

Shape (mirrors :mod:`metalworks.research.sources.stackexchange` — read that first)
---------------------------------------------------------------------------------
A review maps like a comment: the **plugin is the record**, each **review is the
quote-bearing sub-item**. Two keyless endpoints carry the whole connector:

* ``GET /plugins/info/1.2/?action=query_plugins`` — full-text plugin search,
  ``request[search]`` = the brief's terms, paged via ``request[page]`` /
  ``request[per_page]``. Each plugin → :class:`CorpusRecord` (name, short
  description, plugin page url), emitting ``{"installs": active_installs}`` — the
  deployment magnitude — on the plugin record.
* The plugin's public **reviews feed** (``wordpress.org/support/plugin/<slug>/reviews/feed/``)
  — an RSS document, one ``<item>`` per review. Each review →
  :class:`CorpusComment` (verbatim review text + per-review permalink + reviewer
  handle, pseudonymized), emitting ``{"rating": stars}`` per review. ``rating`` is a
  registered *polarity*-capable kind — it is carried (and contributes to ranking),
  but ``polarity`` is NOT yet consumed by the verdict band (a low rating is "demand
  for a fix", computed later). NO new ``register_signal`` here — both ``installs``
  (magnitude) and ``rating`` (polarity) are already registered in
  :mod:`metalworks.research.synthesis.signals`.

Auth is **keyless** — ``auth="none"``, ``access="open"``. Both the search API and
the reviews feed are public and require no key. Sentinel normalization is the
source's job: a review with no recoverable author collapses to an empty author
handle, and an empty-body review is dropped, so the corpus spine never sees a
WordPress-specific marker.

``query`` is the free-text plugin search. WordPress.org is not date-windowed at the
search layer (it ranks by relevance/popularity), so :class:`SourceWindow` is read
only to drop reviews published outside ``window.start`` / ``window.end`` when those
are set; ``window.months`` is ignored.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote
from xml.etree import ElementTree as ET

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

DEFAULT_API_URL = "https://api.wordpress.org/plugins/info/1.2/"
DEFAULT_SUPPORT_BASE = "https://wordpress.org/support/plugin"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_PAGE_SIZE = 25  # The query_plugins API caps per_page at ~250; 25 is one cheap page.
# A sane cap on reviews pulled per plugin (one feed page is plenty; see issue out-of-scope).
DEFAULT_MAX_REVIEWS = 30

_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"\s*</?(?:p|br|div|li)\s*/?>\s*", re.IGNORECASE)
_MULTI_NL_RE = re.compile(r"\n{2,}")
# bbPress prefixes each review body with "Replies: N" / "Rating: N stars" metadata
# lines; we lift the rating from there, then strip those lines from the quote body.
_RATING_RE = re.compile(r"Rating:\s*(\d+)\s*stars?", re.IGNORECASE)
_META_LINE_RE = re.compile(r"^\s*(?:Replies|Rating):.*$", re.IGNORECASE | re.MULTILINE)
# RSS uses the Dublin Core namespace for <dc:creator>.
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _hash_author(handle: str | None, *, salt: str) -> str:
    """Stable, non-reversible author id from a reviewer display handle.

    The reviews feed carries a ``<dc:creator>`` display name (WordPress.org has no
    stable numeric user id in the feed); we hash that. A missing/blank handle
    collapses to an empty author HERE (the spine never sees a WordPress marker).
    """
    if not handle or not handle.strip():
        return ""
    h = hashlib.sha256(f"{salt}:{handle.strip()}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _clean_html(text: str | None) -> str:
    """Turn a review's HTML description into plain text.

    Review bodies are HTML (``<p>`` paragraphs, ``<a href>`` links, entities). We
    convert block tags to newlines, strip every other tag, drop the bbPress
    metadata lines (``Replies:`` / ``Rating:``), collapse blank runs, then unescape.
    """
    if not text:
        return ""
    text = _PARA_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _META_LINE_RE.sub("", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return html.unescape(text).strip()


def _parse_rss_date(value: str | None) -> datetime | None:
    """Parse an RSS ``<pubDate>`` (RFC 822) into a UTC datetime, or ``None``."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class WordPressSource:
    """:class:`ItemSource` over the public, keyless WordPress.org plugin directory.

    ``pull`` searches plugins for the brief's terms and yields each plugin as a
    :class:`CorpusRecord` carrying the ``installs`` magnitude; ``comments_for``
    fetches each plugin's public reviews feed and yields each review as a
    :class:`CorpusComment` carrying a ``rating`` polarity signal. Keyless — no auth.
    """

    source_id = "wordpress"

    def __init__(
        self,
        *,
        api_url: str | None = None,
        support_base: str | None = None,
        author_salt: str = "metalworks-local",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_reviews: int = DEFAULT_MAX_REVIEWS,
        client: Any | None = None,
    ) -> None:
        self._api_url = (api_url or DEFAULT_API_URL).rstrip("/") + "/"
        self._support_base = (support_base or DEFAULT_SUPPORT_BASE).rstrip("/")
        self._salt = author_salt
        self._timeout_s = timeout_s
        self._page_size = max(1, min(page_size, 250))
        self._max_reviews = max(1, max_reviews)
        self._client = client

    # ── HTTP plumbing (lazy httpx) ────────────────────────────────────────────

    def _client_or_temp(self) -> tuple[Any, bool]:
        """The injected client (kept open) or a fresh one (caller must close)."""
        if self._client is not None:
            return self._client, False
        import httpx

        client = httpx.Client(
            timeout=self._timeout_s,
            headers={"User-Agent": "metalworks-research/0.1 (+https://github.com)"},
            follow_redirects=True,
        )
        return client, True

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """One GET → parsed JSON dict. httpx is imported lazily."""
        client, temp = self._client_or_temp()
        try:
            resp = client.get(url, params=params)
        finally:
            if temp:
                client.close()
        resp.raise_for_status()
        payload: Any = resp.json()
        return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}

    def _get_text(self, url: str) -> str:
        """One GET → response text (the reviews RSS feed). httpx imported lazily."""
        client, temp = self._client_or_temp()
        try:
            resp = client.get(url)
        finally:
            if temp:
                client.close()
        resp.raise_for_status()
        return str(resp.text)

    # ── pull (plugins → CorpusRecord) ─────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate plugin records for ``query``.

        Pages ``query_plugins`` until the API reports no more plugins (or ``limit``
        is hit). WordPress.org ranks the search by relevance/popularity and is not
        date-windowed at the search layer, so ``window`` is not applied here (it is
        applied to reviews in :meth:`comments_for`); ``window.months`` is ignored.
        """
        _ = window
        seen: set[str] = set()
        emitted = 0
        page = 1
        while True:
            params: dict[str, Any] = {
                "action": "query_plugins",
                "request[search]": query,
                "request[page]": page,
                "request[per_page]": self._page_size,
            }
            payload = self._get_json(self._api_url, params)
            raw_plugins: Any = payload.get("plugins")
            plugins: list[Any] = (
                cast("list[Any]", raw_plugins) if isinstance(raw_plugins, list) else []
            )
            if not plugins:
                return
            for plugin in plugins:
                if not isinstance(plugin, dict):
                    continue
                record = self._record_from_plugin(cast("dict[str, Any]", plugin))
                if record is None or record.id in seen:
                    continue
                seen.add(record.id)
                yield record
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            info: Any = payload.get("info")
            pages = cast("dict[str, Any]", info).get("pages") if isinstance(info, dict) else None
            if not isinstance(pages, int) or page >= pages:
                return
            page += 1

    def _record_from_plugin(self, plugin: dict[str, Any]) -> CorpusRecord | None:
        """Map one plugin onto the source-neutral spine.

        Title = plugin name, text = short description, url = the plugin page. The
        ``installs`` magnitude is emitted only when ``active_installs`` is a positive
        number — a plugin with no install count OMITS the signal (never ``0.0``).
        """
        slug = str(plugin.get("slug") or "").strip()
        if not slug:
            return None  # slug is the identity AND the reviews-feed key; no slug → drop.
        name = html.unescape(str(plugin.get("name") or "").strip())
        url = f"https://wordpress.org/plugins/{slug}/"
        installs = plugin.get("active_installs")
        signals: dict[str, float] = {}
        if isinstance(installs, (int, float)) and not isinstance(installs, bool) and installs > 0:
            signals["installs"] = float(installs)
        rating = plugin.get("rating")
        num_ratings = plugin.get("num_ratings")
        return CorpusRecord(
            id=f"wordpress_{slug}",
            source="wordpress",
            source_id=slug,
            url=url,
            title=name,
            text=_clean_html(str(plugin.get("short_description") or "")),
            # The plugin record itself has no individual author (it is the marketplace
            # listing); reviewers are the authors, recovered as comments.
            author_hash=None,
            engagement=int(num_ratings) if isinstance(num_ratings, (int, float)) else 0,
            signals=signals,
            created_at=None,
            extra={
                "slug": slug,
                "active_installs": int(installs) if isinstance(installs, (int, float)) else 0,
                "rating": int(rating) if isinstance(rating, (int, float)) else 0,
                "num_ratings": int(num_ratings) if isinstance(num_ratings, (int, float)) else 0,
                "author": html.unescape(str(plugin.get("author") or "")),
            },
        )

    # ── comments (reviews → CorpusComment) ────────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one review batch per plugin record id, in input order.

        WordPress.org plugins always have a reviews layer, so this never returns
        ``None`` (an empty list for a plugin with no reviews is correct, not
        "comment-less"). Each record id is ``wordpress_<slug>``; we fetch that
        plugin's public reviews feed and map each review to a :class:`CorpusComment`.
        """
        return self._iter_reviews(record_ids)

    def _iter_reviews(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        for rid in record_ids:
            slug = rid[len("wordpress_") :] if rid.startswith("wordpress_") else rid
            yield self._reviews_for_slug(slug, parent_id=rid)

    def _reviews_for_slug(self, slug: str, *, parent_id: str) -> list[CorpusComment]:
        if not slug:
            return []
        url = f"{self._support_base}/{quote(slug)}/reviews/feed/"
        try:
            body = self._get_text(url)
        except Exception:
            # A per-plugin feed failure must not abort the batch; that plugin simply
            # yields no reviews (like HN's per-story guard / SE's per-chunk guard).
            return []
        return self._parse_reviews(body, parent_id=parent_id)

    def _parse_reviews(self, body: str, *, parent_id: str) -> list[CorpusComment]:
        """Parse a reviews RSS feed into per-review :class:`CorpusComment`s."""
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return []
        out: list[CorpusComment] = []
        for item in root.iter("item"):
            comment = self._comment_from_item(item, parent_id=parent_id)
            if comment is None:
                continue
            out.append(comment)
            if len(out) >= self._max_reviews:
                break
        return out

    def _comment_from_item(self, item: ET.Element, *, parent_id: str) -> CorpusComment | None:
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        permalink = link or guid
        if not permalink:
            return None  # no permalink → not a citable quote; drop it.
        description = item.findtext("description") or ""
        title = html.unescape((item.findtext("title") or "").strip())
        stars = self._rating_from(description, title)
        text = _clean_html(description)
        if not text:
            return None  # empty/deleted review body → drop, not a tombstone.
        creator = item.findtext(f"{{{_DC_NS}}}creator")
        signals: dict[str, float] = {}
        if stars is not None:
            signals["rating"] = float(stars)
        return CorpusComment(
            id=permalink,
            parent_id=parent_id,
            source="wordpress",
            url=permalink,
            text=text,
            author_hash=_hash_author(creator, salt=self._salt),
            engagement=0,  # a review carries no native engagement; never fabricate one.
            signals=signals,
            created_at=_parse_rss_date(item.findtext("pubDate")),
            extra={
                "title": title,
                "stars": stars if stars is not None else 0,
            },
        )

    def _rating_from(self, description: str, title: str) -> int | None:
        """Extract the star rating (1-5) from the review body or title.

        bbPress writes ``Rating: N stars`` into the body and ``(N stars)`` into the
        title; we read the body first, then fall back to the title. Returns ``None``
        when neither carries a parseable rating (then no ``rating`` signal is emitted).
        """
        for source in (description, title):
            match = _RATING_RE.search(source or "")
            if match:
                value = int(match.group(1))
                if 1 <= value <= 5:
                    return value
        return None

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """WordPress.org serves live data; the latest window ends now (open start).

        ``months`` is empty — the directory is not month-partitioned.
        """
        return SourceWindow(end=datetime.now(tz=UTC))


def _factory(**kwargs: Any) -> WordPressSource:
    return WordPressSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors stackexchange.py).
# Keyless + open — both the query_plugins API and the reviews feed are public, so
# auth stays "none" / access "open". Signals: installs (magnitude, on the plugin
# record) + rating (polarity, per review), both already registered in
# synthesis.signals — no register_signal needed here. ``targeting="keyword"`` (the
# brief's terms drive the plugin search), picked by the ``keyword`` target picker.
register_source(
    "wordpress",
    _factory,
    spec=SourceSpec(
        source_id="wordpress",
        lane="grounding",
        signals=("rating", "installs"),
        targeting="keyword",
        auth="none",
        env=(),
        access="open",
        relevance_hint=(
            "WordPress site admins, agencies & freelancers reviewing plugins in the "
            "open WordPress.org directory — the SMB long-tail (verbatim reviews + "
            "an active-install deployment count)"
        ),
    ),
)


__all__ = ["WordPressSource"]
