"""Visual-design pillar: the grounding-tier ladder, SAFE/RISK, renders, partials.

Offline. FakeChatModel is scripted on the ONE ``_DesignDraft`` output and
FakeRenderer drives the competitor teardown, so the degradation ladder
(renderer > web > model_knowledge), the resilient drop-and-continue, the
DESIGN.md / preview renders, and the honest partials all run for real. No
network, no keys, no browser.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import (
    Competitor,
    CompetitorMap,
    DemandReport,
    EvidenceRef,
    ExistingSolution,
    Fork,
    InsightCluster,
    Landscape,
    SignalStrength,
)
from metalworks.contract.bundle import Research
from metalworks.contract.design import DesignChoice, DesignSystem, LandscapeSignal
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.render.fake import FakeRenderer
from metalworks.research.deps import ResearchDeps
from metalworks.research.design import (
    _CONVERGENCE_FACES,
    _DIMENSIONS,
    DEFAULT_TASTE,
    TASTE_PRESETS,
    _DesignDraft,
    build_design_system,
    render_design_md,
    render_design_preview_html,
    resolve_chrome,
    resolve_taste,
)
from metalworks.stores import MemoryStores

_NOW = datetime(2026, 2, 1, tzinfo=UTC)


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        raise NotImplementedError

    def pull_subreddit(self, **_kwargs: Any) -> Any:
        raise NotImplementedError

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _report() -> DemandReport:
    return DemandReport(
        report_id="rpt-1",
        query="a calm focus timer for makers",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=_NOW,
        date_range_end=_NOW,
        total_threads=40,
        total_distinct_authors=88,
        ranked_clusters=[
            InsightCluster(
                rank=1,
                claim="people want a timer that doesn't nag",
                demand_score=12.0,
                distinct_author_count=30,
                mention_count=30,
                signal=SignalStrength.HIGH,
                quotes=[],
            )
        ],
        generated_at=_NOW,
    )


def _status_quo() -> Competitor:
    return Competitor(competitor_index=99, name="doing nothing", kind="status_quo", one_liner="—")


def _landscape(*, with_urls: bool) -> Landscape:
    sols = (
        [
            ExistingSolution(
                name="Forest",
                url="https://forest.app",
                tagline="gamified focus",
                traction=900,
                evidence=EvidenceRef(kind="cluster", cluster_rank=1),
            ),
            ExistingSolution(
                name="Session",
                url="https://session.app",
                tagline="pomodoro for mac",
                traction=400,
                evidence=EvidenceRef(kind="cluster", cluster_rank=1),
            ),
        ]
        if with_urls
        else []
    )
    return Landscape(
        landscape_id="ls-1",
        report_id="rpt-1",
        competitor_map=CompetitorMap(
            map_id="cm-1",
            report_id="rpt-1",
            competitors=[
                Competitor(competitor_index=1, name="Forest", kind="direct", one_liner="focus app")
            ],
            status_quo_alternative=_status_quo(),
            generated_at=_NOW,
        ),
        existing_solutions=sols,
        generated_at=_NOW,
    )


def _research(*, landscape: Landscape | None) -> Research:
    return Research(demand=_report(), landscape=landscape)


def _draft() -> _DesignDraft:
    choices = [
        DesignChoice(
            dimension=dim,
            decision=f"{dim} decision",
            stance="risk" if dim in ("typography", "color") else "safe",
            rationale=f"why {dim}",
        )
        for dim in _DIMENSIONS
    ]
    return _DesignDraft(
        brand_name="Cadence",
        memorable_thing="the focus app that whispers",
        aesthetic="editorial monochrome, dark-first",
        choices=choices,
        landscape_signals=[
            LandscapeSignal(
                observation="rivals skew gamified + bright",
                implication="go quiet and editorial",
                competitors=["Forest", "Session"],
            )
        ],
    )


def _deps(chat: FakeChatModel) -> ResearchDeps:
    return ResearchDeps(
        chat=chat, embeddings=FakeEmbedding(), corpus=MemoryStores(), reader=_NullReader()
    )


def _chat() -> FakeChatModel:
    chat = FakeChatModel()
    chat.script(_DesignDraft, _draft())
    chat.text_responses = ["Cadence"]
    return chat


# ── the grounding-tier ladder ─────────────────────────────────────────────────


def test_renderer_tier_real_teardown() -> None:
    system = build_design_system(
        _deps(_chat()), _research(landscape=_landscape(with_urls=True)), renderer=FakeRenderer()
    )
    assert isinstance(system, DesignSystem)
    assert system.grounding_tier == "renderer"
    assert not system.partial
    assert {c.dimension for c in system.choices} == set(_DIMENSIONS)
    assert sum(c.stance == "risk" for c in system.choices) >= 2
    assert system.design_md  # rendered into the system


def test_web_tier_no_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.config.resolve_renderer", lambda: None)
    system = build_design_system(_deps(_chat()), _research(landscape=_landscape(with_urls=False)))
    assert system.grounding_tier == "web"  # competitors present, no live teardown
    assert not system.partial


def test_model_knowledge_tier_no_landscape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.config.resolve_renderer", lambda: None)
    system = build_design_system(_deps(_chat()), _research(landscape=None))
    assert system.grounding_tier == "model_knowledge"
    assert system.partial and system.caveat and "model_knowledge" in system.caveat


def test_full_sweep_with_max_teardown_zero() -> None:
    system = build_design_system(
        _deps(_chat()),
        _research(landscape=_landscape(with_urls=True)),
        renderer=FakeRenderer(),
        max_teardown=0,
    )
    assert system.grounding_tier == "renderer"
    assert system.landscape_signals


def test_partial_on_synthesis_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.config.resolve_renderer", lambda: None)
    chat = FakeChatModel()  # _DesignDraft NOT scripted → complete_structured raises
    chat.text_responses = ["Cadence"]
    system = build_design_system(_deps(chat), _research(landscape=_landscape(with_urls=False)))
    assert system.partial and system.caveat and "synthesis" in system.caveat.lower()
    assert system.choices == []


# ── renders ───────────────────────────────────────────────────────────────────


def test_design_md_carries_stance_and_tier() -> None:
    system = build_design_system(
        _deps(_chat()),
        _research(landscape=_landscape(with_urls=True)),
        renderer=FakeRenderer(),
        brand_name="Cadence",
    )
    md = render_design_md(system)
    assert "# Cadence" in md
    assert "RISK" in md and "SAFE" in md
    assert "renderer" in md


def test_preview_html_renders_self_contained() -> None:
    system = build_design_system(
        _deps(_chat()), _research(landscape=_landscape(with_urls=True)), renderer=FakeRenderer()
    )
    html = render_design_preview_html(system)
    assert html.startswith("<!doctype html>")
    assert "grounding: renderer" in html
    assert "RISK" in html


# ── four-surface parity ───────────────────────────────────────────────────────


def test_design_wired_on_all_surfaces() -> None:
    import importlib.util

    from typer.testing import CliRunner

    from metalworks import Metalworks
    from metalworks.cli import app

    # facade
    assert hasattr(Metalworks, "design") and hasattr(Metalworks, "render_design_preview")
    # CLI
    result = CliRunner().invoke(app, ["research", "design", "--help"])
    assert result.exit_code == 0
    # MCP (body + async wrapper + _TOOL_WRAPPERS), when the mcp extra is present
    if importlib.util.find_spec("mcp") is not None:
        from metalworks.mcp import server, tools

        attr = "_TOOL_WRAPPERS"  # variable, not a literal, to dodge the B009/SLF001 ruff pair
        names = {getattr(w, "__name__", "") for w in getattr(server, attr)}
        assert "design_from_report" in names
        assert hasattr(tools, "design_from_report")


# ── taste presets ─────────────────────────────────────────────────────────────


def test_at_least_three_presets_plus_default() -> None:
    assert DEFAULT_TASTE in TASTE_PRESETS
    assert len(TASTE_PRESETS) >= 3
    assert {"editorial", "brutalist", "warm-minimal", "technical"} <= set(TASTE_PRESETS)


def test_resolve_taste_falls_back_for_unknown() -> None:
    assert resolve_taste("brutalist") == "brutalist"
    assert resolve_taste("nope") == DEFAULT_TASTE
    assert resolve_taste(None) == DEFAULT_TASTE


def test_default_taste_preserves_prior_output() -> None:
    # The default preset's director prompt is the original single-voice TASTE: the
    # old constant (bar + output, no extra direction) byte-for-byte.
    from metalworks.research.design import _BAR, _OUTPUT

    assert TASTE_PRESETS[DEFAULT_TASTE] == f"{_BAR}\n\n{_OUTPUT}"
    # And a default-taste system stamps `taste` without otherwise changing the build.
    system = build_design_system(
        _deps(_chat()), _research(landscape=_landscape(with_urls=True)), renderer=FakeRenderer()
    )
    assert system.taste == DEFAULT_TASTE
    assert system.aesthetic == "editorial monochrome, dark-first"  # unchanged from the draft


def test_two_presets_steer_the_model_differently() -> None:
    # Same report, two presets → different director prompt reaches the model AND a
    # different `taste`/chrome on the result (visibly different DesignSystem).
    chat_a, chat_b = _chat(), _chat()
    sys_a = build_design_system(
        _deps(chat_a),
        _research(landscape=_landscape(with_urls=True)),
        taste="editorial",
        renderer=FakeRenderer(),
    )
    sys_b = build_design_system(
        _deps(chat_b),
        _research(landscape=_landscape(with_urls=True)),
        taste="brutalist",
        renderer=FakeRenderer(),
    )
    assert sys_a.taste == "editorial" and sys_b.taste == "brutalist"
    director_a = next(c["system"] for c in chat_a.calls if c["kind"] == "structured")
    director_b = next(c["system"] for c in chat_b.calls if c["kind"] == "structured")
    assert director_a != director_b
    # And the preview chrome diverges (palette + body face), not one fixed theme.
    html_a = render_design_preview_html(sys_a)
    html_b = render_design_preview_html(sys_b)
    assert html_a != html_b
    assert "taste: editorial" in html_a and "taste: brutalist" in html_b


def test_unknown_taste_falls_back_to_default_in_build() -> None:
    system = build_design_system(
        _deps(_chat()),
        _research(landscape=_landscape(with_urls=True)),
        taste="does-not-exist",
        renderer=FakeRenderer(),
    )
    assert system.taste == DEFAULT_TASTE


def test_no_preset_chrome_leads_with_a_blacklisted_body_face() -> None:
    for name in TASTE_PRESETS:
        first_family = resolve_chrome(name).body_font.split(",")[0].strip().strip("'\"").lower()
        assert first_family not in _CONVERGENCE_FACES, f"{name} leads with {first_family!r}"


def test_preview_and_logo_picker_avoid_blacklisted_fonts() -> None:
    from metalworks.contract.logo import LogoOption, LogoSet
    from metalworks.research.logo import render_logo_picker_html

    system = build_design_system(
        _deps(_chat()), _research(landscape=_landscape(with_urls=True)), renderer=FakeRenderer()
    )
    preview = render_design_preview_html(system)
    # The preview's body face is Geist (the editorial chrome), never Inter-led.
    assert "font-family:'Geist'" in preview
    assert "font-family:'Inter'" not in preview
    logo_set = LogoSet(
        report_id="rpt-1",
        brand_name="Cadence",
        options=[LogoOption(angle="symbol", concept="x", svg="<svg></svg>")],
    )
    picker = render_logo_picker_html(logo_set, taste=system.taste)
    assert "font-family:'Inter'" not in picker  # was the blacklisted default
    assert "font-family:'Geist'" in picker


def test_taste_param_present_on_all_surfaces() -> None:
    import importlib.util
    import inspect

    from typer.testing import CliRunner

    from metalworks import Metalworks
    from metalworks.cli import app

    # facade
    assert "taste" in inspect.signature(Metalworks.design).parameters
    # CLI — force a wide terminal so Rich doesn't truncate the option table
    # (CI defaults to 80 cols, which wraps/clips `--taste` out of --help output).
    result = CliRunner().invoke(app, ["research", "design", "--help"], env={"COLUMNS": "400"})
    assert result.exit_code == 0 and "--taste" in result.output
    # MCP (tool body + async wrapper)
    if importlib.util.find_spec("mcp") is not None:
        from metalworks.mcp import server, tools

        assert "taste" in inspect.signature(tools.design_from_report).parameters
        assert "taste" in inspect.signature(server.design_from_report).parameters
    # Skill (the /design SKILL.md documents the param)
    from pathlib import Path

    skill = Path(__file__).resolve().parents[1] / "plugin" / "skills" / "design" / "SKILL.md"
    assert "taste" in skill.read_text(encoding="utf-8")
