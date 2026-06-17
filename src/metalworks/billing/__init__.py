"""Billing — take a report's cited pricing tiers to a real pay URL.

Two layers, deliberately split so the reusable half needs no SDK and no network:

- **Pure logic** (always importable, offline-tested): the subscription gate
  (:func:`require_active_subscription`, :func:`is_subscription_active`) and the
  webhook mapper (:func:`subscription_event_to_record`). This is what a
  downstream app imports to enforce a paywall — just the contract model and a
  :class:`SubscriptionStore`, no metalworks runtime.
- **Adapter** (behind the ``[stripe]`` extra): :class:`StripeBilling`, which
  turns one cited :class:`~metalworks.contract.build.PricingTier` into a real
  Stripe product + recurring price + payment link.

The adapter is imported lazily (``from metalworks.billing.adapters.stripe import
StripeBilling``) so ``import metalworks.billing`` stays free of any SDK — the
same posture as ``metalworks.llm`` / ``metalworks.search``.
"""

from __future__ import annotations

from metalworks.billing.protocol import (
    PROTOCOL_VERSION,
    BillingProvider,
    SubscriptionStore,
)
from metalworks.billing.subscription import (
    is_active_status,
    is_subscription_active,
    require_active_subscription,
)
from metalworks.billing.webhook import subscription_event_to_record

__all__ = [
    "PROTOCOL_VERSION",
    "BillingProvider",
    "SubscriptionStore",
    "is_active_status",
    "is_subscription_active",
    "require_active_subscription",
    "subscription_event_to_record",
]
