"""Pillar G — content/SEO plan: pure deterministic projection from a report.

Fully offline. No network, no numpy, no LLM — ``content_plan_from_report`` is a
pure function over a ``DemandReport``. The fixture is built inline (mirroring
test_research_positioning.py) so the projection runs against a real report shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import (
    DemandReport,
    Fork,
    InsightCluster,
    QuoteCitation,
    ResearchBrief,
    SignalStrength,
)
from metalworks.research.marketing import (
    content_plan_from_report,
    render_content_markdown,
    render_faq_jsonld,
)

# ── fixtures ─────────────────────────────────────────────────────────────────


def _quote(text: str, permalink: str, author_hash: str = "a1") -> QuoteCitation:
    return QuoteCitation(
        text=text, permalink=permalink, subreddit="SkincareAddiction", author_hash=author_hash
    )


def _cluster(
    rank: int,
    *,
    claim: str,
    quotes: list[QuoteCitation],
    distinct_authors: int = 5,
    mentions: int = 12,
) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=claim,
        demand_score=10.0,
        distinct_author_count=distinct_authors,
        mention_count=mentions,
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _brief(must_address: list[str]) -> ResearchBrief:
    return ResearchBrief(
        brief_id="brief-1",
        question="best fade for post-acne marks",
        decision_context="deciding what to build",
        success_criteria=["clear demand"],
        must_address=must_address,
        target_subreddits=[],
        web_research_directions=[],
        relevance_rubric="anything about fading marks",
    )


def _report(
    *,
    clusters: list[InsightCluster],
    brief: ResearchBrief | None = None,
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
        brief=brief,
    )


# ── one page per cluster + normalized phrase ─────────────────────────────────


def test_one_page_per_cluster() -> None:
    report = _report(
        clusters=[
            _cluster(1, claim="consumers want faster fade", quotes=[_quote("a", "https://r/x/1")]),
            _cluster(2, claim="people hate the irritation", quotes=[_quote("b", "https://r/x/2")]),
        ]
    )
    plan = content_plan_from_report(report)
    assert plan.report_id == "rpt-1"
    assert len(plan.pages) == 2
    assert [p.source_cluster_rank for p in plan.pages] == [1, 2]


def test_target_phrase_normalized() -> None:
    report = _report(
        clusters=[
            _cluster(
                1,
                claim="  Consumers   WANT   Faster Fade  ",
                quotes=[_quote("a", "https://r/x/1")],
            )
        ]
    )
    plan = content_plan_from_report(report)
    assert plan.pages[0].target_phrase == "consumers want faster fade"


# ── page_kind heuristic ──────────────────────────────────────────────────────


def test_page_kind_comparison() -> None:
    report = _report(
        clusters=[
            _cluster(1, claim="azelaic vs niacinamide for marks", quotes=[_quote("a", "https://1")])
        ]
    )
    assert content_plan_from_report(report).pages[0].page_kind == "comparison"


def test_page_kind_guide() -> None:
    report = _report(
        clusters=[
            _cluster(1, claim="how to fade post-acne marks", quotes=[_quote("a", "https://1")])
        ]
    )
    assert content_plan_from_report(report).pages[0].page_kind == "guide"


def test_page_kind_answer_default() -> None:
    report = _report(
        clusters=[_cluster(1, claim="marks linger for months", quotes=[_quote("a", "https://1")])]
    )
    assert content_plan_from_report(report).pages[0].page_kind == "answer"


# ── faq verbatim from brief.must_address ─────────────────────────────────────


def test_faq_built_verbatim_from_must_address() -> None:
    brief = _brief(["Does it work on dark skin?", "How long until results?"])
    report = _report(
        clusters=[_cluster(1, claim="want faster fade", quotes=[_quote("a", "https://1")])],
        brief=brief,
    )
    page = content_plan_from_report(report).pages[0]
    assert [f.question for f in page.faq] == [
        "Does it work on dark skin?",
        "How long until results?",
    ]
    assert all(f.answer_hint == "" for f in page.faq)


def test_faq_empty_when_no_brief() -> None:
    report = _report(
        clusters=[_cluster(1, claim="want faster fade", quotes=[_quote("a", "https://1")])]
    )
    assert content_plan_from_report(report).pages[0].faq == []


# ── stat anchors carry real counts ───────────────────────────────────────────


def test_stat_anchors_carry_real_counts() -> None:
    report = _report(
        clusters=[
            _cluster(
                1,
                claim="want faster fade",
                quotes=[_quote("a", "https://1")],
                distinct_authors=7,
                mentions=21,
            )
        ]
    )
    anchors = content_plan_from_report(report).pages[0].stat_anchors
    assert anchors == {"distinct_authors": 7, "mentions": 21}


# ── reddit targets are real, deduped permalinks ──────────────────────────────


def test_reddit_targets_are_deduped_quote_permalinks() -> None:
    report = _report(
        clusters=[
            _cluster(
                1,
                claim="want faster fade",
                quotes=[
                    _quote("a", "https://r/x/1", author_hash="a1"),
                    _quote("b", "https://r/x/2", author_hash="a2"),
                    _quote("c", "https://r/x/1", author_hash="a3"),  # dup permalink
                ],
            ),
            _cluster(2, claim="hate irritation", quotes=[_quote("d", "https://r/x/3")]),
        ]
    )
    targets = content_plan_from_report(report).citation_strategy.reddit_targets
    assert targets == ["https://r/x/1", "https://r/x/2", "https://r/x/3"]


def test_prompt_set_derived_from_phrases() -> None:
    report = _report(
        clusters=[_cluster(1, claim="want faster fade", quotes=[_quote("a", "https://1")])]
    )
    prompts = content_plan_from_report(report).citation_strategy.prompt_set
    assert len(prompts) == 1
    assert "want faster fade" in prompts[0]


# ── renderers ────────────────────────────────────────────────────────────────


def test_render_content_markdown_is_string() -> None:
    report = _report(
        clusters=[_cluster(1, claim="want faster fade", quotes=[_quote("a", "https://r/x/1")])],
        brief=_brief(["Does it work?"]),
    )
    md = render_content_markdown(content_plan_from_report(report))
    assert isinstance(md, str)
    assert "want faster fade" in md
    assert "Does it work?" in md
    assert "https://r/x/1" in md


def test_render_faq_jsonld_shape() -> None:
    report = _report(
        clusters=[_cluster(1, claim="want faster fade", quotes=[_quote("a", "https://1")])],
        brief=_brief(["Does it work on dark skin?"]),
    )
    jsonld = render_faq_jsonld(content_plan_from_report(report))
    assert jsonld["@context"] == "https://schema.org"
    assert jsonld["@type"] == "FAQPage"
    entities = jsonld["mainEntity"]
    assert isinstance(entities, list)
    assert entities[0]["@type"] == "Question"
    assert entities[0]["name"] == "Does it work on dark skin?"
    assert entities[0]["acceptedAnswer"]["@type"] == "Answer"
    assert entities[0]["acceptedAnswer"]["text"] == ""


# ── empty report ─────────────────────────────────────────────────────────────


def test_empty_report_yields_empty_plan() -> None:
    report = _report(clusters=[])
    plan = content_plan_from_report(report)
    assert plan.pages == []
    assert plan.citation_strategy.reddit_targets == []
    assert plan.citation_strategy.prompt_set == []
    # Renderers do not crash on an empty plan.
    md = render_content_markdown(plan)
    assert isinstance(md, str)
    jsonld = render_faq_jsonld(plan)
    assert jsonld["mainEntity"] == []
