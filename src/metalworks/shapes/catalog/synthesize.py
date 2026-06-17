"""Synthesize base stack — turn many external sources into one cited answer.

The intelligence archetype: ingest a corpus from external sources, run embedding
+ LLM synthesis over it, keep every claim cited to its evidence, and render the
result as a report or dashboard. This is the base stack metalworks' own demand
engine is built on, so it conformance-maps to Clique's running pipeline piece for
piece (Clique -> Synthesize conformance):

- "external-source ingestion / connectors" backs onto Clique's
  ``research/sources/`` (arctic, hackernews, producthunt, web, ``ingest``).
- "embedding + LLM synthesis" backs onto ``research/synthesis/``
  (``embed_group``, ``cluster_ranker``, ``demand``, ``market``) over the engine's
  ``embeddings`` + ``llm`` adapters.
- "cited evidence store" backs onto the verified, permalinked quotes carried by
  ``ResolvedCitation`` and the ``contract/evidence`` + ``contract/corpus`` refs —
  the cite-or-die discipline the matcher itself inherits.
- "report / dashboard renderer" backs onto ``DemandReport`` and
  ``contract/site`` (``render_site_html``).

``demand-intelligence`` is the reference shape: it is exactly the product Clique
itself is (Reddit demand mined into a cited report), so a built example already
exists to validate the spec against.
"""

from __future__ import annotations

from metalworks.contract.research import SignalStrength
from metalworks.contract.shape import BaseStack, MatchSignature, ProductShape
from metalworks.shapes import register_base_stack, register_shape

SYNTHESIZE = BaseStack(
    id="synthesize",
    verb="synthesize",
    backend_capabilities=[
        "external-source ingestion / connectors",
        "embedding + LLM synthesis over the corpus",
        "cited evidence store (verified, permalinked quotes)",
        "report / dashboard renderer",
    ],
    default_modules=[],
    scaffold_target="starter:synthesize-intelligence",
)

DEMAND_INTELLIGENCE = ProductShape(
    name="demand-intelligence",
    base_stack="synthesize",
    modules=[],
    domain_skin=(
        "Mine a public corpus for what an audience repeatedly complains about, "
        "ranked and cited — the Clique reference shape this base stack maps to."
    ),
    match_signature=MatchSignature(
        cluster_keywords=[
            "no easy way to see what people say about a topic",
            "find out what customers actually want",
            "surface recurring complaints from a community",
            "validate demand before building",
            "mine forums for real pain points",
        ],
        surface="web",
        build_signals=["corpus", "cluster", "demand", "evidence", "report"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

AGGREGATOR_COMPARISON = ProductShape(
    name="aggregator-comparison",
    base_stack="synthesize",
    modules=[],
    domain_skin="Pull the same facts from many sites and line them up side by side.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "aggregate prices from many sites",
            "compare options in one place",
            "tired of checking ten tabs to compare",
            "one table of every provider and their specs",
            "no single source that lists all the choices",
        ],
        surface="web",
        build_signals=["aggregate", "compare", "table", "providers", "specs"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

SEARCH_DISCOVERY = ProductShape(
    name="search-discovery",
    base_stack="synthesize",
    modules=[],
    domain_skin="Index a messy body of content and let people ask it questions.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "cannot find anything in all these documents",
            "search that actually understands what i mean",
            "ask a question and get a cited answer",
            "too much content and no way to find the right bit",
            "semantic search over our knowledge base",
        ],
        surface="web",
        build_signals=["search", "index", "query", "semantic", "answer"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

ANALYTICS_DASHBOARD = ProductShape(
    name="analytics-dashboard",
    base_stack="synthesize",
    modules=[],
    domain_skin="Roll scattered metrics into one dashboard with a plain-language summary.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "pull all our metrics into one dashboard",
            "no single view of how things are trending",
            "stop exporting spreadsheets to see the numbers",
            "explain what the data actually means",
            "track key numbers over time in one place",
        ],
        surface="web",
        build_signals=["dashboard", "metrics", "trend", "summary", "chart"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

REVIEW_MINING = ProductShape(
    name="review-mining",
    base_stack="synthesize",
    modules=[],
    domain_skin="Turn a pile of reviews into themed, quoted insight.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "turn raw reviews into insight",
            "read thousands of reviews to find the themes",
            "what do customers keep complaining about in reviews",
            "summarize feedback without reading every comment",
            "pull the common gripes out of app store reviews",
        ],
        surface="web",
        build_signals=["reviews", "themes", "sentiment", "feedback", "quotes"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

register_base_stack(SYNTHESIZE)
register_shape(DEMAND_INTELLIGENCE)
register_shape(AGGREGATOR_COMPARISON)
register_shape(SEARCH_DISCOVERY)
register_shape(ANALYTICS_DASHBOARD)
register_shape(REVIEW_MINING)
