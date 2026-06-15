"""Run persistence: `.metalworks/runs/<id>/research.{md,json}` + manifest (offline)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from metalworks.contract import (
    DemandReport,
    Fork,
    InsightCluster,
    Research,
    ResolvedCitation,
    SignalStrength,
    WebFinding,
)
from metalworks.project import Project
from metalworks.runs import render_run_markdown, write_run


def _research() -> Research:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    quote = ResolvedCitation(
        text="I'd pay for a clean focus supplement",
        source_url="https://reddit.com/r/Supplements/comments/x/c/",
        source_name="r/Supplements",
        author_hash="a1",
    )
    cluster = InsightCluster(
        rank=1,
        claim="People want a clean-label focus supplement",
        demand_score=0.9,
        distinct_author_count=3,
        mention_count=5,
        signal=SignalStrength.HIGH,
        quotes=[quote],
    )
    report = DemandReport(
        report_id="rep-123",
        query="demand for a focus supplement?",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=12,
        total_distinct_authors=9,
        ranked_clusters=[cluster],
        generated_at=now,
        verdict="Go — clear unmet demand.",
    )
    return Research(demand=report)


def test_write_run_persists_files_and_updates_manifest(tmp_path: Path) -> None:
    project = Project.init(tmp_path, idea="focus supplement")
    research = _research()

    ref = write_run(project, research, question="demand for a focus supplement?")

    run_dir = project.runs_dir / "rep-123"
    assert (run_dir / "research.json").is_file()
    assert (run_dir / "research.md").is_file()

    # research.json round-trips back to the same bundle (with stable evidence ids).
    restored = Research.model_validate_json((run_dir / "research.json").read_text())
    assert restored.demand.report_id == "rep-123"
    assert restored.evidence == research.evidence

    manifest = project.read_manifest()
    assert len(manifest.runs) == 1
    assert manifest.runs[0] == ref
    assert manifest.runs[0].report_id == "rep-123"


def test_markdown_links_claims_to_real_permalinks() -> None:
    md = render_run_markdown(_research())
    assert "# Research — demand for a focus supplement?" in md
    assert "**Verdict:** Go" in md
    assert "People want a clean-label focus supplement" in md
    # the representative quote links back to its source thread
    assert "https://reddit.com/r/Supplements/comments/x/c/" in md
    assert "rep-123" in md


def test_facade_persists_run_inside_a_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The facade's `if not offline: Project.find()->write_run` wiring: a real
    # (non-demo) research run inside a project writes committed files + a RunRef.
    monkeypatch.chdir(tmp_path)
    import metalworks.research as research_pkg
    from metalworks import Metalworks
    from metalworks.embeddings import FakeEmbedding
    from metalworks.llm import FakeChatModel

    Project.init(tmp_path, idea="focus supplement")
    research = _research()  # report_id="rep-123"
    monkeypatch.setattr(research_pkg, "run_research", lambda *a, **k: research.demand)

    class _Reader:
        def close(self) -> None:
            return None

    mw = Metalworks(chat=FakeChatModel(), embeddings=FakeEmbedding(), reader=_Reader())
    result = mw.research("demand?", subreddits=["Supplements"])  # explicit subs → no planner LLM

    assert result.demand.report_id == "rep-123"
    run_dir = tmp_path / ".metalworks" / "runs" / "rep-123"
    assert (run_dir / "research.json").is_file()
    assert (run_dir / "research.md").is_file()
    found = Project.find(tmp_path)
    assert found is not None
    assert found.read_manifest().runs[0].report_id == "rep-123"


def test_markdown_renders_web_findings_and_partial_caveat() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    report = DemandReport(
        report_id="rep-9",
        query="demand?",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=4,
        total_distinct_authors=2,
        ranked_clusters=[],  # no clusters → the clusters block is skipped
        generated_at=now,
        partial=True,
        caveat="thin corpus",
        web_findings=[
            WebFinding(
                finding_index=1,
                claim="market is growing 12% YoY",
                specifics="12% YoY",
                source_url="https://example.com/report",
                source_title="Market Report 2026",
                confidence=SignalStrength.MEDIUM,
            )
        ],
    )
    md = render_run_markdown(Research(demand=report))
    assert "⚠️ Partial result: thin corpus" in md
    assert "## Web findings" in md
    assert "market is growing 12% YoY" in md
    assert "[Market Report 2026](https://example.com/report)" in md
    assert "## Top demand clusters" not in md  # empty clusters → block omitted
