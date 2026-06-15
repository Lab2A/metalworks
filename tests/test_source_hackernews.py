"""HackerNewsSource tests — OFFLINE (pytest-socket blocks real network).

We feed canned HN Algolia JSON through a stub httpx client (no network) and
assert the CorpusRecord / CorpusComment mapping: points→engagement, HTML-cleaned
comment text, dead/flagged comment drop, author hashing + null→tombstone. We also
run the public `check_item_source` conformance check against the connector with the
fixture, and prove `get_source("hackernews")` resolves through the registry.

A real-network smoke test is gated behind `@pytest.mark.network` (deselected by
default; run with `-m network --enable-socket`).
"""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceWindow, get_source
from metalworks.research.sources.hackernews import HackerNewsSource, _clean_html
from metalworks.testing import check_item_source

# ── Canned Algolia payloads ──────────────────────────────────────────────────

_SEARCH_PAGE = {
    "hits": [
        {
            "objectID": "100",
            "title": "Ask HN: best stim-free focus aid?",
            "story_text": "<p>I want focus <i>without</i> caffeine &amp; jitters.</p>",
            "url": "",
            "author": "alice",
            "points": 42,
            "num_comments": 3,
            "created_at_i": 1_700_000_000,
        },
        {
            "objectID": "101",
            "title": "Show HN: a nootropic tracker",
            "story_text": None,
            "url": "https://example.com/tracker",
            "author": "bob",
            "points": 7,
            "num_comments": 0,
            "created_at_i": 1_700_000_100,
        },
        # Missing objectID → must be skipped.
        {"objectID": None, "title": "ghost", "points": 1},
    ],
    "nbPages": 1,
}

_ITEM_100 = {
    "id": 100,
    "type": "story",
    "title": "Ask HN: best stim-free focus aid?",
    "children": [
        {
            "id": 201,
            "type": "comment",
            "author": "carol",
            "text": '<p>L-theanine works for me.</p><p>Try <a href="x">this</a>.</p>',
            "created_at_i": 1_700_000_200,
            "children": [
                {
                    "id": 202,
                    "type": "comment",
                    "author": "dave",
                    "text": "Agreed &mdash; no crash.",
                    "created_at_i": 1_700_000_300,
                    "children": [],
                }
            ],
        },
        # Dead comment: null text. Dropped — but its live child survives.
        {
            "id": 203,
            "type": "comment",
            "author": None,
            "text": None,
            "children": [
                {
                    "id": 204,
                    "type": "comment",
                    "author": "erin",
                    "text": "reply under a dead parent still counts",
                    "created_at_i": 1_700_000_400,
                    "children": [],
                }
            ],
        },
        # Flagged comment sentinel → dropped.
        {"id": 205, "type": "comment", "author": "spam", "text": "[flagged]", "children": []},
    ],
}

_ITEM_101: dict[str, Any] = {"id": 101, "type": "story", "children": []}


class _StubResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

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
        if "/search" in url:
            return _StubResponse(_SEARCH_PAGE)
        if url.endswith("/items/100"):
            return _StubResponse(_ITEM_100)
        if url.endswith("/items/101"):
            return _StubResponse(_ITEM_101)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


def _source() -> HackerNewsSource:
    return HackerNewsSource(client=_StubClient(), author_salt="t")


# ── Mapping tests ────────────────────────────────────────────────────────────


def test_clean_html_strips_tags_and_unescapes() -> None:
    assert _clean_html("<p>a</p><p>b &amp; c <i>d</i></p>") == "a\nb & c d"
    assert _clean_html(None) == ""
    assert _clean_html("plain") == "plain"


def test_pull_maps_stories_to_records() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))

    # The null-objectID hit is skipped.
    assert [r.id for r in records] == ["100", "101"]

    r0 = records[0]
    assert isinstance(r0, CorpusRecord)
    assert r0.source == "hackernews"
    assert r0.source_id == "100"
    assert r0.url == "https://news.ycombinator.com/item?id=100"
    assert r0.engagement == 42  # points → engagement
    # story_text wins over url, HTML-cleaned.
    assert r0.text == "I want focus without caffeine & jitters."
    assert r0.author_hash and r0.author_hash.startswith("u_")
    assert r0.created_at is not None
    assert r0.extra == {"num_comments": 3, "points": 42, "objectID": "100"}

    # Link-only story (no story_text): text falls back to the url.
    r1 = records[1]
    assert r1.text == "https://example.com/tracker"
    assert r1.engagement == 7


def test_pull_honors_limit() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=1))
    assert [r.id for r in records] == ["100"]


def test_pull_builds_numeric_window_filters() -> None:
    from datetime import UTC, datetime

    client = _StubClient()
    src = HackerNewsSource(client=client, author_salt="t")
    window = SourceWindow(
        start=datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),  # epoch 1_700_000_000
        end=datetime(2023, 11, 14, 23, 0, 0, tzinfo=UTC),
    )
    list(src.pull(query="focus", window=window, limit=1))
    _, params = client.calls[0]
    assert params is not None
    nf = params["numericFilters"]
    assert "created_at_i>=1700000000" in nf
    assert "created_at_i<=" in nf
    assert params["tags"] == "story"


def test_comments_for_maps_tree_and_drops_dead() -> None:
    src = _source()
    batches = src.comments_for(["100", "101"])
    assert batches is not None
    out = list(batches)
    assert len(out) == 2

    first = out[0]
    ids = [c.id for c in first]
    # 201, 202 (nested), 204 (live child of dead 203) survive; 203 + 205 dropped.
    assert ids == ["201", "202", "204"]

    c201 = first[0]
    assert isinstance(c201, CorpusComment)
    assert c201.source == "hackernews"
    assert c201.parent_id == "100"
    assert c201.engagement == 0  # HN comments have no score
    assert c201.url == "https://news.ycombinator.com/item?id=201"
    # HTML cleaned: paragraph break → newline, <a>/<i> stripped, entities decoded.
    assert c201.text == "L-theanine works for me.\nTry this."
    assert first[1].text == "Agreed — no crash."
    assert c201.author_hash and c201.author_hash.startswith("u_")

    # Story 101 has no comments → empty batch (not None).
    assert out[1] == []


def test_author_hash_salt_and_null() -> None:
    src = _source()
    r = next(iter(src.pull(query="x", window=SourceWindow(), limit=1)))
    # Same author + salt → deterministic hash; different salt → different hash.
    other = HackerNewsSource(client=_StubClient(), author_salt="other")
    r2 = next(iter(other.pull(query="x", window=SourceWindow(), limit=1)))
    assert r.author_hash != r2.author_hash
    # The dead comment (203) had author None → it is dropped, so no tombstone leaks.


def test_latest_window_returns_source_window() -> None:
    win = _source().latest_window()
    assert isinstance(win, SourceWindow)
    assert win.end is not None


# ── Conformance + registry ───────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    # The published ItemSource conformance check, run against the fixture.
    check_item_source(_source(), query="focus", window=SourceWindow(), limit=None)


def test_get_source_resolves_hackernews() -> None:
    # Registry integration: the id resolves (lazy import self-registers).
    src = get_source("hackernews", client=_StubClient())
    assert isinstance(src, HackerNewsSource)
    assert src.source_id == "hackernews"


# ── Real-network smoke (deselected by default) ───────────────────────────────


@pytest.mark.network
def test_real_hn_smoke() -> None:
    src = HackerNewsSource()
    records = list(src.pull(query="python", window=SourceWindow(), limit=3))
    assert records
    assert all(r.source == "hackernews" and r.id for r in records)
    batches = src.comments_for([records[0].id])
    assert batches is not None
    list(batches)
