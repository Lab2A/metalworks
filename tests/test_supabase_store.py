"""Supabase backend conformance — gated behind env vars.

Runs in nightly-live (or locally) against a real/`supabase start` project:

    export METALWORKS_TEST_SUPABASE_URL=...
    export METALWORKS_TEST_SUPABASE_KEY=...   # service-role
    # apply metalworks.stores.supabase.SCHEMA_SQL to the project first
    pytest tests/test_supabase_store.py --allow-hosts=...

Offline CI: these tests skip (sockets are blocked anyway); the offline tests
below still verify pagination logic against a stub client.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from metalworks.stores.supabase import SupabaseStores
from metalworks.testing import check_all_repos

_URL = os.environ.get("METALWORKS_TEST_SUPABASE_URL")
_KEY = os.environ.get("METALWORKS_TEST_SUPABASE_KEY")


@pytest.mark.skipif(not (_URL and _KEY), reason="METALWORKS_TEST_SUPABASE_* not set")
def test_supabase_backend_conforms() -> None:
    pytest.importorskip("supabase")
    check_all_repos(SupabaseStores(url=_URL, key=_KEY))


# ── Offline: prove _select_all paginates to exhaustion against a stub ──


class _StubQuery:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self._range: tuple[int, int] | None = None

    def eq(self, *_args: Any) -> _StubQuery:
        return self

    def in_(self, *_args: Any) -> _StubQuery:
        return self

    def range(self, start: int, end: int) -> _StubQuery:
        self._range = (start, end)
        return self

    def execute(self) -> Any:
        assert self._range is not None, "reads must paginate with .range()"
        start, end = self._range

        class _Resp:
            data = self._rows[start : end + 1]

        return _Resp()


class _StubTable:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def select(self, *_cols: str) -> _StubQuery:
        return _StubQuery(self._rows)


class _StubClient:
    """Mimics PostgREST: honors .range() windows over a 2,345-row table."""

    def __init__(self, n: int):
        self._rows = [{"payload": {"comment_id": f"c{i}", "post_id": "p0"}} for i in range(n)]

    def table(self, _name: str) -> _StubTable:
        return _StubTable(self._rows)


def test_select_all_paginates_to_exhaustion() -> None:
    store = SupabaseStores(client=_StubClient(2345))
    rows = store._select_all("comments", lambda q: q)  # noqa: SLF001
    assert len(rows) == 2345, "pagination stopped early — the max-rows truncation bug"
