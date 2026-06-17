"""Match base stack — connect two sides of a market and let them transact.

The two-sided base stack: listings with media, search/match over them, trust via
reviews and ratings, in-app messaging, and a transaction handoff. Its product
shapes are the recognizable marketplace skins (goods / services / rentals) plus
two relationship-first variants — a ``community`` feed and ``intro-matching``
threads — that compose the matching primitives onto a social spine.
"""

from __future__ import annotations

from metalworks.contract.research import SignalStrength
from metalworks.contract.shape import BaseStack, MatchSignature, ProductShape
from metalworks.shapes import register_base_stack, register_shape

MATCH = BaseStack(
    id="match",
    verb="match",
    backend_capabilities=[
        "listings + media",
        "search / match",
        "reviews + trust / ratings",
        "in-app messaging",
        "transaction handoff",
    ],
    default_modules=[],
    scaffold_target="starter:match-marketplace",
)

GOODS_MARKETPLACE = ProductShape(
    name="goods-marketplace",
    base_stack="match",
    modules=[],
    domain_skin="Sellers list physical goods with photos; buyers search, message, and buy.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "no good place to buy and sell niche gear",
            "connect buyers and sellers",
            "a marketplace for this niche",
            "buy and sell used equipment",
        ],
        surface="web",
        build_signals=["listing", "buyer", "seller", "marketplace", "checkout"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

SERVICES_MARKETPLACE = ProductShape(
    name="services-marketplace",
    base_stack="match",
    modules=[],
    domain_skin="Providers list services and rates; clients search, vet, message, and book.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "hard to find a trusted provider for this service",
            "connect clients with local pros",
            "book a vetted service provider",
            "marketplace to hire freelancers",
        ],
        surface="web",
        build_signals=["provider", "booking", "service", "review", "rating"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

RENTAL_MARKETPLACE = ProductShape(
    name="rental-marketplace",
    base_stack="match",
    modules=[],
    domain_skin="Owners list items or space to rent by the day; renters search and reserve.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "no easy way to rent gear by the day",
            "rent out my equipment to others",
            "marketplace to rent instead of buy",
            "find and book rentals nearby",
        ],
        surface="web",
        build_signals=["rental", "availability", "reserve", "owner", "booking"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

COMMUNITY = ProductShape(
    name="community",
    base_stack="match",
    modules=["feed"],
    domain_skin="People with a shared interest gather, post to a feed, and find each other.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "no real community for people like us",
            "a place to connect with others in this niche",
            "find my people around this hobby",
            "shared space to post and discuss",
        ],
        surface="web",
        build_signals=["community", "feed", "post", "member", "profile"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

INTRO_MATCHING = ProductShape(
    name="intro-matching",
    base_stack="match",
    modules=["threads"],
    domain_skin="A matcher pairs two people by fit and opens a private thread to talk.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "no good way to get matched with the right person",
            "match people and introduce them",
            "pair mentors with mentees",
            "warm intros instead of cold outreach",
        ],
        surface="web",
        build_signals=["match", "intro", "pairing", "thread", "profile"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

register_base_stack(MATCH)
register_shape(GOODS_MARKETPLACE)
register_shape(SERVICES_MARKETPLACE)
register_shape(RENTAL_MARKETPLACE)
register_shape(COMMUNITY)
register_shape(INTRO_MATCHING)
