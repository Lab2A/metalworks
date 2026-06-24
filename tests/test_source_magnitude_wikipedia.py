"""Lane-② Wikipedia pageviews magnitude provider tests (issue #144). OFFLINE.

Where npm gives dev-demand volume, Wikipedia pageviews give a broad,
domain-neutral interest-magnitude denominator. This provider runs AFTER clustering
and attaches a ``pageviews`` number to EXISTING themes — it can never create a
cluster. These tests pin the contract against a canned httpx client (no network):

* ``measure`` sums the window's monthly views per article title → summed pageviews;
* a 404 / no-article title is OMITTED — omission is unknown, NEVER ``0.0``;
* window summation is correct across multiple monthly buckets;
* the entity string is used directly as the article title (spaces → underscores,
  URL-encoded);
* ``check_magnitude_provider`` passes offline; registry resolves; spec is the
  magnitude lane with ``auth="none"``.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest

from metalworks.research.sources import SourceWindow
from metalworks.research.sources.magnitude import (
    MAGNITUDE_PROVIDERS,
    MAGNITUDE_SPECS,
    MagnitudeProvider,
    get_magnitude_provider,
)
from metalworks.research.sources.magnitude_wikipedia import WikipediaPageviewsProvider
from metalworks.testing import check_magnitude_provider

# ── offline httpx stub ────────────────────────────────────────────────────────


class _StubWikiResponse:
    def __init__(self, payload: dict[str, Any] | None, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload or {}


class _StubWikiClient:
    """A minimal httpx.Client stand-in for the Wikimedia per-article endpoint.

    Keyed by the URL-path article token (spaces → underscores, percent-encoded);
    the value is the list of monthly ``views`` buckets. An unknown article 404s.
    """

    def __init__(self, views_by_article: dict[str, list[int]]) -> None:
        self._by_article = views_by_article
        self.queried: list[str] = []

    def get(self, url: str) -> _StubWikiResponse:
        # URL shape: .../user/<article>/monthly/<start>/<end>
        article = url.split("/user/", 1)[1].split("/monthly/", 1)[0]
        self.queried.append(article)
        if article not in self._by_article:
            return _StubWikiResponse(None, status_code=404)
        items = [{"views": v, "timestamp": "2026010100"} for v in self._by_article[article]]
        return _StubWikiResponse({"items": items})


# ── 1. measure → summed pageviews; 404 omitted (not 0) ────────────────────────


def test_measure_sums_pageviews_and_omits_404() -> None:
    client = _StubWikiClient(
        {
            "iPhone": [100, 200, 300],
            "Linux": [50, 50],
            # "Nonexistent_Topic" intentionally absent → 404 → omitted (unknown).
        }
    )
    provider = WikipediaPageviewsProvider(client=client)
    got = provider.measure(
        entities=["iPhone", "Linux", "Nonexistent_Topic"],
        window=SourceWindow(),
    )
    assert got == {
        "iPhone": {"pageviews": 600.0},
        "Linux": {"pageviews": 100.0},
    }
    assert "Nonexistent_Topic" not in got  # 404 → omitted, never 0.0


def test_404_is_omitted_never_zero() -> None:
    client = _StubWikiClient({"Known": [10]})
    provider = WikipediaPageviewsProvider(client=client)
    got = provider.measure(entities=["Known", "Missing"], window=SourceWindow())
    assert got == {"Known": {"pageviews": 10.0}}
    assert "Missing" not in got  # omission = unknown


# ── 2. window summation correct ───────────────────────────────────────────────


def test_window_summation_correct() -> None:
    # Twelve monthly buckets sum to their total; a single article, one entity.
    # Spaces → underscores, then the whole title is percent-encoded (parens → %28/%29).
    client = _StubWikiClient({"React_%28software%29": list(range(1, 13))})  # 1..12 = 78
    provider = WikipediaPageviewsProvider(client=client)
    got = provider.measure(entities=["React (software)"], window=SourceWindow())
    assert got == {"React (software)": {"pageviews": 78.0}}
    # The title's spaces became underscores in the queried path token.
    assert client.queried == ["React_%28software%29"]


def test_empty_items_is_unknown_never_zero() -> None:
    # An article that resolves but returns no monthly buckets is unknown, not 0.0.
    client = _StubWikiClient({"Empty": []})
    provider = WikipediaPageviewsProvider(client=client)
    got = provider.measure(entities=["Empty"], window=SourceWindow())
    assert got == {}  # empty items → omitted (unknown)


def test_title_with_special_chars_is_url_encoded() -> None:
    # A slash in a title is percent-encoded (→ %2F) so the path stays one segment.
    client = _StubWikiClient({"AC%2FDC": [42]})
    provider = WikipediaPageviewsProvider(client=client)
    got = provider.measure(entities=["AC/DC"], window=SourceWindow())
    assert got == {"AC/DC": {"pageviews": 42.0}}
    assert client.queried == ["AC%2FDC"]


# ── 3. check_magnitude_provider passes offline ────────────────────────────────


def test_wikipedia_provider_passes_offline_fixture() -> None:
    client = _StubWikiClient({"Python": [1_000, 2_000], "Rust": [500]})
    provider = WikipediaPageviewsProvider(client=client)
    check_magnitude_provider(
        provider,
        entities=["Python", "Rust", "Made_Up_Article"],
        window=SourceWindow(),
    )


def test_wikipedia_registry_resolves_and_spec_is_magnitude_lane() -> None:
    provider = get_magnitude_provider("wikipedia")
    assert provider.provider_id == "wikipedia"
    assert provider.signals == ("pageviews",)
    assert "wikipedia" in MAGNITUDE_PROVIDERS
    spec = MAGNITUDE_SPECS["wikipedia"]
    assert spec.lane == "magnitude"
    assert spec.signals == ("pageviews",)
    assert spec.auth == "none"


def test_protocol_runtime_checkable() -> None:
    assert isinstance(WikipediaPageviewsProvider(), MagnitudeProvider)


# ── network smoke (deselected by default) ─────────────────────────────────────


@pytest.mark.network
def test_wikipedia_real_network_smoke() -> None:
    """Hit the live Wikimedia pageviews API for a known article (run -m network)."""
    from datetime import datetime

    provider = WikipediaPageviewsProvider()
    window = SourceWindow(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 12, 31, tzinfo=UTC),
    )
    got = provider.measure(entities=["Python (programming language)"], window=window)
    assert "Python (programming language)" in got
    assert got["Python (programming language)"]["pageviews"] > 0
