"""Pillar B — positioning: deterministic wedge selection, grounded phrasing.

Offline. FakeChatModel is scripted per output_model (the one phrasing call + the
entailment check); the DemandReport fixture carries clusters/quotes/web/price +
cross-references so the white-space selection and evidence resolution run for
real. No network, no keys.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import (
    CrossReference,
    DemandReport,
    Fork,
    InsightCluster,
    PriceEvidence,
    PriceFinding,
    ResolvedCitation,
    SignalStrength,
    WebFinding,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.synthesis.positioning import (
    _Entailment,
    _WedgePhrasing,
    build_positioning_brief,
)
from metalworks.stores import MemoryStores

# ── fixtures ─────────────────────────────────────────────────────────────────


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        raise NotImplementedError

    def pull_subreddit(self, **_kwargs: Any) -> Any:
        raise NotImplementedError

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _quote(text: str, permalink: str, author_hash: str = "a1") -> ResolvedCitation:
    return ResolvedCitation(
        text=text, source_url=permalink, source_name="r/SkincareAddiction", author_hash=author_hash
    )


def _cluster(
    rank: int,
    *,
    quotes: list[ResolvedCitation],
    signal: SignalStrength = SignalStrength.HIGH,
    demand_score: float = 10.0,
) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"consumers want outcome {rank} without the usual downside",
        demand_score=demand_score,
        distinct_author_count=len({q.author_hash for q in quotes}),
        mention_count=len(quotes),
        signal=signal,
        quotes=quotes,
    )


def _web(index: int) -> WebFinding:
    return WebFinding(
        finding_index=index,
        claim=f"market offers product {index}",
        specifics="$30 OTC",
        source_url=f"https://ex.com/{index}",
        source_title="Market",
        confidence=SignalStrength.MEDIUM,
    )


def _xref(rank: int, agreement: str, web: list[int] | None = None) -> CrossReference:
    return CrossReference(
        cluster_rank=rank, web_finding_indices=web or [], agreement=agreement, note=""
    )


def _report(
    *,
    clusters: list[InsightCluster],
    cross_references: list[CrossReference],
    web: list[WebFinding] | None = None,
    price: PriceFinding | None = None,
) -> DemandReport:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    return DemandReport(
        report_id="rpt-1",
        query="best fade for post-acne marks",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=63,
        total_distinct_authors=130,
        ranked_clusters=clusters,
        generated_at=now,
        web_findings=web or [],
        cross_references=cross_references,
        price_finding=price,
    )


def _deps(chat: FakeChatModel | None = None) -> ResearchDeps:
    return ResearchDeps(
        chat=chat or FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
    )


def _scripted_chat(
    *, attr_ok: bool = True, value_ok: bool = True, raise_on_phrasing: bool = False
) -> FakeChatModel:
    chat = FakeChatModel()
    if not raise_on_phrasing:
        chat.script(
            _WedgePhrasing,
            _WedgePhrasing(
                competitive_alternative="generic OTC azelaic creams",
                unique_attribute="targets PIE without the irritation users report",
                value="fade marks faster with less downtime",
                market_category="azelaic acid serum",
            ),
        )
    chat.script(
        _Entailment,
        _Entailment(unique_attribute_supported=attr_ok, value_supported=value_ok, note="check"),
    )
    return chat


# ── deterministic selection ──────────────────────────────────────────────────


def test_no_whitespace_returns_honest_null() -> None:
    # A strong cluster, but the web AGREES — no white space → honest null.
    c = _cluster(1, quotes=[_quote("PIE is the worst", "https://r/x/1")])
    report = _report(
        clusters=[c],
        cross_references=[_xref(1, "agree", [1])],
        web=[_web(1)],
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.wedge is None
    assert brief.partial is True
    assert "wedge" in brief.positioning_statement.lower()
    assert brief.caveat
    assert brief.report_id == "rpt-1"


def test_below_medium_signal_excluded() -> None:
    # Silent web, but the only candidate is LOW signal → excluded → null.
    c = _cluster(1, quotes=[_quote("niche pain", "https://r/x/1")], signal=SignalStrength.LOW)
    report = _report(
        clusters=[c],
        cross_references=[_xref(1, "silent_web")],
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.wedge is None
    assert brief.partial is True


def test_builds_wedge_from_silent_web_cluster() -> None:
    c = _cluster(1, quotes=[_quote("nothing fades PIE without burning", "https://r/x/1")])
    report = _report(
        clusters=[c],
        cross_references=[_xref(1, "silent_web", [1])],
        web=[_web(1)],
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.wedge is not None
    assert brief.partial is False
    assert brief.wedge.source_cluster_rank == 1
    assert brief.wedge.unique_attribute == "targets PIE without the irritation users report"
    # The Dunford statement weaves the slots together.
    assert "azelaic acid serum" in brief.positioning_statement
    assert brief.wedge.beachhead in brief.positioning_statement


def test_disagree_also_qualifies() -> None:
    c = _cluster(1, quotes=[_quote("the popular pick made it worse", "https://r/x/1")])
    report = _report(
        clusters=[c],
        cross_references=[_xref(1, "disagree", [1])],
        web=[_web(1)],
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.wedge is not None


def test_ranks_by_demand_score() -> None:
    lo = _cluster(1, quotes=[_quote("minor", "https://r/x/1")], demand_score=2.0)
    hi = _cluster(2, quotes=[_quote("major", "https://r/x/2")], demand_score=50.0)
    report = _report(
        clusters=[lo, hi],
        cross_references=[
            _xref(1, "silent_web"),
            _xref(2, "silent_web"),
        ],
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.wedge is not None
    assert brief.wedge.source_cluster_rank == 2  # higher demand_score wins


# ── grounding / verification ─────────────────────────────────────────────────


def test_wedge_evidence_resolves_against_report() -> None:
    q = _quote("nothing fades PIE without burning", "https://r/x/1")
    report = _report(
        clusters=[_cluster(1, quotes=[q])],
        cross_references=[_xref(1, "silent_web", [1])],
        web=[_web(1)],
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.wedge is not None
    evidence_ids = {e.id for e in report.evidence}
    # Every non-cluster ref resolves against the report's evidence (the spine).
    for ref in brief.wedge.evidence:
        if ref.kind == "cluster":
            assert ref.cluster_rank == 1
        else:
            assert ref.evidence_id in evidence_ids
    # The cited quote and web finding are both present.
    assert q.id in evidence_ids
    assert any(r.evidence_id == q.id for r in brief.wedge.evidence)


def test_entailment_failure_marks_partial() -> None:
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("just a vague wish", "https://r/x/1")])],
        cross_references=[_xref(1, "silent_web")],
    )
    brief = build_positioning_brief(_deps(_scripted_chat(attr_ok=False)), report)
    assert brief.wedge is not None  # wedge is still surfaced...
    assert brief.partial is True  # ...but flagged unverified
    assert "unique_attribute" in (brief.caveat or "")


def test_phrasing_failure_returns_partial_null() -> None:
    # No _WedgePhrasing scripted → FakeChatModel raises → caught → partial null.
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("real pain", "https://r/x/1")])],
        cross_references=[_xref(1, "silent_web")],
    )
    brief = build_positioning_brief(_deps(_scripted_chat(raise_on_phrasing=True)), report)
    assert brief.wedge is None
    assert brief.partial is True
    assert "unavailable" in (brief.caveat or "").lower()


# ── price copy-through ───────────────────────────────────────────────────────


def test_price_hypothesis_copied_through() -> None:
    pe = PriceEvidence(
        text="$45 feels right", kind="willingness", amount=45.0, permalink="https://r/x/9"
    )
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("p", "https://r/x/1")])],
        cross_references=[_xref(1, "silent_web")],
        price=PriceFinding(low=30.0, high=60.0, currency="USD", evidence=[pe]),
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.price_hypothesis is not None
    assert brief.price_hypothesis.low == 30.0
    assert brief.price_hypothesis.high == 60.0
    assert brief.price_hypothesis.insufficient_signal is False
    # Price evidence ref resolves against the report.
    assert any(r.evidence_id == pe.id for r in brief.price_hypothesis.evidence)


def test_price_insufficient_signal() -> None:
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("p", "https://r/x/1")])],
        cross_references=[_xref(1, "silent_web")],
        price=PriceFinding(insufficient_signal=True, evidence=[]),
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.price_hypothesis is not None
    assert brief.price_hypothesis.insufficient_signal is True
    assert brief.price_hypothesis.low is None


def test_no_price_finding_yields_none() -> None:
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("p", "https://r/x/1")])],
        cross_references=[_xref(1, "silent_web")],
    )
    brief = build_positioning_brief(_deps(_scripted_chat()), report)
    assert brief.price_hypothesis is None


# ── MCP tool ─────────────────────────────────────────────────────────────────


def test_mcp_positioning_from_report_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: MemoryStores())
    res = tools.positioning_from_report("nope")
    assert res["error"]["error_code"] == "not_found"


def test_mcp_positioning_from_report_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks import config
    from metalworks.mcp import tools

    store = MemoryStores()
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("nothing fades PIE", "https://r/x/1")])],
        cross_references=[_xref(1, "silent_web", [1])],
        web=[_web(1)],
    )
    store.save_report(report)
    monkeypatch.setattr(config, "default_store", lambda *_a, **_k: store)
    monkeypatch.setattr(config, "resolve_chat", lambda *_a, **_k: _scripted_chat())
    monkeypatch.setattr(config, "resolve_embeddings", lambda *_a, **_k: FakeEmbedding())
    monkeypatch.setattr(config, "resolve_search", lambda *_a, **_k: None)
    monkeypatch.setattr("metalworks.research.arctic.ArcticReader", lambda *a, **k: _NullReader())
    res = tools.positioning_from_report(report.report_id)
    assert "positioning" in res
    assert res["positioning"]["report_id"] == "rpt-1"
    assert res["positioning"]["wedge"]["source_cluster_rank"] == 1
