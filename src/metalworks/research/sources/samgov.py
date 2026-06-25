"""``SamGovItemSource`` — a :class:`ItemSource` over the SAM.gov Opportunities API.

Public procurement is the one B2B layer nothing else in the corpus reaches:
**government buyers post explicit unmet needs with a dollar value and a deadline
attached, named** (the contracting agency/office). A solicitation is therefore a
self-representing demand artifact — a verbatim statement of need, a stable
permalink, an attributable author — which makes cite-or-die a *feature* here, not
a problem. This is the marquee Phase-3 grounding singleton: it validates the
procurement shape (a ``yields_units`` grounding source that ALSO carries a
magnitude signal).

Shape (mirrors :mod:`.ats` and :mod:`.web` — both ``yields_units`` grounding)
-----------------------------------------------------------------------------
One paged JSON endpoint carries the whole connector:

* ``GET https://api.sam.gov/opportunities/v2/search`` — keyword search over a
  posted-date window, paged via ``offset`` / ``limit``. Each notice →
  :class:`CorpusRecord` (title = solicitation title, text = the title/solicitation
  summary, url = the notice ``uiLink`` permalink, "author" = the contracting
  agency/office ``fullParentPathName``).

The solicitation IS the unit of signal — there is no comment layer — so this is a
``yields_units`` **grounding** source: each notice becomes a self-representing
record and the ranker measures breadth by **distinct agency/domain**, exactly like
the ATS and web lanes, rather than by a per-record endorsement signal. Because the
breadth axis carries demand, the rule-5 conformance check EXEMPTS a ``yields_units``
source from the "must declare a non-magnitude signal" rule — so this source's only
declared signal is the magnitude ``rfp_budget`` (the literal willingness-to-pay
denominator), and that is legal here.

``rfp_budget`` — the realized willingness-to-pay magnitude
----------------------------------------------------------
A notice that carries an award attaches ``{"rfp_budget": <award amount>}`` — a
literal dollar value a buyer committed to the stated need. It is registered
``is_magnitude=True`` in :mod:`metalworks.research.synthesis.signals` (NO new
``register_signal`` here) and ranks via the 0.2a magnitude path: log-compressed,
so a high-budget notice sorts above an equal-breadth one without dwarfing the
distinct-agency breadth axis. The value is emitted ONLY when the notice actually
carries one — a notice with no award OMITS the signal entirely (never ``0.0``); we
do not fabricate a denominator.

Auth — a free, registered SAM.gov API key
------------------------------------------
SAM.gov requires a free API key (``SAM_GOV_API_KEY``, registered at sam.gov, on a
90-day rotation): ``auth="key"``, ``access="free_key"``, ``env=("SAM_GOV_API_KEY",)``.
The key is passed when present (explicit ``key=`` arg wins, else the env var); the
selector's access gate skips the source cleanly when the key is unset (the #123
floor handles "no key → fall back"), so an un-keyed run never errors here.

``query`` is the ``title`` keyword search. ``window.start`` / ``window.end`` drive
the required ``postedFrom`` / ``postedTo`` date filter (``MM/dd/yyyy``); SAM.gov is
not month-partitioned, so ``window.months`` is ignored. SAM.gov caps a window at one
year and requires both dates, so an open window defaults to the trailing year.

USAspending award-$ overlay (deferred)
---------------------------------------
TODO(#151 fast-follow): USAspending.gov (keyless, public-domain awards) is the
*realized-demand* magnitude complement — a cluster-level award-$ denominator over
the same procurement shape. It is a ``MagnitudeProvider`` (lane-② overlay), not an
``ItemSource``, so it lands as its own provider module; the grounding SAM.gov
connector here is the deliverable. EU TED is a fast-follow on this same shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from metalworks.contract import CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

DEFAULT_BASE_URL = "https://api.sam.gov/opportunities/v2/search"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_PAGE_SIZE = 100  # SAM.gov caps ``limit`` at 1000; 100 keeps a single page cheap.
# SAM.gov requires both posted-date bounds and caps the span at one year; an open
# window therefore defaults to the trailing year ending at the window's end (or now).
_MAX_WINDOW_DAYS = 365
_DATE_FMT = "%m/%d/%Y"  # SAM.gov's required postedFrom/postedTo format.


def _fmt_date(when: datetime) -> str:
    """Render a datetime as SAM.gov's required ``MM/dd/yyyy`` posted-date bound."""
    return when.strftime(_DATE_FMT)


def _parse_posted(value: Any) -> datetime | None:
    """Parse a notice ``postedDate`` (``YYYY-MM-DD`` or ISO-8601) to UTC, or ``None``."""
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _award_amount(award: Any) -> float | None:
    """The committed dollar value from a notice ``award`` block, or ``None``.

    SAM.gov nests the value under ``award.amount`` (a numeric string in practice,
    e.g. ``"800620"``). We coerce it to ``float`` and return ``None`` when absent,
    unparseable, or non-positive — a missing/zero award must OMIT ``rfp_budget``,
    never emit ``0.0`` (we do not fabricate a willingness-to-pay denominator).
    """
    if not isinstance(award, dict):
        return None
    amount: Any = cast("dict[str, Any]", award).get("amount")
    if amount is None or isinstance(amount, bool):
        return None
    try:
        value = float(str(amount).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _registrable_domain(url: str) -> str:
    """The hostname without a leading ``www.`` — the unit-source breadth axis.

    Mirrors :func:`metalworks.research.sources.ats._registrable_domain`: a bare host
    is precise enough for the distinct-agency/domain breadth the ranker counts on a
    ``yields_units`` source. Empty when there's no host.
    """
    host = urlsplit(url.strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


class SamGovItemSource:
    """:class:`ItemSource` over the SAM.gov Opportunities API v2.

    ``key`` is the free SAM.gov API key (read from ``SAM_GOV_API_KEY`` when not
    passed); it is required by the live API but never by construction — an un-keyed
    source still constructs (the selector's access gate skips it). ``pull`` searches
    opportunities for the brief's terms over the posted-date window and yields each
    notice as a self-representing (``yields_units``) :class:`CorpusRecord` (title +
    solicitation summary + ``uiLink`` permalink + contracting agency as author),
    attaching ``rfp_budget`` when the notice carries an award value. There is no
    comment layer — :meth:`comments_for` returns ``None``.
    """

    source_id = "samgov"
    # The solicitation is the synthesis unit; this source has no comment layer. The
    # pipeline reads this opt-in flag to promote each notice to its own unit and rank
    # the pull by distinct agency/domain breadth (see the module docstring + ats.py).
    yields_units = True

    def __init__(
        self,
        *,
        key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        page_size: int = DEFAULT_PAGE_SIZE,
        client: Any | None = None,
    ) -> None:
        import os

        # Optional key: explicit arg wins, else the env var, else un-keyed (the
        # selector skips it cleanly). No env read at import time — only here.
        self._key = key or os.environ.get("SAM_GOV_API_KEY") or None
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._timeout_s = timeout_s
        self._page_size = max(1, min(page_size, 1000))
        self._client = client

    # ── HTTP plumbing (lazy httpx) ────────────────────────────────────────────

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """One GET → parsed JSON dict. httpx is imported lazily (it is core, but a
        bare ``import metalworks`` must not need to construct a client)."""
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

    def _window_bounds(self, window: SourceWindow) -> tuple[str, str]:
        """Resolve the required ``postedFrom`` / ``postedTo`` bounds for ``window``.

        SAM.gov requires both dates and caps the span at one year. We end at
        ``window.end`` (or now) and start at ``window.start`` if set, else the
        trailing year — and clamp a too-wide start up to the one-year floor so the
        API never rejects the request.
        """
        end = window.end or datetime.now(tz=UTC)
        floor = end - timedelta(days=_MAX_WINDOW_DAYS)
        start = window.start or floor
        if start < floor:
            start = floor
        if start > end:
            start = floor
        return _fmt_date(start), _fmt_date(end)

    # ── pull (notices → CorpusRecord) ─────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield candidate notice records for ``query`` over ``window``.

        Pages ``/opportunities/v2/search`` (the ``title`` keyword search) over the
        resolved ``postedFrom`` / ``postedTo`` bounds until SAM.gov reports no more
        records (or ``limit`` is hit). ``window.months`` is ignored — SAM.gov is not
        month-partitioned. Ids are de-duplicated within a pull so an upsert-by-id
        never doubles a notice.
        """
        posted_from, posted_to = self._window_bounds(window)
        seen: set[str] = set()
        emitted = 0
        offset = 0
        while True:
            params: dict[str, Any] = {
                "postedFrom": posted_from,
                "postedTo": posted_to,
                "limit": self._page_size,
                "offset": offset,
            }
            if query:
                params["title"] = query
            if self._key:
                params["api_key"] = self._key
            payload = self._get(self._base_url, params)
            raw_items: Any = payload.get("opportunitiesData")
            items: list[Any] = cast("list[Any]", raw_items) if isinstance(raw_items, list) else []
            if not items:
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                record = self._record_from_notice(cast("dict[str, Any]", item))
                if record is None or record.id in seen:
                    continue
                seen.add(record.id)
                yield record
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            offset += self._page_size
            total = payload.get("totalRecords")
            if not isinstance(total, int) or offset >= total:
                return

    def _record_from_notice(self, item: dict[str, Any]) -> CorpusRecord | None:
        """Map one SAM.gov notice onto the source-neutral spine.

        Title = solicitation title, url = the ``uiLink`` permalink, "author" = the
        contracting agency/office (``fullParentPathName``). ``description`` is a
        SAM.gov URL (the full text needs an authenticated fetch), so the quotable
        body is the title + solicitation number; the description URL is kept in
        ``extra`` for a downstream deep-fetch. ``rfp_budget`` is attached only when
        the notice carries a positive award value.
        """
        notice_id = item.get("noticeId")
        url = str(item.get("uiLink") or "")
        if notice_id is None or not url:
            return None  # no id or permalink → not quotable; drop it.
        notice_id = str(notice_id)
        title = str(item.get("title") or "").strip()
        agency = str(item.get("fullParentPathName") or "").strip()
        sol_number = str(item.get("solicitationNumber") or "").strip()
        # The description field is a URL, not inline prose; the title (plus the
        # solicitation number) is the verbatim, quotable statement of need.
        text = title if not sol_number else f"{title}\nSolicitation {sol_number}"
        if not (title or text):
            return None
        signals: dict[str, float] = {}
        budget = _award_amount(item.get("award"))
        if budget is not None:
            # Magnitude only — emitted when present, OMITTED (never 0.0) when absent.
            signals["rfp_budget"] = budget
        domain = _registrable_domain(url)
        return CorpusRecord(
            id=f"samgov_{notice_id}",
            source="samgov",
            source_id=notice_id,
            url=url,
            title=title,
            text=text,
            # The contracting agency IS the "author" of a solicitation; we name it as
            # a stable, non-PII author handle (a notice has no individual author).
            author_hash=f"agency:{agency}" if agency else None,
            engagement=0,  # a solicitation has no native engagement; never fabricate one.
            signals=signals,
            created_at=_parse_posted(item.get("postedDate")),
            extra={
                "agency": agency,
                "solicitation_number": sol_number,
                "notice_type": str(item.get("type") or ""),
                # The unit-source breadth axis (distinct agency/domain), like ats/web.
                "domain": domain or "sam.gov",
                # The description is a URL needing an authenticated fetch — kept for a
                # downstream deep-fetch, not inlined as quotable body.
                "description_url": str(item.get("description") or ""),
            },
        )

    # ── comments (solicitations have none) ────────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[Any]] | None:
        """Solicitations have no comment layer → return ``None``.

        Per the protocol, ``None`` (not an empty iterator) marks the source as
        comment-less, so the ingest path records the run that way rather than
        treating it as a failure. The solicitation is the unit (``yields_units``).
        """
        _ = record_ids
        return None

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        """SAM.gov serves live notices; the latest window is the trailing year to now.

        ``months`` is empty — SAM.gov windows by datetime span only, and requires a
        bounded span, so the anchor is the trailing year (not an open start).
        """
        now = datetime.now(tz=UTC)
        return SourceWindow(start=now - timedelta(days=_MAX_WINDOW_DAYS), end=now)


def _factory(**kwargs: Any) -> SamGovItemSource:
    return SamGovItemSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors ats.py / web.py). A
# ``yields_units`` grounding source: it ranks by distinct agency/domain breadth (like
# the ATS and web lanes), which makes it rule-5 exempt — so its ONLY declared signal
# is the magnitude ``rfp_budget`` (already registered is_magnitude in synthesis.signals;
# no register_signal here). Auth is a free, registered key (SAM_GOV_API_KEY): the
# selector skips the source cleanly when it is unset. ``targeting="keyword"`` (the
# brief's terms drive the title search), picked by the ``keyword`` target picker.
register_source(
    "samgov",
    _factory,
    spec=SourceSpec(
        source_id="samgov",
        lane="grounding",
        signals=("rfp_budget",),
        targeting="keyword",
        auth="key",
        env=("SAM_GOV_API_KEY",),
        access="free_key",
        relevance_hint=(
            "U.S. government buyers posting explicit unmet needs with a dollar value "
            "and a deadline — public procurement (the contracting agency states the need)"
        ),
    ),
)


__all__ = ["SamGovItemSource"]
