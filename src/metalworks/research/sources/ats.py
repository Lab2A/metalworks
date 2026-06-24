"""``ATSItemSource`` — a keyless :class:`ItemSource` over public ATS job boards.

Applicant-tracking-system (ATS) boards are a B2B **pain & spend proxy** nothing
else in the corpus reaches: a company hiring for a tool/skill states the explicit
need *in the job description*, and the count of matching postings is itself a
demand magnitude. Three vendors host the public boards most companies use, each
behind a **keyless** JSON endpoint parameterized only by a company ``slug``:

* **Greenhouse** — ``https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true``
  (``{"jobs": [{title, absolute_url, content, location, …}]}``; ``content`` is
  HTML-escaped HTML).
* **Lever** — ``https://api.lever.co/v0/postings/<slug>?mode=json``
  (a top-level list of ``{text, hostedUrl, descriptionPlain, categories, …}``).
* **Ashby** — ``https://api.ashbyhq.com/posting-api/job-board/<slug>``
  (``{"jobs": [{title, jobUrl, descriptionPlain | descriptionHtml, location, …}]}``).

The job description IS the unit of signal — there is no comment layer — so this is
a ``yields_units`` **grounding** source (see :class:`ItemSource` + :mod:`.web`):
each posting becomes a self-representing :class:`CorpusRecord` and the ranker
measures breadth by **distinct company/domain**, exactly like the web lane, rather
than by a per-record endorsement signal. Accordingly we emit **no** per-record
signal (``signals=()``): a JD has no upvote/view analogue, and the demand
magnitude here is *posting frequency* (a cluster-level count), which is a deferred
overlay — NOT a per-item number. We never fabricate one.

No "list all companies" endpoint — the slug registry is curated DATA
-----------------------------------------------------------------
None of the three vendors expose a "list every company on our platform" route:
you can only fetch a board once you already know its ``slug``. So slug *discovery*
is not something this connector can do generically. We seed a small **curated**
registry (:data:`CURATED_SLUGS`) as DATA and let a brief name companies; full
slug-discovery (crawling, a web-lane lookup) is a deliberately later concern. The
:func:`metalworks.research.planner.source_picker` ``slug`` picker reads this same
registry. Treat the registry as a starting set, not an authority.

``query`` is a free-text term filter: a posting is kept when ANY whitespace token
of ``query`` (case-folded) appears in its title or JD text — the brief's terms
narrow a whole board to the roles that actually state the need. ``window.start`` /
``window.end`` filter by the posting's updated/created time when the vendor
exposes one; ``window.months`` is ignored (boards are not month-partitioned).
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlsplit

from metalworks.contract import CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

Provider = Literal["greenhouse", "lever", "ashby"]

DEFAULT_PROVIDER: Provider = "greenhouse"
DEFAULT_TIMEOUT_S = 30.0
_PROVIDERS: frozenset[str] = frozenset({"greenhouse", "lever", "ashby"})

_BASE_URLS: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards",
    "lever": "https://api.lever.co/v0/postings",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board",
}

# A small curated set of company board slugs per vendor — DATA, not discovery.
# There is no "list all companies" endpoint, so this seeds a starting set a brief
# can name from; expand it as needed. Slugs are the path segment each vendor uses
# (e.g. greenhouse.io/<slug>, jobs.lever.co/<slug>, jobs.ashbyhq.com/<slug>).
CURATED_SLUGS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("stripe", "airbnb", "databricks", "figma", "dropbox"),
    "lever": ("netflix", "spotify", "brex", "ramp"),
    "ashby": ("ashby", "linear", "vercel", "replit"),
}

_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"\s*</?(?:p|br|div|li|ul|ol|h[1-6])\s*/?>\s*", re.IGNORECASE)
_MULTI_NL_RE = re.compile(r"\n{2,}")


def _clean_html(text: str | None) -> str:
    """Turn a vendor's HTML JD body into plain text.

    Greenhouse ``content`` is HTML-entity-escaped HTML; Ashby may return
    ``descriptionHtml``. We unescape entities first, convert block tags to
    newlines, strip every other tag, collapse blank runs. A vendor's plain-text
    field (Lever ``descriptionPlain`` / Ashby ``descriptionPlain``) passes through
    unchanged (no tags to strip).
    """
    if not text:
        return ""
    text = html.unescape(text)
    text = _PARA_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return text.strip()


def _registrable_domain(url: str) -> str:
    """The hostname without a leading ``www.`` — the unit-source breadth axis.

    Mirrors :func:`metalworks.research.sources.web._registrable_domain`: a bare
    host (no public-suffix split, no extra dependency) is precise enough for the
    distinct-company/domain breadth the ranker counts. Empty when there's no host.
    """
    host = urlsplit(url.strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _parse_epoch_ms(value: Any) -> datetime | None:
    """Parse a vendor epoch-millis timestamp (Greenhouse/Lever) to UTC, or ``None``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    return None


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (Greenhouse ``updated_at``) to UTC, or ``None``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _query_terms(query: str) -> list[str]:
    """Case-folded whitespace tokens of ``query`` — the term filter's predicate."""
    return [t for t in query.casefold().split() if t]


def _matches(terms: Sequence[str], *, title: str, text: str) -> bool:
    """A posting matches when ANY query term appears in its title or JD text.

    No terms (empty query) ⇒ keep everything: an un-narrowed pull returns the whole
    board, which the pipeline then triages — the same posture as the other sources'
    candidate pulls.
    """
    if not terms:
        return True
    hay = f"{title}\n{text}".casefold()
    return any(t in hay for t in terms)


class ATSItemSource:
    """:class:`ItemSource` over the public, keyless Greenhouse / Lever / Ashby boards.

    Construct with a ``provider`` (one of ``greenhouse`` / ``lever`` / ``ashby``)
    and a company ``slug`` (a board). ``pull`` fetches that board once, filters its
    postings to the brief's terms, and yields each as a self-representing
    :class:`CorpusRecord` (title = role, text = JD, url = posting permalink,
    company = the "author"). There is no comment layer — :meth:`comments_for`
    returns ``None`` and ``yields_units`` is ``True``.
    """

    source_id = "ats"
    # The JD is the synthesis unit; this source has no comment layer. The pipeline
    # reads this opt-in flag to promote each posting to its own unit and rank the
    # pull by distinct company/domain breadth (see the module docstring + web.py).
    yields_units = True

    def __init__(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        slug: str = "",
        base_url: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: Any | None = None,
    ) -> None:
        prov = (provider or DEFAULT_PROVIDER).strip().lower()
        if prov not in _PROVIDERS:
            raise ValueError(
                f"ATSItemSource: unknown provider {provider!r}; "
                f"expected one of {sorted(_PROVIDERS)}"
            )
        self._provider: Provider = cast("Provider", prov)
        self._slug = (slug or "").strip().strip("/")
        self._base_url = (base_url or _BASE_URLS[self._provider]).rstrip("/")
        self._timeout_s = timeout_s
        self._client = client

    @property
    def provider(self) -> Provider:
        return self._provider

    # ── HTTP plumbing (lazy httpx) ────────────────────────────────────────────

    def _board_url(self) -> str:
        """The single board endpoint for this provider + slug."""
        if self._provider == "greenhouse":
            return f"{self._base_url}/{self._slug}/jobs"
        # Lever and Ashby take the slug as the final path segment.
        return f"{self._base_url}/{self._slug}"

    def _board_params(self) -> dict[str, Any]:
        if self._provider == "greenhouse":
            return {"content": "true"}
        if self._provider == "lever":
            return {"mode": "json"}
        return {}

    def _get(self, url: str, params: dict[str, Any]) -> Any:
        """One GET → parsed JSON (a dict or a list; Lever returns a top-level list).

        httpx is imported lazily (it is core, but a bare ``import metalworks`` must
        not need a client).
        """
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
        return resp.json()

    # ── pull (postings → CorpusRecord) ────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield the board's postings that match ``query``, within ``window``.

        Fetches the board ONCE (these endpoints return the full posting list, not a
        paged search), filters to postings whose title/JD contains any ``query``
        term and whose timestamp (when the vendor exposes one) falls in
        ``[window.start, window.end]``, and maps each to a :class:`CorpusRecord`.
        ``window.months`` is ignored — boards are not month-partitioned. Ids are
        de-duplicated within a pull so an upsert-by-id never doubles a posting.
        """
        if not self._slug:
            return
        terms = _query_terms(query)
        payload = self._get(self._board_url(), self._board_params())
        seen: set[str] = set()
        emitted = 0
        for raw in self._iter_postings(payload):
            record = self._record_from_posting(raw)
            if record is None or record.id in seen:
                continue
            if not _matches(terms, title=record.title, text=record.text):
                continue
            if not self._in_window(record.created_at, window):
                continue
            seen.add(record.id)
            yield record
            emitted += 1
            if limit is not None and emitted >= limit:
                return

    def _iter_postings(self, payload: Any) -> Iterator[dict[str, Any]]:
        """The vendor's posting list — a top-level list (Lever) or under ``jobs``."""
        items: Any
        if isinstance(payload, dict):
            items = cast("dict[str, Any]", payload).get("jobs")
        else:
            items = payload  # Lever returns a top-level list
        if not isinstance(items, list):
            return
        for item in cast("list[Any]", items):
            if isinstance(item, dict):
                yield cast("dict[str, Any]", item)

    def _in_window(self, when: datetime | None, window: SourceWindow) -> bool:
        """Keep a posting with no timestamp; else require it inside the span."""
        if when is None:
            return True
        if window.start is not None and when < window.start:
            return False
        return not (window.end is not None and when > window.end)

    def _record_from_posting(self, item: dict[str, Any]) -> CorpusRecord | None:
        """Map one vendor posting onto the source-neutral spine (per provider)."""
        if self._provider == "greenhouse":
            native_id = item.get("id")
            url = str(item.get("absolute_url") or "")
            title = str(item.get("title") or "")
            text = _clean_html(item.get("content"))
            when = _parse_iso(item.get("updated_at"))
            location = _location_name(item.get("location"))
        elif self._provider == "lever":
            native_id = item.get("id")
            url = str(item.get("hostedUrl") or item.get("applyUrl") or "")
            title = str(item.get("text") or "")
            text = _clean_html(item.get("descriptionPlain") or item.get("description"))
            when = _parse_epoch_ms(item.get("createdAt"))
            location = _lever_location(item.get("categories"))
        else:  # ashby
            native_id = item.get("id")
            url = str(item.get("jobUrl") or item.get("applyUrl") or "")
            title = str(item.get("title") or "")
            text = _clean_html(item.get("descriptionPlain") or item.get("descriptionHtml"))
            when = _parse_iso(item.get("publishedAt") or item.get("updatedAt"))
            location = str(item.get("location") or "")

        if native_id is None or not url:
            return None  # a posting with no id or permalink is not quotable; drop it.
        native_id = str(native_id)
        if not (title or text):
            return None
        record_id = f"ats_{self._provider}_{self._slug}_{native_id}"
        return CorpusRecord(
            id=record_id,
            source="ats",
            source_id=native_id,
            url=url,
            title=title,
            text=text,
            # The company IS the "author" of a posting; we name the board slug as a
            # stable, non-PII author handle (a JD has no individual author).
            author_hash=f"company:{self._slug}" if self._slug else None,
            engagement=0,  # a JD has no native engagement; never fabricate one.
            signals={},  # no per-record signal — breadth-by-company carries demand.
            created_at=when,
            extra={
                "provider": self._provider,
                "company": self._slug,
                # The unit-source breadth axis (distinct company/domain), like web.
                "domain": _registrable_domain(url) or self._slug,
                "location": location,
            },
        )

    # ── comments (ATS postings have none) ─────────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[Any]] | None:
        """ATS postings have no comment layer → return ``None``.

        Per the protocol, ``None`` (not an empty iterator) marks the source as
        comment-less, so the ingest path records the run that way rather than
        treating it as a failure. The JD is the unit (``yields_units``).
        """
        _ = record_ids
        return None

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """Boards serve live postings; the latest window ends now (open start).

        ``months`` is empty — ATS boards window by datetime span only.
        """
        return SourceWindow(end=datetime.now(tz=UTC))


def _location_name(location: Any) -> str:
    """Greenhouse ``location`` is ``{"name": "…"}``; return the name or ``""``."""
    if isinstance(location, dict):
        name = cast("dict[str, Any]", location).get("name")
        return str(name) if name else ""
    return str(location) if location else ""


def _lever_location(categories: Any) -> str:
    """Lever nests the location under ``categories.location``."""
    if isinstance(categories, dict):
        loc = cast("dict[str, Any]", categories).get("location")
        return str(loc) if loc else ""
    return ""


def _factory(**kwargs: Any) -> ATSItemSource:
    return ATSItemSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors web.py). Keyless +
# open across all three vendors (no key raises a quota — auth "none" / access
# "open"). A ``yields_units`` grounding source: it ranks by distinct company/
# domain breadth (like the web lane), so it declares NO per-record signal
# (signals=()) and registers no new signal kind — the postings-count magnitude
# overlay is a deferred, cluster-level concern. ``targeting="slug"`` (a company
# board), picked by the ``slug`` target picker over the curated registry.
register_source(
    "ats",
    _factory,
    spec=SourceSpec(
        source_id="ats",
        lane="grounding",
        signals=(),
        targeting="slug",
        auth="none",
        env=(),
        access="open",
        relevance_hint=(
            "companies hiring for a tool/skill — B2B pain & spend (the JD states the need)"
        ),
    ),
)


__all__ = ["CURATED_SLUGS", "ATSItemSource", "Provider"]
