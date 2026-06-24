"""Lane-② magnitude provider — Wikipedia pageviews (broad interest-magnitude).

Where :class:`~metalworks.research.sources.magnitude.NpmDownloadsProvider` reads
*dev-demand* volume (package installs), Wikipedia pageviews give a **broad,
domain-neutral interest-magnitude** denominator — how many people look something
up — applicable far beyond software. The source is the keyless Wikimedia REST
pageviews API; the ``pageviews`` signal kind is already registered
``is_magnitude=True`` in :mod:`metalworks.research.synthesis.signals`.

The whole shape mirrors the npm reference provider: a number for an entity,
attached AFTER clustering, that can never create a cluster. Each entity is treated
directly as an English-Wikipedia article title (spaces → underscores,
URL-encoded); the run's monthly views over the window are summed. An entity with
no article (404) is OMITTED — omission is unknown, NEVER ``0.0``. Title
disambiguation / fuzzy search is deliberately out of scope (keeps it
deterministic). Wikimedia REQUIRES a descriptive ``User-Agent`` header, which the
owned client sets.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from metalworks.research.sources.magnitude import (
    MagnitudeSpec,
    register_magnitude,
)

if TYPE_CHECKING:
    from metalworks.research.sources import SourceWindow

# The keyless Wikimedia REST pageviews "per-article" endpoint. Path shape:
#   <base>/per-article/en.wikipedia/all-access/user/<title>/monthly/<start>/<end>
# where <start>/<end> are YYYYMMDD(HH) tokens. ``user`` access excludes bots/spiders
# (the closest analogue to "people who care"); ``all-access`` spans desktop+mobile.
_WIKI_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
_WIKI_PROJECT = "en.wikipedia"
_WIKI_ACCESS = "all-access"
_WIKI_AGENT = "user"
_WIKI_GRANULARITY = "monthly"
_WIKI_TIMEOUT_S = 30.0
# Wikimedia requires a descriptive User-Agent identifying the caller (bare clients
# are rate-limited / blocked). Mirrors the npm provider's UA shape.
_WIKI_UA = "metalworks-research/0.1 (+https://github.com/Lab2A/metalworks)"
# Pageviews data begins July 2015; with no window we sweep a wide-but-bounded span
# so the popularity proxy still resolves (clamped at the tail Wikimedia accepts).
_WIKI_DEFAULT_START = "20150701"


def _wiki_window_tokens(window: SourceWindow | None) -> tuple[str, str]:
    """Translate a :class:`SourceWindow` into Wikimedia's ``YYYYMMDD`` start/end.

    The endpoint accepts ``YYYYMMDD`` (or ``YYYYMMDDHH``) tokens. We map the run's
    window to its absolute span when it carries datetimes (so the measurement tracks
    the brief's window), else fall back to a wide default span so the broad
    popularity proxy still resolves. The end is clamped to "now" so a future-dated
    window never asks for views that don't exist yet.
    """
    now = datetime.now(UTC)
    start_token = _WIKI_DEFAULT_START
    if window is not None and window.start is not None:
        start_token = window.start.strftime("%Y%m%d")
    end_token = now.strftime("%Y%m%d")
    if window is not None and window.end is not None:
        # Compare in the window end's own tz-awareness, then clamp to "now" so a
        # future-dated window never asks for views that don't exist yet.
        ref = now if window.end.tzinfo is not None else now.replace(tzinfo=None)
        end_token = min(window.end, ref).strftime("%Y%m%d")
    return start_token, end_token


@dataclass
class WikipediaPageviewsProvider:
    """Magnitude over the public, keyless Wikimedia REST pageviews API.

    Maps each entity (an English-Wikipedia article title) to its TOTAL pageviews
    over the run's window via the ``per-article`` monthly endpoint, summing the
    window's monthly buckets → ``{entity: {"pageviews": <total>}}``. The entity
    string is used directly as the article title (spaces → underscores,
    URL-encoded). An entity with no article (404) is OMITTED — omission is unknown,
    never ``0.0``.

    The HTTP client is injectable (``client=``) so the offline conformance fixture
    drives it without a live network; the real network path is exercised only by a
    ``network``-marked test. The owned client sets the descriptive ``User-Agent``
    Wikimedia requires.
    """

    provider_id: str = "wikipedia"
    signals: tuple[str, ...] = ("pageviews",)
    timeout_s: float = _WIKI_TIMEOUT_S
    client: Any | None = None

    def measure(
        self, *, entities: Sequence[str], window: SourceWindow | None = None
    ) -> dict[str, dict[str, float]]:
        start, end = _wiki_window_tokens(window)
        out: dict[str, dict[str, float]] = {}
        seen: set[str] = set()
        for entity in entities:
            title = entity.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            total = self._fetch_pageviews(title, start, end)
            if total is not None:  # omission = unknown; never store 0.0 for a miss
                out[entity] = {"pageviews": float(total)}
        return out

    def _fetch_pageviews(self, title: str, start: str, end: str) -> int | None:
        """One GET → the article's summed pageviews over the window, or ``None``.

        A 404 (Wikimedia has no such article / no data for the range) returns
        ``None`` — the entity is omitted, not zeroed. An empty ``items`` list also
        maps to ``None`` (no data is unknown, not 0). Any other HTTP error raises,
        so a transport failure propagates to the best-effort caller as a degraded
        stage.
        """
        import httpx

        # Spaces → underscores, then percent-encode the whole title (Wikimedia's own
        # convention). ``safe=""`` so slashes / ampersands in a title are escaped too.
        article = quote(title.replace(" ", "_"), safe="")
        url = (
            f"{_WIKI_API}/{_WIKI_PROJECT}/{_WIKI_ACCESS}/{_WIKI_AGENT}/"
            f"{article}/{_WIKI_GRANULARITY}/{start}/{end}"
        )
        client = self.client
        owns = client is None
        if owns:
            client = httpx.Client(
                timeout=self.timeout_s,
                headers={"User-Agent": _WIKI_UA},
            )
        try:
            resp = client.get(url)
        finally:
            if owns:
                client.close()
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        payload: Any = resp.json()
        if not isinstance(payload, dict):
            return None
        items = cast("dict[str, Any]", payload).get("items")
        if not isinstance(items, list) or not items:
            return None  # no monthly buckets → unknown, never 0.0
        total = 0
        for item in cast("list[Any]", items):
            if not isinstance(item, dict):
                continue
            views = cast("dict[str, Any]", item).get("views")
            if isinstance(views, bool) or not isinstance(views, (int, float)):
                continue
            total += int(views)
        return total


def _wikipedia_factory(**kwargs: Any) -> WikipediaPageviewsProvider:
    return WikipediaPageviewsProvider(**kwargs)


# Self-register on import (append-friendly registry; mirrors the npm provider).
# The Wikimedia pageviews API is open + keyless; "pageviews" is its registered
# magnitude kind (already is_magnitude=True in synthesis.signals).
register_magnitude(
    "wikipedia",
    _wikipedia_factory,
    spec=MagnitudeSpec(
        provider_id="wikipedia",
        signals=("pageviews",),
        targeting="keyword",
        auth="none",
        env=(),
        access="open",
        relevance_hint="broad public interest magnitude for a named topic (Wikipedia pageviews)",
    ),
)


__all__ = [
    "WikipediaPageviewsProvider",
]
