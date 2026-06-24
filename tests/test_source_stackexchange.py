"""StackExchangeSource tests — OFFLINE (pytest-socket blocks real network).

We feed canned Stack Exchange API 2.3 JSON through a stub httpx client (no network)
and assert the CorpusRecord / CorpusComment mapping: question score → ``votes``,
``view_count`` → ``views`` magnitude signal, HTML-cleaned body, answers → comments
parented to their question, deleted-owner → tombstone author, empty-body answer
drop. We also run the public ``check_item_source`` conformance check, prove
``get_source("stackexchange")`` resolves through the registry, and that the
synthesis ranker reflects ``views``.

A real-network smoke test is gated behind ``@pytest.mark.network`` (deselected by
default; run with ``-m network --enable-socket``).
"""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceWindow, get_source
from metalworks.research.sources.stackexchange import StackExchangeSource, _clean_html
from metalworks.research.synthesis.signals import (
    SIGNAL_SPECS,
    aggregate_signals,
    score_signals,
)
from metalworks.testing import check_item_source

# ── Canned Stack Exchange payloads ────────────────────────────────────────────

_SEARCH_PAGE: dict[str, Any] = {
    "items": [
        {
            "question_id": 100,
            "title": "How to keep a focus daemon from &amp; wrecking RAM?",
            "body": "<p>I want focus <i>without</i> jitters.</p><p>Any tips?</p>",
            "link": "https://stackoverflow.com/q/100",
            "score": 42,
            "view_count": 47000,
            "answer_count": 2,
            "is_answered": False,
            "creation_date": 1_700_000_000,
            "tags": ["performance", "memory"],
            "owner": {"user_id": 5, "display_name": "alice", "link": "https://so/u/5"},
        },
        {
            "question_id": 101,
            "title": "Deleted-owner question",
            "body": "<p>body two</p>",
            "link": "https://stackoverflow.com/q/101",
            "score": 7,
            "view_count": 120,
            "answer_count": 0,
            "is_answered": False,
            "creation_date": 1_700_000_100,
            "owner": {"user_type": "does_not_exist"},  # deleted owner → no user_id
        },
        # Missing question_id → must be skipped.
        {"question_id": None, "title": "ghost", "score": 1},
    ],
    "has_more": False,
}

_ANSWERS_100_101: dict[str, Any] = {
    "items": [
        {
            "answer_id": 201,
            "question_id": 100,
            "body": "<p>L-theanine works for me.</p><p>Try <a href='x'>this</a>.</p>",
            "link": "https://stackoverflow.com/a/201",
            "score": 9,
            "is_accepted": True,
            "creation_date": 1_700_000_200,
            "owner": {"user_id": 6, "display_name": "carol"},
        },
        {
            "answer_id": 202,
            "question_id": 100,
            "body": "Agreed &mdash; no crash.",
            "link": "https://stackoverflow.com/a/202",
            "score": 3,
            "is_accepted": False,
            "creation_date": 1_700_000_300,
            "owner": {"user_id": 7, "display_name": "dave"},
        },
        # Empty-body (deleted) answer → dropped, not a tombstone.
        {
            "answer_id": 203,
            "question_id": 101,
            "body": "",
            "link": "https://stackoverflow.com/a/203",
            "score": 0,
            "creation_date": 1_700_000_400,
            "owner": {"user_id": 8},
        },
    ],
    "has_more": False,
}


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
        if "/search/advanced" in url:
            return _StubResponse(_SEARCH_PAGE)
        if "/answers" in url:
            return _StubResponse(_ANSWERS_100_101)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


def _source() -> StackExchangeSource:
    return StackExchangeSource(client=_StubClient(), author_salt="t")


# ── Mapping tests ────────────────────────────────────────────────────────────


def test_clean_html_strips_tags_and_unescapes() -> None:
    assert _clean_html("<p>a</p><p>b &amp; c <i>d</i></p>") == "a\nb & c d"
    assert _clean_html(None) == ""
    assert _clean_html("plain") == "plain"


def test_pull_maps_questions_to_records() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))

    # The null-question_id hit is skipped.
    assert [r.id for r in records] == ["100", "101"]

    r0 = records[0]
    assert isinstance(r0, CorpusRecord)
    assert r0.source == "stackexchange"
    assert r0.source_id == "100"
    assert r0.url == "https://stackoverflow.com/q/100"
    assert r0.title == "How to keep a focus daemon from & wrecking RAM?"  # entity decoded
    assert r0.engagement == 42  # score → engagement
    assert r0.text == "I want focus without jitters.\nAny tips?"
    assert r0.author_hash and r0.author_hash.startswith("u_")
    # Signals carry BOTH votes (social) and views (magnitude).
    assert r0.signals == {"votes": 42.0, "views": 47000.0}
    assert r0.created_at is not None
    assert r0.extra["view_count"] == 47000
    assert r0.extra["site"] == "stackoverflow"
    assert r0.extra["answer_count"] == 2

    # Deleted owner (no user_id) → tombstone author (None).
    r1 = records[1]
    assert r1.author_hash is None
    assert r1.signals == {"votes": 7.0, "views": 120.0}


def test_pull_honors_limit() -> None:
    records = list(_source().pull(query="focus", window=SourceWindow(), limit=1))
    assert [r.id for r in records] == ["100"]


def test_pull_builds_date_window_and_site_params() -> None:
    from datetime import UTC, datetime

    client = _StubClient()
    src = StackExchangeSource(client=client, author_salt="t", site="serverfault")
    window = SourceWindow(
        start=datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),  # epoch 1_700_000_000
        end=datetime(2023, 11, 14, 23, 0, 0, tzinfo=UTC),
    )
    list(src.pull(query="focus", window=window, limit=1))
    _, params = client.calls[0]
    assert params is not None
    assert params["site"] == "serverfault"
    assert params["fromdate"] == 1_700_000_000
    assert "todate" in params
    assert params["filter"] == "withbody"
    assert params["q"] == "focus"
    # Keyless by default → no key param leaked.
    assert "key" not in params


def test_optional_key_is_passed_when_set() -> None:
    client = _StubClient()
    src = StackExchangeSource(client=client, author_salt="t", key="abc123")
    list(src.pull(query="x", window=SourceWindow(), limit=1))
    _, params = client.calls[0]
    assert params is not None
    assert params["key"] == "abc123"


def test_comments_for_maps_answers_and_drops_empty() -> None:
    src = _source()
    batches = src.comments_for(["100", "101"])
    assert batches is not None
    out = list(batches)
    assert len(out) == 2

    first = out[0]
    assert [c.id for c in first] == ["201", "202"]
    c201 = first[0]
    assert isinstance(c201, CorpusComment)
    assert c201.source == "stackexchange"
    assert c201.parent_id == "100"
    assert c201.engagement == 9  # answer score → engagement
    assert c201.signals == {"votes": 9.0}
    assert c201.url == "https://stackoverflow.com/a/201"
    assert c201.text == "L-theanine works for me.\nTry this."
    assert c201.extra["is_accepted"] is True
    assert c201.author_hash and c201.author_hash.startswith("u_")

    # Question 101's only answer had an empty body → dropped → empty batch (not None).
    assert out[1] == []


def test_comments_batch_input_order_preserved() -> None:
    # Re-ordering the ids must re-order the yielded batches to match input order.
    src = _source()
    batches = src.comments_for(["101", "100"])
    assert batches is not None
    out = list(batches)
    assert out[0] == []  # 101 first now
    assert [c.id for c in out[1]] == ["201", "202"]


def test_latest_window_returns_source_window() -> None:
    win = _source().latest_window()
    assert isinstance(win, SourceWindow)
    assert win.end is not None


# ── Signals: views magnitude reflected in ranking ─────────────────────────────


def test_views_magnitude_lifts_ranking_score() -> None:
    """A cluster carrying high ``view_count`` scores above an equal-votes low-view one."""
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    high_view = records[0]  # 42 votes / 47k views
    # Same votes, but only a handful of views.
    low_view = high_view.model_copy(update={"signals": {"votes": 42.0, "views": 10.0}})

    high = score_signals(aggregate_signals([high_view]))
    low = score_signals(aggregate_signals([low_view]))
    assert high > low, "views (magnitude) must lift the ranking score"
    # And ``views`` is the registered magnitude kind doing the lifting.
    assert SIGNAL_SPECS["views"].is_magnitude
    assert not SIGNAL_SPECS["votes"].is_magnitude


# ── Conformance + registry ───────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    check_item_source(_source(), query="focus", window=SourceWindow(), limit=None)


def test_get_source_resolves_stackexchange() -> None:
    # Registry integration: the id resolves (lazy import self-registers).
    src = get_source("stackexchange", client=_StubClient())
    assert isinstance(src, StackExchangeSource)
    assert src.source_id == "stackexchange"


# ── Real-network smoke (deselected by default) ───────────────────────────────


@pytest.mark.network
def test_real_stackexchange_smoke() -> None:
    src = StackExchangeSource(site="stackoverflow")
    records = list(src.pull(query="python asyncio", window=SourceWindow(), limit=3))
    assert records
    assert all(r.source == "stackexchange" and r.id for r in records)
    assert any(r.signals.get("views", 0) > 0 for r in records)
