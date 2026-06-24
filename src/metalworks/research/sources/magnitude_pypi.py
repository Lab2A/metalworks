"""Lane-② magnitude: PyPI package downloads (keyless, dev-demand volume).

The second worked **free** magnitude provider after :class:`NpmDownloadsProvider`
(see :mod:`metalworks.research.sources.magnitude` for the lane's contract). PyPI is
the cleanest second number: keyless, a real dev-adoption volume, and the
``downloads`` kind it emits is already registered ``is_magnitude=True`` in
:mod:`metalworks.research.synthesis.signals` — no new ``register_signal``.

:class:`PyPIDownloadsProvider` maps each entity that looks like a PyPI package name
to its last-month download count via pypistats.org's public ``recent`` endpoint
(``GET pypistats.org/api/packages/<pkg>/recent``). A package pypistats has no data
for (404, or a null/absent count) is OMITTED from the result — omission is unknown,
never ``0.0`` (the #122 contract). Transport failures propagate to the best-effort
caller (caveat + ``partial``), never fatal.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from metalworks.research.sources.magnitude import (
    MagnitudeSpec,
    register_magnitude,
)

if TYPE_CHECKING:
    from metalworks.research.sources import SourceWindow


_PYPI_API = "https://pypistats.org/api/packages"
_PYPI_TIMEOUT_S = 30.0
# pypistats' ``recent`` endpoint exposes last-day/last-week/last-month totals; the
# last-month count is the standard package-popularity proxy (mirrors npm last-month).
_PYPI_RECENT_KEY = "last_month"


def _is_pypi_package_name(entity: str) -> bool:
    """Whether ``entity`` looks like a PyPI package name we can safely query.

    PyPI project names are case-insensitive and allow ASCII letters, digits, and any
    of ``-`` / ``_`` / ``.`` as separators (PEP 503). We reject anything with
    whitespace or a path/URL shape so a free-text claim or a domain is never sent as
    a package name (pypistats would 404 it, but skipping is cheaper and cleaner).
    """
    e = entity.strip()
    if not e or " " in e or "/" in e:
        return False
    return all(c.isalnum() or c in "-._" for c in e)


def _normalize_pypi_name(entity: str) -> str:
    """The PEP 503 normalized form pypistats keys on (lowercase, runs → ``-``)."""
    import re

    return re.sub(r"[-_.]+", "-", entity.strip()).lower()


@dataclass
class PyPIDownloadsProvider:
    """Magnitude over the public, keyless pypistats.org recent-downloads API.

    Maps each entity that looks like a PyPI package name to its last-month download
    count via ``pypistats.org/api/packages/<pkg>/recent``. A package pypistats has no
    data for (404, or a null ``last_month``) is OMITTED from the result — omission is
    unknown, never ``0.0``. Entities that are not package-shaped (a domain with a
    path, a free-text product name with spaces) are skipped entirely, so a non-package
    handle never gets mis-queried.

    The HTTP client is injectable (``client=``) so the offline conformance fixture
    drives it without a live network; the real network path is exercised only by a
    ``network``-marked test.
    """

    provider_id: str = "pypi"
    signals: tuple[str, ...] = ("downloads",)
    timeout_s: float = _PYPI_TIMEOUT_S
    client: Any | None = None

    def measure(
        self, *, entities: Sequence[str], window: SourceWindow | None = None
    ) -> dict[str, dict[str, float]]:
        # pypistats' recent endpoint has no window parameter — it always reports the
        # trailing last-month total, the package-popularity proxy. ``window`` is part
        # of the protocol signature but unused here (npm clamps to a span; pypistats
        # does not expose one).
        del window
        out: dict[str, dict[str, float]] = {}
        seen: set[str] = set()
        for entity in entities:
            name = entity.strip()
            if not _is_pypi_package_name(name) or name in seen:
                continue
            seen.add(name)
            count = self._fetch_downloads(name)
            if count is not None:  # omission = unknown; never store 0.0 for a miss
                out[entity] = {"downloads": float(count)}
        return out

    def _fetch_downloads(self, package: str) -> int | None:
        """One GET → the package's last-month download count, or ``None`` (unknown).

        A 404 (pypistats has no such package / no data) returns ``None`` — the entity
        is omitted, not zeroed. A null/absent ``last_month`` field also maps to
        ``None``. Any other HTTP error raises, so a transport failure propagates to
        the best-effort caller as a degraded stage.
        """
        import httpx

        url = f"{_PYPI_API}/{_normalize_pypi_name(package)}/recent"
        client = self.client
        owns = client is None
        if owns:
            client = httpx.Client(
                timeout=self.timeout_s,
                headers={"User-Agent": "metalworks-research/0.1 (+https://github.com)"},
            )
        try:
            resp = client.get(url)
        finally:
            if owns:
                client.close()
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        payload: Any = resp.json()
        if not isinstance(payload, dict):
            return None
        data = cast("dict[str, Any]", payload).get("data")
        if not isinstance(data, dict):
            return None
        value = cast("dict[str, Any]", data).get(_PYPI_RECENT_KEY)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)


def _pypi_factory(**kwargs: Any) -> PyPIDownloadsProvider:
    return PyPIDownloadsProvider(**kwargs)


# Self-register on import (append-friendly registry; mirrors the npm provider).
# pypistats.org is open + keyless; "downloads" is its registered magnitude kind.
register_magnitude(
    "pypi",
    _pypi_factory,
    spec=MagnitudeSpec(
        provider_id="pypi",
        signals=("downloads",),
        targeting="slug",
        auth="none",
        env=(),
        access="open",
        relevance_hint="package adoption / install demand for a named PyPI package",
    ),
)


__all__ = ["PyPIDownloadsProvider"]
