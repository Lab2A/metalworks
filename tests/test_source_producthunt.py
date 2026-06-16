"""ProductHuntSource over a canned GraphQL client (offline, no network/token).

A fake client returns a posts page and a comments page; we prove the Post →
CorpusRecord and Comment → CorpusComment mapping, the window-pull cache (the
per-subreddit loop hits the API once), and the no-token error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.research.sources import ItemSource, SourceWindow
from metalworks.research.sources.producthunt import ProductHuntSource

_POSTS_RESP = {
    "data": {
        "posts": {
            "edges": [
                {
                    "node": {
                        "id": "1",
                        "name": "FocusFlow",
                        "tagline": "a jitter-free focus app for devs",
                        "description": "helps developers stay focused without the crash",
                        "slug": "focusflow",
                        "url": "https://www.producthunt.com/posts/focusflow",
                        "votesCount": 340,
                        "commentsCount": 2,
                        "createdAt": "2026-01-15T10:00:00Z",
                        "topics": {"edges": [{"node": {"name": "Productivity"}}]},
                        "user": {"id": "u1", "name": "Ada", "username": "ada"},
                    }
                },
                {
                    "node": {
                        "id": "2",
                        "name": "Chairly",
                        "tagline": "ergonomic chairs",
                        "description": "",
                        "slug": "chairly",
                        "url": "https://www.producthunt.com/posts/chairly",
                        "votesCount": 120,
                        "commentsCount": 0,
                        "createdAt": "2026-01-16T10:00:00Z",
                        "topics": {"edges": []},
                        "user": {"id": "u2", "name": "Bob", "username": "bob"},
                    }
                },
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": "c1"},
        }
    }
}

_COMMENTS_RESP = {
    "data": {
        "post": {
            "comments": {
                "edges": [
                    {
                        "node": {
                            "id": "c1",
                            "body": "I'd pay for this — caffeine wrecks my afternoons",
                            "votesCount": 12,
                            "createdAt": "2026-01-15T11:00:00Z",
                            "url": "https://www.producthunt.com/posts/focusflow#c1",
                            "user": {"id": "u3", "name": "Cara", "username": "cara"},
                        }
                    },
                    {  # empty body → dropped
                        "node": {"id": "c2", "body": "", "votesCount": 0, "user": {}}
                    },
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": "x"},
            }
        }
    }
}


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._p = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._p


class _FakeClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def post(self, _url: str, *, json: dict[str, Any], headers: Any = None) -> _FakeResp:
        q = str(json["query"])
        self.queries.append(q)
        return _FakeResp(_POSTS_RESP if "posts(" in q else _COMMENTS_RESP)


_WINDOW = SourceWindow(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 2, 1, tzinfo=UTC))


def _source(client: _FakeClient | None = None) -> ProductHuntSource:
    return ProductHuntSource(token="dev-token", client=client or _FakeClient())


def test_satisfies_protocol() -> None:
    assert isinstance(_source(), ItemSource)


def test_pull_maps_posts() -> None:
    src = _source()
    records = list(src.pull(query="ignored", window=_WINDOW))
    assert {r.id for r in records} == {"1", "2"}
    r1 = next(r for r in records if r.id == "1")
    assert r1.source == "producthunt"
    assert r1.engagement == 340
    assert r1.title == "FocusFlow — a jitter-free focus app for devs"
    assert r1.author_hash and r1.author_hash.startswith("u_")
    assert r1.extra["topics"] == ["Productivity"]
    assert r1.extra["num_comments"] == 2
    assert r1.url == "https://www.producthunt.com/posts/focusflow"


def test_comments_map_and_drop_empty() -> None:
    src = _source()
    batch = next(iter(src.comments_for(["1"])))
    assert {c.id for c in batch} == {"c1"}  # empty-body c2 dropped
    c = batch[0]
    assert c.parent_id == "1"
    assert c.source == "producthunt"
    assert c.engagement == 12
    assert c.text.startswith("I'd pay for this")


def test_window_pull_is_cached() -> None:
    client = _FakeClient()
    src = _source(client)
    # the pipeline calls pull once per brief subreddit — the API must be hit once
    list(src.pull(query="sub-a", window=_WINDOW))
    list(src.pull(query="sub-b", window=_WINDOW))
    assert sum("posts(" in q for q in client.queries) == 1


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRODUCT_HUNT_TOKEN", raising=False)
    monkeypatch.delenv("PRODUCT_HUNT_DEVELOPER_TOKEN", raising=False)
    src = ProductHuntSource(token=None, client=_FakeClient())
    with pytest.raises(RuntimeError, match="developer token"):
        list(src.pull(query="x", window=_WINDOW))
