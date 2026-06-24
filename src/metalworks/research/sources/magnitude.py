"""Lane-② magnitude providers — numbers attached to themes, never new themes.

A :class:`~metalworks.research.sources.ItemSource` pulls *quotable* records
(grounding): every claim it carries traces to a real comment. A **magnitude**
source is a different shape entirely — search volume, install counts, package
downloads, funding totals. It has no quotable record and no author; it is a raw
number for an *entity* (a package, a product name, a domain). Forcing it through
``ItemSource`` would either fabricate a quote (cite-or-die violation) or let a bare
number conjure a cluster out of thin air. So magnitude gets its own lane:

* :class:`MagnitudeProvider` runs **after** clustering. It is handed the entities
  the pipeline already extracted *deterministically* from grounded artifacts
  (cluster quote product/package names, the brief's slot-plan product, web-finding
  domains) and returns ``entity -> {kind: value}`` — a measurement for each entity
  it actually has data for.
* The pipeline merges those values into the matching
  :class:`~metalworks.contract.InsightCluster.demand_signals` vector and rescores
  (RANKING only — ``compute_demand_score``; the verdict band never sees it).
* **It can NEVER create a cluster.** A magnitude with no theme to attach to is
  dropped, not promoted. That is the cite-or-die guardrail: a number is only ever
  evidence *for an already-grounded theme*, never a theme on its own.

Two non-negotiables the contract enforces:

* **Omission means unknown, never ``0.0``.** :meth:`MagnitudeProvider.measure`
  returns only the entities it has real data for. A package with no downloads in
  the window is simply absent from the result — the pipeline records "unknown",
  not "zero demand". Returning ``0.0`` would silently demote a real theme.
* **Best-effort.** A provider that raises or times out is degraded, not fatal: the
  pipeline appends to ``stage_errors``, sets ``partial=True``, and adds a caveat —
  the same posture web research uses. A magnitude failure never breaks a run.

Registry. :data:`MAGNITUDE_PROVIDERS` mirrors
:data:`~metalworks.research.sources.SOURCES`: a provider self-registers on import
via :func:`register_magnitude`, declaring a :class:`SourceSpec` whose ``lane`` is
``"magnitude"`` (the one place that lane is legal — an ``ItemSource`` spec rejects
it). One worked **free** provider ships here: :class:`NpmDownloadsProvider`
(``auth=none``, ``api.npmjs.org/downloads``), emitting the ``downloads`` kind.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from metalworks.research.sources.spec import (
    Access,
    Auth,
    Targeting,
)

if TYPE_CHECKING:
    from metalworks.research.sources import SourceWindow


# ── magnitude spec (lane='magnitude', which the ItemSource spec rejects) ──────


@dataclass(frozen=True)
class MagnitudeSpec:
    """Declarative metadata for one magnitude provider — the magnitude-lane peer
    of :class:`~metalworks.research.sources.spec.SourceSpec`.

    A magnitude provider's lane is fixed (``"magnitude"``), the very value
    :class:`SourceSpec` forbids (an ``ItemSource`` pulls grounding/web items, not a
    raw denominator). The rest mirrors ``SourceSpec``: ``signals`` are the
    ``is_magnitude`` kinds it emits (each registered in
    :mod:`metalworks.research.synthesis.signals`), ``targeting`` is the entity shape
    it measures (a package ``slug``, a ``keyword``, a domain), and
    ``auth`` / ``env`` / ``access`` describe reachability. ``relevance_hint`` is the
    one line the catalog ranks on.

    The validity matrix mirrors ``SourceSpec``: an auth'd provider must name its
    ``env`` var(s), and ``signals`` must be non-empty (a magnitude provider with no
    declared kind has nothing to attach).
    """

    provider_id: str
    signals: tuple[str, ...]
    targeting: Targeting
    auth: Auth
    env: tuple[str, ...]
    access: Access
    relevance_hint: str

    lane: str = "magnitude"

    def __post_init__(self) -> None:
        if not self.signals:
            raise ValueError(
                f"magnitude provider {self.provider_id!r}: 'signals' must be non-empty "
                "(a provider with no declared kind has nothing to attach)"
            )
        if self.auth in {"key", "oauth", "paid"} and not self.env:
            raise ValueError(
                f"magnitude provider {self.provider_id!r}: auth {self.auth!r} requires a "
                "non-empty 'env' naming the var(s) it reads"
            )


# ── the provider protocol ─────────────────────────────────────────────────────


@runtime_checkable
class MagnitudeProvider(Protocol):
    """A lane-② source: a number for an entity, attached AFTER clustering.

    ``provider_id`` is the registry key; ``signals`` are the ``is_magnitude`` kinds
    it emits (e.g. ``("downloads",)``). :meth:`measure` is the whole contract: given
    the entities the pipeline extracted deterministically from grounded artifacts
    and the run's window, return ``entity -> {kind: value}`` for the entities it has
    real data for. Omission is unknown — NEVER return ``0.0`` for a miss. A provider
    never sees the corpus, never emits a quote, and can never create a cluster.
    """

    provider_id: str
    signals: tuple[str, ...]

    def measure(
        self, *, entities: Sequence[str], window: SourceWindow
    ) -> dict[str, dict[str, float]]:
        """Measure ``entities`` over ``window`` → ``entity -> {kind: value}``.

        Returns only entities it has real data for: an absent entity is *unknown*,
        not zero. May raise on transport failure — the caller treats that as
        best-effort (caveat + ``partial``), never fatal.
        """
        ...


# ── append-friendly registry (mirrors ``register_source``) ────────────────────

MagnitudeFactory = Callable[..., MagnitudeProvider]

# Module-level registry. Providers self-register here on import via
# ``register_magnitude`` — never by editing a shared inline list — so concurrent
# provider streams can land without colliding.
MAGNITUDE_PROVIDERS: dict[str, MagnitudeFactory] = {}
MAGNITUDE_SPECS: dict[str, MagnitudeSpec] = {}


def register_magnitude(provider_id: str, factory: MagnitudeFactory, *, spec: MagnitudeSpec) -> None:
    """Register ``factory`` under ``provider_id`` (idempotent on re-import).

    Re-registering the same id overwrites — module re-imports under pytest must not
    raise, and a downstream override of a built-in is intentional. Unlike
    ``register_source``, ``spec`` is REQUIRED: a magnitude provider with no declared
    ``signals`` has nothing to attach, so there is no meaningful default. A passed
    ``spec.provider_id`` must match ``provider_id``.
    """
    if spec.provider_id != provider_id:
        raise ValueError(
            f"spec.provider_id {spec.provider_id!r} does not match register id {provider_id!r}"
        )
    MAGNITUDE_PROVIDERS[provider_id] = factory
    MAGNITUDE_SPECS[provider_id] = spec


def get_magnitude_provider(provider_id: str, **kwargs: object) -> MagnitudeProvider:
    """Construct the registered magnitude provider for ``provider_id``.

    Triggers a lazy import of the built-in providers so a bare ``import`` of this
    package stays free of ``httpx``. Unknown ids raise ``KeyError``.
    """
    _BUILTIN_MODULES = {
        "npm": "metalworks.research.sources.magnitude",
        "wikipedia": "metalworks.research.sources.magnitude_wikipedia",
        "pypi": "metalworks.research.sources.magnitude_pypi",
    }
    if provider_id not in MAGNITUDE_PROVIDERS and provider_id in _BUILTIN_MODULES:
        import importlib

        importlib.import_module(_BUILTIN_MODULES[provider_id])
    try:
        factory = MAGNITUDE_PROVIDERS[provider_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown magnitude provider {provider_id!r}; registered: {sorted(MAGNITUDE_PROVIDERS)}"
        ) from exc
    return factory(**kwargs)


# ── the worked free provider: npm package downloads ──────────────────────────

_NPM_API = "https://api.npmjs.org/downloads"
_NPM_TIMEOUT_S = 30.0
# npm's point endpoint exposes named ranges; "last-month" is the demand window we
# read (a 30-day download count is the standard package-popularity proxy).
_NPM_RANGE = "last-month"


def _npm_window_point(window: SourceWindow | None) -> str:
    """Translate a :class:`SourceWindow` into npm's point-range token.

    npm's point endpoint accepts named ranges (``last-day`` / ``last-week`` /
    ``last-month``) OR an explicit ``YYYY-MM-DD:YYYY-MM-DD`` span. We map the run's
    window to an explicit span when it carries datetimes (so the measurement tracks
    the brief's window), else fall back to the standard ``last-month`` popularity
    proxy. Spans longer than npm's 18-month cap are clamped at the tail.
    """
    if window is None or window.start is None or window.end is None:
        return _NPM_RANGE
    start = window.start.date()
    end = window.end.date()
    # npm rejects ranges over 18 months; clamp the start forward if needed.
    floor = end - timedelta(days=540)
    if start < floor:
        start = floor
    if start > end:
        return _NPM_RANGE
    return f"{start.isoformat()}:{end.isoformat()}"


def _is_npm_package_name(entity: str) -> bool:
    """Whether ``entity`` looks like an npm package name we can safely query.

    npm names are lowercase, may be scoped (``@scope/name``), and allow
    ``-`` / ``.`` / ``_``. We deliberately reject anything with whitespace or a
    path/URL shape so a free-text claim or a domain never gets sent as a package
    name (which npm would 404 on, but skipping is cheaper and cleaner).
    """
    e = entity.strip()
    if not e or " " in e or "/" in e.removeprefix("@") or e != e.lower():
        return False
    body = e[1:] if e.startswith("@") else e
    return bool(body) and all(c.isalnum() or c in "-._" for c in body)


@dataclass
class NpmDownloadsProvider:
    """Magnitude over the public, keyless npm registry downloads API.

    Maps each entity that looks like an npm package name to its download count over
    the run's window via ``api.npmjs.org/downloads/point/<range>/<pkg>``. A package
    npm has no data for (404, or a null ``downloads``) is OMITTED from the result —
    omission is unknown, never ``0.0``. Entities that are not package-shaped (a
    domain, a free-text product name with spaces) are skipped entirely, so a domain
    never gets mis-queried.

    The HTTP client is injectable (``client=``) so the offline conformance fixture
    and the ``FakeMagnitudeProvider``-free integration test drive it without a live
    network; the real network path is exercised only by a ``network``-marked test.
    """

    provider_id: str = "npm"
    signals: tuple[str, ...] = ("downloads",)
    timeout_s: float = _NPM_TIMEOUT_S
    client: Any | None = None

    def measure(
        self, *, entities: Sequence[str], window: SourceWindow | None = None
    ) -> dict[str, dict[str, float]]:
        point = _npm_window_point(window)
        out: dict[str, dict[str, float]] = {}
        seen: set[str] = set()
        for entity in entities:
            name = entity.strip()
            if not _is_npm_package_name(name) or name in seen:
                continue
            seen.add(name)
            count = self._fetch_downloads(name, point)
            if count is not None:  # omission = unknown; never store 0.0 for a miss
                out[entity] = {"downloads": float(count)}
        return out

    def _fetch_downloads(self, package: str, point: str) -> int | None:
        """One GET → the package's download count, or ``None`` (unknown).

        A 404 (npm has no such package / no data for the range) returns ``None`` —
        the entity is omitted, not zeroed. A null/absent ``downloads`` field also
        maps to ``None``. Any other HTTP error raises, so a transport failure
        propagates to the best-effort caller as a degraded stage.
        """
        import httpx

        url = f"{_NPM_API}/point/{point}/{package}"
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
        downloads = cast("dict[str, Any]", payload).get("downloads")
        if isinstance(downloads, bool) or not isinstance(downloads, (int, float)):
            return None
        return int(downloads)


def _npm_factory(**kwargs: Any) -> NpmDownloadsProvider:
    return NpmDownloadsProvider(**kwargs)


# Self-register on import (append-friendly registry; mirrors the source connectors).
# The npm downloads API is open + keyless; "downloads" is its registered magnitude kind.
register_magnitude(
    "npm",
    _npm_factory,
    spec=MagnitudeSpec(
        provider_id="npm",
        signals=("downloads",),
        targeting="slug",
        auth="none",
        env=(),
        access="open",
        relevance_hint="package adoption / install demand for a named npm package",
    ),
)


# ── deterministic entity extraction (NO LLM — preserves determinism) ──────────


def _registrable_domain(url: str) -> str:
    """Hostname of ``url`` without a leading ``www.`` (empty when there is none)."""
    from urllib.parse import urlsplit

    host = urlsplit(url.strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def extract_entities(
    *,
    clusters: Sequence[Any],
    slot_plan_product: str | None,
    web_finding_urls: Sequence[str] = (),
) -> list[str]:
    """Deterministically derive measurable entities from already-grounded artifacts.

    PURE function, NO LLM call — this is the determinism non-negotiable (review H1):
    the entities a magnitude provider measures are read straight off the grounded
    output, never guessed. Sources, in order:

    * **cluster quote source names** — a quote's ``source_name`` (e.g. an npm
      package label) is a real, cited handle for the theme;
    * **the brief's slot-plan product** — the pinned product the run is about;
    * **web-finding domains** — the registrable domain of each grounded web finding.

    Returns a de-duplicated, order-stable list (first-seen wins) so two runs over
    the same report extract byte-identical entities. The provider decides which of
    these it can actually measure (a package-shaped name, a domain); extraction does
    not pre-filter by provider shape — it offers every grounded handle.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str | None) -> None:
        if not value:
            return
        v = value.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    if slot_plan_product:
        _add(slot_plan_product)
    for cluster in clusters:
        for quote in getattr(cluster, "quotes", []) or []:
            _add(getattr(quote, "source_name", None))
    for url in web_finding_urls:
        _add(_registrable_domain(url))
    return out


# ── merge + rescore (RANKING only — the verdict band never sees this) ─────────


def merge_magnitude_into_clusters(
    clusters: Sequence[Any],
    measurements: Mapping[str, Mapping[str, float]],
    *,
    rescore: Callable[[int, Mapping[str, float]], float],
) -> int:
    """Merge entity measurements into each cluster's ``demand_signals`` + rescore.

    For every cluster, the entities it OWNS are the source names of its quotes (the
    same handles :func:`extract_entities` read). Any measurement keyed by one of
    those entities is summed into the cluster's ``demand_signals`` by kind, then the
    cluster's ``demand_score`` is recomputed via ``rescore(breadth, signals)`` — the
    existing ``compute_demand_score`` path (RANKING only; the verdict band is
    untouched, issue 0.2b). A cluster that matches no measurement is left exactly as
    it was. Returns the number of clusters whose signals changed (observability).

    A magnitude measurement can only ever ADD a signal to an EXISTING cluster — this
    function never constructs a cluster, the cite-or-die guardrail.
    """
    changed = 0
    for cluster in clusters:
        owned = {
            getattr(q, "source_name", "").strip()
            for q in (getattr(cluster, "quotes", []) or [])
            if getattr(q, "source_name", "").strip()
        }
        merged: dict[str, float] = {}
        for entity in owned:
            kinds = measurements.get(entity)
            if not kinds:
                continue
            for kind, value in kinds.items():
                merged[kind] = merged.get(kind, 0.0) + float(value)
        if not merged:
            continue
        signals = dict(cluster.demand_signals)
        for kind, value in merged.items():
            signals[kind] = signals.get(kind, 0.0) + value
        cluster.demand_signals = signals
        cluster.demand_score = rescore(cluster.breadth_count, signals)
        changed += 1
    return changed


__all__ = [
    "MAGNITUDE_PROVIDERS",
    "MAGNITUDE_SPECS",
    "Access",
    "Auth",
    "MagnitudeFactory",
    "MagnitudeProvider",
    "MagnitudeSpec",
    "NpmDownloadsProvider",
    "Targeting",
    "extract_entities",
    "get_magnitude_provider",
    "merge_magnitude_into_clusters",
    "register_magnitude",
]
