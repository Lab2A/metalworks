"""ATSItemSource tests — OFFLINE (pytest-socket blocks real network).

We feed canned Greenhouse / Lever / Ashby board JSON through a stub httpx client
(no network) and assert the connector satisfies the :class:`ItemSource` protocol,
maps each vendor's postings to self-representing (``yields_units``) records (JD
text + permalink + company), filters to the brief's terms, ranks by distinct
company/domain breadth, returns ``None`` from ``comments_for``, and resolves
through the registry. The connector imports only the core stack (stdlib + lazy
httpx), so this whole module runs on the bare CI variant.

A real-network smoke test is gated behind ``@pytest.mark.network`` (deselected by
default; run with ``-m network --enable-socket``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import CorpusRecord
from metalworks.research.sources import ItemSource, SourceWindow, get_source
from metalworks.research.sources.ats import (
    CURATED_SLUGS,
    ATSItemSource,
    _clean_html,
    _registrable_domain,
)
from metalworks.testing import check_item_source

_NOW = datetime(2026, 6, 1, tzinfo=UTC)

# ── Canned vendor board payloads ──────────────────────────────────────────────

_GREENHOUSE = {
    "jobs": [
        {
            "id": 800,
            "title": "Staff Engineer, Focus Tooling",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/800",
            "content": "&lt;p&gt;Build focus tools for developers.&lt;/p&gt;",
            "updated_at": "2026-05-20T00:00:00Z",
            "location": {"name": "Remote"},
        },
        {
            # No matching term ('focus'/'tooling') → filtered out by the query.
            "id": 801,
            "title": "Office Manager",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/801",
            "content": "&lt;p&gt;Run the office.&lt;/p&gt;",
            "updated_at": "2026-05-19T00:00:00Z",
            "location": {"name": "NYC"},
        },
    ]
}

# Lever returns a TOP-LEVEL list (not under "jobs").
_LEVER = [
    {
        "id": "lev-1",
        "text": "Senior Focus Platform Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/lev-1",
        "descriptionPlain": "Own the focus platform. No caffeine required.",
        "createdAt": 1_747_699_200_000,  # 2025-05-20 in ms
        "categories": {"location": "Remote"},
    }
]

_ASHBY = {
    "jobs": [
        {
            "id": "ash-1",
            "title": "Focus Infrastructure Lead",
            "jobUrl": "https://jobs.ashbyhq.com/acme/ash-1",
            "descriptionPlain": "Lead focus infrastructure for the platform.",
            "publishedAt": "2026-05-18T00:00:00Z",
            "location": "Remote",
        }
    ]
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
        return _StubResponse(self._payload)

    def close(self) -> None:
        return None


def _source(provider: str, payload: Any, *, slug: str = "acme") -> ATSItemSource:
    return ATSItemSource(provider=provider, slug=slug, client=_StubClient(payload))


# ── Helper-level mapping ──────────────────────────────────────────────────────


def test_clean_html_unescapes_then_strips() -> None:
    assert _clean_html("&lt;p&gt;Hi&lt;/p&gt;there") == "Hi\nthere"
    assert _clean_html("plain text, no tags") == "plain text, no tags"
    assert _clean_html(None) == ""


def test_registrable_domain_strips_www_keeps_subdomain() -> None:
    # Like web.py: only a leading www. is stripped — a subdomain host is the breadth
    # axis (each company board lives on its own host), so it is kept verbatim.
    assert _registrable_domain("https://boards.greenhouse.io/acme/jobs/1") == "boards.greenhouse.io"
    assert _registrable_domain("https://www.example.com/x") == "example.com"


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        ATSItemSource(provider="workday", slug="acme")


def test_curated_slugs_are_data() -> None:
    # The curated registry is seeded DATA (no discovery endpoint exists).
    assert set(CURATED_SLUGS) == {"greenhouse", "lever", "ashby"}
    assert all(CURATED_SLUGS[v] for v in CURATED_SLUGS)


# ── Per-provider board → postings → units ─────────────────────────────────────


def test_greenhouse_maps_postings_and_filters_by_query() -> None:
    src = _source("greenhouse", _GREENHOUSE)
    records = list(src.pull(query="focus tooling", window=SourceWindow(), limit=None))

    # Only the matching posting survives the term filter.
    assert [r.source_id for r in records] == ["800"]
    r = records[0]
    assert isinstance(r, CorpusRecord)
    assert r.source == "ats"
    assert r.id == "ats_greenhouse_acme_800"
    assert r.url == "https://boards.greenhouse.io/acme/jobs/800"
    assert r.title == "Staff Engineer, Focus Tooling"
    assert r.text == "Build focus tools for developers."  # HTML unescaped + stripped
    assert r.author_hash == "company:acme"  # the company is the "author"
    assert r.engagement == 0  # a JD has no native engagement
    assert r.signals == {}  # no per-record signal — breadth carries demand
    assert r.extra["domain"] == "boards.greenhouse.io"
    assert r.extra["company"] == "acme"
    assert r.extra["provider"] == "greenhouse"
    assert r.created_at == datetime(2026, 5, 20, tzinfo=UTC)


def test_lever_maps_top_level_list() -> None:
    src = _source("lever", _LEVER)
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    assert len(records) == 1
    r = records[0]
    assert r.id == "ats_lever_acme_lev-1"
    assert r.url == "https://jobs.lever.co/acme/lev-1"
    assert r.title == "Senior Focus Platform Engineer"
    assert r.text == "Own the focus platform. No caffeine required."
    assert r.extra["domain"] == "jobs.lever.co"
    assert isinstance(r, CorpusRecord)


def test_ashby_maps_postings() -> None:
    src = _source("ashby", _ASHBY)
    records = list(src.pull(query="focus", window=SourceWindow(), limit=None))
    assert len(records) == 1
    r = records[0]
    assert r.id == "ats_ashby_acme_ash-1"
    assert r.url == "https://jobs.ashbyhq.com/acme/ash-1"
    assert r.title == "Focus Infrastructure Lead"
    assert r.text == "Lead focus infrastructure for the platform."
    assert r.extra["domain"] == "jobs.ashbyhq.com"


def test_empty_query_keeps_whole_board() -> None:
    src = _source("greenhouse", _GREENHOUSE)
    records = list(src.pull(query="", window=SourceWindow(), limit=None))
    assert {r.source_id for r in records} == {"800", "801"}


def test_pull_honors_limit_and_dedups() -> None:
    src = _source("greenhouse", _GREENHOUSE)
    records = list(src.pull(query="", window=SourceWindow(), limit=1))
    assert len(records) == 1


def test_pull_filters_by_window() -> None:
    src = _source("greenhouse", _GREENHOUSE)
    # Window ends before either posting's updated_at → nothing in range.
    window = SourceWindow(end=datetime(2026, 5, 1, tzinfo=UTC))
    assert list(src.pull(query="", window=window, limit=None)) == []


def test_empty_slug_pulls_nothing() -> None:
    src = ATSItemSource(provider="greenhouse", slug="", client=_StubClient(_GREENHOUSE))
    assert list(src.pull(query="focus", window=SourceWindow(), limit=None)) == []


# ── yields_units + domain breadth ─────────────────────────────────────────────


def test_yields_units_and_domain_breadth() -> None:
    src = _source("greenhouse", _GREENHOUSE)
    assert src.yields_units is True
    records = list(src.pull(query="", window=SourceWindow(), limit=None))
    domains = {r.extra["domain"] for r in records}
    assert domains == {"boards.greenhouse.io"}  # the unit-source breadth axis is domain
    assert all(r.extra["domain"] for r in records)


def test_query_request_params_per_provider() -> None:
    client = _StubClient(_GREENHOUSE)
    gh = ATSItemSource(provider="greenhouse", slug="acme", client=client)
    list(gh.pull(query="focus", window=SourceWindow(), limit=None))
    url, params = client.calls[0]
    assert url.endswith("/acme/jobs")
    assert params == {"content": "true"}


# ── Comments + window ─────────────────────────────────────────────────────────


def test_comments_for_returns_none() -> None:
    # ATS postings have no comment layer → None (run recorded comment-less).
    assert _source("greenhouse", _GREENHOUSE).comments_for(["ats_greenhouse_acme_800"]) is None


def test_latest_window_open_start() -> None:
    win = _source("greenhouse", _GREENHOUSE).latest_window()
    assert isinstance(win, SourceWindow)
    assert win.start is None
    assert win.end is not None


# ── Conformance + registry ────────────────────────────────────────────────────


def test_conformance_check_passes() -> None:
    check_item_source(
        _source("greenhouse", _GREENHOUSE), query="focus", window=SourceWindow(), limit=None
    )


def test_get_source_resolves_ats() -> None:
    src = get_source("ats", provider="greenhouse", slug="acme", client=_StubClient(_GREENHOUSE))
    assert isinstance(src, ATSItemSource)
    assert src.source_id == "ats"
    assert isinstance(src, ItemSource)


def test_ats_registers_in_sources() -> None:
    import metalworks.research.sources.ats  # noqa: F401
    from metalworks.research.sources import SOURCE_SPECS, SOURCES

    assert "ats" in SOURCES
    spec = SOURCE_SPECS["ats"]
    assert spec.lane == "grounding"
    assert spec.signals == ()
    assert spec.targeting == "slug"
    assert spec.auth == "none"
    assert spec.access == "open"


# ── Real-network smoke (deselected by default) ───────────────────────────────


@pytest.mark.network
def test_real_greenhouse_smoke() -> None:
    # Stripe runs a public Greenhouse board; this is a live read.
    src = ATSItemSource(provider="greenhouse", slug="stripe")
    records = list(src.pull(query="engineer", window=SourceWindow(), limit=3))
    assert records
    assert all(r.source == "ats" and r.id and r.url for r in records)
    assert all(r.extra.get("domain") for r in records)
