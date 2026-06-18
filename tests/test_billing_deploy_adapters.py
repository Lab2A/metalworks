"""Stripe + Vercel adapter tests — offline, mocked SDK / mocked HTTP.

Mirrors ``tests/test_adapters.py``:

1. The adapter modules import cleanly with no SDK installed (lazy import).
2. Missing SDK → :class:`MissingExtraError`; SDK present but no key →
   :class:`MissingKeyError`.
3. Behavior is exercised against a scripted fake ``stripe`` module (Stripe) and a
   monkeypatched ``httpx.post`` (Vercel), asserting request shape and the mapped
   contract — including the unpriced-tier and live-key safety rules.

Any test that would touch the real Stripe/Vercel APIs is marked ``network`` and
deselected by default (see the bottom of this file).
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest

from metalworks.contract.build import PricingTier
from metalworks.contract.evidence import EvidenceRef
from metalworks.errors import BillingError, DeployError, MissingExtraError, MissingKeyError

ADAPTER_MODULES = (
    "metalworks.billing.adapters",
    "metalworks.billing.adapters.stripe",
    "metalworks.deploy.adapters",
    "metalworks.deploy.adapters.vercel",
)


@pytest.mark.parametrize("module_name", ADAPTER_MODULES)
def test_adapter_module_imports_clean(module_name: str) -> None:
    importlib.import_module(module_name)


# ── Stripe: a scripted fake `stripe` module ──────────────────────────────────


class _Resource:
    """A fake Stripe resource (Product/Price/PaymentLink) recording its create calls."""

    def __init__(self, result: Any, *, raises: Exception | None = None) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._result


def _fake_stripe(
    *,
    product_id: str = "prod_1",
    price_id: str = "price_1",
    link_url: str = "https://buy.stripe.com/test_1",
    product_raises: Exception | None = None,
) -> ModuleType:
    module = ModuleType("stripe")

    class AuthenticationError(Exception):
        pass

    class StripeError(Exception):
        pass

    module.AuthenticationError = AuthenticationError  # type: ignore[attr-defined]
    module.StripeError = StripeError  # type: ignore[attr-defined]
    module.Product = _Resource(  # type: ignore[attr-defined]
        SimpleNamespace(id=product_id), raises=product_raises
    )
    module.Price = _Resource(SimpleNamespace(id=price_id))  # type: ignore[attr-defined]
    module.PaymentLink = _Resource(  # type: ignore[attr-defined]
        SimpleNamespace(id="plink_1", url=link_url)
    )
    return module


def _install_stripe(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> ModuleType:
    monkeypatch.setitem(sys.modules, "stripe", module)
    return module


def _tier(price: float | None = 19.0, *, currency: str = "USD") -> PricingTier:
    return PricingTier(
        name="Pro",
        price=price,
        currency=currency,
        rationale="cited",
        evidence=[EvidenceRef(evidence_id="p:1", kind="price")],
    )


def test_stripe_missing_sdk_raises_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "stripe", None)  # None entry → ImportError
    from metalworks.billing.adapters.stripe import StripeBilling

    with pytest.raises(MissingExtraError) as exc:
        StripeBilling(api_key="sk_test_x")
    assert 'pip install "metalworks[stripe]"' in (exc.value.fix or "")


def test_stripe_missing_key_raises_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stripe(monkeypatch, _fake_stripe())
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from metalworks.billing.adapters.stripe import StripeBilling

    with pytest.raises(MissingKeyError) as exc:
        StripeBilling()
    assert "STRIPE_SECRET_KEY" in (exc.value.fix or "")


def test_stripe_create_priced_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _install_stripe(monkeypatch, _fake_stripe())
    from metalworks.billing.adapters.stripe import StripeBilling

    billing = StripeBilling(api_key="sk_test_abc")
    product = billing.create_product(name="taxlock", tier=_tier(19.0))

    assert billing.provider_id == "stripe"
    assert product.product_id == "prod_1"
    assert product.price_id == "price_1"
    assert product.payment_link_url == "https://buy.stripe.com/test_1"
    assert product.amount == 19.0
    assert product.mode == "test"
    assert product.partial is False
    assert [r.evidence_id for r in product.evidence] == ["p:1"]

    # request shape: metadata stamps the product slug; price is cents + recurring.
    prod_call = module.Product.calls[0]  # type: ignore[attr-defined]
    assert prod_call["metadata"] == {"product": "taxlock"}
    assert prod_call["api_key"] == "sk_test_abc"
    price_call = module.Price.calls[0]  # type: ignore[attr-defined]
    assert price_call["unit_amount"] == 1900
    assert price_call["currency"] == "usd"
    assert price_call["recurring"] == {"interval": "month"}
    link_call = module.PaymentLink.calls[0]  # type: ignore[attr-defined]
    assert link_call["line_items"] == [{"price": "price_1", "quantity": 1}]
    assert link_call["subscription_data"] == {"metadata": {"product": "taxlock"}}


def test_stripe_unpriced_tier_skips_price_and_link(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _install_stripe(monkeypatch, _fake_stripe())
    from metalworks.billing.adapters.stripe import StripeBilling

    billing = StripeBilling(api_key="sk_test_abc")
    product = billing.create_product(name="taxlock", tier=_tier(None))

    assert product.partial is True
    assert product.price_id is None
    assert product.payment_link_url is None
    assert product.amount is None
    assert product.caveat is not None and "unpriced" in product.caveat
    # the product was created, but no price/link calls happened
    assert len(module.Product.calls) == 1  # type: ignore[attr-defined]
    assert module.Price.calls == []  # type: ignore[attr-defined]
    assert module.PaymentLink.calls == []  # type: ignore[attr-defined]


def test_stripe_zero_decimal_currency_not_multiplied(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _install_stripe(monkeypatch, _fake_stripe())
    from metalworks.billing.adapters.stripe import StripeBilling

    billing = StripeBilling(api_key="sk_test_abc")
    billing.create_product(name="x", tier=_tier(500.0, currency="JPY"))
    assert module.Price.calls[0]["unit_amount"] == 500  # type: ignore[attr-defined]


def test_stripe_live_key_refused_without_explicit_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stripe(monkeypatch, _fake_stripe())
    from metalworks.billing.adapters.stripe import StripeBilling

    billing = StripeBilling(api_key="sk_live_danger")
    with pytest.raises(BillingError) as exc:
        billing.create_product(name="x", tier=_tier(19.0))
    assert "live" in str(exc.value).lower()


def test_stripe_live_key_with_explicit_live_charges(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stripe(monkeypatch, _fake_stripe())
    from metalworks.billing.adapters.stripe import StripeBilling

    billing = StripeBilling(api_key="sk_live_real")
    product = billing.create_product(name="x", tier=_tier(19.0), mode_live=True)
    assert product.mode == "live"


def test_stripe_auth_error_maps_to_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _fake_stripe()
    # Raise the installed module's own AuthenticationError so the adapter's
    # isinstance check (against that same class) recognizes it.
    auth_exc = module.AuthenticationError("bad key")  # type: ignore[attr-defined]
    module.Product = _Resource(  # type: ignore[attr-defined]
        SimpleNamespace(id="prod_1"), raises=auth_exc
    )
    _install_stripe(monkeypatch, module)
    from metalworks.billing.adapters.stripe import StripeBilling

    billing = StripeBilling(api_key="sk_test_abc")
    with pytest.raises(MissingKeyError):
        billing.create_product(name="x", tier=_tier(19.0))


# ── Vercel: monkeypatched httpx.post ─────────────────────────────────────────


def _capture_vercel(
    monkeypatch: pytest.MonkeyPatch, *, status: int = 200, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Patch the vercel module's httpx.post to record the request and return a real Response."""
    from metalworks.deploy.adapters import vercel as vercel_mod

    captured: dict[str, Any] = {}
    body = (
        payload
        if payload is not None
        else {
            "url": "taxlock-abc.vercel.app",
            "readyState": "READY",
            "inspectorUrl": "https://vercel.com/acme/taxlock/abc",
        }
    )

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        request = httpx.Request("POST", url)
        return httpx.Response(status, json=body, request=request)

    monkeypatch.setattr(vercel_mod.httpx, "post", fake_post)
    return captured


def test_vercel_missing_token_raises_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    from metalworks.deploy.adapters.vercel import VercelDeploy

    with pytest.raises(MissingKeyError) as exc:
        VercelDeploy()
    assert "VERCEL_TOKEN" in (exc.value.fix or "")


def test_vercel_deploy_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_vercel(monkeypatch)
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy(token="vt_123")
    result = deploy.deploy(name="TaxLock Site", files={"index.html": "<html></html>"})

    assert result.provider == "vercel"
    assert result.target == "preview"
    assert result.url == "https://taxlock-abc.vercel.app"
    assert result.ready is True
    assert result.inspector_url == "https://vercel.com/acme/taxlock/abc"

    body = captured["json"]
    assert body["name"] == "taxlock-site"  # slugified
    assert body["files"] == [{"file": "index.html", "data": "<html></html>"}]
    assert body["projectSettings"] == {"framework": None}
    assert "target" not in body  # preview omits target
    assert captured["headers"]["Authorization"] == "Bearer vt_123"


def test_vercel_deploy_production_sets_target(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_vercel(monkeypatch)
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy(token="vt_123")
    result = deploy.deploy(name="site", files={"index.html": "x"}, target="production")
    assert result.target == "production"
    assert captured["json"]["target"] == "production"


def test_vercel_team_id_passed_as_query(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_vercel(monkeypatch)
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy(token="vt_123", team_id="team_9")
    deploy.deploy(name="site", files={"index.html": "x"})
    assert captured["params"] == {"teamId": "team_9"}


def test_vercel_empty_files_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_vercel(monkeypatch)
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy(token="vt_123")
    with pytest.raises(DeployError):
        deploy.deploy(name="site", files={})


def test_vercel_401_maps_to_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_vercel(monkeypatch, status=401, payload={"error": "forbidden"})
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy(token="vt_bad")
    with pytest.raises(MissingKeyError):
        deploy.deploy(name="site", files={"index.html": "x"})


def test_vercel_500_maps_to_deploy_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_vercel(monkeypatch, status=500, payload={"error": "boom"})
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy(token="vt_123")
    with pytest.raises(DeployError):
        deploy.deploy(name="site", files={"index.html": "x"})


def test_vercel_no_url_in_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_vercel(monkeypatch, payload={"readyState": "QUEUED"})
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy(token="vt_123")
    with pytest.raises(DeployError):
        deploy.deploy(name="site", files={"index.html": "x"})


# ── Real-API smoke tests — deselected by default (network), never run in CI ───
#
# These hit the live providers, so they are marked `network` (deselected unless
# `-m network --enable-socket`) AND skipped unless a credential is present. Use a
# Stripe TEST key (sk_test_) only — never a live key in a test run.


@pytest.mark.network
def test_stripe_real_create_product_test_mode() -> None:
    import os

    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        pytest.skip("set a Stripe TEST key (sk_test_) to run the real Stripe smoke test")
    from metalworks.billing.adapters.stripe import StripeBilling

    billing = StripeBilling()
    product = billing.create_product(name="metalworks-smoke", tier=_tier(5.0))
    assert product.mode == "test"
    assert product.payment_link_url and product.payment_link_url.startswith("http")


@pytest.mark.network
def test_vercel_real_preview_deploy() -> None:
    import os

    if not os.environ.get("VERCEL_TOKEN"):
        pytest.skip("set VERCEL_TOKEN to run the real Vercel smoke test")
    from metalworks.deploy.adapters.vercel import VercelDeploy

    deploy = VercelDeploy()
    result = deploy.deploy(
        name="metalworks-smoke",
        files={"index.html": "<!doctype html><title>metalworks smoke</title>"},
    )
    assert result.url.startswith("https://")
