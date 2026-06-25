"""SamGovItemSource tests — OFFLINE (pytest-socket blocks real network).

We feed canned SAM.gov Opportunities API v2 JSON through a stub httpx client (no
network) and assert the connector satisfies the :class:`ItemSource` protocol, maps
each notice to a self-representing (``yields_units``) record (solicitation text +
``uiLink`` permalink + contracting agency as author), filters/windows by the brief's
terms and posted-date span, attaches ``rfp_budget`` when (and only when) a notice
carries an award value, ranks by distinct agency/domain breadth, returns ``None``
from ``comments_for``, and resolves through the registry. The connector imports only
the core stack (stdlib + lazy httpx), so this whole module runs on the bare CI variant.

A real-network smoke test is gated behind ``@pytest.mark.network`` (deselected by
default; run with ``-m network --enable-socket``, needs ``SAM_GOV_API_KEY``).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import CorpusRecord
from metalworks.research.sources import ItemSource, SourceWindow, get_source
from metalworks.research.sources.samgov import (
    SamGovItemSource,
    _award_amount,
    _registrable_domain,
)
from metalworks.testing import check_item_source

# ── Canned SAM.gov Opportunities API payloads ─────────────────────────────────

_NOTICE_WITH_AWARD = {
    "noticeId": "n-100",
    "title": "Stim-free focus aid for federal employees",
    "solicitationNumber": "SOL-2026-001",
    "fullParentPathName": "GENERAL SERVICES ADMINISTRATION.FAS",
    "uiLink": "https://sam.gov/opp/n-100/view",
    "description": "https://api.sam.gov/opportunities/v1/noticedesc?noticeid=n-100",
    "postedDate": "2026-05-15",
    "type": "Solicitation",
    "award": {"amount": "500000", "date": "2026-05-20"},
}
_NOTICE_NO_AWARD = {
    "noticeId": "n-200",
    "title": "Caffeine-free wellness program",
    "solicitationNumber": "SOL-2026-002",
    "fullParentPathName": "DEPARTMENT OF DEFENSE.ARMY",
    "uiLink": "https://sam.gov/opp/n-200/view",
    "description": "https://api.sam.gov/opportunities/v1/noticedesc?noticeid=n-200",
    "postedDate": "2026-05-10",
    "type": "Presolicitation",
    # No "award" block at all → rfp_budget must be OMITTED (not 0.0).
}

_SEARCH_PAYLOAD = {
    "totalRecords": 2,
    "limit": 100,
    "offset": 0,
    "opportunitiesData": [_NOTICE_WITH_AWARD, _NOTICE_NO_AWARD],
}


class _StubResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _StubClient:
    """A minimal httpx.Client stand-in: returns a fixed payload, records calls."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        self.calls.append((url, params))
        # After the first page the offset passes totalRecords, so the connector
        # stops; return the same single page each call (the dedup guard handles it).
        return _StubResponse(self._payload)

    def close(self) -> None:
        return None


def _source(payload: Any = _SEARCH_PAYLOAD, *, key: str | None = "dev-key") -> SamGovItemSource:
    return SamGovItemSource(key=key, client=_StubClient(payload))


# ── Helper-level mapping ──────────────────────────────────────────────────────


def test_award_amount_parses_present_omits_absent() -> None:
    assert _award_amount({"amount": "500000"}) == 500000.0
    assert _award_amount({"amount": "$1,250,000.50"}) == 1250000.50
    # Absent / zero / non-positive / non-dict → None (OMIT, never 0.0).
    assert _award_amount({"amount": "0"}) is None
    assert _award_amount({"amount": None}) is None
    assert _award_amount({}) is None
    assert _award_amount(None) is None
    assert _award_amount({"amount": True}) is None


def test_registrable_domain_strips_www() -> None:
    assert _registrable_domain("https://sam.gov/opp/n-100/view") == "sam.gov"
    assert _registrable_domain("https://www.sam.gov/x") == "sam.gov"


# ── search → notice → unit ────────────────────────────────────────────────────


def test_maps_notice_with_agency_as_author() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    assert [r.source_id for r in records] == ["n-100", "n-200"]
    r = records[0]
    assert isinstance(r, CorpusRecord)
    assert r.source == "samgov"
    assert r.id == "samgov_n-100"
    assert r.url == "https://sam.gov/opp/n-100/view"
    assert r.title == "Stim-free focus aid for federal employees"
    # The solicitation number is appended to the verbatim, quotable statement of need.
    assert "Solicitation SOL-2026-001" in r.text
    # The contracting agency is the "author".
    assert r.author_hash == "agency:GENERAL SERVICES ADMINISTRATION.FAS"
    assert r.engagement == 0  # a solicitation has no native engagement
    assert r.extra["agency"] == "GENERAL SERVICES ADMINISTRATION.FAS"
    assert r.extra["domain"] == "sam.gov"
    assert r.extra["solicitation_number"] == "SOL-2026-001"
    # The description is a URL kept for a downstream deep-fetch, not inlined.
    assert r.extra["description_url"].startswith("https://api.sam.gov/")
    assert r.created_at == datetime(2026, 5, 15, tzinfo=UTC)


def test_rfp_budget_attached_when_award_present() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    with_award = next(r for r in records if r.source_id == "n-100")
    assert with_award.signals == {"rfp_budget": 500000.0}


def test_rfp_budget_omitted_not_zero_when_absent() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    no_award = next(r for r in records if r.source_id == "n-200")
    # OMITTED entirely — never present as 0.0.
    assert "rfp_budget" not in no_award.signals
    assert no_award.signals == {}


# ── yields_units + breadth + request shape ────────────────────────────────────


def test_yields_units_and_domain_breadth() -> None:
    src = _source()
    assert src.yields_units is True
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    assert all(r.extra["domain"] for r in records)  # the unit-source breadth axis


def test_pull_sends_keyword_and_window_and_key_params() -> None:
    client = _StubClient(_SEARCH_PAYLOAD)
    src = SamGovItemSource(key="secret-key", client=client)
    window = SourceWindow(
        start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 31, tzinfo=UTC)
    )
    list(src.pull(query="focus aid", window=window, limit=None))
    url, params = client.calls[0]
    assert url.endswith("/opportunities/v2/search")
    assert params is not None
    assert params["title"] == "focus aid"
    assert params["api_key"] == "secret-key"
    assert params["postedFrom"] == "05/01/2026"
    assert params["postedTo"] == "05/31/2026"


def test_unkeyed_source_omits_api_key_param() -> None:
    # The selector skips an unkeyed source, but construction never errors and a pull
    # simply omits api_key (the live API would 401, which is the selector's concern).
    client = _StubClient(_SEARCH_PAYLOAD)
    src = SamGovItemSource(key=None, client=client)
    list(src.pull(query="focus", window=SourceWindow(), limit=1))
    _url, params = client.calls[0]
    assert params is not None
    assert "api_key" not in params


def test_pull_honors_limit_and_dedups() -> None:
    src = _source()
    records = list(src.pull(query="focus", window=SourceWindow(), limit=1))
    assert len(records) == 1


def test_window_clamps_to_one_year_when_open() -> None:
    client = _StubClient(_SEARCH_PAYLOAD)
    src = SamGovItemSource(key="k", client=client)
    list(src.pull(query="x", window=SourceWindow(), limit=1))
    _url, params = client.calls[0]
    assert params is not None
    start = datetime.strptime(params["postedFrom"], "%m/%d/%Y")
    end = datetime.strptime(params["postedTo"], "%m/%d/%Y")
    assert 364 <= (end - start).days <= 366


# ── Comments + window ─────────────────────────────────────────────────────────


def test_comments_for_returns_none() -> None:
    # Solicitations have no comment layer → None (run recorded comment-less).
    assert _source().comments_for(["samgov_n-100"]) is None


def test_latest_window_is_bounded_trailing_year() -> None:
    win = _source().latest_window()
    assert isinstance(win, SourceWindow)
    assert win.start is not None
    assert win.end is not None
    assert 364 <= (win.end - win.start).days <= 366


# ── Conformance + registry ────────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    check_item_source(_source(), query="focus", window=SourceWindow(), limit=None)


def test_get_source_resolves_samgov() -> None:
    src = get_source("samgov", key="dev-key", client=_StubClient(_SEARCH_PAYLOAD))
    assert isinstance(src, SamGovItemSource)
    assert src.source_id == "samgov"
    assert isinstance(src, ItemSource)


def test_samgov_registers_in_sources() -> None:
    import metalworks.research.sources.samgov  # noqa: F401
    from metalworks.research.sources import SOURCE_SPECS, SOURCES

    assert "samgov" in SOURCES
    spec = SOURCE_SPECS["samgov"]
    assert spec.lane == "grounding"
    assert spec.signals == ("rfp_budget",)
    assert spec.targeting == "keyword"
    assert spec.auth == "key"
    assert spec.access == "free_key"
    assert spec.env == ("SAM_GOV_API_KEY",)


# ── Real-network smoke (deselected by default) ───────────────────────────────


@pytest.mark.network
def test_real_samgov_smoke() -> None:
    key = os.environ.get("SAM_GOV_API_KEY")
    if not key:
        pytest.skip("SAM_GOV_API_KEY not set")
    src = SamGovItemSource(key=key)
    records = list(src.pull(query="software", window=src.latest_window(), limit=3))
    assert records
    assert all(r.source == "samgov" and r.id and r.url for r in records)
    assert all(r.extra.get("domain") for r in records)
