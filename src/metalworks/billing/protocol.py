"""Billing protocols — the seams the billing logic speaks through.

Two ports, versioned as a unit:

- :class:`SubscriptionStore` — persistence for the access record. The webhook
  mapper writes rows; the gate reads them. Keeping it a protocol lets the pure
  gating logic be unit-tested against a fake with no Stripe and no network, and
  swaps the storage backend without touching the rules. Core ships no hosted,
  Stripe-backed store — that is a downstream concern, the same posture the repo
  takes with hosted corpus stores.
- :class:`BillingProvider` — the create-a-product seam an adapter (Stripe)
  implements. Turns one cited :class:`~metalworks.contract.build.PricingTier`
  into a real product + recurring price + payment link.

``protocol_version`` is bumped as a unit: a minor bump is additive
keyword-only params with defaults; a major bump is breaking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from metalworks.contract.billing import BillingProduct, Subscription
    from metalworks.contract.build import PricingTier

PROTOCOL_VERSION = "1.0"


@runtime_checkable
class SubscriptionStore(Protocol):
    """Persistence port for the access record — one row per ``(user_id, product)``.

    The webhook mapper produces a :class:`~metalworks.contract.billing.Subscription`
    and the host upserts it here; the access gate reads it back. Implementations
    are the host's concern (Supabase, Postgres, a dict in a test).
    """

    def get_subscription(self, user_id: str, product: str) -> Subscription | None:
        """The owner's current subscription for a product, or ``None`` if none."""
        ...

    def upsert_subscription(self, record: Subscription) -> None:
        """Insert or update the row keyed by ``(user_id, product)``."""
        ...


@runtime_checkable
class BillingProvider(Protocol):
    """Create-a-product seam. Adapters (Stripe) live behind extras.

    ``create_product`` turns one cited tier into a real product + recurring price
    + payment link. ``mode_live`` is a guard, not the source of truth: the
    adapter resolves test-vs-live from the key it reads and refuses to charge
    live unless both the key and this flag agree.
    """

    protocol_version: ClassVar[str]
    provider_id: str

    def create_product(
        self,
        *,
        name: str,
        tier: PricingTier,
        mode_live: bool = False,
    ) -> BillingProduct:
        """Create a product + price + payment link from a cited tier."""
        ...
