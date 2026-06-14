"""Pillar E — marketing site: constrained role/fragment selection, exact-match grounding.

Offline. FakeChatModel is scripted on the ONE ``_SitePhrasing`` output; the
DemandReport fixture carries clusters with verified quotes so the exact-match
grounding, the no-quote-no-section drop, the connective claim-free gate, the
hero-by-distinct-author selection, and the HTML footnote all run for real. No
network, no keys, no numpy (exact-match, not embeddings).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from metalworks.contract import (
    DemandReport,
    Fork,
    InsightCluster,
    QuoteCitation,
    SignalStrength,
)
from metalworks.contract.site import MarketingSite
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.site import (
    _ConnectivePhrasing,
    _SectionPhrasing,
    _SitePhrasing,
    build_marketing_site,
    render_site_html,
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


def _quote(text: str, permalink: str, author_hash: str = "a1") -> QuoteCitation:
    return QuoteCitation(
        text=text, permalink=permalink, subreddit="SkincareAddiction", author_hash=author_hash
    )


def _cluster(
    rank: int,
    *,
    quotes: list[QuoteCitation],
    demand_score: float = 10.0,
    distinct_author_count: int | None = None,
) -> InsightCluster:
    distinct = (
        distinct_author_count
        if distinct_author_count is not None
        else len({q.author_hash for q in quotes})
    )
    return InsightCluster(
        rank=rank,
        claim=f"consumers want outcome {rank}",
        demand_score=demand_score,
        distinct_author_count=distinct,
        mention_count=len(quotes),
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _report(*, clusters: list[InsightCluster]) -> DemandReport:
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
    )


def _deps(chat: FakeChatModel | None = None) -> ResearchDeps:
    return ResearchDeps(
        chat=chat or FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
    )


def _chat(phrasing: _SitePhrasing) -> FakeChatModel:
    chat = FakeChatModel()
    chat.script(_SitePhrasing, phrasing)
    return chat


# ── exact-match grounding ────────────────────────────────────────────────────


def test_verbatim_section_kept_when_fragment_matches_quote() -> None:
    q = _quote("nothing fades PIE without burning my skin", "https://r/x/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=1,
                role="feature",
                copy="Tired of burning? nothing fades PIE without burning your skin — until now.",
                fragment="nothing fades PIE without burning",
            )
        ],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    assert site.partial is False
    assert len(site.sections) == 1
    sec = site.sections[0]
    assert sec.provenance == "verbatim"
    assert sec.evidence_refs[0].evidence_id == q.id
    assert sec.evidence_refs[0].kind == "quote"


def test_nonmatching_fragment_section_is_dropped() -> None:
    # The fragment is a paraphrase — not a real substring of any quote → dropped.
    q = _quote("nothing fades PIE without burning", "https://r/x/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=1,
                role="feature",
                copy="Fade marks gently and fast.",
                fragment="fades marks gently and fast",  # not in the quote
            )
        ],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    assert site.sections == []
    assert site.partial is True
    assert site.caveat


def test_section_pointing_at_unknown_cluster_is_dropped() -> None:
    q = _quote("real verified pain here", "https://r/x/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=99,  # not in the top set
                role="feature",
                copy="real verified pain here",
                fragment="real verified pain here",
            )
        ],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    assert site.sections == []
    assert site.partial is True


# ── connective copy ──────────────────────────────────────────────────────────


def test_connective_copy_has_no_refs_and_must_be_claim_free() -> None:
    q = _quote("this actually cleared my marks", "https://r/x/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=1,
                role="social_proof",
                copy="this actually cleared my marks",
                fragment="this actually cleared my marks",
            )
        ],
        connective=[
            _ConnectivePhrasing(role="cta", copy="See how it could work for you."),
            _ConnectivePhrasing(role="cta", copy="The best results in 30 days."),  # claim → drop
        ],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    connective = [s for s in site.sections if s.provenance == "connective"]
    assert len(connective) == 1  # the claim-bearing one was dropped
    assert connective[0].copy == "See how it could work for you."
    assert connective[0].evidence_refs == []


# ── grounding spine ──────────────────────────────────────────────────────────


def test_every_shipped_ref_resolves_against_report_evidence() -> None:
    q1 = _quote("burning every single time I try azelaic", "https://r/x/1", author_hash="a1")
    q2 = _quote("the popular pick made my marks worse", "https://r/x/2", author_hash="a2")
    report = _report(
        clusters=[
            _cluster(1, quotes=[q1], demand_score=20.0),
            _cluster(2, quotes=[q2], demand_score=10.0),
        ]
    )
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=1,
                role="feature",
                copy="burning every single time I try azelaic",
                fragment="burning every single time",
            ),
            _SectionPhrasing(
                cluster_rank=2,
                role="objection",
                copy="the popular pick made my marks worse",
                fragment="made my marks worse",
            ),
        ],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    evidence_ids = {e.id for e in report.evidence}
    shipped_refs = [r for s in site.sections for r in s.evidence_refs]
    assert shipped_refs  # at least one verbatim section shipped
    for ref in shipped_refs:
        assert ref.evidence_id in evidence_ids


# ── hero selection ───────────────────────────────────────────────────────────


def test_hero_is_highest_distinct_author_cluster() -> None:
    # Cluster 2 has a higher demand_score, but cluster 1 has more DISTINCT authors
    # → the hero is built on cluster 1, and ordered first.
    broad = _cluster(
        1,
        quotes=[_quote("broad pain everyone has", "https://r/x/1")],
        demand_score=10.0,
        distinct_author_count=80,
    )
    loud = _cluster(
        2,
        quotes=[_quote("loud niche complaint", "https://r/x/2")],
        demand_score=50.0,
        distinct_author_count=5,
    )
    report = _report(clusters=[broad, loud])
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=2,
                role="feature",
                copy="loud niche complaint",
                fragment="loud niche complaint",
            ),
            _SectionPhrasing(
                cluster_rank=1,
                role="feature",
                copy="broad pain everyone has",
                fragment="broad pain everyone has",
            ),
        ],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    hero = [s for s in site.sections if s.role == "hero"]
    assert len(hero) == 1
    assert "broad pain everyone has" in hero[0].copy
    # Hero is ordered first.
    assert site.sections[0].role == "hero"


# ── best-effort failure ──────────────────────────────────────────────────────


def test_llm_failure_returns_partial_empty_site() -> None:
    # No _SitePhrasing scripted → FakeChatModel raises → caught → partial empty.
    report = _report(clusters=[_cluster(1, quotes=[_quote("real pain", "https://r/x/1")])])
    site = build_marketing_site(_deps(FakeChatModel()), report)
    assert isinstance(site, MarketingSite)
    assert site.sections == []
    assert site.partial is True
    assert "unavailable" in (site.caveat or "").lower()


def test_no_quote_backed_clusters_returns_partial() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    report = DemandReport(
        report_id="rpt-2",
        query="q",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=1,
        total_distinct_authors=1,
        ranked_clusters=[],
        generated_at=now,
    )
    site = build_marketing_site(_deps(_chat(_SitePhrasing())), report)
    assert site.sections == []
    assert site.partial is True


# ── rendering ────────────────────────────────────────────────────────────────


def test_render_site_html_includes_permalink_for_verbatim_section() -> None:
    q = _quote("nothing fades PIE without burning", "https://reddit.com/r/x/comments/1/c")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=1,
                role="feature",
                copy="nothing fades PIE without burning",
                fragment="nothing fades PIE without burning",
            )
        ],
        connective=[_ConnectivePhrasing(role="cta", copy="See if it fits your routine.")],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    html_out = render_site_html(site, report)
    assert "<!doctype html>" in html_out
    # The verbatim section's permalink is footnoted with the evidence id.
    assert "https://reddit.com/r/x/comments/1/c" in html_out
    assert f'data-evidence="{q.id}"' in html_out
    assert 'data-provenance="verbatim"' in html_out
    # Connective copy renders without a footnote link.
    assert 'data-provenance="connective"' in html_out
    assert "See if it fits your routine." in html_out


def test_render_without_report_falls_back_to_evidence_id_anchor() -> None:
    q = _quote("real verified line", "https://r/x/1")
    report = _report(clusters=[_cluster(1, quotes=[q])])
    phrasing = _SitePhrasing(
        sections=[
            _SectionPhrasing(
                cluster_rank=1,
                role="feature",
                copy="real verified line",
                fragment="real verified line",
            )
        ],
    )
    site = build_marketing_site(_deps(_chat(phrasing)), report)
    html_out = render_site_html(site)  # no report passed
    assert f'data-evidence="{q.id}"' in html_out
    assert f"#evidence-{q.id}" in html_out
