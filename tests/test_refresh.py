"""Refresh = re-synthesize a prior report against the current corpus → a new
pinned version in the same lineage + a diff. Offline, reusing the FakeSource
scaffolding from test_itemsource for a real end-to-end pipeline refresh."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from metalworks.contract import DemandReport, Fork
from metalworks.research.refresh import refresh_report
from metalworks.stores import MemoryStores

# Reuse the scripted-pipeline scaffolding (FakeSource, scripted chat, deps).
from test_itemsource import FakeSource, _brief, _deps  # type: ignore[import-not-found]

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def test_refresh_pins_next_version_with_empty_diff_on_unchanged_corpus() -> None:
    pytest.importorskip("rank_bm25")
    pytest.importorskip("numpy")
    from metalworks.research.pipeline import run_research

    corpus = MemoryStores()
    deps = _deps([FakeSource()], corpus)
    v1 = run_research(deps, brief=_brief())
    assert v1.version == 1
    assert v1.effective_lineage_id == v1.report_id  # lineage rooted at the run
    assert v1.parent_report_id is None

    # Refresh against the same (unchanged) corpus + deterministic scripted chat.
    v2, diff = refresh_report(deps, v1)

    # New version, same lineage, parent linked, distinct artifact id.
    assert v2.version == 2
    assert v2.lineage_id == v1.report_id
    assert v2.effective_lineage_id == v1.effective_lineage_id
    assert v2.parent_report_id == v1.report_id
    assert v2.report_id != v1.report_id

    # The diff points the right way and — corpus unchanged, synthesis scripted —
    # reports no material change (the determinism guarantee end to end).
    assert (diff.from_version, diff.to_version) == (1, 2)
    assert (diff.from_report_id, diff.to_report_id) == (v1.report_id, v2.report_id)
    assert diff.lineage_id == v1.report_id
    assert diff.is_empty is True


def test_refresh_without_brief_raises() -> None:
    report = DemandReport(
        report_id="r1",
        query="x",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="x",
        optimized_axis="y",
        date_range_start=_NOW,
        date_range_end=_NOW,
        total_threads=0,
        total_distinct_authors=0,
        ranked_clusters=[],
        generated_at=_NOW,
        brief=None,
    )

    class _Deps:
        from metalworks.embeddings import FakeEmbedding

        embeddings = FakeEmbedding()

    with pytest.raises(ValueError, match="no brief"):
        refresh_report(_Deps(), report)  # type: ignore[arg-type]
