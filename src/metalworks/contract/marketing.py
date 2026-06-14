"""Marketing contract — the Pillar G (Content/SEO Plan) output.

A :class:`ContentPlan` projects a finished
:class:`~metalworks.contract.research.DemandReport` into a deterministic
content/SEO plan: one :class:`ContentPage` per ranked
:class:`~metalworks.contract.research.InsightCluster`, plus a
:class:`CitationStrategy` aimed at LLM-citability (answer-first formatting,
FAQPage structure, disclosed Reddit permalink targets).

Honesty contract:
- The whole pillar is PURE DETERMINISTIC — no LLM, no embeddings, no external
  keys. Every field is *projected* from the report; nothing is invented.
- ``target_phrase`` is the cluster's own ``claim`` (normalized), never a
  conjured keyword. ``stat_anchors`` carry the cluster's REAL distinct-author
  and mention counts — the base-rate honesty travels into the content brief.
- ``faq`` is built VERBATIM from ``report.brief.must_address`` when a brief is
  present; each item becomes a question with an empty ``answer_hint`` (the
  human/LLM fills the answer later — the plan never fabricates one).
- ``CitationStrategy.reddit_targets`` are the actual ``QuoteCitation.permalink``
  values from the report's top clusters — disclosed, real sources to cite, not
  placeholders.
- NO RANKING PROMISES anywhere. This is a structural plan for citable content,
  not an SEO guarantee.

This is the stable shape ``Metalworks().research(...).content_plan`` exposes
once Pillar G has run.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FaqItem(BaseModel):
    """One FAQ entry, projected verbatim from a brief ``must_address`` item.

    ``question`` is copied through unchanged; ``answer_hint`` is intentionally
    empty — the plan never fabricates an answer, it only marks the slot a
    citable answer must fill.
    """

    question: str = Field(description="The sub-question, copied verbatim from brief.must_address.")
    answer_hint: str = Field(
        default="",
        description="Always '' at plan time — the answer is authored later, never invented here.",
    )


class ContentPage(BaseModel):
    """One planned page, projected from a single ranked InsightCluster.

    ``target_phrase`` is the cluster's normalized ``claim`` (never an invented
    keyword); ``page_kind`` is a deterministic heuristic on that text;
    ``source_cluster_rank`` ties the page back to its cluster;
    ``stat_anchors`` carry the cluster's real distinct-author / mention counts;
    ``outline`` is a fixed markdown section list for answer-first formatting.
    """

    target_phrase: str = Field(
        description="Normalized cluster claim (lowercased, collapsed whitespace). Not invented."
    )
    page_kind: str = Field(
        description="Deterministic heuristic: 'comparison' | 'guide' | 'answer'."
    )
    source_cluster_rank: int = Field(
        description="1-based InsightCluster.rank this page is projected from."
    )
    faq: list[FaqItem] = Field(
        default_factory=list[FaqItem],
        description="FAQ items, built verbatim from brief.must_address (empty when no brief).",
    )
    stat_anchors: dict[str, int] = Field(
        default_factory=dict[str, int],
        description="Real counts: {'distinct_authors': ..., 'mentions': ...} from the cluster.",
    )
    outline: list[str] = Field(
        default_factory=list[str],
        description="Deterministic markdown section headings for answer-first formatting.",
    )


class CitationStrategy(BaseModel):
    """The LLM-citability play for the plan as a whole.

    ``prompt_set`` are example prompts (derived mechanically from the pages'
    target phrases) a consumer might ask an assistant — the content should be
    the citable answer. ``reddit_targets`` are the REAL, disclosed
    ``QuoteCitation.permalink`` values from the report's top clusters, deduped.
    """

    prompt_set: list[str] = Field(
        default_factory=list[str],
        description="Example LLM prompts derived from target_phrases (for citability checks).",
    )
    reddit_targets: list[str] = Field(
        default_factory=list[str],
        description="Deduped, disclosed quote permalinks to cite — real sources, not placeholders.",
    )


class ContentPlan(BaseModel):
    """Pillar G output — a deterministic content/SEO plan for one report.

    FKs to exactly one report via ``report_id``. One ``ContentPage`` per ranked
    cluster, plus a ``CitationStrategy``. Makes NO ranking promises — it is a
    structural plan for citable, evidence-anchored content.
    """

    report_id: str = Field(description="The DemandReport this plan was projected from.")
    pages: list[ContentPage] = Field(
        default_factory=list[ContentPage],
        description="One page per ranked InsightCluster, in rank order.",
    )
    citation_strategy: CitationStrategy = Field(
        description="LLM-citability play: prompt set + disclosed Reddit permalink targets."
    )
