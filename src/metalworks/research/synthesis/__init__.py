"""The post-triage, post-hydration synthesis stage.

Inputs:
  - a finalized `ResearchBrief`
  - the post-triage subset of `post_id`s already hydrated into the corpus repo

Outputs (`SynthesisOutput`): the analytical guts of a `DemandReport` — ranked
InsightClusters, verdict, slot_plan, audience_profile, segments, market_sizing,
price_finding, source_map, plus the two counts the pipeline orchestrator
stitches into the final report (`total_distinct_authors`, `n_synthesized` —
post-cluster-dedup, fills ExplorationReport.threads_synthesized).

Flow:

    hydrated_post_ids
      ↓ loader.load_posts / load_comments       (corpus repo → in-memory)
      ↓ embed_group                              (near-dup dedup)
      ↓ cluster_ranker.build_clusters            (LLM theme labeling)
      ↓ audience.build_audience_profile / describe_audience
      ↓ market.build_market_sizing               (deterministic)
      ↓ pricing.build_price_finding              (only when Price is a Find slot)
      ↓ segments.build_segments                  (LLM, best-effort)
      ↓ verdict.derive_verdict                   (deterministic)
      ↓ SynthesisOutput

Structural-provenance contract:
  - Clusters reference INDICES into the comment list (member/quote indices),
    never quote text. Quotes are exact-matched against stored comment bodies.
  - `source_map` entries reflect the hydrated post subset, never the LLM's prose.

Failure model:
  - The cluster_ranker call RAISES after 3 retries — never returns a silent
    empty ranked_clusters. Secondary calls (segments, pricing, audience_profile)
    are best-effort and degrade individually.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from metalworks.contract import ResearchBrief, SlotPlan, SourceMapEntry
from metalworks.research.synthesis import (
    audience as audience_mod,
)
from metalworks.research.synthesis import (
    cluster_ranker,
    embed_group,
    loader,
    market,
    pricing,
    segments,
    verdict,
)
from metalworks.research.types import LoadedPost, SynthesisOutput

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

__all__ = [
    "audience_mod",
    "cluster_ranker",
    "embed_group",
    "loader",
    "market",
    "pricing",
    "segments",
    "synthesize",
    "verdict",
]


def _slot_plan_from_brief(brief: ResearchBrief) -> SlotPlan:
    """The brief's research question seeds the SlotPlan.

    The brief carries `question` + `target_subreddits` but no explicit
    product/audience/price split. We default to a product-seeded plan with the
    question as the product slot — synthesis fills the audience side, and price
    stays a Find slot so the pricing extractor runs.
    """
    return SlotPlan.resolve(product=brief.question)


def _axis_context(brief: ResearchBrief) -> str:
    """The one-line research goal handed to the synthesis LLM."""
    if brief.decision_context:
        return f"{brief.question}\nDecision context: {brief.decision_context}"
    return brief.question


def _build_source_map(
    posts: list[LoadedPost],
    coded_lookup: dict[str, str],
) -> list[SourceMapEntry]:
    """One SourceMapEntry per subreddit in the hydrated post set.

    `threads_examined` = number of hydrated posts in that sub. `skew` = the
    static-map audience descriptor when the sub is coded.
    """
    counts = Counter(p.subreddit for p in posts if p.subreddit)
    out: list[SourceMapEntry] = []
    for sub, n in counts.most_common():
        sub_label = sub if sub.startswith("r/") else f"r/{sub}"
        out.append(
            SourceMapEntry(
                subreddit=sub_label,
                threads_examined=n,
                skew=coded_lookup.get(sub.lower().lstrip("r/").strip()),
            )
        )
    return out


def synthesize(
    deps: ResearchDeps,
    *,
    brief: ResearchBrief,
    hydrated_post_ids: list[str],
) -> SynthesisOutput:
    """Run synthesis against the post-triage hydrated subset.

    Args:
        deps: Injected dependencies.
        brief: The finalized ResearchBrief this run is against.
        hydrated_post_ids: Bare Reddit submission ids already persisted to the
            corpus repo.

    Returns: A SynthesisOutput. Raises RuntimeError if the core cluster
    synthesis LLM fails 3 retries (fail loud, never empty-success).
    """
    # 1. Load hydrated rows.
    posts = loader.load_posts(deps, hydrated_post_ids)
    comments = loader.load_comments(deps, hydrated_post_ids)
    if not comments:
        return SynthesisOutput(
            ranked_clusters=[],
            verdict=verdict.derive_verdict(total_distinct_authors=0),
            slot_plan=_slot_plan_from_brief(brief),
            audience_profile=None,
            segments=[],
            market_sizing=None,
            price_finding=None,
            source_map=_build_source_map(posts, {}),
            total_distinct_authors=0,
            n_synthesized=0,
        )

    # 2. Embed-group dedup.
    def _embed(t: str) -> list[float] | None:
        return deps.embeddings.embed([t], task="document")[0]

    groups = embed_group.embed_group(comments, _embed)
    representatives = [comments[g[0]] for g in groups]  # one per near-dup group

    # 3. LLM theme labeling — RAISES after retries.
    clusters, cluster_authors, _cluster_subs, member_indices = cluster_ranker.build_clusters(
        deps,
        axis_context=_axis_context(brief),
        representatives=representatives,
        groups=groups,
        comments=comments,
    )

    # 4. Audience inference (descriptors + structured profile).
    sub_counts = Counter(c.subreddit for c in comments).most_common()
    coded = audience_mod.coded_subreddits(sub_counts)
    coded_lookup = dict(coded)
    audience_profile = audience_mod.build_audience_profile(deps, coded)

    # 5. Per-cluster attribution_method/confidence from the static map.
    for cluster, mi in zip(clusters, member_indices, strict=False):
        method, confidence = audience_mod.describe_audience([comments[i].subreddit for i in mi])
        cluster.attribution_method = method
        cluster.attribution_confidence = confidence

    # 6. Market sizing (deterministic).
    total_distinct = len({c.author_hash for c in comments if c.author_hash})
    market_sizing = market.build_market_sizing(total_distinct)

    # 7. Slot plan + pricing (only when Price is a Find slot).
    slot_plan = _slot_plan_from_brief(brief)
    price_finding = pricing.build_price_finding(deps, comments, slot_plan)

    # 8. Segmentation (best-effort).
    seg_list = segments.build_segments(deps, clusters, cluster_authors, audience_profile)

    # 9. Verdict + source_map (both deterministic).
    verdict_str = verdict.derive_verdict(
        total_distinct_authors=total_distinct,
        market=market_sizing,
        price=price_finding,
    )
    source_map = _build_source_map(posts, coded_lookup)

    # n_synthesized — distinct post_ids whose comments survived dedup AND ended
    # up in at least one cluster's member set. The honest post-cluster-dedup
    # count for ExplorationReport.threads_synthesized.
    synthesized_post_ids: set[str] = set()
    for mi in member_indices:
        for i in mi:
            if 0 <= i < len(comments):
                pid = comments[i].post_id
                if pid:
                    synthesized_post_ids.add(pid)

    return SynthesisOutput(
        ranked_clusters=clusters,
        verdict=verdict_str,
        slot_plan=slot_plan,
        audience_profile=audience_profile,
        segments=seg_list,
        market_sizing=market_sizing,
        price_finding=price_finding,
        source_map=source_map,
        total_distinct_authors=total_distinct,
        n_synthesized=len(synthesized_post_ids),
    )
