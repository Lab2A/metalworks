"""Built-in startup-shape catalog — self-registers on import.

The first proof slice: the **Store** base stack and one product shape on it,
**submission-portal**. Store is chosen first because it is the most common output
and consolidates the Clique-side record-keeping archetypes; submission-portal has
a known-good built example (Clique's TaxLock) to validate the spec against.

Adding a shape is one ``register_shape`` call here (or in any module that imports
and registers) — the fan-out of the full base x module catalog lands the same way,
without editing a shared inline list.
"""

from __future__ import annotations

from metalworks.contract.research import SignalStrength
from metalworks.contract.shape import BaseStack, MatchSignature, ProductShape
from metalworks.shapes import register_base_stack, register_shape

# ── Base stacks ──────────────────────────────────────────────────────────────

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

# ── Product shapes (base + modules + skin) ───────────────────────────────────

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


def _register() -> None:
    register_base_stack(STORE)
    register_shape(SUBMISSION_PORTAL)


_register()
