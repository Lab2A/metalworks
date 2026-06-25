"""GitHubItemSource tests — OFFLINE (pytest-socket blocks real network).

We feed canned GitHub REST API JSON through a stub httpx client (no network) and
assert the CorpusRecord / CorpusComment mapping: issue 👍 (``+1``) → ``reactions``
magnitude signal, comment count → ``engagement`` (non-magnitude social), author
login pseudonymized, body/title/``html_url`` carried, ghost author → tombstone,
empty-body comment dropped. We also assert the keyless path leaks NO token, run the
public ``check_item_source`` conformance check, prove ``get_source("github")``
resolves through the registry, and that the synthesis ranker reflects ``reactions``.

A real-network smoke test is gated behind ``@pytest.mark.network`` (deselected by
default; run with ``-m network --force-enable-socket``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceWindow, get_source
from metalworks.research.sources.github import GitHubItemSource, _build_query, _thumbs_up
from metalworks.research.synthesis.signals import (
    SIGNAL_SPECS,
    aggregate_signals,
    score_signals,
)
from metalworks.testing import check_item_source

# ── Canned GitHub REST API payloads ────────────────────────────────────────────

_SEARCH_PAGE: dict[str, Any] = {
    "items": [
        {
            "id": 100,
            "number": 42,
            "title": "Plugin X doesn't support SSO",
            "body": "We need SSO for the enterprise tier.",
            "html_url": "https://github.com/acme/plugin/issues/42",
            "repository_url": "https://api.github.com/repos/acme/plugin",
            "user": {"login": "alice", "id": 5},
            "comments": 3,
            "reactions": {"+1": 340, "-1": 2, "total_count": 360},
            "state": "open",
            "created_at": "2026-05-15T10:00:00Z",
        },
        {
            "id": 101,
            "number": 7,
            "title": "Ghost-author issue",
            "body": "filed then the author was deleted",
            "html_url": "https://github.com/acme/plugin/issues/7",
            "repository_url": "https://api.github.com/repos/acme/plugin",
            "user": None,  # deleted/ghost author → tombstone
            "comments": 0,
            "reactions": {"+1": 4},
            "state": "closed",
            "created_at": "2026-05-16T10:00:00Z",
        },
        # Missing id → must be skipped.
        {"id": None, "html_url": "https://github.com/x/y/issues/1"},
        # Missing html_url → must be skipped (not quotable).
        {"id": 999, "html_url": ""},
    ],
    "total_count": 2,
}

_COMMENTS_42: list[dict[str, Any]] = [
    {
        "id": 201,
        "body": "+1, we hit this on Okta too.",
        "html_url": "https://github.com/acme/plugin/issues/42#issuecomment-201",
        "user": {"login": "carol"},
        "reactions": {"+1": 9},
        "created_at": "2026-05-15T11:00:00Z",
    },
    # Empty-body (deleted) comment → dropped, not a tombstone.
    {
        "id": 202,
        "body": "   ",
        "html_url": "https://github.com/acme/plugin/issues/42#issuecomment-202",
        "user": {"login": "dave"},
        "created_at": "2026-05-15T12:00:00Z",
    },
]


class _StubResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _StubClient:
    """A minimal httpx.Client stand-in: routes by URL, records calls + headers. No network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None, dict[str, str] | None]] = []

    def get(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> _StubResponse:
        self.calls.append((url, params, headers))
        if "/search/issues" in url:
            return _StubResponse(_SEARCH_PAGE)
        if "/issues/42/comments" in url:
            return _StubResponse(_COMMENTS_42)
        if "/comments" in url:
            return _StubResponse([])
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


def _source(client: _StubClient | None = None, **kwargs: Any) -> GitHubItemSource:
    return GitHubItemSource(client=client or _StubClient(), author_salt="t", **kwargs)


# ── Small helpers ──────────────────────────────────────────────────────────────


def test_thumbs_up_reads_plus_one_only() -> None:
    assert _thumbs_up({"+1": 340, "-1": 5, "total_count": 360}) == 340
    assert _thumbs_up({"total_count": 9}) == 0  # no +1 key
    assert _thumbs_up(None) == 0
    assert _thumbs_up({"+1": True}) == 0  # bool is not a count


# ── Mapping tests ──────────────────────────────────────────────────────────────


def test_pull_maps_issues_to_records() -> None:
    src = _source()
    records = list(src.pull(query="sso", window=SourceWindow(), limit=None))

    # The null-id and empty-html_url hits are skipped.
    assert [r.id for r in records] == ["github_100", "github_101"]

    r0 = records[0]
    assert isinstance(r0, CorpusRecord)
    assert r0.source == "github"
    assert r0.source_id == "100"
    assert r0.url == "https://github.com/acme/plugin/issues/42"
    assert r0.title == "Plugin X doesn't support SSO"
    assert r0.text == "We need SSO for the enterprise tier."
    assert r0.engagement == 3  # comment count → engagement
    assert r0.author_hash and r0.author_hash.startswith("u_")
    # Signals carry reactions (magnitude, +1 count) and engagement (comment count).
    assert r0.signals == {"reactions": 340.0, "engagement": 3.0}
    assert r0.created_at is not None
    assert r0.extra["owner"] == "acme"
    assert r0.extra["repo"] == "plugin"
    assert r0.extra["number"] == 42
    assert r0.extra["reactions_plus1"] == 340

    # Ghost author (user None) → tombstone author (None).
    r1 = records[1]
    assert r1.author_hash is None
    assert r1.signals == {"reactions": 4.0, "engagement": 0.0}


def test_pull_honors_limit() -> None:
    records = list(_source().pull(query="sso", window=SourceWindow(), limit=1))
    assert [r.id for r in records] == ["github_100"]


def test_pull_builds_created_window_and_type_qualifier() -> None:
    client = _StubClient()
    src = _source(client=client)
    window = SourceWindow(
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
    )
    list(src.pull(query="sso", window=window, limit=1))
    url, params, headers = client.calls[0]
    assert "/search/issues" in url
    assert params is not None
    assert params["q"] == "sso type:issue created:2026-01-01..2026-06-01"
    assert params["advanced_search"] == "true"
    assert params["sort"] == "reactions"
    # Keyless by default → NO Authorization header leaked.
    assert headers is not None
    assert "Authorization" not in headers
    assert headers["Accept"] == "application/vnd.github+json"


def test_query_window_variants() -> None:
    assert (
        _build_query("sso", SourceWindow(start=datetime(2026, 1, 1, tzinfo=UTC)))
        == "sso type:issue created:>=2026-01-01"
    )
    assert (
        _build_query("sso", SourceWindow(end=datetime(2026, 6, 1, tzinfo=UTC)))
        == "sso type:issue created:<=2026-06-01"
    )
    assert _build_query("sso", SourceWindow()) == "sso type:issue"
    assert _build_query("", SourceWindow()) == "type:issue"


def test_keyless_leaks_no_token() -> None:
    """The keyless construction sends no Authorization header at all (no token leak)."""
    client = _StubClient()
    src = _source(client=client)  # no token, no env
    list(src.pull(query="x", window=SourceWindow(), limit=1))
    for _url, _params, headers in client.calls:
        assert headers is not None
        assert "Authorization" not in headers


def test_token_is_sent_as_bearer_when_set() -> None:
    client = _StubClient()
    src = _source(client=client, token="ghp_secret")
    list(src.pull(query="x", window=SourceWindow(), limit=1))
    _url, _params, headers = client.calls[0]
    assert headers is not None
    assert headers["Authorization"] == "Bearer ghp_secret"


def test_token_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    client = _StubClient()
    src = GitHubItemSource(client=client, author_salt="t")
    list(src.pull(query="x", window=SourceWindow(), limit=1))
    _url, _params, headers = client.calls[0]
    assert headers is not None
    assert headers["Authorization"] == "Bearer env-token"


def test_comments_for_maps_comments_and_drops_empty() -> None:
    src = _source()
    # Must pull first so owner/repo/number are captured for issue 42.
    list(src.pull(query="sso", window=SourceWindow(), limit=None))
    batches = src.comments_for(["github_100", "github_101"])
    assert batches is not None
    out = list(batches)
    assert len(out) == 2

    first = out[0]
    assert [c.id for c in first] == ["201"]  # empty-body 202 dropped
    c201 = first[0]
    assert isinstance(c201, CorpusComment)
    assert c201.source == "github"
    assert c201.parent_id == "github_100"
    assert c201.engagement == 9  # comment +1 → engagement
    assert c201.signals == {"reactions": 9.0}
    assert c201.url == "https://github.com/acme/plugin/issues/42#issuecomment-201"
    assert c201.text == "+1, we hit this on Okta too."
    assert c201.author_hash and c201.author_hash.startswith("u_")

    # Issue 101 (number 7) → the stub returns an empty comment list.
    assert out[1] == []


def test_comments_for_unknown_id_yields_empty() -> None:
    """An id never seen by a pull (no owner/repo captured) yields an empty batch, not an error."""
    src = _source()
    batches = src.comments_for(["github_404"])
    assert batches is not None
    assert list(batches) == [[]]


def test_comments_for_batch_input_order_preserved() -> None:
    src = _source()
    list(src.pull(query="sso", window=SourceWindow(), limit=None))
    batches = src.comments_for(["github_101", "github_100"])
    assert batches is not None
    out = list(batches)
    assert out[0] == []  # 101 first now
    assert [c.id for c in out[1]] == ["201"]


def test_latest_window_returns_source_window() -> None:
    win = _source().latest_window()
    assert isinstance(win, SourceWindow)
    assert win.end is not None


# ── Signals: reactions magnitude reflected in ranking ──────────────────────────


def test_reactions_registered_is_magnitude() -> None:
    assert "reactions" in SIGNAL_SPECS
    assert SIGNAL_SPECS["reactions"].is_magnitude
    # The rule-5 social signal it ships alongside is non-magnitude.
    assert not SIGNAL_SPECS["engagement"].is_magnitude


def test_reactions_magnitude_lifts_ranking_score() -> None:
    """A cluster carrying high 👍 reactions scores above an equal-engagement low-👍 one."""
    src = _source()
    records = list(src.pull(query="sso", window=SourceWindow(), limit=None))
    high = records[0]  # 340 reactions / 3 comments
    low = high.model_copy(update={"signals": {"reactions": 1.0, "engagement": 3.0}})

    high_score = score_signals(aggregate_signals([high]))
    low_score = score_signals(aggregate_signals([low]))
    assert high_score > low_score, "reactions (magnitude) must lift the ranking score"


# ── Conformance + registry ─────────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    check_item_source(_source(), query="sso", window=SourceWindow(), limit=None)


def test_get_source_resolves_github() -> None:
    # Registry integration: the id resolves (lazy import self-registers).
    src = get_source("github", client=_StubClient())
    assert isinstance(src, GitHubItemSource)
    assert src.source_id == "github"


# ── Real-network smoke (deselected by default) ─────────────────────────────────


@pytest.mark.network
def test_real_github_smoke() -> None:
    src = GitHubItemSource()
    window = SourceWindow(start=datetime(2024, 1, 1, tzinfo=UTC))
    records = list(src.pull(query="feature request dark mode", window=window, limit=3))
    assert records
    assert all(r.source == "github" and r.id for r in records)
    assert all(r.url.startswith("https://github.com/") for r in records)
