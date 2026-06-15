"""Pillar G — content/SEO plan: pure deterministic projection from a report.

No LLM, no embeddings, no external keys. ``content_plan_from_report`` takes a
:class:`~metalworks.contract.research.DemandReport` and projects one
:class:`~metalworks.contract.marketing.ContentPage` per ranked cluster, plus a
:class:`~metalworks.contract.marketing.CitationStrategy`. Two renderers turn the
typed plan into a markdown outline pack and a JSON-LD FAQPage stub — both built
mechanically from typed fields, never from free text.

Honesty: every value is projected from the report. No keyword, quote, or answer
is invented; no ranking is promised.
"""

from __future__ import annotations

from metalworks.contract.marketing import (
    CitationStrategy,
    ContentPage,
    ContentPlan,
    FaqItem,
)
from metalworks.contract.research import DemandReport, InsightCluster

# How many top clusters contribute their quote permalinks to the citation
# strategy's disclosed reddit targets.
_TOP_CLUSTERS_FOR_CITATION = 3

# The deterministic markdown section list every page carries. Answer-first
# (the honest answer up top), then the FAQ block for FAQPage structure.
_OUTLINE: list[str] = [
    "## What people actually want",
    "## Common approaches",
    "## The honest answer",
    "## FAQ",
]

# Tokens that flip the page kind, checked as whole words against the
# normalized claim.
_COMPARISON_TOKENS: frozenset[str] = frozenset({"vs", "versus", "or", "best"})
_GUIDE_TOKENS: frozenset[str] = frozenset({"how", "guide", "tips"})


def _normalize_phrase(text: str) -> str:
    """Lowercase, collapse internal whitespace, strip ends. Pure."""
    return " ".join(text.lower().split())


def _page_kind(normalized_claim: str) -> str:
    """Deterministic heuristic on the normalized claim text.

    'comparison' when it reads like a choice (vs/versus/or/best), 'guide' when
    it reads like a how-to (how/guide/tips), otherwise 'answer'.
    """
    words = set(normalized_claim.split())
    if words & _COMPARISON_TOKENS:
        return "comparison"
    if words & _GUIDE_TOKENS:
        return "guide"
    return "answer"


def _faq_from_report(report: DemandReport) -> list[FaqItem]:
    """FAQ items built verbatim from brief.must_address (empty when no brief)."""
    if report.brief is None:
        return []
    return [FaqItem(question=item, answer_hint="") for item in report.brief.must_address]


def _page_from_cluster(cluster: InsightCluster, faq: list[FaqItem]) -> ContentPage:
    """Project one ranked cluster into a content page. Pure."""
    return ContentPage(
        target_phrase=_normalize_phrase(cluster.claim),
        page_kind=_page_kind(_normalize_phrase(cluster.claim)),
        source_cluster_rank=cluster.rank,
        faq=list(faq),
        stat_anchors={
            "distinct_authors": cluster.distinct_author_count,
            "mentions": cluster.mention_count,
        },
        outline=list(_OUTLINE),
    )


def _reddit_targets(report: DemandReport) -> list[str]:
    """Deduped quote source URLs from the top clusters, in encounter order."""
    targets: list[str] = []
    seen: set[str] = set()
    for cluster in report.ranked_clusters[:_TOP_CLUSTERS_FOR_CITATION]:
        for quote in cluster.quotes:
            if quote.source_url and quote.source_url not in seen:
                seen.add(quote.source_url)
                targets.append(quote.source_url)
    return targets


def _prompt_set(pages: list[ContentPage]) -> list[str]:
    """A few example LLM-citability prompts derived from target phrases. Pure."""
    prompts: list[str] = []
    seen: set[str] = set()
    for page in pages[:_TOP_CLUSTERS_FOR_CITATION]:
        phrase = page.target_phrase
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        prompts.append(f"What's the honest answer about {phrase}?")
    return prompts


def content_plan_from_report(report: DemandReport) -> ContentPlan:
    """Project a demand report into a deterministic content/SEO plan.

    Pure function — no deps, no LLM, no network. One page per ranked cluster;
    every field projected from the report. Makes no ranking promises.
    """
    faq = _faq_from_report(report)
    pages = [_page_from_cluster(cluster, faq) for cluster in report.ranked_clusters]
    citation_strategy = CitationStrategy(
        prompt_set=_prompt_set(pages),
        reddit_targets=_reddit_targets(report),
    )
    return ContentPlan(
        report_id=report.report_id,
        pages=pages,
        citation_strategy=citation_strategy,
    )


def render_content_markdown(plan: ContentPlan) -> str:
    """Render the plan as a markdown outline pack. Mechanical from typed fields."""
    lines: list[str] = [f"# Content plan — {plan.report_id}", ""]
    if not plan.pages:
        lines.append("_No clusters in the source report — empty plan._")
        lines.append("")
    for page in plan.pages:
        lines.append(f"## {page.target_phrase}")
        lines.append(f"- kind: {page.page_kind}")
        lines.append(f"- source cluster rank: {page.source_cluster_rank}")
        lines.append(
            f"- evidence density: {page.stat_anchors.get('distinct_authors', 0)} distinct "
            f"authors / {page.stat_anchors.get('mentions', 0)} mentions"
        )
        lines.append("")
        lines.append("### Outline")
        for section in page.outline:
            lines.append(f"- {section}")
        lines.append("")
        if page.faq:
            lines.append("### FAQ")
            for item in page.faq:
                lines.append(f"- {item.question}")
            lines.append("")
    if plan.citation_strategy.reddit_targets:
        lines.append("## Citation targets (disclosed Reddit sources)")
        for target in plan.citation_strategy.reddit_targets:
            lines.append(f"- {target}")
        lines.append("")
    if plan.citation_strategy.prompt_set:
        lines.append("## Citability prompts")
        for prompt in plan.citation_strategy.prompt_set:
            lines.append(f"- {prompt}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_faq_jsonld(plan: ContentPlan) -> dict[str, object]:
    """Build a schema.org FAQPage JSON-LD stub mechanically from typed fields.

    Aggregates every page's FAQ items into one FAQPage. ``acceptedAnswer.text``
    carries the (empty) ``answer_hint`` — no free-text answer is fabricated.
    De-dups questions across pages by first-seen order.
    """
    entities: list[dict[str, object]] = []
    seen: set[str] = set()
    for page in plan.pages:
        for item in page.faq:
            if item.question in seen:
                continue
            seen.add(item.question)
            entities.append(
                {
                    "@type": "Question",
                    "name": item.question,
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": item.answer_hint,
                    },
                }
            )
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": entities,
    }
