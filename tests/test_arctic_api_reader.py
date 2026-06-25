"""Offline tests for the live-API corpus reader (the new default) and the
provider/reader resolution it plugs into.

Network is blocked (pytest-socket). The Arctic Shift client methods are exercised
against a respx-mocked transport; the reader logic (windowing, limit, select_cols,
content-type guard, id chunking) runs against a recording stub client.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from metalworks.research.arctic import ArcticReader, ArcticShiftApiClient, ArcticShiftReader
from metalworks.research.arctic.api_reader import _month_window
from metalworks.research.types import MonthRef

_BASE = "https://arctic-shift.photon-reddit.com/api"


# ── the live client's new posts methods ──────────────────────────────────────


@respx.mock
def test_search_submissions_maps_rows_and_window() -> None:
    route = respx.get(f"{_BASE}/posts/search").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "p1", "subreddit": "espresso", "title": "t"}]}
        )
    )
    client = ArcticShiftApiClient(min_interval=0.0)
    rows = client.search_submissions(
        subreddit="espresso", after=1000, before=2000, limit=5, sort="desc"
    )
    client.close()
    assert rows == [{"id": "p1", "subreddit": "espresso", "title": "t"}]
    sent = route.calls.last.request.url
    assert sent.params["subreddit"] == "espresso"
    assert sent.params["after"] == "1000"
    assert sent.params["before"] == "2000"
    assert sent.params["limit"] == "5"


@respx.mock
def test_submissions_by_ids_joins_ids() -> None:
    route = respx.get(f"{_BASE}/posts/ids").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})
    )
    client = ArcticShiftApiClient(min_interval=0.0)
    rows = client.submissions_by_ids(["a", "", "b"])
    client.close()
    assert [r["id"] for r in rows] == ["a", "b"]
    assert route.calls.last.request.url.params["ids"] == "a,b"


def test_submissions_by_ids_empty_short_circuits() -> None:
    client = ArcticShiftApiClient(min_interval=0.0)
    assert client.submissions_by_ids([]) == []
    client.close()


# ── the reader logic (recording stub client) ─────────────────────────────────


class _StubClient:
    """Records search/by-id calls; returns canned rows per (subreddit, after)."""

    def __init__(self, rows_by_month: dict[int, list[dict[str, Any]]]) -> None:
        self.rows_by_month = rows_by_month
        self.search_calls: list[dict[str, Any]] = []
        self.id_calls: list[list[str]] = []
        self.closed = False

    def search_submissions(
        self, *, subreddit: str, after: int, before: int, limit: int, sort: str
    ) -> list[dict[str, Any]]:
        self.search_calls.append(
            {"subreddit": subreddit, "after": after, "before": before, "limit": limit}
        )
        return self.rows_by_month.get(after, [])[:limit]

    def submissions_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        self.id_calls.append(list(ids))
        return [{"id": i} for i in ids]

    def close(self) -> None:
        self.closed = True


def _reader(
    rows_by_month: dict[int, list[dict[str, Any]]], page_limit: int = 100
) -> tuple[ArcticShiftReader, _StubClient]:
    stub = _StubClient(rows_by_month)
    return ArcticShiftReader(client=stub, page_limit=page_limit), stub  # type: ignore[arg-type]


def test_pull_subreddit_newest_first_across_months() -> None:
    jan_after = _month_window(MonthRef(2025, 1))[0]
    feb_after = _month_window(MonthRef(2025, 2))[0]
    reader, stub = _reader({jan_after: [{"id": "j"}], feb_after: [{"id": "f"}]})
    rows = list(
        reader.pull_subreddit(
            subreddit="x",
            content_type="submissions",
            months=[MonthRef(2025, 1), MonthRef(2025, 2)],
        )
    )
    # Newest month (Feb) first.
    assert [r["id"] for r in rows] == ["f", "j"]
    assert [c["after"] for c in stub.search_calls] == [feb_after, jan_after]


def test_pull_subreddit_limit_caps_total() -> None:
    jan_after = _month_window(MonthRef(2025, 1))[0]
    reader, _ = _reader({jan_after: [{"id": "a"}, {"id": "b"}, {"id": "c"}]})
    rows = list(
        reader.pull_subreddit(
            subreddit="x", content_type="submissions", months=[MonthRef(2025, 1)], limit=2
        )
    )
    assert [r["id"] for r in rows] == ["a", "b"]


def test_pull_subreddit_select_cols_projects() -> None:
    jan_after = _month_window(MonthRef(2025, 1))[0]
    reader, _ = _reader({jan_after: [{"id": "a", "title": "t", "extra": "drop"}]})
    rows = list(
        reader.pull_subreddit(
            subreddit="x",
            content_type="submissions",
            months=[MonthRef(2025, 1)],
            select_cols=["id", "title"],
        )
    )
    assert rows == [{"id": "a", "title": "t"}]


def test_pull_subreddit_non_submissions_yields_nothing() -> None:
    reader, stub = _reader({})
    rows = list(
        reader.pull_subreddit(subreddit="x", content_type="comments", months=[MonthRef(2025, 1)])
    )
    assert rows == []
    assert stub.search_calls == []


def test_fetch_submissions_by_ids_chunks() -> None:
    reader, stub = _reader({})
    ids = [str(i) for i in range(120)]
    out = list(reader.fetch_submissions_by_ids(ids, months=[]))
    assert len(out) == 120
    # 120 ids → chunks of 50 → 50, 50, 20.
    assert [len(c) for c in stub.id_calls] == [50, 50, 20]


def test_latest_available_month_is_a_recent_month() -> None:
    reader, _ = _reader({})
    m = reader.latest_available_month()
    assert isinstance(m, MonthRef)
    assert m.year >= 2025


def test_close_propagates_only_when_owned() -> None:
    stub = _StubClient({})
    reader = ArcticShiftReader(client=stub, page_limit=10)  # type: ignore[arg-type]
    reader.close()
    # Caller-injected client is NOT closed by the reader.
    assert stub.closed is False


# ── resolver + provider overrides ────────────────────────────────────────────


def test_resolve_corpus_reader_default_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCTIC_SHIFT_SOURCE", raising=False)
    from metalworks import config

    assert isinstance(config.resolve_corpus_reader(), ArcticShiftReader)


def test_resolve_corpus_reader_hf_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCTIC_SHIFT_SOURCE", "hf")
    from metalworks import config

    assert isinstance(config.resolve_corpus_reader(), ArcticReader)


def test_metalworks_model_env_beats_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.config import _resolve_chat_provider

    # Stray Vertex env would otherwise hijack provider selection.
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "p")
    monkeypatch.setenv("METALWORKS_MODEL", "deepseek/deepseek-v4-flash")
    provider, model_id = _resolve_chat_provider(None)
    assert provider == "openrouter"
    assert model_id == "deepseek/deepseek-v4-flash"


def test_explicit_model_arg_beats_metalworks_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.config import _resolve_chat_provider

    monkeypatch.setenv("METALWORKS_MODEL", "openrouter:fallback")
    provider, model_id = _resolve_chat_provider("openai:gpt-5")
    assert provider == "openai"
    assert model_id == "gpt-5"


def test_arctic_reader_reads_hf_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_TOKEN", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_secret")
    reader = ArcticReader(probe_sleep_s=0.0)
    assert reader._hf_token == "hf_secret"  # noqa: SLF001 — verifying env wiring
