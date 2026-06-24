"""DiscourseSource tests — OFFLINE (pytest-socket blocks real network).

We feed canned Discourse JSON (``/search.json`` + ``/t/<id>.json``) through a stub
httpx client (no network) and assert the CorpusRecord / CorpusComment mapping:
topic like_count → ``upvotes``, topic ``views`` → ``views`` magnitude signal,
``cooked`` HTML cleaned, the post stream → comments parented to their topic with
per-post permalinks, anonymous post → tombstone author, empty-body post dropped. We
also prove a login-gated host (403) is skipped gracefully (empty pull, no crash),
run the public ``check_item_source`` conformance check, prove ``get_source`` resolves
through the registry, and that the synthesis ranker reflects ``views``.

A real-network smoke test is gated behind ``@pytest.mark.network`` (deselected by
default; run with ``-m network --enable-socket``).
"""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.planner.source_picker import discourse_instances
from metalworks.research.sources import SourceWindow, get_source
from metalworks.research.sources.discourse import DiscourseSource, _clean_html
from metalworks.research.synthesis.signals import (
    SIGNAL_SPECS,
    aggregate_signals,
    score_signals,
)
from metalworks.testing import check_item_source

# ── Canned Discourse payloads ─────────────────────────────────────────────────

_SEARCH: dict[str, Any] = {
    "topics": [
        {
            "id": 800,
            "title": "How to keep a focus daemon from &amp; wrecking RAM?",
            "slug": "focus-daemon-ram",
            "views": 47000,
            "like_count": 42,
            "posts_count": 3,
            "category_id": 5,
            "created_at": "2026-05-15T10:00:00Z",
            "last_poster_username": "alice",
        },
        {
            "id": 801,
            "title": "Anonymous-author topic",
            "slug": "anon-topic",
            "views": 120,
            "like_count": 7,
            "posts_count": 1,
            "created_at": "2026-05-15T10:05:00Z",
            "last_poster_username": "",  # deleted/anon poster → tombstone author
        },
        {"id": None, "title": "ghost"},  # missing id → skipped
    ],
    "posts": [
        {"id": 9001, "topic_id": 800, "blurb": "I want focus <i>without</i> jitters."},
        {"id": 9101, "topic_id": 801, "blurb": "second topic blurb"},
    ],
}

_TOPIC_800: dict[str, Any] = {
    "id": 800,
    "slug": "focus-daemon-ram",
    "post_stream": {
        "posts": [
            {
                "id": 9001,
                "post_number": 1,
                "username": "alice",
                "cooked": "<p>I want focus without jitters.</p><p>Any tips?</p>",
                "like_count": 5,
                "created_at": "2026-05-15T10:00:00Z",
            },
            {
                "id": 9002,
                "post_number": 2,
                "username": "carol",
                "cooked": "<p>L-theanine works for me.</p><p>Try <a href='x'>this</a>.</p>",
                "like_count": 9,
                "created_at": "2026-05-15T11:00:00Z",
            },
            # Deleted/empty post → dropped, not a tombstone.
            {
                "id": 9003,
                "post_number": 3,
                "username": "dave",
                "cooked": "",
                "like_count": 0,
                "created_at": "2026-05-15T12:00:00Z",
            },
        ]
    },
}

_TOPIC_801: dict[str, Any] = {
    "id": 801,
    "slug": "anon-topic",
    "post_stream": {"posts": []},
}


class _StubResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _StubClient:
    """A minimal httpx.Client stand-in: routes by URL, records calls. No network."""

    def __init__(self, *, status_code: int = 200) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._status = status_code

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        self.calls.append((url, params))
        if self._status != 200:
            return _StubResponse({}, status_code=self._status)
        if "/search.json" in url:
            return _StubResponse(_SEARCH)
        if "/t/800.json" in url:
            return _StubResponse(_TOPIC_800)
        if "/t/801.json" in url:
            return _StubResponse(_TOPIC_801)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


def _source(**kwargs: Any) -> DiscourseSource:
    kwargs.setdefault("client", _StubClient())
    kwargs.setdefault("author_salt", "t")
    kwargs.setdefault("instance", "meta.discourse.org")
    return DiscourseSource(**kwargs)


# ── Mapping tests ────────────────────────────────────────────────────────────


def test_clean_html_strips_tags_and_unescapes() -> None:
    assert _clean_html("<p>a</p><p>b &amp; c <i>d</i></p>") == "a\nb & c d"
    assert _clean_html(None) == ""
    assert _clean_html("plain") == "plain"


def test_pull_maps_topics_to_records() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))

    # The null-id topic is skipped.
    assert [r.source_id for r in records] == ["800", "801"]

    r0 = records[0]
    assert isinstance(r0, CorpusRecord)
    assert r0.source == "discourse"
    assert r0.id == "meta.discourse.org:800"  # host-scoped spine id
    assert r0.source_id == "800"
    assert r0.url == "https://meta.discourse.org/t/focus-daemon-ram/800"
    assert r0.title == "How to keep a focus daemon from & wrecking RAM?"  # entity decoded
    assert r0.engagement == 42  # like_count → engagement
    assert r0.text == "I want focus without jitters."  # from the search blurb
    assert r0.author_hash and r0.author_hash.startswith("u_")
    # Signals carry BOTH upvotes (social) and views (magnitude).
    assert r0.signals == {"upvotes": 42.0, "views": 47000.0}
    assert r0.created_at is not None
    assert r0.extra["views"] == 47000
    assert r0.extra["instance"] == "meta.discourse.org"
    assert r0.extra["slug"] == "focus-daemon-ram"

    # Anonymous poster (empty username) → tombstone author (None).
    r1 = records[1]
    assert r1.author_hash is None
    assert r1.signals == {"upvotes": 7.0, "views": 120.0}


def test_pull_honors_limit() -> None:
    records = list(_source().pull(query="focus", window=SourceWindow(), limit=1))
    assert [r.source_id for r in records] == ["800"]


def test_pull_builds_date_window_in_query() -> None:
    from datetime import UTC, datetime

    client = _StubClient()
    src = DiscourseSource(client=client, author_salt="t", instance="community.openai.com")
    window = SourceWindow(
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 5, 31, tzinfo=UTC),
    )
    list(src.pull(query="focus app", window=window, limit=1))
    url, params = client.calls[0]
    assert url == "https://community.openai.com/search.json"
    assert params is not None
    assert params["q"] == "focus app after:2026-05-01 before:2026-05-31"


def test_comments_for_maps_posts_and_drops_empty() -> None:
    src = _source()
    batches = src.comments_for(["meta.discourse.org:800", "meta.discourse.org:801"])
    assert batches is not None
    out = list(batches)
    assert len(out) == 2

    first = out[0]
    # Post 9003 had an empty body → dropped.
    assert [c.id for c in first] == ["meta.discourse.org:9001", "meta.discourse.org:9002"]
    c1 = first[0]
    assert isinstance(c1, CorpusComment)
    assert c1.source == "discourse"
    assert c1.parent_id == "meta.discourse.org:800"
    assert c1.engagement == 5  # like_count → engagement
    assert c1.signals == {"upvotes": 5.0}
    # Per-post permalink: /t/<slug>/<topic>/<post_number>
    assert c1.url == "https://meta.discourse.org/t/focus-daemon-ram/800/1"
    assert c1.text == "I want focus without jitters.\nAny tips?"
    assert c1.author_hash and c1.author_hash.startswith("u_")

    c2 = first[1]
    assert c2.url == "https://meta.discourse.org/t/focus-daemon-ram/800/2"
    assert c2.text == "L-theanine works for me.\nTry this."

    # Topic 801 has no posts → empty batch (not None).
    assert out[1] == []


def test_comments_for_accepts_bare_native_id() -> None:
    # A bare native topic id (not the spine <host>:<id>) must still resolve.
    src = _source()
    batches = src.comments_for(["800"])
    assert batches is not None
    out = list(batches)
    assert [c.parent_id for c in out[0]] == [
        "meta.discourse.org:800",
        "meta.discourse.org:800",
    ]


def test_latest_window_returns_source_window() -> None:
    win = _source().latest_window()
    assert isinstance(win, SourceWindow)
    assert win.end is not None


# ── Gated host (403) skipped gracefully ───────────────────────────────────────


def test_gated_host_pull_is_skipped_not_crashed() -> None:
    """A login-gated host answers 403 → the pull yields nothing, no exception."""
    src = DiscourseSource(client=_StubClient(status_code=403), author_salt="t")
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    assert records == []


def test_gated_host_comments_yield_empty() -> None:
    """A gated topic fetch (403) yields an empty batch per id, not a crash."""
    src = DiscourseSource(client=_StubClient(status_code=403), author_salt="t")
    batches = src.comments_for(["meta.discourse.org:800"])
    assert batches is not None
    assert list(batches) == [[]]


def test_unreachable_host_5xx_skipped() -> None:
    """A transport/5xx-shaped failure also collapses to a graceful skip."""

    class _BoomClient:
        def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
            raise RuntimeError("connection reset")

        def close(self) -> None:
            return None

    src = DiscourseSource(client=_BoomClient(), author_salt="t")
    assert list(src.pull(query="x", window=SourceWindow(), limit=None)) == []


# ── instance normalization ────────────────────────────────────────────────────


def test_full_url_instance_is_normalized_to_host() -> None:
    src = DiscourseSource(client=_StubClient(), instance="https://community.openai.com/")
    records = list(src.pull(query="x", window=SourceWindow(), limit=1))
    assert records[0].extra["instance"] == "community.openai.com"


# ── Signals: views magnitude reflected in ranking ─────────────────────────────


def test_views_magnitude_lifts_ranking_score() -> None:
    """A topic carrying high ``views`` scores above an equal-likes low-view one."""
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    high_view = records[0]  # 42 upvotes / 47k views
    low_view = high_view.model_copy(update={"signals": {"upvotes": 42.0, "views": 10.0}})

    high = score_signals(aggregate_signals([high_view]))
    low = score_signals(aggregate_signals([low_view]))
    assert high > low, "views (magnitude) must lift the ranking score"
    assert SIGNAL_SPECS["views"].is_magnitude
    assert not SIGNAL_SPECS["upvotes"].is_magnitude


# ── instance picker seed ──────────────────────────────────────────────────────


def test_discourse_instances_seed_and_brief_hosts() -> None:
    seeded = discourse_instances()
    assert seeded[0] == "meta.discourse.org"  # non-removable default leads
    assert "community.openai.com" in seeded

    # Brief-named hosts append (normalized), bad free text is rejected.
    extended = discourse_instances(["https://forum.MyApp.com/c/x", "not a host", "www.foo.bar"])
    assert "forum.myapp.com" in extended  # scheme/path stripped, lowercased
    assert "foo.bar" in extended  # www. stripped
    assert "not a host" not in extended
    assert extended[0] == "meta.discourse.org"


# ── Conformance + registry ───────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    check_item_source(_source(), query="focus", window=SourceWindow(), limit=None)


def test_get_source_resolves_discourse() -> None:
    src = get_source("discourse", client=_StubClient())
    assert isinstance(src, DiscourseSource)
    assert src.source_id == "discourse"


# ── Real-network smoke (deselected by default) ───────────────────────────────


@pytest.mark.network
def test_real_discourse_smoke() -> None:
    src = DiscourseSource(instance="meta.discourse.org")
    records = list(src.pull(query="api rate limit", window=SourceWindow(), limit=3))
    assert records
    assert all(r.source == "discourse" and r.source_id for r in records)
    ids = [r.source_id for r in records]
    batches = src.comments_for([r.id for r in records])
    assert batches is not None
    out = list(batches)
    assert any(out), "at least one topic should have quotable posts"
    assert ids  # topic ids resolved
