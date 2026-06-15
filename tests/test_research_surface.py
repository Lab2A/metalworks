"""Pillar C — surface decision + UX skeleton.

Offline. FakeChatModel is scripted per output_model; FakeEmbedding makes
identical text cosine-match, so a rubric finding / screen purpose whose text
equals a real quote is grounded, and a non-matching one is an assumption /
hypothesis. cosine_topk needs numpy (the [research] extra).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("numpy")  # grounding uses cosine_topk (the [research] extra)

from metalworks.contract import (
    DemandReport,
    Fork,
    InsightCluster,
    PositioningBrief,
    ResolvedCitation,
    SignalStrength,
    WebFinding,
    WedgeClaim,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.surface import (
    _RubricItem,
    _ScreenItem,
    _SurfacePhrasing,
    _UxPhrasing,
    build_ux_skeleton,
    decide_surface,
)
from metalworks.stores import MemoryStores

_CLOCK = datetime(2026, 2, 3, tzinfo=UTC)


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        raise NotImplementedError

    def pull_subreddit(self, **_kwargs: Any) -> Any:
        raise NotImplementedError

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _quote(text: str, permalink: str) -> ResolvedCitation:
    return ResolvedCitation(text=text, source_url=permalink, source_name="r/X", author_hash="a1")


def _cluster(rank: int, *, quotes: list[ResolvedCitation]) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"pain {rank}",
        demand_score=10.0,
        distinct_author_count=len(quotes),
        mention_count=len(quotes),
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _report(*, clusters: list[InsightCluster], web: list[WebFinding] | None = None) -> DemandReport:
    return DemandReport(
        report_id="rpt-1",
        query="a dev tool for X",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=_CLOCK,
        date_range_end=_CLOCK,
        total_threads=10,
        total_distinct_authors=20,
        ranked_clusters=clusters,
        generated_at=_CLOCK,
        web_findings=web or [],
    )


def _positioning() -> PositioningBrief:
    return PositioningBrief(
        report_id="rpt-1",
        positioning_statement="stmt",
        wedge=WedgeClaim(
            competitive_alternative="a",
            unique_attribute="does the thing fast",
            value="b",
            beachhead="devs",
            market_category="dev tool",
            source_cluster_rank=1,
        ),
    )


def _deps(chat: FakeChatModel) -> ResearchDeps:
    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        clock=lambda: _CLOCK,
    )


# ── decide_surface ───────────────────────────────────────────────────────────


def test_grounds_matched_dims_and_marks_assumptions() -> None:
    g1 = "users live in the terminal all day"
    g2 = "they script everything and hate guis"
    report = _report(
        clusters=[_cluster(1, quotes=[_quote(g1, "https://r/1"), _quote(g2, "https://r/2")])]
    )
    phrasing = _SurfacePhrasing(
        chosen="cli",
        runner_up="web",
        rationale="devs live in the shell",
        rubric=[
            _RubricItem(name="where_are_the_users", finding=g1),  # grounded
            _RubricItem(name="technical_sophistication", finding=g2),  # grounded
            _RubricItem(name="usage_frequency", finding="probably daily, guessing"),  # assumption
            _RubricItem(name="realtime_or_hardware", finding="no special needs"),  # assumption
            _RubricItem(name="distribution", finding="npm maybe"),  # assumption
        ],
        trade_offs=["no GUI discoverability"],
    )
    chat = FakeChatModel()
    chat.script(_SurfacePhrasing, phrasing)
    rec = decide_surface(_deps(chat), report, _positioning())
    assert rec.chosen == "cli"
    assert rec.runner_up == "web"
    by = {d.name: d for d in rec.rubric}
    assert by["where_are_the_users"].is_assumption is False
    assert by["where_are_the_users"].evidence_refs
    assert by["usage_frequency"].is_assumption is True
    assert by["usage_frequency"].evidence_refs == []
    assert rec.confidence == SignalStrength.MEDIUM  # exactly 2 grounded
    assert rec.partial is False
    assert rec.generated_at == _CLOCK


def test_thin_grounding_marks_partial() -> None:
    g1 = "the one matching complaint"
    report = _report(clusters=[_cluster(1, quotes=[_quote(g1, "https://r/1")])])
    phrasing = _SurfacePhrasing(
        chosen="web",
        rationale="r",
        rubric=[
            _RubricItem(name="where_are_the_users", finding=g1),  # only 1 grounded
            _RubricItem(name="distribution", finding="unrelated guess"),
        ],
        trade_offs=[],
    )
    chat = FakeChatModel()
    chat.script(_SurfacePhrasing, phrasing)
    rec = decide_surface(_deps(chat), report, _positioning())
    assert rec.partial is True
    assert rec.confidence == SignalStrength.LOW
    assert "hypothesis" in (rec.caveat or "")


def test_surface_phrasing_failure_returns_partial_default() -> None:
    report = _report(clusters=[_cluster(1, quotes=[_quote("q", "https://r/1")])])
    rec = decide_surface(_deps(FakeChatModel()), report, _positioning())  # no script → raises
    assert rec.partial is True
    assert rec.chosen == "web"
    assert "unavailable" in (rec.caveat or "").lower()


def test_rubric_refs_resolve_against_report() -> None:
    g1 = "users live in the terminal all day"
    q = _quote(g1, "https://r/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    phrasing = _SurfacePhrasing(
        chosen="cli",
        rationale="r",
        rubric=[_RubricItem(name="where_are_the_users", finding=g1)],
        trade_offs=[],
    )
    chat = FakeChatModel()
    chat.script(_SurfacePhrasing, phrasing)
    rec = decide_surface(_deps(chat), report, _positioning())
    evidence_ids = {e.id for e in report.evidence}
    refs = [r for d in rec.rubric for r in d.evidence_refs]
    assert refs
    for r in refs:
        assert r.evidence_id in evidence_ids


# ── build_ux_skeleton ────────────────────────────────────────────────────────


def test_screens_validated_when_backed_else_hypothesis() -> None:
    backed = "let me paste a snippet and get a fix"
    report = _report(clusters=[_cluster(1, quotes=[_quote(backed, "https://r/1")])])
    phrasing = _UxPhrasing(
        screens=[
            _ScreenItem(name="Paste", purpose=backed, primary_action="paste", serves_wedge=True),
            _ScreenItem(name="Settings", purpose="configure obscure prefs", primary_action="save"),
        ]
    )
    chat = FakeChatModel()
    chat.script(_UxPhrasing, phrasing)
    sk = build_ux_skeleton(_deps(chat), report, _positioning(), "web")
    assert sk.surface == "web"
    paste = next(s for s in sk.screens if s.name == "Paste")
    settings = next(s for s in sk.screens if s.name == "Settings")
    assert paste.validated is True
    assert paste.evidence_refs
    assert settings.validated is False
    assert settings.evidence_refs == []
    assert sk.partial is True  # one unvalidated screen
    assert "unvalidated" in (sk.caveat or "")


def test_ux_phrasing_failure_returns_partial() -> None:
    report = _report(clusters=[_cluster(1, quotes=[_quote("q", "https://r/1")])])
    sk = build_ux_skeleton(_deps(FakeChatModel()), report, _positioning(), "cli")  # no script
    assert sk.partial is True
    assert sk.surface == "cli"
    assert sk.screens == []


# ── MCP tools ────────────────────────────────────────────────────────────────


def test_mcp_surface_recommend_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    assert tools.surface_recommend("nope")["error"]["error_code"] == "not_found"


def test_mcp_surface_recommend_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools
    from metalworks.research import arctic

    g1 = "users live in the terminal all day"
    report = _report(clusters=[_cluster(1, quotes=[_quote(g1, "https://r/1")])])
    store = MemoryStores()
    store.save_report(report)
    chat = FakeChatModel()
    chat.script(
        _SurfacePhrasing,
        _SurfacePhrasing(
            chosen="cli",
            rationale="r",
            rubric=[_RubricItem(name="where_are_the_users", finding=g1)],
            trade_offs=[],
        ),
    )
    # surface_recommend also builds positioning first → script its phrasing as a no-op fallback.
    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    monkeypatch.setattr(config, "resolve_chat", lambda *_a, **_k: chat)
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr(arctic, "ArcticReader", lambda *a, **k: _NullReader())
    res = tools.surface_recommend(report.report_id)
    assert "surface_recommendation" in res
    assert res["surface_recommendation"]["chosen"] == "cli"
