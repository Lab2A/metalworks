"""CLI tests for `deploy` + `billing` — gates, fakes, and the doctor line (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import metalworks.config as config
from metalworks.cli import app
from metalworks.contract.build import BuildSpec, PricingTier
from metalworks.contract.evidence import EvidenceRef
from metalworks.testing import FakeBillingProvider, FakeDeploy

runner = CliRunner()


def _spec_file(tmp_path: Path, *tiers: PricingTier) -> Path:
    spec = BuildSpec(
        spec_id="spec_1",
        report_id="taxlock",
        surface="web",
        stack="empty",
        pricing_tiers=list(tiers),
    )
    path = tmp_path / "spec.json"
    path.write_text(spec.model_dump_json(), encoding="utf-8")
    return path


def _pro_tier() -> PricingTier:
    return PricingTier(
        name="Pro",
        price=19.0,
        currency="USD",
        rationale="cited",
        evidence=[EvidenceRef(evidence_id="p:1", kind="price")],
    )


# ── deploy ───────────────────────────────────────────────────────────────────


def test_deploy_site_preview(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeDeploy()
    monkeypatch.setattr(config, "resolve_deploy", lambda: fake)
    site = tmp_path / "index.html"
    site.write_text("<html>hi</html>", encoding="utf-8")

    result = runner.invoke(app, ["deploy", "--site", str(site)])
    assert result.exit_code == 0, result.output
    assert "Deployed" in result.output
    assert "preview" in result.output
    assert fake.calls[0]["target"] == "preview"
    assert fake.calls[0]["files"] == {"index.html": "<html>hi</html>"}


def test_deploy_prod_requires_yes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeDeploy()
    monkeypatch.setattr(config, "resolve_deploy", lambda: fake)
    site = tmp_path / "index.html"
    site.write_text("<html></html>", encoding="utf-8")

    result = runner.invoke(app, ["deploy", "--site", str(site), "--prod"])
    assert result.exit_code == 0
    assert "gated" in result.output.lower()
    # The gate fires before any provider call.
    assert fake.calls == []


def test_deploy_prod_with_yes_promotes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeDeploy()
    monkeypatch.setattr(config, "resolve_deploy", lambda: fake)
    site = tmp_path / "index.html"
    site.write_text("<html></html>", encoding="utf-8")

    result = runner.invoke(app, ["deploy", "--site", str(site), "--prod", "--yes"])
    assert result.exit_code == 0, result.output
    assert "production" in result.output
    assert fake.calls[0]["target"] == "production"


def test_deploy_missing_site_file_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "resolve_deploy", lambda: FakeDeploy())
    result = runner.invoke(app, ["deploy", "--site", str(tmp_path / "nope.html")])
    assert result.exit_code == 1


# ── billing create ─────────────────────────────────────────────────────────


def test_billing_create_from_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeBillingProvider()
    monkeypatch.setattr(config, "resolve_billing", lambda: fake)
    spec = _spec_file(tmp_path, _pro_tier())

    result = runner.invoke(app, ["billing", "create", str(spec)])
    assert result.exit_code == 0, result.output
    assert "Pro" in result.output
    assert "test" in result.output
    assert "pay" in result.output.lower()
    assert fake.calls[0]["mode_live"] is False


def test_billing_create_writes_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "resolve_billing", lambda: FakeBillingProvider())
    spec = _spec_file(tmp_path, _pro_tier())
    out = tmp_path / "product.json"

    result = runner.invoke(app, ["billing", "create", str(spec), "--json", str(out)])
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "product_id" in out.read_text(encoding="utf-8")


def test_billing_create_unpriced_tier_is_partial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "resolve_billing", lambda: FakeBillingProvider())
    spec = _spec_file(tmp_path, PricingTier(name="Free", price=None, rationale="no price"))

    result = runner.invoke(app, ["billing", "create", str(spec)])
    assert result.exit_code == 0, result.output
    assert "partial" in result.output.lower()


def test_billing_create_live_requires_yes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeBillingProvider()
    monkeypatch.setattr(config, "resolve_billing", lambda: fake)
    spec = _spec_file(tmp_path, _pro_tier())

    result = runner.invoke(app, ["billing", "create", str(spec), "--live"])
    assert result.exit_code == 0
    assert "gated" in result.output.lower()
    assert fake.calls == []  # refused before the provider is touched


def test_billing_create_named_tier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeBillingProvider()
    monkeypatch.setattr(config, "resolve_billing", lambda: fake)
    spec = _spec_file(
        tmp_path,
        PricingTier(name="Starter", price=9.0, rationale="cited"),
        PricingTier(name="Pro", price=29.0, rationale="cited"),
    )

    result = runner.invoke(app, ["billing", "create", str(spec), "--tier", "Pro"])
    assert result.exit_code == 0, result.output
    tier = fake.calls[0]["tier"]
    assert isinstance(tier, PricingTier) and tier.name == "Pro"


def test_billing_create_unknown_tier_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "resolve_billing", lambda: FakeBillingProvider())
    spec = _spec_file(tmp_path, _pro_tier())
    result = runner.invoke(app, ["billing", "create", str(spec), "--tier", "Enterprise"])
    assert result.exit_code == 1


# ── billing status + doctor ─────────────────────────────────────────────────


def test_billing_status_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    result = runner.invoke(app, ["billing", "status"])
    assert result.exit_code == 0
    assert "unset" in result.output.lower()


def test_billing_status_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc")
    result = runner.invoke(app, ["billing", "status"])
    assert result.exit_code == 0
    assert "test" in result.output
    # the secret itself is never echoed
    assert "sk_test_abc" not in result.output


def test_doctor_shows_deploy_billing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_secret")
    monkeypatch.setenv("VERCEL_TOKEN", "vt_secret")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Deploy & billing" in result.output
    assert "live" in result.output
    # secrets never printed
    assert "sk_live_secret" not in result.output
    assert "vt_secret" not in result.output
