"""The two-shape citation contract (Phase 1c).

`ResolvedCitation` is the MATERIALIZED, portable citation form — the one that
serializes into ``runs/*.json`` and every MCP response. Its load-bearing
guarantee: it carries the verbatim ``text`` + ``source_url`` + ``author_hash``
INLINE, so a report stays readable and provenance-linked when it is DETACHED
from the corpus (committed to git, sent over the wire). These tests pin that
guarantee — a citation round-trips through JSON with NO corpus present and still
renders, and the thin `CitationRef` form stays a faithful pointer to it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import (
    CitationRef,
    DemandReport,
    Fork,
    InsightCluster,
    Research,
    ResolvedCitation,
    SignalStrength,
)
from metalworks.runs import render_run_markdown


def _quote() -> ResolvedCitation:
    return ResolvedCitation(
        record_id="c_abc123",
        source="reddit",
        source_name="r/Supplements",
        source_url="https://reddit.com/r/Supplements/comments/x/c/",
        text="I'd pay for a clean focus supplement that doesn't wreck my sleep",
        author_hash="a1",
        engagement=42,
    )


def test_resolved_citation_carries_text_and_url_inline() -> None:
    q = _quote()
    # The portable form is self-contained: text + url + author live ON it.
    assert q.text.startswith("I'd pay")
    assert q.source_url.startswith("https://")
    assert q.author_hash == "a1"
    # Content-addressed id, hashed from (source_url, text) — Reddit-independent.
    assert q.id.startswith("q:")


def test_round_trip_with_no_corpus_preserves_text_url_author() -> None:
    """The portability guarantee: serialize, drop the corpus, reload — verbatim
    text + provenance url + author survive byte-for-byte, no corpus needed."""
    q = _quote()
    dumped = q.model_dump_json()
    # Simulate a detached report: nothing but the JSON string remains.
    reloaded = ResolvedCitation.model_validate_json(dumped)
    assert reloaded.text == q.text
    assert reloaded.source_url == q.source_url
    assert reloaded.author_hash == q.author_hash
    assert reloaded.source == q.source
    assert reloaded.source_name == q.source_name
    assert reloaded.engagement == q.engagement
    # The stable evidence id survives the round trip (recomputed from content).
    assert reloaded.id == q.id


def test_id_is_stable_and_independent_of_engagement_and_author() -> None:
    a = ResolvedCitation(text="same", source_url="https://x/1", author_hash="a", engagement=1)
    b = ResolvedCitation(text="same", source_url="https://x/1", author_hash="z", engagement=999)
    assert a.id == b.id  # id is (source_url, text) only
    c = ResolvedCitation(text="same", source_url="https://x/2", author_hash="a")
    assert a.id != c.id  # different url → different id


def test_citation_ref_is_a_faithful_thin_pointer() -> None:
    q = _quote()
    ref = q.as_ref()
    assert isinstance(ref, CitationRef)
    assert ref.evidence_id == q.id
    assert ref.record_id == q.record_id
    assert ref.kind == "quote"


def _report_with_quote(q: ResolvedCitation) -> DemandReport:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    cluster = InsightCluster(
        rank=1,
        claim="People want a clean-label focus supplement",
        demand_score=1.0,
        distinct_author_count=1,
        mention_count=1,
        signal=SignalStrength.HIGH,
        quotes=[q],
    )
    return DemandReport(
        report_id="rep-1",
        query="demand for a focus supplement?",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=1,
        total_distinct_authors=1,
        ranked_clusters=[cluster],
        generated_at=now,
        demand_summary="Go.",
    )


def test_detached_report_still_renders_markdown_with_corpus_absent() -> None:
    """A report reloaded from JSON (no corpus, no stores) still renders its
    quote + provenance link — the whole point of materializing the citation."""
    report = _report_with_quote(_quote())
    research = Research(demand=report)

    # Drop the corpus entirely: keep only the serialized JSON, then reload.
    raw = research.model_dump_json()
    detached = Research.model_validate_json(raw)

    md = render_run_markdown(detached)
    assert "I'd pay for a clean focus supplement" in md  # verbatim text present
    assert "https://reddit.com/r/Supplements/comments/x/c/" in md  # provenance link present
    assert "r/Supplements" in md  # human-readable source label present


def test_report_evidence_resolves_from_resolved_citation_with_no_corpus() -> None:
    """`DemandReport.evidence` builds EvidenceRecords from the inline citation
    fields (source_url / text) — it needs no corpus to resolve."""
    q = _quote()
    report = _report_with_quote(q)
    detached = DemandReport.model_validate_json(report.model_dump_json())
    by_id = {r.id: r for r in detached.evidence}
    rec = by_id[q.id]
    assert rec.kind == "quote"
    assert rec.text == q.text
    assert rec.url == q.source_url  # url comes from source_url, not a Reddit permalink
    assert rec.provenance == "verbatim"
