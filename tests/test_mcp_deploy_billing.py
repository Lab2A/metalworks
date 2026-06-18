"""MCP deploy + billing tool bodies — gates and envelopes (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from metalworks.mcp import tools


def test_production_deploy_blocked_without_allow_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METALWORKS_ALLOW_DEPLOY", raising=False)
    result = tools.deploy_marketing_site("any", target="production")
    assert result["error"]["error_code"] == "missing_key"  # ALLOW_DEPLOY gate
    assert "METALWORKS_ALLOW_DEPLOY" in (result["error"]["fix"] or "")


def test_deploy_invalid_target_returns_envelope() -> None:
    result = tools.deploy_marketing_site("any", target="staging")
    assert result["error"]["error_code"] == "invalid_argument"


def test_preview_deploy_missing_report_returns_not_found(tmp_path: Path) -> None:
    # Preview needs no opt-in; a missing report short-circuits before any key use.
    result = tools.deploy_marketing_site("nope", store_path=str(tmp_path / "store.db"))
    assert result["error"]["error_code"] == "not_found"


def test_live_billing_blocked_without_allow_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METALWORKS_ALLOW_BILLING", raising=False)
    result = tools.billing_create_product("any", live=True)
    assert result["error"]["error_code"] == "missing_key"  # ALLOW_BILLING gate
    assert "METALWORKS_ALLOW_BILLING" in (result["error"]["fix"] or "")


def test_test_mode_billing_missing_report_returns_not_found(tmp_path: Path) -> None:
    result = tools.billing_create_product("nope", store_path=str(tmp_path / "store.db"))
    assert result["error"]["error_code"] == "not_found"


def test_new_tools_are_registered() -> None:
    # The registration tuple is the source of truth for what the server exposes;
    # checking it needs no mcp SDK and stays offline.
    from metalworks.mcp import server

    names = {fn.__name__ for fn in server._TOOL_WRAPPERS}  # noqa: SLF001
    assert {"deploy_marketing_site", "billing_create_product"} <= names
