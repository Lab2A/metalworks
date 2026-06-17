"""FakeBillingProvider — deterministic, offline, ships in core.

Test your paywall (or Task A's factory) against the :class:`BillingProvider`
seam with no Stripe and no network, the same way :class:`FakeChatModel` stands in
for a real model. Every call is recorded on ``.calls`` for assertions.

It honors the unpriced-tier contract: a tier with ``price is None`` yields a
``partial`` :class:`~metalworks.contract.billing.BillingProduct` (product id only,
no price id / pay URL), never a crash — the same way the real Stripe adapter
must behave.
"""

from __future__ import annotations

from typing import ClassVar

from metalworks.billing.protocol import PROTOCOL_VERSION
from metalworks.contract.billing import BillingProduct, Subscription
from metalworks.contract.build import PricingTier


class FakeBillingProvider:
    """Deterministic BillingProvider for tests.

    Ids are derived from the tier name so assertions are stable. ``mode_live``
    flows straight to ``BillingProduct.mode`` so a caller can prove it threaded
    the live/test choice through.
    """

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_product(
        self,
        *,
        name: str,
        tier: PricingTier,
        mode_live: bool = False,
    ) -> BillingProduct:
        self.calls.append({"name": name, "tier": tier, "mode_live": mode_live})
        slug = tier.name.strip().lower().replace(" ", "-") or "tier"
        mode = "live" if mode_live else "test"
        if tier.price is None:
            return BillingProduct(
                product_id=f"prod_fake_{slug}",
                price_id=None,
                payment_link_url=None,
                amount=None,
                currency=tier.currency,
                interval="month",
                mode=mode,
                evidence=list(tier.evidence),
                partial=True,
                caveat=f"tier {tier.name!r} is unpriced; no price or payment link was created.",
            )
        return BillingProduct(
            product_id=f"prod_fake_{slug}",
            price_id=f"price_fake_{slug}",
            payment_link_url=f"https://pay.fake/{slug}",
            amount=tier.price,
            currency=tier.currency,
            interval="month",
            mode=mode,
            evidence=list(tier.evidence),
        )


class FakeSubscriptionStore:
    """In-memory :class:`SubscriptionStore` for testing the access gate.

    One row per ``(user_id, product)``; ``upsert_subscription`` overwrites by that
    key. Seed it with records and point the gate at it — no DB, no network.
    """

    def __init__(self, *records: Subscription) -> None:
        self._rows: dict[tuple[str, str], Subscription] = {}
        for record in records:
            self.upsert_subscription(record)

    def get_subscription(self, user_id: str, product: str) -> Subscription | None:
        return self._rows.get((user_id, product))

    def upsert_subscription(self, record: Subscription) -> None:
        self._rows[(record.user_id, record.product)] = record
