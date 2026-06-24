"""Lane-② MagnitudeProvider tests — the 0.3 overlay (issue #122). OFFLINE.

A magnitude provider runs AFTER clustering and attaches numbers (search volume,
package downloads) to EXISTING themes. It can never create a cluster — that is the
cite-or-die guardrail. These tests pin the whole contract:

* a provider's numbers land on the matching cluster's ``demand_signals`` and the
  cluster RE-SCORES (ranking reflects it);
* the nil / partial / error contract — omission is unknown (never ``0.0``), a
  raising provider degrades best-effort (``stage_errors`` + ``partial`` + caveat);
* a magnitude provider can NEVER add a cluster (guard);
* entity extraction is DETERMINISTIC — no LLM in the extract/merge path;
* ``check_magnitude_provider`` + ``FakeMagnitudeProvider`` exist and the npm
  provider passes the conformance check offline (canned httpx client, no network).
"""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.contract import InsightCluster, ResolvedCitation, SignalStrength, WebFinding
from metalworks.research.sources import SourceWindow
from metalworks.research.sources.magnitude import (
    MAGNITUDE_PROVIDERS,
    MAGNITUDE_SPECS,
    MagnitudeProvider,
    MagnitudeSpec,
    NpmDownloadsProvider,
    extract_entities,
    get_magnitude_provider,
    merge_magnitude_into_clusters,
    register_magnitude,
)
from metalworks.research.synthesis.cluster_ranker import compute_demand_score
from metalworks.testing import FakeMagnitudeProvider, check_magnitude_provider

# ── builders ──────────────────────────────────────────────────────────────────


def _quote(source_name: str, *, text: str = "I'd pay for this") -> ResolvedCitation:
    return ResolvedCitation(
        record_id="c_" + source_name,
        source="reddit",
        source_name=source_name,
        source_url="https://reddit.com/r/x/comments/y/c/",
        text=text,
        author_hash="a1",
        engagement=10,
    )


def _cluster(
    rank: int,
    *,
    source_name: str,
    breadth: int = 3,
    demand_signals: dict[str, float] | None = None,
) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"pain {rank}",
        demand_score=compute_demand_score(breadth, demand_signals or {"upvotes": 5}),
        distinct_author_count=breadth,
        breadth_count=breadth,
        mention_count=1,
        demand_signals=dict(demand_signals or {"upvotes": 5}),
        signal=SignalStrength.LOW,
        quotes=[_quote(source_name)],
    )


# ── 1. a provider attaches signals to matching clusters; ranking reflects it ──


def test_magnitude_attaches_and_rescore_reorders() -> None:
    # Two equal-breadth clusters; a magnitude on the 2nd should lift it above the 1st.
    c1 = _cluster(1, source_name="left-pad", breadth=3)
    c2 = _cluster(2, source_name="lodash", breadth=3)
    clusters = [c1, c2]
    assert c1.demand_score >= c2.demand_score  # tied on breadth, equal signals

    provider = FakeMagnitudeProvider({"lodash": {"downloads": 5_000_000.0}})
    measurements = provider.measure(entities=["left-pad", "lodash"], window=SourceWindow())

    changed = merge_magnitude_into_clusters(clusters, measurements, rescore=compute_demand_score)
    assert changed == 1
    # The measured cluster now carries the kind and outscores the unmeasured one.
    assert c2.demand_signals["downloads"] == 5_000_000.0
    assert "downloads" not in c1.demand_signals
    assert c2.demand_score > c1.demand_score


def test_magnitude_sums_into_existing_signal_vector() -> None:
    c = _cluster(1, source_name="react", demand_signals={"upvotes": 5, "downloads": 100.0})
    merge_magnitude_into_clusters(
        [c], {"react": {"downloads": 900.0}}, rescore=compute_demand_score
    )
    # Existing 100 + new 900 — magnitude ADDS to the vector, never replaces.
    assert c.demand_signals["downloads"] == 1000.0
    assert c.demand_signals["upvotes"] == 5


# ── 2. nil / partial / error contract ─────────────────────────────────────────


def test_measure_empty_leaves_clusters_untouched() -> None:
    c = _cluster(1, source_name="react")
    before = dict(c.demand_signals)
    before_score = c.demand_score
    changed = merge_magnitude_into_clusters([c], {}, rescore=compute_demand_score)
    assert changed == 0
    assert c.demand_signals == before
    assert c.demand_score == before_score


def test_omission_is_unknown_never_zero() -> None:
    # Provider has data for "react" only; "vue" is OMITTED, not returned as 0.0.
    provider = FakeMagnitudeProvider({"react": {"downloads": 42.0}})
    got = provider.measure(entities=["react", "vue"], window=SourceWindow())
    assert got == {"react": {"downloads": 42.0}}
    assert "vue" not in got  # omission = unknown

    c_react = _cluster(1, source_name="react")
    c_vue = _cluster(2, source_name="vue")
    merge_magnitude_into_clusters([c_react, c_vue], got, rescore=compute_demand_score)
    # The unknown cluster never gets a 0.0 downloads key (that would demote it).
    assert "downloads" in c_react.demand_signals
    assert "downloads" not in c_vue.demand_signals


def test_provider_failure_is_best_effort_in_pipeline_hook() -> None:
    # Drive the real pipeline hook with a raising provider: stage_errors gains
    # 'magnitude', a caveat string is returned, clusters are untouched.
    from metalworks.research.pipeline import _apply_magnitude_overlay

    deps = _fake_deps(providers=[FakeMagnitudeProvider({"react": {"downloads": 1.0}}, raises=True)])
    c = _cluster(1, source_name="react")
    before = dict(c.demand_signals)
    stage_errors: list[str] = []
    err = _apply_magnitude_overlay(
        deps,
        slot_plan_product=None,
        clusters=[c],
        web_findings=[],
        months=_MONTHS,
        stage_errors=stage_errors,
    )
    assert err is not None  # caveat string surfaced
    assert "magnitude" in stage_errors  # partial=True derives from stage_errors
    assert c.demand_signals == before  # failure never mutated the cluster


# ── 3. a magnitude provider can NEVER add a cluster (guard) ────────────────────


def test_magnitude_never_creates_a_cluster() -> None:
    # An empty cluster list + a fat measurement for some entity yields NO clusters.
    clusters: list[InsightCluster] = []
    changed = merge_magnitude_into_clusters(
        clusters, {"ghost-package": {"downloads": 9e9}}, rescore=compute_demand_score
    )
    assert changed == 0
    assert clusters == []  # nothing conjured

    # And in the pipeline hook: a measurement that matches no cluster's quotes
    # leaves the (single) cluster's membership and the list length unchanged.
    from metalworks.research.pipeline import _apply_magnitude_overlay

    deps = _fake_deps(providers=[FakeMagnitudeProvider({"unrelated": {"downloads": 5.0}})])
    c = _cluster(1, source_name="react")
    out = [c]
    _apply_magnitude_overlay(
        deps,
        slot_plan_product=None,
        clusters=out,
        web_findings=[],
        months=_MONTHS,
        stage_errors=[],
    )
    assert out == [c] and len(out) == 1
    assert "downloads" not in c.demand_signals  # no match → no attach


# ── 4. entity extraction is DETERMINISTIC (no LLM) ────────────────────────────


def test_extract_entities_is_pure_and_deterministic() -> None:
    c1 = _cluster(1, source_name="react")
    c2 = _cluster(2, source_name="vue")
    web = [
        WebFinding(
            finding_index=1,
            claim="x",
            specifics="y",
            source_url="https://www.npmjs.com/package/react",
            source_title="t",
            confidence=SignalStrength.MEDIUM,
        )
    ]
    args: dict[str, Any] = {
        "clusters": [c1, c2],
        "slot_plan_product": "my-product",
        "web_finding_urls": [w.source_url for w in web],
    }
    first = extract_entities(**args)
    second = extract_entities(**args)
    assert first == second  # pure: byte-identical across calls
    # Order-stable, de-duplicated, drawn from grounded handles only.
    assert first == ["my-product", "react", "vue", "npmjs.com"]


def test_overlay_makes_no_llm_call() -> None:
    # The hook receives a chat model that FAILS if invoked — proving the
    # extract/merge/band path never touches the LLM (determinism non-negotiable).
    from metalworks.llm.fake import FakeChatModel
    from metalworks.research.pipeline import _apply_magnitude_overlay

    class _ExplodingChat(FakeChatModel):
        def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("magnitude overlay must not call the LLM")

    deps = _fake_deps(
        providers=[FakeMagnitudeProvider({"react": {"downloads": 1234.0}})],
        chat=_ExplodingChat(),
    )
    c = _cluster(1, source_name="react")
    _apply_magnitude_overlay(
        deps,
        slot_plan_product="react",
        clusters=[c],
        web_findings=[],
        months=_MONTHS,
        stage_errors=[],
    )
    assert c.demand_signals["downloads"] == 1234.0  # ran, and never called the LLM


# ── 5. check_magnitude_provider + FakeMagnitudeProvider; npm passes offline ───


def test_fake_provider_conforms() -> None:
    provider = FakeMagnitudeProvider({"react": {"downloads": 100.0}, "vue": {"downloads": 50.0}})
    check_magnitude_provider(provider, entities=["react", "vue", "absent"])


def test_npm_provider_passes_offline_fixture() -> None:
    client = _StubNpmClient(
        {
            "react": 18_000_000,
            "lodash": 40_000_000,
            # "ghost-pkg" intentionally absent → 404 → omitted (unknown, not 0).
        }
    )
    provider = NpmDownloadsProvider(client=client)
    # Conformance check against the npm provider with the canned client (no network).
    check_magnitude_provider(
        provider,
        entities=["react", "lodash", "ghost-pkg"],
        window=SourceWindow(),
    )
    got = provider.measure(entities=["react", "lodash", "ghost-pkg"], window=SourceWindow())
    assert got == {
        "react": {"downloads": 18_000_000.0},
        "lodash": {"downloads": 40_000_000.0},
    }
    assert "ghost-pkg" not in got  # 404 → omitted, never 0.0


def test_npm_skips_non_package_entities() -> None:
    client = _StubNpmClient({"react": 5})
    provider = NpmDownloadsProvider(client=client)
    # Free-text (spaces), an over-deep scoped path, and an uppercase name are NOT
    # package-shaped — they are never even queried. A bare host like "npmjs.com" is
    # name-shaped so it IS queried, but npm 404s it → omitted (unknown), so it never
    # pollutes the result with a fabricated number.
    got = provider.measure(
        entities=["my cool product", "@scope/pkg/x", "ReactDOM", "npmjs.com", "react"],
        window=SourceWindow(),
    )
    assert got == {"react": {"downloads": 5.0}}
    # The malformed shapes were skipped outright (never sent to npm).
    assert "my cool product" not in client.queried
    assert "@scope/pkg/x" not in client.queried
    assert "ReactDOM" not in client.queried


def test_npm_registry_resolves_and_spec_is_magnitude_lane() -> None:
    provider = get_magnitude_provider("npm")
    assert provider.provider_id == "npm"
    assert "npm" in MAGNITUDE_PROVIDERS
    spec = MAGNITUDE_SPECS["npm"]
    assert spec.lane == "magnitude"
    assert spec.signals == ("downloads",)
    assert spec.auth == "none"


def test_register_magnitude_rejects_id_mismatch() -> None:
    spec = MagnitudeSpec(
        provider_id="other",
        signals=("downloads",),
        targeting="slug",
        auth="none",
        env=(),
        access="open",
        relevance_hint="x",
    )
    with pytest.raises(ValueError, match="does not match register id"):
        register_magnitude("npm", lambda **_: NpmDownloadsProvider(), spec=spec)


def test_magnitude_spec_requires_signals() -> None:
    with pytest.raises(ValueError, match="must be non-empty"):
        MagnitudeSpec(
            provider_id="x",
            signals=(),
            targeting="slug",
            auth="none",
            env=(),
            access="open",
            relevance_hint="x",
        )


def test_protocol_runtime_checkable() -> None:
    assert isinstance(FakeMagnitudeProvider(), MagnitudeProvider)
    assert isinstance(NpmDownloadsProvider(), MagnitudeProvider)


# ── network smoke (deselected by default) ─────────────────────────────────────


@pytest.mark.network
def test_npm_real_network_smoke() -> None:
    """Hit the live npm downloads API for a known package (run -m network)."""
    provider = NpmDownloadsProvider()
    got = provider.measure(entities=["react"], window=SourceWindow())
    assert "react" in got and got["react"]["downloads"] > 0


# ── offline httpx stub + fake deps ────────────────────────────────────────────

_MONTHS: list[Any] = []


def _months() -> list[Any]:
    from metalworks.research.types import MonthRef

    return [MonthRef(year=2026, month=5), MonthRef(year=2026, month=6)]


_MONTHS = _months()


class _StubNpmResponse:
    def __init__(self, payload: dict[str, Any] | None, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload or {}


class _StubNpmClient:
    """A minimal httpx.Client stand-in for the npm point endpoint. No network."""

    def __init__(self, downloads_by_pkg: dict[str, int]) -> None:
        self._by_pkg = downloads_by_pkg
        self.queried: list[str] = []

    def get(self, url: str) -> _StubNpmResponse:
        # URL shape: .../downloads/point/<range>/<package>
        package = url.rsplit("/", 1)[-1]
        self.queried.append(package)
        if package not in self._by_pkg:
            return _StubNpmResponse(None, status_code=404)
        return _StubNpmResponse({"downloads": self._by_pkg[package], "package": package})


def _fake_deps(
    *,
    providers: list[MagnitudeProvider],
    chat: Any | None = None,
) -> Any:
    from metalworks.embeddings import FakeEmbedding
    from metalworks.llm.fake import FakeChatModel
    from metalworks.research.deps import ResearchDeps
    from metalworks.stores import MemoryStores

    return ResearchDeps(
        chat=chat or FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_FakeReader(),
        magnitude_providers=providers,
    )


class _FakeReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        from metalworks.research.types import MonthRef

        return MonthRef(year=2026, month=6)

    def pull_subreddit(self, **kwargs: Any) -> Any:
        return iter([])

    def fetch_submissions_by_ids(self, *args: Any, **kwargs: Any) -> Any:
        return iter([])

    def close(self) -> None:
        return None
