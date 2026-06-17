"""Stripe BillingProvider adapter (``metalworks[stripe]``).

Turns one cited :class:`~metalworks.contract.build.PricingTier` into a real
Stripe product + recurring price + payment link — a working pay URL — and carries
the tier's ``evidence`` through to the returned
:class:`~metalworks.contract.billing.BillingProduct` so the pay URL still traces
to real demand.

Integration approach mirrors the LLM adapters: the ``stripe`` SDK is lazy-imported
inside ``__init__`` (gating the ``[stripe]`` extra with
:class:`~metalworks.errors.MissingExtraError`), and the secret key is read from
``STRIPE_SECRET_KEY`` at construction (:class:`~metalworks.errors.MissingKeyError`
when absent), never at import. We call the classic module-level resource API
(``stripe.Product.create`` / ``stripe.Price.create`` / ``stripe.PaymentLink.create``)
passing ``api_key`` per call — stable across ``stripe>=11`` and trivially mocked
in offline tests.

Safety — the key decides reality, the flag is the intent:

- A ``sk_test_`` key always produces a ``test``-mode product (no real charge),
  whatever ``mode_live`` says.
- A ``sk_live_`` key would create real charges, so the adapter REFUSES to use one
  unless ``mode_live=True`` is passed explicitly — "live → paid" never happens by
  accident. The CLI double-gates this further (``billing create --live --yes``).

Unpriced tiers (``price is None``): the product is created and a **partial**
:class:`BillingProduct` returned (no ``price_id`` / ``payment_link_url``, with a
``caveat``) — never a crash trying to create a price from ``None``.

Attribution: the product slug is stamped into Stripe ``metadata`` (on the
product, the price, and the payment link's ``subscription_data``) so the webhook
mapper can later tie events back to the product. The per-user half of attribution
is stamped by the downstream app at checkout — see
:mod:`metalworks.billing.webhook`.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, ClassVar

from metalworks.billing.protocol import PROTOCOL_VERSION
from metalworks.contract.billing import BillingMode, BillingProduct
from metalworks.contract.build import PricingTier
from metalworks.errors import BillingError, MissingExtraError, MissingKeyError

# Currencies Stripe denominates without a minor unit (no multiply by 100). The
# common case (USD/EUR/GBP/...) uses cents; this keeps JPY and friends correct.
_ZERO_DECIMAL = frozenset(
    {
        "bif",
        "clp",
        "djf",
        "gnf",
        "jpy",
        "kmf",
        "krw",
        "mga",
        "pyg",
        "rwf",
        "ugx",
        "vnd",
        "vuv",
        "xaf",
        "xof",
        "xpf",
    }
)
_DEFAULT_INTERVAL = "month"


class StripeBilling:
    """BillingProvider over the Stripe API. Behind the ``[stripe]`` extra."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "stripe"

    def __init__(self, *, api_key: str | None = None) -> None:
        try:
            self._stripe: Any = importlib.import_module("stripe")
        except ImportError as exc:
            raise MissingExtraError("stripe") from exc
        key = api_key or os.environ.get("STRIPE_SECRET_KEY")
        if not key:
            raise MissingKeyError("STRIPE_SECRET_KEY", provider="Stripe")
        self._key: str = key
        self._key_is_live: bool = key.startswith("sk_live_")

    def create_product(
        self,
        *,
        name: str,
        tier: PricingTier,
        mode_live: bool = False,
    ) -> BillingProduct:
        mode = self._resolve_mode(mode_live)
        metadata = {"product": name}
        product = self._create("Product", name=name, metadata=metadata)
        product_id = str(getattr(product, "id", "") or "")

        if tier.price is None:
            return BillingProduct(
                product_id=product_id,
                price_id=None,
                payment_link_url=None,
                amount=None,
                currency=tier.currency,
                interval=_DEFAULT_INTERVAL,
                mode=mode,
                evidence=list(tier.evidence),
                partial=True,
                caveat=(
                    f"tier {tier.name!r} is unpriced; the Stripe product was created but no "
                    "price or payment link could be — set a price to enable checkout."
                ),
            )

        price = self._create(
            "Price",
            product=product_id,
            unit_amount=self._amount_minor(tier.price, tier.currency),
            currency=tier.currency.lower(),
            recurring={"interval": _DEFAULT_INTERVAL},
            metadata=metadata,
        )
        price_id = str(getattr(price, "id", "") or "")
        link = self._create(
            "PaymentLink",
            line_items=[{"price": price_id, "quantity": 1}],
            metadata=metadata,
            subscription_data={"metadata": metadata},
        )
        return BillingProduct(
            product_id=product_id,
            price_id=price_id,
            payment_link_url=str(getattr(link, "url", "") or "") or None,
            amount=tier.price,
            currency=tier.currency,
            interval=_DEFAULT_INTERVAL,
            mode=mode,
            evidence=list(tier.evidence),
        )

    def _resolve_mode(self, mode_live: bool) -> BillingMode:
        """The key decides reality; refuse a live key without explicit intent."""
        if self._key_is_live and not mode_live:
            raise BillingError(
                "Refusing to use a live Stripe key (sk_live_) without explicit live mode — "
                "this would create real charges."
            )
        return "live" if self._key_is_live else "test"

    @staticmethod
    def _amount_minor(price: float, currency: str) -> int:
        """Convert a major-unit price to Stripe's integer minor unit (cents)."""
        if currency.lower() in _ZERO_DECIMAL:
            return round(price)
        return round(price * 100)

    def _create(self, resource: str, **params: Any) -> Any:
        """Call ``stripe.<Resource>.create`` with the key, mapping failures to typed errors."""
        factory = getattr(self._stripe, resource)
        try:
            return factory.create(api_key=self._key, **params)
        except Exception as exc:  # stripe.StripeError + anything the SDK raises
            if self._is_auth_error(exc):
                raise MissingKeyError(
                    "STRIPE_SECRET_KEY",
                    provider="Stripe",
                    detail="the key was rejected (check test vs live and that it is current).",
                ) from exc
            raise BillingError(f"Stripe {resource}.create failed: {exc}") from exc

    def _is_auth_error(self, exc: Exception) -> bool:
        auth_error = getattr(self._stripe, "AuthenticationError", None)
        return isinstance(auth_error, type) and isinstance(exc, auth_error)
