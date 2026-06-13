"""Offline tests for ArcticMirrorReader (the metalworks[supabase] perf tier).

Network is blocked (pytest-socket). The Supabase client is a fake whose storage
``list``/``create_signed_urls`` resolve to LOCAL parquet paths, so the reader's
real DuckDB SQL path runs end to end without network; ``arctic_shift_pulls`` is
a canned table response.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from metalworks.research.arctic import ArcticMirrorReader
from metalworks.research.arctic.mirror_reader import _id_chunks, _sql_array
from metalworks.research.types import MonthRef

duckdb = pytest.importorskip("duckdb")

# ── Local parquet fixture ────────────────────────────────────────────────


def _write_submissions(path: str, rows: list[dict[str, Any]]) -> None:
    con = duckdb.connect(":memory:")
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
    con.execute(f"COPY s TO '{path}' (FORMAT PARQUET)")
    con.close()


# ── Fake Supabase client ─────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def select(self, *_a: Any, **_k: Any) -> _FakeQuery:
        return self

    eq = order = limit = select  # same passthrough shape

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self._rows)


class _FakeStorageBucket:
    def __init__(self, shard_path: str, *, empty: bool = False) -> None:
        self._shard_path = shard_path
        self._empty = empty

    def list(self, _prefix: str, _opts: dict[str, Any]) -> list[dict[str, str]]:
        return [] if self._empty else [{"name": "skincare.parquet"}]

    def create_signed_urls(self, paths: list[str], _ttl: int) -> list[dict[str, str]]:
        # Resolve every requested object to the one local parquet file.
        return [{"signedURL": self._shard_path} for _ in paths]


class _FakeStorage:
    def __init__(self, shard_path: str, *, empty: bool = False) -> None:
        self._bucket = _FakeStorageBucket(shard_path, empty=empty)

    def from_(self, _bucket: str) -> _FakeStorageBucket:
        return self._bucket


class FakeSupabase:
    def __init__(
        self, *, months: list[dict[str, Any]], shard_path: str, empty_listing: bool = False
    ) -> None:
        self._months = months
        self.storage = _FakeStorage(shard_path, empty=empty_listing)

    def table(self, _name: str) -> _FakeQuery:
        return _FakeQuery(self._months)


@pytest.fixture
def mirror(tmp_path: Any) -> ArcticMirrorReader:
    shard = str(tmp_path / "skincare.parquet")
    _write_submissions(
        shard,
        [
            {"id": "p1", "subreddit": "SkincareAddiction", "title": "azelaic acid",
             "selftext": "fades PIE", "author": "a", "score": 10, "num_comments": 3,
             "url": "u1", "created_utc": 200.0},
            {"id": "p2", "subreddit": "SkincareAddiction", "title": "niacinamide",
             "selftext": "barrier", "author": "b", "score": 5, "num_comments": 1,
             "url": "u2", "created_utc": 300.0},
            {"id": "x9", "subreddit": "OtherSub", "title": "noise",
             "selftext": "", "author": "c", "score": 1, "num_comments": 0,
             "url": "u3", "created_utc": 400.0},
        ],
    )
    client = FakeSupabase(months=[{"year": 2026, "month": 2}], shard_path=shard)
    return ArcticMirrorReader(client=client)


# ── Helper tests ─────────────────────────────────────────────────────────


def test_sql_array_escapes_quotes() -> None:
    assert _sql_array(["a", "b'c"]) == "['a', 'b''c']"


def test_id_chunks() -> None:
    assert list(_id_chunks(["1", "2", "3"], 2)) == [["1", "2"], ["3"]]


# ── Reader tests (fake client + local parquet) ───────────────────────────


def test_latest_available_month(mirror: ArcticMirrorReader) -> None:
    assert mirror.latest_available_month("submissions") == MonthRef(2026, 2)


def test_latest_available_month_empty_raises(tmp_path: Any) -> None:
    client = FakeSupabase(months=[], shard_path=str(tmp_path / "none.parquet"))
    with pytest.raises(RuntimeError, match="no complete"):
        ArcticMirrorReader(client=client).latest_available_month()


def test_pull_subreddit_filters_and_orders(mirror: ArcticMirrorReader) -> None:
    rows = list(
        mirror.pull_subreddit(
            subreddit="SkincareAddiction", content_type="submissions", months=[MonthRef(2026, 2)]
        )
    )
    assert [r["id"] for r in rows] == ["p2", "p1"]  # created_utc DESC, OtherSub excluded


def test_pull_subreddit_select_and_limit(mirror: ArcticMirrorReader) -> None:
    rows = list(
        mirror.pull_subreddit(
            subreddit="SkincareAddiction",
            content_type="submissions",
            months=[MonthRef(2026, 2)],
            select_cols=["id", "score"],
            limit=1,
        )
    )
    assert rows == [{"id": "p2", "score": 5}]


def test_fetch_submissions_by_ids(mirror: ArcticMirrorReader) -> None:
    rows = list(mirror.fetch_submissions_by_ids(["p1", "missing"], [MonthRef(2026, 2)]))
    assert [r["id"] for r in rows] == ["p1"]
    assert rows[0]["selftext"] == "fades PIE"


def test_fetch_submissions_by_ids_empty(mirror: ArcticMirrorReader) -> None:
    assert list(mirror.fetch_submissions_by_ids([], [MonthRef(2026, 2)])) == []


def test_no_shards_raises() -> None:
    client = FakeSupabase(months=[{"year": 2026, "month": 2}], shard_path="x", empty_listing=True)
    with pytest.raises(RuntimeError, match="no shards"):
        list(
            ArcticMirrorReader(client=client).pull_subreddit(
                subreddit="X", content_type="submissions", months=[MonthRef(2026, 2)]
            )
        )


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCTIC_SHIFT_MIRROR_BUCKET", "custom-bucket")
    monkeypatch.setenv("ARCTIC_SHIFT_SIGNED_URL_TTL", "60")
    r = ArcticMirrorReader(client=FakeSupabase(months=[], shard_path="x"))
    assert r._bucket == "custom-bucket"  # noqa: SLF001 - asserting config resolution
    assert r._ttl == 60  # noqa: SLF001 - asserting config resolution


def test_close_is_idempotent(mirror: ArcticMirrorReader) -> None:
    mirror.close()
    mirror.close()  # no error after a no-op connection


def test_client_resolver_selects_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCTIC_SHIFT_SOURCE", "mirror")
    from metalworks.client import _Resolver

    resolver = _Resolver(
        chat=None, fast_chat=None, embeddings=None, store=None, reader=None,
        search=None, comments=None, model=None, fast_model=None, offline=False,
    )
    # Construct lazily; a bare ArcticMirrorReader needs no creds until a call.
    assert isinstance(resolver.reader(), ArcticMirrorReader)
