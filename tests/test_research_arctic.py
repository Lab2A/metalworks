"""Offline tests for the Arctic Shift data-access subtree.

Network is blocked (pytest-socket). The reader is exercised against a LOCAL
directory of ``.parquet`` shards written in-test with duckdb; the API client is
exercised against a respx-mocked httpx transport.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import duckdb
import httpx
import pytest
import respx

from metalworks.contract import RedditComment, RedditPost
from metalworks.errors import RateLimitedError
from metalworks.research.arctic import (
    ArcticReader,
    ArcticShiftApiClient,
    hydrate_comments,
    hydrate_submissions,
)
from metalworks.research.arctic.api import _flatten_listing
from metalworks.research.arctic.reader import (
    _id_chunks,
    _sql_array,
    month_glob,
    window_patterns,
)
from metalworks.research.deps import ResearchDeps
from metalworks.research.types import MonthRef
from metalworks.stores.memory import MemoryStores

# ── Local parquet fixture ────────────────────────────────────────────────


def _write_submissions(root: str, m: MonthRef, rows: list[dict[str, Any]]) -> None:
    """Write a one-shard parquet file under root/submissions/YYYY/MM/000.parquet."""
    import os

    d = os.path.join(root, "submissions", f"{m.year:04d}", f"{m.month:02d}")
    os.makedirs(d, exist_ok=True)
    con = duckdb.connect(":memory:")
    # Build a VALUES table so the parquet schema is explicit and stable.
    con.execute(
        "CREATE TABLE s (id VARCHAR, subreddit VARCHAR, title VARCHAR, selftext VARCHAR, "
        "author VARCHAR, score BIGINT, num_comments BIGINT, url VARCHAR, created_utc DOUBLE)"
    )
    for r in rows:
        con.execute(
            "INSERT INTO s VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                r["id"],
                r["subreddit"],
                r.get("title", ""),
                r.get("selftext", ""),
                r.get("author"),
                r.get("score", 0),
                r.get("num_comments", 0),
                r.get("url", ""),
                r.get("created_utc", 0.0),
            ],
        )
    out = os.path.join(d, "000.parquet")
    con.execute(f"COPY s TO '{out}' (FORMAT PARQUET)")
    con.close()


@pytest.fixture
def local_corpus(tmp_path: Any) -> tuple[str, MonthRef]:
    root = str(tmp_path / "data")
    m = MonthRef(2026, 2)
    _write_submissions(
        root,
        m,
        [
            {
                "id": "p1",
                "subreddit": "Supplements",
                "title": "Magnesium for sleep",
                "selftext": "anyone tried it",
                "author": "alice",
                "score": 42,
                "num_comments": 7,
                "url": "https://reddit.com/r/Supplements/comments/p1/",
                "created_utc": 1_700_000_100.0,
            },
            {
                "id": "p2",
                "subreddit": "Supplements",
                "title": "Creatine timing",
                "selftext": "",
                "author": "[deleted]",
                "score": 5,
                "num_comments": 1,
                "url": "https://reddit.com/r/Supplements/comments/p2/",
                "created_utc": 1_700_000_200.0,
            },
            {
                "id": "x9",
                "subreddit": "Other",
                "title": "off topic",
                "selftext": "",
                "author": "bob",
                "score": 1,
                "num_comments": 0,
                "url": "",
                "created_utc": 1_700_000_300.0,
            },
        ],
    )
    return root, m


# ── Pure-function tests ──────────────────────────────────────────────────


def test_month_glob_and_window_patterns() -> None:
    m = MonthRef(2026, 2)
    assert month_glob("submissions", m, root="hf://x") == "hf://x/submissions/2026/02/*.parquet"
    pats = window_patterns("comments", [MonthRef(2025, 12), m], root="r")
    assert pats == ["r/comments/2025/12/*.parquet", "r/comments/2026/02/*.parquet"]
    with pytest.raises(ValueError, match="at least one month"):
        window_patterns("submissions", [], root="r")


def test_sql_array_escapes_quotes() -> None:
    assert _sql_array(["a'b", "c"]) == "['a''b', 'c']"


def test_id_chunks() -> None:
    chunks = list(_id_chunks(["a", "", "b", "c"], 2))
    assert chunks == [["a", "b"], ["c"]]


# ── Reader tests (local parquet) ─────────────────────────────────────────


def test_pull_subreddit_local(local_corpus: tuple[str, MonthRef]) -> None:
    root, m = local_corpus
    reader = ArcticReader(data_root=root, probe_sleep_s=0.0)
    rows = list(
        reader.pull_subreddit(subreddit="Supplements", content_type="submissions", months=[m])
    )
    reader.close()
    ids = {r["id"] for r in rows}
    assert ids == {"p1", "p2"}
    # created_utc DESC — p2 newer than p1.
    assert [r["id"] for r in rows] == ["p2", "p1"]


def test_pull_subreddit_select_and_limit(local_corpus: tuple[str, MonthRef]) -> None:
    root, m = local_corpus
    reader = ArcticReader(data_root=root, probe_sleep_s=0.0)
    rows = list(
        reader.pull_subreddit(
            subreddit="Supplements",
            content_type="submissions",
            months=[m],
            select_cols=["id", "score"],
            limit=1,
        )
    )
    reader.close()
    assert len(rows) == 1
    assert set(rows[0].keys()) == {"id", "score"}


def test_fetch_submissions_by_ids_local(local_corpus: tuple[str, MonthRef]) -> None:
    root, m = local_corpus
    reader = ArcticReader(data_root=root, probe_sleep_s=0.0)
    rows = list(reader.fetch_submissions_by_ids(["p1", "p2", "missing"], [m]))
    reader.close()
    assert {r["id"] for r in rows} == {"p1", "p2"}
    assert rows[0]["subreddit"] == "Supplements"


def test_fetch_submissions_by_ids_empty_returns_nothing(local_corpus: tuple[str, MonthRef]) -> None:
    root, m = local_corpus
    reader = ArcticReader(data_root=root, probe_sleep_s=0.0)
    assert list(reader.fetch_submissions_by_ids([], [m])) == []
    reader.close()


def test_latest_available_month_local(local_corpus: tuple[str, MonthRef]) -> None:
    # Only 2026-02 exists; probing from "now" walks back to it within 12 months
    # so long as the test runs within a year of that month. To stay
    # deterministic we just assert the probe finds *a* month equal to ours when
    # we seed only that one and the harness clock is near it; instead we assert
    # the glob construction by pointing at the known month directly via probe.
    root, m = local_corpus
    reader = ArcticReader(data_root=root, probe_sleep_s=0.0)
    # The reader probes from the real current month backward. Our shard is at
    # 2026-02; this test environment's clock (2026-06) is within search_back=12.
    found = reader.latest_available_month("submissions")
    reader.close()
    assert found == m


# ── API client tests (respx) ─────────────────────────────────────────────

_BASE = "https://arctic-shift.photon-reddit.com/api"


def test_flatten_listing_nested() -> None:
    nested = [
        {
            "kind": "t1",
            "data": {
                "id": "c1",
                "body": "top",
                "replies": {
                    "kind": "Listing",
                    "data": {"children": [{"kind": "t1", "data": {"id": "c2", "body": "child"}}]},
                },
            },
        },
        {"kind": "t1", "data": {"id": "c3", "body": "sibling", "replies": ""}},
    ]
    out: list[dict[str, Any]] = []
    _flatten_listing(nested, out)
    assert [c["id"] for c in out] == ["c1", "c2", "c3"]
    # replies popped so the tree isn't re-serialized.
    assert all("replies" not in c for c in out)


@respx.mock
def test_comments_tree_flattens() -> None:
    respx.get(f"{_BASE}/comments/tree").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"kind": "t1", "data": {"id": "c1", "body": "hi", "link_id": "t3_p1"}},
                ]
            },
        )
    )
    client = ArcticShiftApiClient(min_interval=0.0)
    out = client.comments_tree(link_id="p1")
    client.close()
    assert out[0]["id"] == "c1"


@respx.mock
def test_rate_limit_gate_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("metalworks.research.arctic.api.time.sleep", lambda s: sleeps.append(s))
    respx.get(f"{_BASE}/comments/tree").mock(return_value=httpx.Response(200, json={"data": []}))
    client = ArcticShiftApiClient(min_interval=0.5)
    # First call: no prior request, no gate sleep. Second call: gate sleeps
    # because monotonic delta < min_interval (real sleep is patched out).
    client.comments_tree(link_id="a")
    client.comments_tree(link_id="b")
    client.close()
    assert any(s > 0 for s in sleeps), "gate should have requested a positive sleep"


@respx.mock
def test_429_backoff_raises_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.research.arctic.api.time.sleep", lambda _s: None)
    respx.get(f"{_BASE}/comments/tree").mock(
        return_value=httpx.Response(429, headers={"X-RateLimit-Reset": "1"})
    )
    client = ArcticShiftApiClient(min_interval=0.0, max_retries=3)
    with pytest.raises(RateLimitedError):
        client.comments_tree(link_id="a")
    client.close()


@respx.mock
def test_per_link_failure_accumulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.research.arctic.api.time.sleep", lambda _s: None)
    # p1 succeeds; p2 always 429 -> RateLimitedError, recorded as a skip.
    router = respx.get(f"{_BASE}/comments/tree")

    def _resp(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("link_id") == "p1":
            return httpx.Response(200, json={"data": [{"kind": "t1", "data": {"id": "c1"}}]})
        return httpx.Response(429, headers={"X-RateLimit-Reset": "0"})

    router.mock(side_effect=_resp)
    client = ArcticShiftApiClient(min_interval=0.0, max_retries=2)
    batches = list(client.comments_for_links(["p1", "p2"]))
    client.close()
    assert [len(b) for b in batches] == [1, 0]
    assert client.last_skipped == 1
    assert len(client.last_errors) == 1
    assert "p2" in client.last_errors[0]


# ── Hydration tests (fakes + MemoryStores) ───────────────────────────────


class FakeReader:
    """CorpusReader stand-in returning canned submission rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.requested_ids: list[str] = []

    def latest_available_month(self, content_type: str = "submissions") -> MonthRef:
        return MonthRef(2026, 2)

    def pull_subreddit(self, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        yield from self._rows

    def fetch_submissions_by_ids(
        self, post_ids: Sequence[str], months: Sequence[MonthRef]
    ) -> Iterator[dict[str, Any]]:
        wanted = set(post_ids)
        self.requested_ids = list(post_ids)
        for r in self._rows:
            if r["id"] in wanted:
                yield r

    def close(self) -> None:
        return None


class FakeCommentSource:
    """CommentSource stand-in with per-link failure accumulation."""

    def __init__(self, threads: dict[str, list[dict[str, Any]]], fail: set[str] | None = None):
        self._threads = threads
        self._fail = fail or set()
        self.last_skipped = 0
        self.last_errors: list[str] = []

    def comments_for_links(self, link_ids: Sequence[str]) -> Iterator[list[dict[str, Any]]]:
        self.last_skipped = 0
        self.last_errors = []
        for lid in link_ids:
            if lid in self._fail:
                self.last_skipped += 1
                self.last_errors.append(f"{lid}: boom")
                yield []
            else:
                yield self._threads.get(lid, [])


def _deps(reader: Any = None, comments: Any = None, *, salt: str = "salt-A") -> ResearchDeps:
    from metalworks.embeddings import FakeEmbedding
    from metalworks.llm import FakeChatModel

    stores = MemoryStores()
    return ResearchDeps(
        chat=FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=stores,
        reader=reader or FakeReader([]),
        comments=comments,
        author_salt=salt,
    )


def test_hydrate_submissions_upserts_posts() -> None:
    rows = [
        {
            "id": "p1",
            "subreddit": "Supplements",
            "title": "T",
            "selftext": "b",
            "author": "alice",
            "score": 9,
            "num_comments": 2,
            "url": "https://reddit.com/p1",
            "created_utc": 1_700_000_000.0,
        },
        {
            "id": "p2",
            "subreddit": "Supplements",
            "title": "T2",
            "selftext": "",
            "author": "[deleted]",
            "score": 0,
            "num_comments": 0,
            "url": "",
            "created_utc": 1_700_000_050.0,
        },
    ]
    stores = MemoryStores()
    deps = _deps(reader=FakeReader(rows))
    deps.corpus = stores
    result = hydrate_submissions(deps, post_ids=["p1", "p2"], months=[MonthRef(2026, 2)])
    assert result.requested == 2
    assert result.upserted == 2
    posts = stores.get_posts(["p1", "p2"])
    by_id = {p.post_id: p for p in posts}
    assert isinstance(by_id["p1"], RedditPost)
    # [deleted] preserved through hashing.
    assert by_id["p2"].author == "[deleted]"
    # Real author hashed (not cleartext).
    assert by_id["p1"].author is not None
    assert by_id["p1"].author.startswith("u_")
    assert "alice" not in (by_id["p1"].author or "")


def test_hydrate_submissions_salt_changes_hash() -> None:
    rows = [
        {
            "id": "p1",
            "subreddit": "S",
            "title": "T",
            "selftext": "",
            "author": "alice",
            "score": 0,
            "num_comments": 0,
            "url": "",
            "created_utc": 1.0,
        }
    ]
    s1 = MemoryStores()
    d1 = _deps(reader=FakeReader(rows), salt="salt-A")
    d1.corpus = s1
    hydrate_submissions(d1, post_ids=["p1"], months=[MonthRef(2026, 2)])

    s2 = MemoryStores()
    d2 = _deps(reader=FakeReader(rows), salt="salt-B")
    d2.corpus = s2
    hydrate_submissions(d2, post_ids=["p1"], months=[MonthRef(2026, 2)])

    h1 = s1.get_posts(["p1"])[0].author
    h2 = s2.get_posts(["p1"])[0].author
    assert h1 != h2


def test_hydrate_comments_populates_skipped_and_errors() -> None:
    threads = {
        "p1": [
            {
                "id": "t1_c1",
                "link_id": "t3_p1",
                "subreddit": "Supplements",
                "parent_id": "t3_p1",
                "body": "great",
                "author": "carol",
                "score": 3,
                "created_utc": 1_700_000_000.0,
            }
        ],
    }
    src = FakeCommentSource(threads, fail={"p2"})
    stores = MemoryStores()
    deps = _deps(comments=src)
    deps.corpus = stores
    result = hydrate_comments(deps, link_ids=["p1", "p2"])
    assert result.upserted == 1
    assert result.skipped == 1
    assert result.errors and "p2" in result.errors[0]
    comments = stores.get_comments_for_posts(["p1"])
    assert isinstance(comments[0], RedditComment)
    assert comments[0].comment_id == "c1"  # t1_ prefix stripped
    assert comments[0].author_hash.startswith("u_")


def test_hydrate_empty_inputs_are_noops() -> None:
    deps = _deps(comments=FakeCommentSource({}))
    assert hydrate_submissions(deps, post_ids=[], months=[MonthRef(2026, 2)]).requested == 0
    assert hydrate_comments(deps, link_ids=[]).requested == 0
