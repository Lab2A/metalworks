"""Run persistence: `.metalworks/runs/<id>/research.{md,json}` + manifest (offline)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from metalworks.contract import (
    DemandReport,
    Fork,
    InsightCluster,
    QuoteCitation,
    Research,
    SignalStrength,
)
from metalworks.project import Project
from metalworks.runs import render_run_markdown, write_run


def _research() -> Research:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    quote = QuoteCitation(
        text="I'd pay for a clean focus supplement",
        permalink="https://reddit.com/r/Supplements/comments/x/c/",
        subreddit="Supplements",
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
