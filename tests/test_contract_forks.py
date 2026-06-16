"""Decision-bearing fork contracts: SegmentChoice / CandidateWedge / DemandReport selectors.

These lock in the PR1 guarantees the review flagged:
- old `AudienceSegment`-shape payloads (carrying `name`) still validate into the enriched
  `SegmentChoice` — the additive-parity guard, as a round-trip (not the schema snapshot);
- `default_*` / `active_*` are `None`-safe on the empty (zero-cluster cold-start) report;
- a user's `chosen_*` pick wins over the deterministic default;
- content-addressed ids are stable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import (
    AudienceSegment,
    CandidateWedge,
    DemandReport,
    Fork,
    IdeaSketch,
    Research,
    SegmentChoice,
)
from metalworks.contract.research import AudienceProfile


def _report(
    *,
    segments: list[SegmentChoice] | None = None,
    candidate_wedges: list[CandidateWedge] | None = None,
    chosen_segment_id: str | None = None,
    chosen_wedge_id: str | None = None,
) -> DemandReport:
    return DemandReport(
        report_id="r1",
        query="q",
        fork=Fork.BOTH,
        pinned_axis="",
        optimized_axis="",
        date_range_start=datetime(2026, 1, 1, tzinfo=UTC),
        date_range_end=datetime(2026, 2, 1, tzinfo=UTC),
        total_threads=0,
        total_distinct_authors=0,
        ranked_clusters=[],
        generated_at=datetime(2026, 2, 1, tzinfo=UTC),
        segments=segments or [],
        candidate_wedges=candidate_wedges or [],
        chosen_segment_id=chosen_segment_id,
        chosen_wedge_id=chosen_wedge_id,
    )


def test_audience_segment_is_segment_choice() -> None:
    assert AudienceSegment is SegmentChoice


def test_old_audience_segment_payload_validates() -> None:
    """A pre-enrichment payload (name + profile + scores, no fork fields) round-trips."""
    payload = {
        "name": "indie devs",
        "profile": {},
        "preferences": ["cheap"],
        "demand_score": 4.0,
        "distinct_author_count": 12,
    }
    seg = SegmentChoice.model_validate(payload)
    assert seg.name == "indie devs"  # the canonical field every downstream reader uses
    assert seg.demand_score == 4.0
    assert seg.evidence == [] and seg.overlap == {}  # new fields default cleanly
    assert seg.id.startswith("s:")


def test_empty_report_selectors_are_none_safe() -> None:
    """Zero-cluster cold-start is the common case, not an error — never raise."""
    r = _report()
    assert r.default_segment is None
    assert r.active_segment is None
    assert r.default_wedge is None
    assert r.active_wedge is None


def test_default_segment_is_top_by_demand_score() -> None:
    lo = SegmentChoice(name="a", profile=AudienceProfile(), demand_score=1.0)
    hi = SegmentChoice(name="b", profile=AudienceProfile(), demand_score=9.0)
    r = _report(segments=[lo, hi])
    assert r.default_segment is hi
    assert r.active_segment is hi  # no pick → default


def test_chosen_segment_wins_over_default() -> None:
    lo = SegmentChoice(name="a", profile=AudienceProfile(), demand_score=1.0)
    hi = SegmentChoice(name="b", profile=AudienceProfile(), demand_score=9.0)
    r = _report(segments=[lo, hi], chosen_segment_id=lo.id)
    assert r.active_segment is lo  # the human's pick, not the top score


def test_default_wedge_is_top_by_breadth() -> None:
    narrow = CandidateWedge(label="x", pain="p1", scope="minimal", breadth_count=3)
    broad = CandidateWedge(label="y", pain="p2", scope="broad", breadth_count=40)
    r = _report(candidate_wedges=[narrow, broad])
    assert r.default_wedge is broad
    assert r.active_wedge is broad
    r2 = _report(candidate_wedges=[narrow, broad], chosen_wedge_id=narrow.id)
    assert r2.active_wedge is narrow


def test_wedge_id_is_stable_and_content_addressed() -> None:
    a = CandidateWedge(label="x", pain="caffeine crash", scope="minimal")
    b = CandidateWedge(label="different label", pain="caffeine crash", scope="minimal")
    assert a.id == b.id  # id is content-addressed on (pain, scope), not the label
    assert a.id.startswith("w:")


def test_research_bundle_carries_loop_pillars_additively() -> None:
    """The Research bundle gained landscape/assessment/ideation — additive, default None."""
    r = Research(demand=_report())
    assert r.landscape is None and r.assessment is None and r.ideation is None
    # and it accepts a loop pillar when present (frozen + composable)
    with_idea = Research(
        demand=_report(),
        ideation=IdeaSketch(idea="x", hypothesis="x", provenance="idea-first"),
    )
    assert with_idea.ideation is not None
    assert with_idea.evidence == with_idea.demand.evidence  # evidence still delegates
