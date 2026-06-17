"""The interactive / decluttered CLI: id-defaulting, the saving research wrapper,
the guided session, and the validate --auto seam — all offline via CliRunner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

import metalworks.cli as cli
from metalworks import config
from metalworks.cli import _resolve_report_id, _saving_research, app
from metalworks.contract import DemandReport, Fork, RunSummary
from metalworks.contract.assess import Assessment, Decision, GapAnalysis
from metalworks.contract.ideate import IdeaSketch
from metalworks.contract.research import SignalStrength
from metalworks.contract.validate import ValidationResult
from metalworks.stores import MemoryStores

runner = CliRunner()

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_T1 = datetime(2026, 2, 1, tzinfo=UTC)


def _report(report_id: str, *, when: datetime = _T0, authors: int = 50) -> DemandReport:
    return DemandReport(
        report_id=report_id,
        query="q",
        fork=Fork.BOTH,
        pinned_axis="",
        optimized_axis="",
        date_range_start=when,
        date_range_end=when,
        total_threads=1,
        total_distinct_authors=authors,
        ranked_clusters=[],
        generated_at=when,
    )


def _seed(store: MemoryStores, report_id: str, *, when: datetime = _T0) -> DemandReport:
    rep = _report(report_id, when=when)
    store.save_report(rep)
    store.save_run(RunSummary.from_report(rep))
    return rep


def _assessment(report_id: str, decision: Decision = Decision.GO) -> Assessment:
    gap = GapAnalysis(
        demand_strength=SignalStrength.HIGH,
        demand_summary="strong",
        landscape_saturation=SignalStrength.LOW,
        reasoning="because",
    )
    return Assessment(
        assessment_id="as:1",
        report_id=report_id,
        decision=decision,
        rationale="r",
        gap=gap,
        generated_at=_T0,
    )


# ── _resolve_report_id ───────────────────────────────────────────────────────


def test_resolve_defaults_to_latest_run() -> None:
    store = MemoryStores()
    _seed(store, "rpt-old", when=_T0)
    _seed(store, "rpt-new", when=_T1)
    assert _resolve_report_id(store, None) == "rpt-new"


def test_resolve_exact_hit() -> None:
    store = MemoryStores()
    _seed(store, "rpt-old", when=_T0)
    _seed(store, "rpt-new", when=_T1)
    assert _resolve_report_id(store, "rpt-old") == "rpt-old"


def test_resolve_unique_prefix() -> None:
    store = MemoryStores()
    _seed(store, "rpt-old", when=_T0)
    _seed(store, "rpt-new", when=_T1)
    assert _resolve_report_id(store, "rpt-n") == "rpt-new"


def test_resolve_ambiguous_prefix_exits() -> None:
    store = MemoryStores()
    _seed(store, "rpt-old", when=_T0)
    _seed(store, "rpt-new", when=_T1)
    with pytest.raises(typer.Exit):
        _resolve_report_id(store, "rpt-")  # matches both


def test_resolve_not_found_exits() -> None:
    store = MemoryStores()
    _seed(store, "rpt-old", when=_T0)
    with pytest.raises(typer.Exit):
        _resolve_report_id(store, "zzz")


def test_resolve_no_runs_exits() -> None:
    with pytest.raises(typer.Exit):
        _resolve_report_id(MemoryStores(), None)


# ── id-defaulting through a real command (assess, no id → latest) ────────────


def test_assess_with_no_id_uses_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryStores()
    _seed(store, "rpt-old", when=_T0)
    _seed(store, "rpt-new", when=_T1)
    monkeypatch.setattr(config, "default_store", lambda *a, **k: store)
    monkeypatch.setattr(config, "resolve_search", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_resolve_chat_or_exit", lambda: object())
    monkeypatch.setattr(cli, "_resolve_embeddings_or_exit", lambda: object())

    seen: dict[str, str] = {}
    import metalworks.research as research_pkg

    def _fake_landscape(_deps: Any, report: DemandReport) -> Any:
        seen["landscape"] = report.report_id
        return object()

    def _fake_assess(_deps: Any, report: DemandReport, _ls: Any) -> Assessment:
        seen["assess"] = report.report_id
        return _assessment(report.report_id)

    monkeypatch.setattr(research_pkg, "run_landscape", _fake_landscape)
    monkeypatch.setattr(research_pkg, "run_assessment", _fake_assess)

    result = runner.invoke(app, ["research", "assess"])  # no id → latest
    assert result.exit_code == 0, result.output
    assert seen["assess"] == "rpt-new"
    assert "GO" in result.output


# ── _saving_research wrapper ─────────────────────────────────────────────────


def test_saving_research_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryStores()
    rep = _report("rpt-x")
    import importlib

    val = importlib.import_module("metalworks.research.validate")
    monkeypatch.setattr(val, "default_research", lambda _deps, _sketch: rep)
    sketch = IdeaSketch(idea="an idea", hypothesis="h", provenance="idea-first")

    out = _saving_research(store)(None, sketch)  # type: ignore[arg-type]
    assert out.report_id == "rpt-x"
    assert store.get_report("rpt-x") is not None
    assert store.list_runs(limit=5)[0].report_id == "rpt-x"


# ── validate --auto vs interactive (the decide seam) ─────────────────────────


def _patch_validate_spy(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    monkeypatch.setattr(config, "default_store", lambda *a, **k: MemoryStores())
    monkeypatch.setattr(config, "resolve_search", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_resolve_chat_or_exit", lambda: object())
    monkeypatch.setattr(cli, "_resolve_embeddings_or_exit", lambda: object())
    import metalworks.research as research_pkg

    def _spy(_deps: Any, _idea: str, *, decide: Any = None, **_k: Any) -> ValidationResult:
        captured["decide"] = decide
        return ValidationResult(
            outcome="no_go", final_assessment=None, decision_log=[], iterations=0
        )

    monkeypatch.setattr(research_pkg, "validate", _spy)


def test_validate_auto_passes_no_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _patch_validate_spy(monkeypatch, captured)
    result = runner.invoke(app, ["research", "validate", "an idea", "--auto"])
    assert result.exit_code == 0, result.output
    assert captured["decide"] is None


def test_validate_default_is_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _patch_validate_spy(monkeypatch, captured)
    result = runner.invoke(app, ["research", "validate", "an idea"])
    assert result.exit_code == 0, result.output
    assert callable(captured["decide"])


# ── the guided session (bare `metalworks`) ──────────────────────────────────


def test_guided_session_no_key_exits_with_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_present_providers", lambda: [])
    monkeypatch.setattr(config, "vertex_enabled", lambda: False)
    result = runner.invoke(app, [], input="")
    assert result.exit_code == 0, result.output
    assert "No provider key" in result.output


def test_guided_session_go_offers_build_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.project import Project

    store = MemoryStores()
    _seed(store, "rpt-x")
    monkeypatch.setattr(cli, "_present_providers", lambda: [("anthropic", "ANTHROPIC_API_KEY")])
    monkeypatch.setattr(Project, "find", classmethod(lambda _cls, start=None: object()))
    monkeypatch.setattr(config, "default_store", lambda *a, **k: store)
    monkeypatch.setattr(config, "resolve_search", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_resolve_chat_or_exit", lambda: object())
    monkeypatch.setattr(cli, "_resolve_embeddings_or_exit", lambda: object())

    import metalworks.research as research_pkg

    def _fake_validate(_deps: Any, _idea: str, **_k: Any) -> ValidationResult:
        return ValidationResult(
            outcome="go", final_assessment=_assessment("rpt-x"), decision_log=[], iterations=1
        )

    monkeypatch.setattr(research_pkg, "validate", _fake_validate)

    # idea, then "4" = Done in the next-steps menu.
    result = runner.invoke(app, [], input="a focus supplement\n4\n")
    assert result.exit_code == 0, result.output
    assert "GO" in result.output
    assert "What next?" in result.output


def test_bare_help_still_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "research" in result.output
