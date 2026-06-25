"""WordPressSource tests — OFFLINE (pytest-socket blocks real network).

We feed canned WordPress.org plugin-directory JSON + a reviews RSS feed through a
stub httpx client (no network) and assert the CorpusRecord / CorpusComment mapping:
plugin search → record (with the ``installs`` magnitude), reviews feed → quotes
(verbatim text + per-review permalink + pseudonymized author, with the ``rating``
polarity signal). We also run the public ``check_item_source`` conformance check,
prove ``get_source("wordpress")`` resolves through the registry, and that the
synthesis ranker reflects ``installs``.

A real-network smoke test is gated behind ``@pytest.mark.network`` (deselected by
default; run with ``-m network --enable-socket``).
"""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceWindow, get_source
from metalworks.research.sources.wordpress import WordPressSource, _clean_html
from metalworks.research.synthesis.signals import (
    SIGNAL_SPECS,
    aggregate_signals,
    score_signals,
)
from metalworks.testing import check_item_source

# ── Canned WordPress.org payloads ─────────────────────────────────────────────

_SEARCH_PAGE: dict[str, Any] = {
    "info": {"page": 1, "pages": 1, "results": 2},
    "plugins": [
        {
            "slug": "focus-flow",
            "name": "Focus Flow &amp; Friends",
            "short_description": "<p>A focus aid for site admins &amp; agencies.</p>",
            "active_installs": 50000,
            "rating": 92,
            "num_ratings": 120,
            "author": "Ada Lovelace",
        },
        {
            # No active_installs → installs signal OMITTED (never 0.0).
            "slug": "quiet-cache",
            "name": "Quiet Cache",
            "short_description": "Caching, but calm.",
            "active_installs": 0,
            "rating": 80,
            "num_ratings": 4,
            "author": "Grace",
        },
        # Missing slug → must be skipped (slug is identity + reviews-feed key).
        {"slug": "", "name": "ghost", "active_installs": 10},
    ],
}

_REVIEWS_FOCUS_FLOW = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>Reviews</title>
<item>
<guid>https://wordpress.org/support/topic/best-focus-aid-1/</guid>
<title><![CDATA[Best focus aid (5 stars)]]></title>
<link>https://wordpress.org/support/topic/best-focus-aid-1/</link>
<pubDate>Tue, 23 Jun 2026 03:56:12 +0000</pubDate>
<dc:creator>Senri Miura</dc:creator>
<description><![CDATA[
<p>Replies: 1</p>
<p>Rating: 5 stars</p>
<p>L-theanine works for me, no crash. Try <a href="x">this</a>.</p>
]]></description>
</item>
<item>
<guid>https://wordpress.org/support/topic/meh-2/</guid>
<title><![CDATA[Meh]]></title>
<link>https://wordpress.org/support/topic/meh-2/</link>
<pubDate>Wed, 24 Jun 2026 10:00:00 +0000</pubDate>
<dc:creator></dc:creator>
<description><![CDATA[<p>Rating: 2 stars</p><p>Crashed my admin once.</p>]]></description>
</item>
<item>
<!-- empty body → dropped, not a tombstone -->
<guid>https://wordpress.org/support/topic/blank-3/</guid>
<link>https://wordpress.org/support/topic/blank-3/</link>
<pubDate>Wed, 24 Jun 2026 11:00:00 +0000</pubDate>
<dc:creator>ghost</dc:creator>
<description><![CDATA[<p>Rating: 1 stars</p>]]></description>
</item>
</channel>
</rss>
"""

_REVIEWS_QUIET_CACHE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel></channel>
</rss>
"""


class _StubResponse:
    def __init__(self, payload: dict[str, Any] | None = None, *, text: str = "") -> None:
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _StubClient:
    """A minimal httpx.Client stand-in: routes by URL, records calls. No network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        self.calls.append((url, params))
        if "/plugins/info/" in url:
            return _StubResponse(_SEARCH_PAGE)
        if "/focus-flow/reviews/feed/" in url:
            return _StubResponse(text=_REVIEWS_FOCUS_FLOW)
        if "/quiet-cache/reviews/feed/" in url:
            return _StubResponse(text=_REVIEWS_QUIET_CACHE)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


def _source() -> WordPressSource:
    return WordPressSource(client=_StubClient(), author_salt="t")


# ── Mapping tests ────────────────────────────────────────────────────────────


def test_clean_html_strips_tags_meta_and_unescapes() -> None:
    assert _clean_html("<p>a</p><p>b &amp; c</p>") == "a\nb & c"
    assert _clean_html("<p>Rating: 5 stars</p><p>good</p>") == "good"
    assert _clean_html(None) == ""


def test_pull_maps_plugins_to_records() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))

    # The empty-slug hit is skipped.
    assert [r.id for r in records] == ["wordpress_focus-flow", "wordpress_quiet-cache"]

    r0 = records[0]
    assert isinstance(r0, CorpusRecord)
    assert r0.source == "wordpress"
    assert r0.source_id == "focus-flow"
    assert r0.url == "https://wordpress.org/plugins/focus-flow/"
    assert r0.title == "Focus Flow & Friends"  # entity decoded
    assert r0.text == "A focus aid for site admins & agencies."
    assert r0.author_hash is None  # the plugin listing has no individual author
    # installs (magnitude) emitted on the plugin record.
    assert r0.signals == {"installs": 50000.0}
    assert r0.extra["active_installs"] == 50000

    # No active_installs → installs OMITTED (never 0.0).
    r1 = records[1]
    assert r1.signals == {}
    assert "installs" not in r1.signals


def test_pull_honors_limit() -> None:
    records = list(_source().pull(query="focus", window=SourceWindow(), limit=1))
    assert [r.id for r in records] == ["wordpress_focus-flow"]


def test_pull_builds_search_params() -> None:
    client = _StubClient()
    src = WordPressSource(client=client, author_salt="t")
    list(src.pull(query="focus aid", window=SourceWindow(), limit=1))
    _, params = client.calls[0]
    assert params is not None
    assert params["action"] == "query_plugins"
    assert params["request[search]"] == "focus aid"
    assert params["request[page]"] == 1


def test_comments_for_maps_reviews_with_rating_and_drops_empty() -> None:
    src = _source()
    batches = src.comments_for(["wordpress_focus-flow", "wordpress_quiet-cache"])
    assert batches is not None
    out = list(batches)
    assert len(out) == 2

    first = out[0]
    # The blank-body review is dropped; two real reviews remain.
    assert [c.id for c in first] == [
        "https://wordpress.org/support/topic/best-focus-aid-1/",
        "https://wordpress.org/support/topic/meh-2/",
    ]
    c0 = first[0]
    assert isinstance(c0, CorpusComment)
    assert c0.source == "wordpress"
    assert c0.parent_id == "wordpress_focus-flow"
    assert c0.url == "https://wordpress.org/support/topic/best-focus-aid-1/"
    assert c0.text == "L-theanine works for me, no crash. Try this."
    # rating (polarity) emitted per review.
    assert c0.signals == {"rating": 5.0}
    assert c0.extra["stars"] == 5
    assert c0.author_hash and c0.author_hash.startswith("u_")

    # Blank reviewer handle → empty author (collapsed here, no WP marker downstream).
    c1 = first[1]
    assert c1.signals == {"rating": 2.0}
    assert c1.author_hash == ""

    # Quiet Cache has no reviews → empty batch (not None).
    assert out[1] == []


def test_comments_batch_input_order_preserved() -> None:
    src = _source()
    batches = src.comments_for(["wordpress_quiet-cache", "wordpress_focus-flow"])
    assert batches is not None
    out = list(batches)
    assert out[0] == []  # quiet-cache first now
    assert [c.id for c in out[1]] == [
        "https://wordpress.org/support/topic/best-focus-aid-1/",
        "https://wordpress.org/support/topic/meh-2/",
    ]


def test_latest_window_returns_source_window() -> None:
    win = _source().latest_window()
    assert isinstance(win, SourceWindow)
    assert win.end is not None


# ── Signals: installs magnitude reflected in ranking ──────────────────────────


def test_installs_magnitude_lifts_ranking_score() -> None:
    """A cluster carrying high ``active_installs`` scores above a low-install one."""
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    high_install = records[0]  # 50k installs
    low_install = high_install.model_copy(update={"signals": {"installs": 10.0}})

    high = score_signals(aggregate_signals([high_install]))
    low = score_signals(aggregate_signals([low_install]))
    assert high > low, "installs (magnitude) must lift the ranking score"
    assert SIGNAL_SPECS["installs"].is_magnitude
    # rating is polarity, NOT magnitude (carried, not band-affecting).
    assert not SIGNAL_SPECS["rating"].is_magnitude


# ── Conformance + registry ───────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    check_item_source(_source(), query="focus", window=SourceWindow(), limit=None)


def test_get_source_resolves_wordpress() -> None:
    src = get_source("wordpress", client=_StubClient())
    assert isinstance(src, WordPressSource)
    assert src.source_id == "wordpress"


# ── Real-network smoke (deselected by default) ───────────────────────────────


@pytest.mark.network
def test_real_wordpress_smoke() -> None:
    src = WordPressSource()
    records = list(src.pull(query="seo", window=SourceWindow(), limit=3))
    assert records
    assert all(r.source == "wordpress" and r.id for r in records)
    assert any(r.signals.get("installs", 0) > 0 for r in records)
    batches = src.comments_for([records[0].id])
    assert batches is not None
    first = next(iter(batches), [])
    # The top SEO plugin reliably has reviews with a parsed rating.
    assert any(c.signals.get("rating", 0) > 0 for c in first)
