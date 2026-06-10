"""Contract guarantees: schema snapshots are diff-gated and generation is
deterministic (run twice → byte-identical)."""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from metalworks.contract import (
    ComplianceVerdict,
    DemandReport,
    Fork,
    ResearchBrief,
    SlotPlan,
    TargetSubreddit,
)

REPO = Path(__file__).resolve().parents[1]


def test_schema_snapshots_match_contract() -> None:
    """CI drift gate: contract/schema/*.json must match the live models."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_ts_types.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"contract drift:\n{result.stdout}\n{result.stderr}"


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two renders must be byte-identical."""
    sys.path.insert(0, str(REPO / "scripts"))
    import gen_ts_types

    first = gen_ts_types._render()  # noqa: SLF001
    second = gen_ts_types._render()  # noqa: SLF001
    assert first == second


def test_demand_report_minimal_validates() -> None:
    report = DemandReport(
        report_id="r1",
        query="focus supplements for gym-goers",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=datetime(2025, 6, 1, tzinfo=UTC),
        date_range_end=datetime(2026, 6, 1, tzinfo=UTC),
        total_threads=0,
        total_distinct_authors=0,
        ranked_clusters=[],
        generated_at=datetime(2026, 6, 9, tzinfo=UTC),
    )
    assert report.client_id == "local"  # tenant defaults for library use
    assert report.partial is False


def test_research_brief_tenant_defaults() -> None:
    brief = ResearchBrief(
        brief_id="b1",
        question="q",
        decision_context="d",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core sub")],
        web_research_directions=[],
        relevance_rubric="r",
    )
    assert brief.workspace_id == "local"
    assert brief.version == 1


def test_slot_plan_resolve_rules() -> None:
    plan = SlotPlan.resolve(product="focus gummies")
    assert plan.given == ["product"]
    assert plan.find == ["audience", "price"]

    import pytest

    with pytest.raises(ValueError, match="At least one slot"):
        SlotPlan.resolve()


def test_compliance_verdict_wire_alias() -> None:
    """The gate's wire format uses `pass`; Python uses `pass_`."""
    v = ComplianceVerdict.model_validate({"pass": True, "violations": [], "confidence": 0.95})
    assert v.pass_ is True
    assert v.model_dump(by_alias=True)["pass"] is True
