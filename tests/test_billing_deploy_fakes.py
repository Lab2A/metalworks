"""Fakes conform to their protocols, and the unpriced-tier rule holds.

The fakes ship in core (re-exported from ``metalworks.testing``) so downstream
users — and Task A's factory — can test against the billing/deploy seams the same
way they test against ``FakeChatModel``. These checks pin the protocol
conformance and the one behavior the real Stripe adapter must also honor: an
unpriced tier yields a partial product, never a crash.
"""

from __future__ import annotations

from metalworks.billing.protocol import BillingProvider, SubscriptionStore
from metalworks.contract.build import PricingTier
from metalworks.contract.evidence import EvidenceRef
from metalworks.deploy.protocol import DeployProvider
from metalworks.testing import (
    FakeBillingProvider,
    FakeDeploy,
    FakeSubscriptionStore,
)


def test_fakes_satisfy_their_runtime_protocols() -> None:
    assert isinstance(FakeBillingProvider(), BillingProvider)
    assert isinstance(FakeDeploy(), DeployProvider)
    assert isinstance(FakeSubscriptionStore(), SubscriptionStore)


def test_billing_priced_tier_yields_full_product() -> None:
    provider = FakeBillingProvider()
    tier = PricingTier(
        name="Pro",
        price=19.0,
        currency="USD",
        rationale="cited",
        evidence=[EvidenceRef(evidence_id="p:1", kind="price")],
    )
    product = provider.create_product(name="taxlock", tier=tier, mode_live=False)
    assert product.partial is False
    assert product.amount == 19.0
    assert product.price_id is not None
    assert product.payment_link_url is not None
    assert product.mode == "test"
    # The cite-or-die spine survives to the pay URL.
    assert [ref.evidence_id for ref in product.evidence] == ["p:1"]
    assert provider.calls and provider.calls[0]["mode_live"] is False


def test_billing_unpriced_tier_yields_partial_product() -> None:
    provider = FakeBillingProvider()
    tier = PricingTier(name="Free", price=None, rationale="no price cited")
    product = provider.create_product(name="taxlock", tier=tier)
    assert product.partial is True
    assert product.amount is None
    assert product.price_id is None
    assert product.payment_link_url is None
    assert product.caveat is not None and "unpriced" in product.caveat


def test_billing_live_mode_threads_through() -> None:
    provider = FakeBillingProvider()
    tier = PricingTier(name="Pro", price=9.0, rationale="cited")
    product = provider.create_product(name="x", tier=tier, mode_live=True)
    assert product.mode == "live"


def test_deploy_preview_is_default() -> None:
    deploy = FakeDeploy()
    result = deploy.deploy(name="My Site", files={"index.html": "<html></html>"})
    assert result.target == "preview"
    assert result.url.startswith("https://")
    assert deploy.calls[0]["files"] == {"index.html": "<html></html>"}


def test_deploy_production_target() -> None:
    deploy = FakeDeploy()
    result = deploy.deploy(name="site", files={"index.html": "x"}, target="production")
    assert result.target == "production"
    assert result.ready is True


def test_subscription_store_upserts_by_key() -> None:
    from metalworks.contract.billing import Subscription

    store = FakeSubscriptionStore()
    assert store.get_subscription("u1", "p1") is None
    store.upsert_subscription(Subscription(user_id="u1", product="p1", status="active"))
    store.upsert_subscription(Subscription(user_id="u1", product="p1", status="canceled"))
    got = store.get_subscription("u1", "p1")
    assert got is not None and got.status == "canceled"
