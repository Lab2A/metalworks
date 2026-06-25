"""Offline tests for the brief-aware source selector + per-target pickers.

Covers the acceptance criteria of issues #123 (the selector machinery) and #167
(sources-by-idea as the default — the CUT + default-on):

* relevance ranking + the deterministic access/auth gate,
* the **CUT** (#167) — ``select_sources`` returns only the relevant few + the
  non-removable reddit floor, NOT all reachable; an omitted source is dropped, so
  an espresso/consumer brief does not pull ats/wordpress,
* the **default-on** selector (#167) — ``[sources].select`` defaults ON; a run with
  no override selects by idea, an explicit override still wins,
* the **blast-radius guard** (#167) — no chat model / a failed ranking degrades to
  the reddit floor ONLY (deterministic offline), never all-reachable,
* the **non-removable floor** — a brief that matches only paid sources with no
  keys falls back to ``reddit`` with a distinct caveat, never an empty corpus,
* the pre-flight "skipped (no key): X — set ENV" line built from the specs,
* the targeting→picker conformance (every non-``none`` targeting a registered
  source declares has a registered picker).

The selector reads ``SOURCE_SPECS``; tests monkeypatch the environment to flip the
access gate and script ``FakeChatModel`` for the ranking, so they stay offline.
"""

from __future__ import annotations

import os
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
    SELECT_CAP,
    _RankingOutput,
    candidate_specs,
    preflight_lines,
    registered_targetings,
)
from metalworks.research.sources.spec import SOURCE_SPECS
from metalworks.stores.memory import MemoryStores


def _ranking(*ids: str) -> _RankingOutput:
    """A scripted ``_RankingOutput`` naming ``ids`` in order (the selector's pick)."""
    return _RankingOutput.model_validate({"ranked": [{"source_id": sid} for sid in ids]})


def _espresso_brief() -> ResearchBrief:
    """A consumer/lifestyle brief — community sources fit; ats/wordpress do not."""
    return ResearchBrief(
        brief_id="espresso",
        question="Will home baristas buy a self-cleaning espresso machine?",
        decision_context="Validating a consumer hardware v0",
        success_criteria=["clear verdict"],
        must_address=["price point"],
        target_subreddits=[],
        web_research_directions=["pricing"],
        relevance_rubric="rubric",
    )


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


# ── #167: select_sources CUTS (the default path) ─────────────────────────────


def test_select_sources_cuts_to_the_relevant_few() -> None:
    """select_sources returns the model's selected few + floor, NOT all reachable.

    The reachable keyless set includes ats/wordpress/hackernews_archive/… — 9 ids.
    An espresso/consumer brief should pull community sources and CUT the dev/B2B
    and CMS/ATS ones. We script the fake to select reddit + discourse only; the
    omitted ids (ats, wordpress, stackexchange, …) must be dropped, not re-appended.
    """
    chat = FakeChatModel()
    chat.script(_RankingOutput, _ranking("reddit", "discourse"))
    selection = select_sources(_deps(chat), brief=_espresso_brief())

    assert selection.selected == ["reddit", "discourse"]
    # The cut respects omission — irrelevant keyless sources are NOT re-appended.
    assert "ats" not in selection.selected
    assert "wordpress" not in selection.selected
    assert "stackexchange" not in selection.selected
    assert "hackernews_archive" not in selection.selected
    assert selection.floor_applied is False
    # A real cut, not the all-reachable set.
    reachable = {s.source_id for s in candidate_specs() if s.auth == "none"}
    assert len(selection.selected) < len(reachable)


def test_select_sources_keeps_reddit_floor_when_model_omits_it() -> None:
    """The non-removable reddit floor is kept (prepended) even if the model omits it."""
    chat = FakeChatModel()
    # Model selects only stackexchange — reddit must still be kept as the floor.
    chat.script(_RankingOutput, _ranking("stackexchange"))
    selection = select_sources(_deps(chat), brief=_brief())
    assert FLOOR_SOURCE in selection.selected
    assert selection.selected[0] == FLOOR_SOURCE  # floor leads
    assert "stackexchange" in selection.selected
    assert selection.floor_applied is False  # a real pick happened; floor not a fallback


def test_select_sources_caps_the_pick() -> None:
    """The cut never exceeds SELECT_CAP connectors, keeping the reddit floor."""
    chat = FakeChatModel()
    # Name far more than the cap; reddit is among them. The cut trims to SELECT_CAP.
    many = ["ats", "discourse", "hackernews", "stackexchange", "wordpress", "hn_archive"]
    chat.script(_RankingOutput, _ranking("reddit", *many))
    selection = select_sources(_deps(chat), brief=_brief())
    assert len(selection.selected) <= SELECT_CAP
    assert FLOOR_SOURCE in selection.selected


def test_select_sources_drops_hallucinated_ids() -> None:
    """A selected id outside the candidate set is dropped, not pulled."""
    chat = FakeChatModel()
    chat.script(_RankingOutput, _ranking("totally_made_up", "discourse"))
    selection = select_sources(_deps(chat), brief=_brief())
    assert "totally_made_up" not in selection.selected
    assert "discourse" in selection.selected


# ── #167: blast-radius guard — no chat / ranking-fails → reddit floor only ────


def test_select_sources_no_usable_pick_degrades_to_reddit_floor() -> None:
    """An UNSCRIPTED fake (ranking call raises) → reddit floor ONLY, not all reachable.

    This is the blast-radius guard: every existing offline research test that uses a
    FakeChatModel not scripted for the ranking call gets reddit-only — exactly the
    old default — so the default-on migration is near-zero.
    """
    chat = FakeChatModel()  # unscripted -> complete_structured raises -> cut degrades
    selection = select_sources(_deps(chat), brief=_brief())
    assert selection.selected == [FLOOR_SOURCE]  # NOT the 9 reachable keyless ids
    assert selection.floor_applied is True
    assert selection.caveat is not None


def test_select_sources_empty_selection_degrades_to_reddit_floor() -> None:
    """A model that selects nothing (empty ranked list) → reddit floor only."""
    chat = FakeChatModel()
    chat.script(_RankingOutput, _ranking())  # explicit empty pick
    selection = select_sources(_deps(chat), brief=_brief())
    assert selection.selected == [FLOOR_SOURCE]
    assert selection.floor_applied is True


# ── #167: access gate still excludes unkeyed sources in select mode ──────────


def test_select_sources_access_gate_excludes_unkeyed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A keyed source the model selects but can't reach (no key) is NOT pulled.

    The model names ``web`` (auth=key, all search keys cleared by the fixture). The
    access gate runs BEFORE selection, so ``web`` is never a candidate — it is cut by
    the gate and surfaced as skipped, never silently pulled keyless.
    """
    chat = FakeChatModel()
    chat.script(_RankingOutput, _ranking("reddit", "web", "discourse"))
    selection = select_sources(_deps(chat), brief=_brief())
    assert "web" not in selection.selected  # gated out (no key)
    assert "reddit" in selection.selected
    assert "discourse" in selection.selected
    assert any(s.source_id == "web" for s in selection.skipped)


# ── #167: [sources].select defaults ON; override still wins ──────────────────


def test_source_selector_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing configured, source_selector_enabled() is True (#167 default flip)."""
    import metalworks.config as config

    # No [sources] table → select unset → defaults ON.
    monkeypatch.setattr(config, "load_sources_config", dict)
    assert config.source_selector_enabled() is True


def test_source_selector_opt_out_with_explicit_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit [sources].select = false opts back out (the only off switch)."""
    import metalworks.config as config

    monkeypatch.setattr(config, "load_sources_config", lambda: {"select": False})
    assert config.source_selector_enabled() is False
    monkeypatch.setattr(config, "load_sources_config", lambda: {"select": True})
    assert config.source_selector_enabled() is True


def test_default_on_selects_by_idea_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run with no explicit sources selects by idea (default-on path)."""
    import metalworks.config as config
    from metalworks.research.pipeline import _maybe_select_sources

    # Real default-on (don't monkeypatch the flag) — just clear the config table.
    monkeypatch.setattr(config, "load_sources_config", dict)
    monkeypatch.setattr(config, "default_source_id", lambda: "reddit")
    chat = FakeChatModel()
    chat.script(_RankingOutput, _ranking("reddit", "discourse"))
    selection = _maybe_select_sources(_deps(chat), brief=_espresso_brief())
    assert selection is not None
    assert selection.selected == ["reddit", "discourse"]  # picked by idea, not reddit-only


def test_explicit_override_beats_default_on_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit deps.sources override wins even with the selector default-on."""
    import metalworks.config as config
    from metalworks.research.pipeline import _maybe_select_sources

    monkeypatch.setattr(config, "load_sources_config", dict)  # selector default-on
    chat = FakeChatModel()
    chat.script(_RankingOutput, _ranking("reddit", "discourse"))
    deps = _deps(chat)
    deps.sources = []  # an explicit override means "operator chose" — selector skipped
    assert _maybe_select_sources(deps, brief=_espresso_brief()) is None


# ── #167: network selector-quality eval (needs a real model) ─────────────────


@pytest.mark.network
@pytest.mark.parametrize(
    ("question", "context", "expect_in", "expect_cut"),
    [
        (
            "Will home baristas buy a self-cleaning espresso machine?",
            "Consumer hardware v0",
            {"reddit"},
            {"ats", "wordpress", "github"},
        ),
        (
            "Should we build a CLI for managing Kubernetes secrets across clusters?",
            "Developer tooling / B2B infra v0",
            {"stackexchange"},
            {"ats", "wordpress"},
        ),
        (
            "Is there demand for a WordPress plugin that auto-translates posts?",
            "WordPress ecosystem plugin v0",
            {"wordpress"},
            set(),
        ),
    ],
)
def test_selector_quality_real_model(
    question: str, context: str, expect_in: set[str], expect_cut: set[str]
) -> None:
    """A real-model cut puts relevant sources in and cuts irrelevant ones (per brief).

    Marked ``network`` (deselected by default): it resolves a real chat model and
    runs the actual selection LLM call, asserting per-brief that the expected
    relevant sources are selected and the clearly-irrelevant ones are cut. Skips
    when no chat key is set so it never fails for a credential.
    """
    has_key = any(
        os.environ.get(k)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
    )
    if not has_key:
        pytest.skip("no chat key set (ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY)")

    from metalworks.config import resolve_chat

    brief = ResearchBrief(
        brief_id="eval",
        question=question,
        decision_context=context,
        success_criteria=["clear verdict"],
        must_address=["price point"],
        target_subreddits=[],
        web_research_directions=["pricing"],
        relevance_rubric="rubric",
    )
    deps = _deps(resolve_chat())  # type: ignore[arg-type]
    selection = select_sources(deps, brief=brief)
    selected = set(selection.selected)

    assert FLOOR_SOURCE in selected, "the reddit floor is always kept"
    assert expect_in <= selected, f"expected {expect_in} selected, got {selected}"
    assert not (expect_cut & selected), f"expected {expect_cut} cut, but {expect_cut & selected} in"
    # A real cut, not the full reachable corpus.
    reachable = {s.source_id for s in candidate_specs() if s.auth == "none"}
    assert len(selected) < len(reachable), "the cut must be smaller than all-reachable"
