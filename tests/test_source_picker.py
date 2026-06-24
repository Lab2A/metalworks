"""Offline tests for the 0.4 brief-aware source selector + per-target pickers.

Covers the acceptance criteria of issue #123:

* relevance ranking + the deterministic access/auth gate,
* the **non-removable floor** — a brief that matches only paid sources with no
  keys falls back to ``reddit`` with a distinct caveat, never an empty corpus,
* the pre-flight "skipped (no key): X — set ENV" line built from the specs,
* the targeting→picker conformance (every non-``none`` targeting a registered
  source declares has a registered picker),
* selector-opt-in default (it does not run unless ``[sources].select`` is on).

The selector reads ``SOURCE_SPECS``; tests monkeypatch the environment to flip the
access gate and script ``FakeChatModel`` for the ranking, so they stay offline.
"""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.contract import ResearchBrief
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.planner import (
    pick_sources,
    preflight_skipped,
    register_target_picker,
    select_sources,
)
from metalworks.research.planner.source_picker import (
    FLOOR_SOURCE,
    _RankingOutput,
    candidate_specs,
    preflight_lines,
    registered_targetings,
)
from metalworks.research.sources.spec import SOURCE_SPECS
from metalworks.stores.memory import MemoryStores

# Env vars the paid/keyed built-ins read; clearing them makes those sources
# unreachable through the access gate (so only the open ones survive).
_KEY_ENV_VARS = (
    "PRODUCT_HUNT_TOKEN",
    "PRODUCT_HUNT_DEVELOPER_TOKEN",
    "EXA_API_KEY",
    "TAVILY_API_KEY",
    "PARALLEL_API_KEY",
    "FIRECRAWL_API_KEY",
)


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every key OFF so the gate's reachable set is deterministic."""
    for var in _KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _deps(chat: FakeChatModel) -> ResearchDeps:
    from metalworks.embeddings import FakeEmbedding

    class _Reader:
        def latest_available_month(self, content_type: str = "submissions") -> Any:
            from metalworks.research.types import MonthRef

            return MonthRef(2026, 2)

        def pull_subreddit(self, **_kwargs: Any) -> Any:
            return iter(())

        def fetch_submissions_by_ids(self, *_args: Any, **_kwargs: Any) -> Any:
            return iter(())

        def close(self) -> None:
            return None

    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_Reader(),
    )


def _brief() -> ResearchBrief:
    return ResearchBrief(
        brief_id="b1",
        question="Will people buy a sleep supplement?",
        decision_context="Validating a v0",
        success_criteria=["clear verdict"],
        must_address=["price point"],
        target_subreddits=[],
        web_research_directions=["pricing"],
        relevance_rubric="rubric",
    )


# ── relevance ranking + access/auth gate ─────────────────────────────────────


def test_pick_sources_gates_unreachable_and_keeps_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no keys set, only the keyless (open) sources are pickable."""
    chat = FakeChatModel()  # unscripted -> ranking falls back to registry order
    ids = pick_sources(_deps(chat), brief=_brief())
    # Open/keyless built-ins survive; keyed ones (producthunt, web) are gated out.
    assert "reddit" in ids
    assert "hackernews" in ids
    assert "producthunt" not in ids  # auth=key, PRODUCT_HUNT_TOKEN unset
    assert "web" not in ids  # auth=key, all search keys unset


def test_pick_sources_admits_keyed_source_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting a source's env var flips the access gate so it becomes pickable."""
    monkeypatch.setenv("PRODUCT_HUNT_TOKEN", "tok")
    chat = FakeChatModel()
    ids = pick_sources(_deps(chat), brief=_brief())
    assert "producthunt" in ids


def test_pick_sources_llm_rank_reorders_append_only() -> None:
    """The LLM ranking reorders the reachable set; omitted ids append in order."""
    chat = FakeChatModel()
    # Rank hackernews first; omit the rest. Append-only: every reachable id stays.
    chat.script(
        _RankingOutput,
        _RankingOutput.model_validate({"ranked": [{"source_id": "hackernews"}]}),
    )
    ids = pick_sources(_deps(chat), brief=_brief())
    assert ids[0] == "hackernews"
    # Nothing reachable was dropped, and no source appears twice.
    assert "reddit" in ids
    assert len(ids) == len(set(ids))


def test_pick_sources_ignores_hallucinated_ids() -> None:
    """A ranked id outside the candidate set is dropped, not pulled."""
    chat = FakeChatModel()
    chat.script(
        _RankingOutput,
        _RankingOutput.model_validate(
            {"ranked": [{"source_id": "totally_made_up"}, {"source_id": "reddit"}]}
        ),
    )
    ids = pick_sources(_deps(chat), brief=_brief())
    assert "totally_made_up" not in ids
    assert "reddit" in ids


# ── non-removable floor: zero gated sources → reddit + caveat ────────────────


def test_floor_applies_when_nothing_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A registry of only keyed sources (no keys set) falls back to the floor.

    Simulates 'the brief matched only paid sources with no keys': we shrink the
    spec registry to a single paid source, gate it out, and assert the selection
    is the reddit floor with a distinct caveat — NOT empty.
    """
    only_paid = {sid: spec for sid, spec in candidate_specs_map().items() if spec.auth != "none"}
    monkeypatch.setattr(
        "metalworks.research.planner.source_picker.SOURCE_SPECS", only_paid, raising=True
    )
    # Stop _ensure_specs_registered from re-populating the real registry under us.
    monkeypatch.setattr(
        "metalworks.research.planner.source_picker._ensure_specs_registered", lambda: None
    )

    chat = FakeChatModel()
    selection = select_sources(_deps(chat), brief=_brief())
    assert selection.selected == [FLOOR_SOURCE]  # never empty
    assert selection.floor_applied is True
    assert selection.caveat is not None
    assert FLOOR_SOURCE in selection.caveat
    # The gated-out paid sources are surfaced so the operator can unlock them.
    assert selection.skipped, "skipped key sources must be surfaced"


def candidate_specs_map() -> dict[str, Any]:
    """The real registry as a dict, populated via candidate_specs()."""
    return {s.source_id: s for s in candidate_specs()}


# ── pre-flight "skipped (no key)" line from specs ────────────────────────────


def test_preflight_skipped_lists_keyed_sources_with_env() -> None:
    """The pre-flight rows name each unreachable keyed source + its env var."""
    skipped = preflight_skipped()
    by_id = {s.source_id: s for s in skipped}
    # producthunt is auth=key with PRODUCT_HUNT_TOKEN, cleared by the fixture.
    assert "producthunt" in by_id
    ph = by_id["producthunt"]
    assert "PRODUCT_HUNT_TOKEN" in ph.env_var
    assert "PRODUCT_HUNT_TOKEN" in (ph.fix or "")  # MissingKeyError fix shape


def test_preflight_lines_render_selected_and_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """preflight_lines emits a 'Selected:' line + one 'Skipped (no key):' per row."""
    chat = FakeChatModel()
    selection = select_sources(_deps(chat), brief=_brief())
    lines = preflight_lines(selection)
    assert lines[0].startswith("Selected:")
    skip_lines = [ln for ln in lines if ln.startswith("Skipped (no key):")]
    assert any("producthunt" in ln for ln in skip_lines)
    assert any("PRODUCT_HUNT_TOKEN" in ln for ln in skip_lines)


# ── targeting → picker conformance ───────────────────────────────────────────


def test_every_declared_targeting_has_a_registered_picker() -> None:
    """Every non-'none' targeting a registered source declares has a picker.

    The selector dispatches per-target work through the picker registry; a source
    whose targeting has no picker would silently no-op. Importing the planner
    package registers subreddit/keyword/instance/slug, so the declared set must be
    a subset of the registered set.
    """
    declared = {spec.targeting for spec in candidate_specs() if spec.targeting != "none"}
    assert declared, "the built-in sources should declare at least one targeting"
    missing = declared - set(registered_targetings())
    assert not missing, f"targeting(s) with no registered picker: {sorted(missing)}"


def test_register_target_picker_is_idempotent() -> None:
    """Re-registering a targeting overwrites without raising (re-import safe)."""

    def _p(deps: ResearchDeps, *, brief: ResearchBrief) -> list[str]:
        return ["x"]

    register_target_picker("keyword", _p)
    assert "keyword" in registered_targetings()


# ── selector is opt-in by default ────────────────────────────────────────────


def test_selector_is_opt_in_pipeline_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """With [sources].select unset, the pipeline computes no selection."""
    import metalworks.config as config
    from metalworks.research.pipeline import _maybe_select_sources

    monkeypatch.setattr(config, "source_selector_enabled", lambda: False)
    chat = FakeChatModel()
    assert _maybe_select_sources(_deps(chat), brief=_brief()) is None


def test_selector_runs_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With [sources].select on (and no override), the pipeline selects."""
    import metalworks.config as config
    from metalworks.research.pipeline import _maybe_select_sources

    monkeypatch.setattr(config, "source_selector_enabled", lambda: True)
    monkeypatch.setattr(config, "default_source_id", lambda: "reddit")
    chat = FakeChatModel()
    selection = _maybe_select_sources(_deps(chat), brief=_brief())
    assert selection is not None
    assert selection.selected  # never empty (floor guarantees it)


def test_selector_skipped_when_source_override_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit deps.sources override wins — the selector does not run."""
    import metalworks.config as config
    from metalworks.research.pipeline import _maybe_select_sources

    monkeypatch.setattr(config, "source_selector_enabled", lambda: True)
    chat = FakeChatModel()
    deps = _deps(chat)
    deps.sources = []  # an explicit (even empty) override means "operator chose"
    assert _maybe_select_sources(deps, brief=_brief()) is None


# ── registry sanity ──────────────────────────────────────────────────────────


def test_candidate_specs_populates_lean_registry() -> None:
    """candidate_specs() triggers the built-in imports so the registry is non-empty."""
    ids = {s.source_id for s in candidate_specs()}
    assert {"reddit", "hackernews", "producthunt", "web"} <= ids
    assert ids <= set(SOURCE_SPECS)
