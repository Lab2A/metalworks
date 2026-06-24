"""Lane-② PyPI downloads magnitude provider tests (issue #143). OFFLINE.

The second worked magnitude provider after npm. These pin its slice of the #122
contract: ``measure`` maps PyPI package names to last-month downloads via a stub
pypistats client, a 404/no-data package is OMITTED (unknown, never ``0.0``),
non-package handles are skipped outright, it passes ``check_magnitude_provider``,
and it resolves through the registry with a ``magnitude``-lane spec. A live smoke
against pypistats.org is marked ``network`` (deselected by default).
"""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.research.sources import SourceWindow
from metalworks.research.sources.magnitude import (
    MAGNITUDE_PROVIDERS,
    MAGNITUDE_SPECS,
    MagnitudeProvider,
    get_magnitude_provider,
)
from metalworks.research.sources.magnitude_pypi import PyPIDownloadsProvider
from metalworks.testing import check_magnitude_provider

# ── 1. measure → downloads, 404 omitted (not 0) ──────────────────────────────


def test_pypi_provider_passes_offline_fixture() -> None:
    client = _StubPyPIClient(
        {
            "requests": 60_000_000,
            "numpy": 90_000_000,
            # "ghost-pkg" intentionally absent → 404 → omitted (unknown, not 0).
        }
    )
    provider = PyPIDownloadsProvider(client=client)
    # Conformance check against the pypi provider with the canned client (no network).
    check_magnitude_provider(
        provider,
        entities=["requests", "numpy", "ghost-pkg"],
        window=SourceWindow(),
    )
    got = provider.measure(entities=["requests", "numpy", "ghost-pkg"], window=SourceWindow())
    assert got == {
        "requests": {"downloads": 60_000_000.0},
        "numpy": {"downloads": 90_000_000.0},
    }
    assert "ghost-pkg" not in got  # 404 → omitted, never 0.0


def test_pypi_skips_non_package_entities_and_normalizes() -> None:
    # pypistats keys on the PEP 503 normalized name (lowercase, runs of -_. → -).
    client = _StubPyPIClient({"scikit-learn": 12_000_000})
    provider = PyPIDownloadsProvider(client=client)
    # "Scikit_Learn" normalizes to "scikit-learn" and IS queried; free-text (spaces)
    # and a path-shaped handle are NOT package-shaped → never sent to pypistats.
    got = provider.measure(
        entities=["my cool product", "github.com/psf/requests", "Scikit_Learn"],
        window=SourceWindow(),
    )
    assert got == {"Scikit_Learn": {"downloads": 12_000_000.0}}
    assert "my cool product" not in client.queried
    assert "github.com/psf/requests" not in client.queried
    assert client.queried == ["scikit-learn"]  # normalized before the GET


# ── 2. check_magnitude_provider passes ───────────────────────────────────────


def test_pypi_provider_conforms() -> None:
    client = _StubPyPIClient({"flask": 8_000_000, "django": 9_000_000})
    provider = PyPIDownloadsProvider(client=client)
    check_magnitude_provider(provider, entities=["flask", "django", "absent"])


def test_pypi_registry_resolves_and_spec_is_magnitude_lane() -> None:
    provider = get_magnitude_provider("pypi")
    assert provider.provider_id == "pypi"
    assert "pypi" in MAGNITUDE_PROVIDERS
    spec = MAGNITUDE_SPECS["pypi"]
    assert spec.lane == "magnitude"
    assert spec.signals == ("downloads",)
    assert spec.auth == "none"


def test_pypi_protocol_runtime_checkable() -> None:
    assert isinstance(PyPIDownloadsProvider(), MagnitudeProvider)


# ── network smoke (deselected by default) ────────────────────────────────────


@pytest.mark.network
def test_pypi_real_network_smoke() -> None:
    """Hit the live pypistats API for a known package (run -m network)."""
    provider = PyPIDownloadsProvider()
    got = provider.measure(entities=["requests"], window=SourceWindow())
    assert "requests" in got and got["requests"]["downloads"] > 0


# ── offline httpx stub ───────────────────────────────────────────────────────


class _StubPyPIResponse:
    def __init__(self, payload: dict[str, Any] | None, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload or {}


class _StubPyPIClient:
    """A minimal httpx.Client stand-in for the pypistats recent endpoint. No network."""

    def __init__(self, downloads_by_pkg: dict[str, int]) -> None:
        self._by_pkg = downloads_by_pkg
        self.queried: list[str] = []

    def get(self, url: str) -> _StubPyPIResponse:
        # URL shape: .../api/packages/<package>/recent
        package = url.rsplit("/", 2)[-2]
        self.queried.append(package)
        if package not in self._by_pkg:
            return _StubPyPIResponse(None, status_code=404)
        return _StubPyPIResponse(
            {
                "data": {
                    "last_day": 0,
                    "last_week": 0,
                    "last_month": self._by_pkg[package],
                },
                "package": package,
                "type": "recent_downloads",
            }
        )
