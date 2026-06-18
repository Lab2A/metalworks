"""Billing contract — the typed shapes the Stripe seam speaks.

Two halves, matching how Clique split billing:

- :class:`Subscription` is the access record. The webhook mapper
  (:mod:`metalworks.billing.webhook`) writes it from a Stripe event; the gate
  (:mod:`metalworks.billing.subscription`) reads it to decide if a user holds
  access right now. It is what a downstream app persists, one row per
  ``(user_id, product)``.
- :class:`BillingProduct` is what ``billing create`` returns — a real Stripe
  product + recurring price + payment link, carrying the source tier's
  ``evidence`` so the cite-or-die spine survives all the way to the pay URL.

A tier's ``price`` may be ``None`` (the report cited demand but no price point).
That is not an error: :class:`BillingProduct` then ships ``partial=True`` with a
``caveat`` and no ``price_id`` / ``payment_link_url`` — the product exists, the
price does not, and the honesty signal says so (the same ``partial`` / ``caveat``
idiom :class:`~metalworks.contract.site.MarketingSite` and
:class:`~metalworks.contract.build.BuildSpec` use).

No secret ever lives on a contract — only ids and the public pay URL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef

SubscriptionStatus = Literal[
    "active",
    "trialing",
    "past_due",
    "canceled",
    "unpaid",
    "incomplete",
    "incomplete_expired",
    "paused",
]
"""The Stripe subscription statuses the gate reasons about. ``active`` and
``trialing`` grant access; everything else does not (see
:func:`metalworks.billing.subscription.is_active_status`)."""

BillingMode = Literal["test", "live"]


class Subscription(BaseModel):
    """One owner's subscription to one product — the access record.

    The webhook mapper produces it; the gate consumes it. ``current_period_end``
    is the instant access lapses (``None`` means no known end — treated as open
    while the status is active). Keyed downstream by ``(user_id, product)``.
    """

    product: str = Field(description="Product slug this subscription grants access to.")
    user_id: str = Field(description="The owner (auth user id) the subscription belongs to.")
    status: SubscriptionStatus = Field(description="Stripe subscription status.")
    stripe_customer_id: str | None = Field(default=None)
    stripe_subscription_id: str | None = Field(default=None)
    current_period_end: datetime | None = Field(
        default=None,
        description="When the paid period closes; access lapses after this instant.",
    )


class BillingProduct(BaseModel):
    """A real Stripe product + recurring price + payment link for one tier.

    ``amount`` is the monthly price in major currency units (e.g. dollars),
    copied through from the cited tier — never recomputed. When the tier is
    unpriced, ``amount`` / ``price_id`` / ``payment_link_url`` are ``None`` and
    ``partial`` is set with a ``caveat``: the product was created but no price
    could be. ``evidence`` carries the source tier's refs so the pay URL still
    traces to real demand.
    """

    product_id: str = Field(description="The Stripe product id.")
    price_id: str | None = Field(
        default=None, description="The recurring price id; None when the tier is unpriced."
    )
    payment_link_url: str | None = Field(
        default=None, description="A working hosted pay URL; None when the tier is unpriced."
    )
    amount: float | None = Field(
        default=None,
        description="Monthly price in major units (e.g. dollars), copied from the tier.",
    )
    currency: str = Field(default="USD")
    interval: str = Field(default="month", description="Billing interval (e.g. 'month', 'year').")
    mode: BillingMode = Field(
        description="'test' for a sk_test_ key, 'live' for sk_live_ (real charges)."
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Refs carried from the source tier — keeps the pay URL grounded.",
    )
    partial: bool = Field(
        default=False, description="True when the product exists but the price/link could not."
    )
    caveat: str | None = Field(
        default=None, description="Why the product is partial (e.g. the tier had no price)."
    )
