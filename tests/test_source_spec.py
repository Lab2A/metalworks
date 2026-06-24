"""``SourceSpec`` validity matrix + built-in spec backfill.

The metadata layer the chassis reads (the selector, catalog, and 0.5 conformance
guardrail all read :data:`SOURCE_SPECS`). Two things matter here:

* ``__post_init__`` rejects every illegal lane/auth/access combo loudly, so an
  ill-declared source can't silently mis-route.
* The 5 built-in connectors each register a real spec (not the grounding stub),
  and every signal kind they declare is registered in the signals registry.
"""

from __future__ import annotations

import importlib
from datetime import date

import pytest

from metalworks.research.sources import (
    SOURCE_SPECS,
    SourceSpec,
    register_source,
)
from metalworks.research.sources.spec import _grounding_default
from metalworks.research.synthesis.signals import SIGNAL_SPECS

# id → module that self-registers it (importing runs ``register_source`` at module
# scope). We import to trigger registration without constructing — the factories
# need real readers/clients we don't have in a unit test.
_BUILTIN_MODULES = {
    "reddit": "metalworks.research.sources.arctic",
    "arctic": "metalworks.research.sources.arctic",
    "hackernews": "metalworks.research.sources.hackernews",
    "hackernews_archive": "metalworks.research.sources.hn_archive",
    "hn_archive": "metalworks.research.sources.hn_archive",
    "producthunt": "metalworks.research.sources.producthunt",
    "web": "metalworks.research.sources.web",
}


def _ensure_registered(source_id: str) -> None:
    """Import the connector module so its module-scope ``register_source`` runs."""
    importlib.import_module(_BUILTIN_MODULES[source_id])


def _valid_spec(**overrides: object) -> SourceSpec:
    base: dict[str, object] = {
        "source_id": "x",
        "lane": "grounding",
        "signals": ("upvotes",),
        "targeting": "none",
        "auth": "none",
        "env": (),
        "access": "open",
        "relevance_hint": "hint",
    }
    base.update(overrides)
    return SourceSpec(**base)  # type: ignore[arg-type]


# ── __post_init__ validity matrix (one per rule) ─────────────────────────────


def test_post_init_rejects_blocked_non_web_lane() -> None:
    """access 'blocked' ⇒ lane 'web' (a blocked source is context-only)."""
    with pytest.raises(ValueError, match="blocked"):
        _valid_spec(access="blocked", lane="grounding")


def test_post_init_rejects_key_auth_with_empty_env() -> None:
    """auth in {key,oauth,paid} ⇒ env non-empty (must name its var)."""
    with pytest.raises(ValueError, match="env"):
        _valid_spec(auth="key", env=())


def test_post_init_rejects_oauth_auth_with_empty_env() -> None:
    """oauth is an authed mode too, so the empty-env rule applies."""
    with pytest.raises(ValueError, match="env"):
        _valid_spec(auth="oauth", env=())


def test_post_init_rejects_magnitude_lane() -> None:
    """lane 'magnitude' is illegal on an ItemSource (discrete items only)."""
    with pytest.raises(ValueError, match="magnitude"):
        _valid_spec(lane="magnitude")


# ── valid combos construct cleanly (the matrix is not over-strict) ───────────


def test_post_init_allows_blocked_web() -> None:
    spec = _valid_spec(access="blocked", lane="web", signals=())
    assert spec.access == "blocked"
    assert spec.lane == "web"


def test_post_init_allows_key_auth_with_env() -> None:
    spec = _valid_spec(auth="key", env=("SOME_TOKEN",), access="free_key")
    assert spec.env == ("SOME_TOKEN",)


def test_sunset_defaults_none_and_accepts_date() -> None:
    assert _valid_spec().sunset is None
    assert _valid_spec(sunset=date(2030, 1, 1)).sunset == date(2030, 1, 1)


# ── built-in backfill ────────────────────────────────────────────────────────

_BUILTINS = (
    "reddit",
    "arctic",
    "hackernews",
    "hackernews_archive",
    "hn_archive",
    "producthunt",
    "web",
)


@pytest.mark.parametrize("source_id", _BUILTINS)
def test_builtin_registers_real_spec(source_id: str) -> None:
    """Importing each built-in lands a real spec (not the grounding stub)."""
    _ensure_registered(source_id)
    spec = SOURCE_SPECS[source_id]
    assert spec.source_id == source_id
    assert spec.relevance_hint  # a real source declares its hint
    # Not the bare grounding default (which is hint-less / signal-less).
    assert spec != _grounding_default(source_id)


def test_builtin_lanes_and_auth() -> None:
    """The backfilled lane/auth/signal facts match each connector's reality."""
    for sid in ("reddit", "arctic"):
        _ensure_registered(sid)
        assert SOURCE_SPECS[sid].lane == "grounding"
        assert SOURCE_SPECS[sid].auth == "none"
        assert SOURCE_SPECS[sid].signals == ("upvotes",)

    for sid in ("hackernews", "hackernews_archive", "hn_archive"):
        _ensure_registered(sid)
        assert SOURCE_SPECS[sid].lane == "grounding"
        assert SOURCE_SPECS[sid].auth == "none"
        assert SOURCE_SPECS[sid].signals == ("points",)

    _ensure_registered("producthunt")
    ph = SOURCE_SPECS["producthunt"]
    assert ph.lane == "grounding"
    assert ph.auth == "key"
    assert "PRODUCT_HUNT_TOKEN" in ph.env
    assert ph.signals == ("votes",)

    _ensure_registered("web")
    web = SOURCE_SPECS["web"]
    assert web.lane == "web"
    assert web.signals == ()


@pytest.mark.parametrize("source_id", _BUILTINS)
def test_builtin_signals_are_registered(source_id: str) -> None:
    """Every signal kind a built-in declares is registered in synthesis/signals."""
    _ensure_registered(source_id)
    for kind in SOURCE_SPECS[source_id].signals:
        assert kind in SIGNAL_SPECS, f"{source_id} emits unregistered signal {kind!r}"


# ── runtime back-compat: spec is optional ────────────────────────────────────


def test_register_without_spec_lands_grounding_default() -> None:
    """A bare register (no spec=) keeps working and gets a grounding stub."""

    def _factory(**_: object) -> object:
        return object()

    register_source("spectest_bare", _factory)  # type: ignore[arg-type]
    assert SOURCE_SPECS["spectest_bare"] == _grounding_default("spectest_bare")


def test_register_spec_id_mismatch_raises() -> None:
    def _factory(**_: object) -> object:
        return object()

    with pytest.raises(ValueError, match="does not match"):
        register_source(
            "spectest_mismatch",
            _factory,  # type: ignore[arg-type]
            spec=_valid_spec(source_id="other"),
        )
