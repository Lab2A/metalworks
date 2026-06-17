"""Store base stack — manage records for a workflow.

The first base stack, and the most common output. Consolidates the Clique-side
record-keeping archetypes (tracker, submission-portal, lookup-verify, estimator).
``submission-portal`` is the first product shape on it; it has a known-good built
example (Clique's TaxLock) to validate the spec against.
"""

from __future__ import annotations

from metalworks.contract.research import SignalStrength
from metalworks.contract.shape import BaseStack, MatchSignature, ProductShape
from metalworks.shapes import register_base_stack, register_shape

STORE = BaseStack(
    id="store",
    verb="store",
    backend_capabilities=[
        "multitenant auth (email OTP)",
        "typed CRUD + schema migrations",
        "roles / row-level ownership",
        "list + detail views, CSV export",
        "billing hook (subscription gate)",
    ],
    default_modules=[],
    scaffold_target="starter:store-saas",
)

SUBMISSION_PORTAL = ProductShape(
    name="submission-portal",
    base_stack="store",
    modules=[],
    domain_skin="An owner sets a request with a rule; others submit against it under that rule.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "collect documents from clients",
            "upload portal",
            "submission deadline",
            "chasing people for files",
            "intake form",
        ],
        surface="web",
        build_signals=["upload", "request", "deadline", "portal", "submission"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

register_base_stack(STORE)
register_shape(SUBMISSION_PORTAL)
