"""Evidence-id scheme + EvidenceRef/EvidenceRecord + report.evidence.

The spine of the cross-pillar grounded-evidence chain. These guarantees are
what every downstream pillar (positioning, competitors, site, launch,
content) depends on, so they get exhaustive coverage:

- ids are content-addressed, deterministic, and stable across (de)serialization
- ids are prefixed per evidence family (q:/w:/p:) and survive an input `id`
- report.evidence collates all three families with correct provenance labels
- report.evidence de-dups a quote shared by multiple clusters
- an EvidenceRef resolves against report.evidence exactly (no-cite-no-claim)
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import (
    DemandReport,
    EvidenceRecord,
    EvidenceRef,
    Fork,
    InsightCluster,
    PriceEvidence,
    PriceFinding,
    ResolvedCitation,
    SignalStrength,
    WebFinding,
)


def _quote(text: str, permalink: str, author_hash: str = "a1") -> ResolvedCitation:
    return ResolvedCitation(
        text=text, source_url=permalink, source_name="r/Supplements", author_hash=author_hash
    )


def _cluster(rank: int, quotes: list[ResolvedCitation]) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"claim {rank}",
        demand_score=1.0,
        distinct_author_count=len({q.author_hash for q in quotes}),
        mention_count=len(quotes),
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _report(
    *,
    clusters: list[InsightCluster],
    web: list[WebFinding] | None = None,
    price: PriceFinding | None = None,
) -> DemandReport:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return DemandReport(
        report_id="r1",
        query="q",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=1,
        total_distinct_authors=1,
        ranked_clusters=clusters,
        generated_at=now,
        web_findings=web or [],
        price_finding=price,
    )


# ── id determinism / stability ──────────────────────────────────────────────


def test_quote_id_is_content_addressed_and_author_independent() -> None:
    a = _quote("too sweet", "https://r/x/1", author_hash="aaa")
    b = _quote("too sweet", "https://r/x/1", author_hash="zzz")
    assert a.id == b.id  # id is (source_url, text) only — engagement/author don't move it
    assert a.id.startswith("q:")


def test_quote_id_changes_with_content() -> None:
    a = _quote("too sweet", "https://r/x/1")
    assert a.id != _quote("too sweet", "https://r/x/2").id  # different source_url
    assert a.id != _quote("too bitter", "https://r/x/1").id  # different text


def test_unit_separator_prevents_collision() -> None:
    # ("ab","c") must not collide with ("a","bc")
    assert _quote("c", "https://ab").id != _quote("bc", "https://a").id


def test_web_and_price_id_prefixes() -> None:
    w = WebFinding(
        finding_index=1,
        claim="market is 2B",
        specifics="2B",
        source_url="https://ex.com",
        source_title="T",
        confidence=SignalStrength.HIGH,
    )
    p = PriceEvidence(text="$40 is fair", kind="willingness", permalink="https://r/x/9")
    assert w.id.startswith("w:")
    assert p.id.startswith("p:")


def test_id_survives_round_trip_and_ignores_injected_id() -> None:
    q = _quote("too sweet", "https://r/x/1")
    dumped = q.model_dump()
    assert dumped["id"] == q.id  # computed id serializes
    # a reload that carries a bogus id in the payload recomputes from content
    reloaded = ResolvedCitation(**{**dumped, "id": "q:deadbeef"})
    assert reloaded.id == q.id


# ── report.evidence collation ────────────────────────────────────────────────


def test_report_evidence_collates_all_families_with_provenance() -> None:
    q = _quote("verbatim voice", "https://r/x/1")
    w = WebFinding(
        finding_index=1,
        claim="web claim",
        specifics="x",
        source_url="https://ex.com",
        source_title="T",
        confidence=SignalStrength.MEDIUM,
    )
    p_cited = PriceEvidence(text="$40", kind="point", permalink="https://r/x/9")
    p_uncited = PriceEvidence(text="cheap", kind="vibe")
    report = _report(
        clusters=[_cluster(1, [q])],
        web=[w],
        price=PriceFinding(evidence=[p_cited, p_uncited]),
    )
    by_id = {r.id: r for r in report.evidence}
    assert all(isinstance(r, EvidenceRecord) for r in report.evidence)
    assert by_id[q.id].provenance == "verbatim"
    assert by_id[q.id].url == "https://r/x/1"
    assert by_id[w.id].provenance == "grounded-web"
    assert by_id[w.id].url == "https://ex.com"
    assert by_id[p_cited.id].provenance == "verbatim"  # has a permalink
    assert by_id[p_uncited.id].provenance == "derived"  # no permalink
    assert by_id[p_uncited.id].url == ""


def test_report_evidence_dedups_quote_shared_across_clusters() -> None:
    q = _quote("shared voice", "https://r/x/1")
    report = _report(clusters=[_cluster(1, [q]), _cluster(2, [q])])
    matching = [r for r in report.evidence if r.id == q.id]
    assert len(matching) == 1  # de-duped, even though two clusters cite it


def test_report_with_no_price_finding_has_only_quote_and_web_evidence() -> None:
    q = _quote("voice", "https://r/x/1")
    report = _report(clusters=[_cluster(1, [q])])
    assert {r.kind for r in report.evidence} == {"quote"}


# ── EvidenceRef resolution (no-cite-no-claim) ────────────────────────────────


def test_evidence_ref_resolves_against_report() -> None:
    q = _quote("voice", "https://r/x/1")
    report = _report(clusters=[_cluster(1, [q])])
    index = {r.id: r for r in report.evidence}

    good = EvidenceRef(evidence_id=q.id, kind="quote")
    bad = EvidenceRef(evidence_id="q:doesnotexist", kind="quote")
    assert good.evidence_id in index  # resolves
    assert bad.evidence_id not in index  # unresolvable → claim would be dropped


def test_cluster_ref_carries_rank_not_leaf_id() -> None:
    ref = EvidenceRef(kind="cluster", cluster_rank=3)
    assert ref.evidence_id == ""  # clusters have no leaf id
    assert ref.cluster_rank == 3
