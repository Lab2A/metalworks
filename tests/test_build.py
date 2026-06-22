"""Pillar D — build: feature grounding, persona/pricing copy-through, scaffold writer.

Offline. FakeChatModel is scripted with one `_BuildPhrasing`; the DemandReport
fixture carries clusters/quotes/segments/price so feature grounding and evidence
resolution run for real. The scaffold writer is pure templating — asserted on
disk under tmp_path. The generated cite-or-die lint is exercised via subprocess.
No network, no keys, no embeddings.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from metalworks.build import scaffold
from metalworks.build.spec import (
    _BuildPhrasing,
    _FeatureDraft,
    _ScreenDraft,
    _ScreenPhrasing,
    build_spec_from_report,
)
from metalworks.contract import (
    AudienceProfile,
    AudienceSegment,
    DemandReport,
    Fork,
    InsightCluster,
    PriceEvidence,
    PriceFinding,
    ResolvedCitation,
    SignalStrength,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.stores import MemoryStores

# ── fixtures ─────────────────────────────────────────────────────────────────


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions") -> Any:
        raise NotImplementedError

    def pull_subreddit(self, **_kwargs: Any) -> Any:
        raise NotImplementedError

    def fetch_submissions_by_ids(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _quote(text: str, permalink: str, author_hash: str = "a1") -> ResolvedCitation:
    return ResolvedCitation(
        text=text, source_url=permalink, source_name="r/SkincareAddiction", author_hash=author_hash
    )


def _cluster(rank: int, *, quotes: list[ResolvedCitation]) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"consumers want outcome {rank}",
        demand_score=10.0,
        distinct_author_count=len({q.author_hash for q in quotes}),
        mention_count=len(quotes),
        signal=SignalStrength.HIGH,
        quotes=quotes,
    )


def _report(
    *,
    clusters: list[InsightCluster] | None = None,
    segments: list[AudienceSegment] | None = None,
    price: PriceFinding | None = None,
) -> DemandReport:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    if clusters is None:
        clusters = [
            _cluster(
                1,
                quotes=[
                    _quote("nothing fades PIE without burning my skin", "https://r/x/1", "a1"),
                    _quote("every cream left me red and raw", "https://r/x/2", "a2"),
                ],
            ),
            _cluster(2, quotes=[_quote("I want a routine I can track", "https://r/x/3", "a3")]),
        ]
    return DemandReport(
        report_id="rpt-1",
        query="best fade for post-acne marks",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=63,
        total_distinct_authors=130,
        ranked_clusters=clusters,
        generated_at=now,
        segments=segments or [],
        price_finding=price,
    )


def _deps(chat: FakeChatModel) -> ResearchDeps:
    return ResearchDeps(
        chat=chat, embeddings=FakeEmbedding(), corpus=MemoryStores(), reader=_NullReader()
    )


def _scripted(features: list[_FeatureDraft]) -> FakeChatModel:
    return FakeChatModel().script(_BuildPhrasing, _BuildPhrasing(features=features))


def _draft(fid: str, rank: int) -> _FeatureDraft:
    return _FeatureDraft(
        feature_id=fid,
        title=f"Feature {fid}",
        rationale="serves a real pain",
        source_cluster_rank=rank,
    )


def _scripted_with_screens(
    *,
    features: list[_FeatureDraft],
    screens: list[_ScreenDraft],
    chosen_surface: str = "cli",
    surface_rationale: str = "the audience lives in the terminal",
) -> FakeChatModel:
    """Script BOTH the feature/surface call and the post-feature screens call."""
    chat = FakeChatModel()
    chat.script(
        _BuildPhrasing,
        _BuildPhrasing(
            features=features,
            chosen_surface=chosen_surface,  # type: ignore[arg-type]
            surface_rationale=surface_rationale,
        ),
    )
    chat.script(_ScreenPhrasing, _ScreenPhrasing(screens=screens))
    return chat


def _screen(name: str, feature_ids: list[str], *, scaffolding: bool = False) -> _ScreenDraft:
    return _ScreenDraft(
        name=name,
        purpose=f"the {name} screen",
        primary_action="do the thing",
        feature_ids=feature_ids,
        scaffolding=scaffolding,
    )


# ── feature grounding (the honesty gate) ─────────────────────────────────────


def test_feature_mapped_to_real_cluster_carries_that_clusters_quotes() -> None:
    report = _report()
    chat = _scripted([_draft("fade-tracker", 1)])
    spec = build_spec_from_report(_deps(chat), report)
    assert [f.feature_id for f in spec.features] == ["fade-tracker"]
    refs = spec.features[0].evidence
    assert refs, "a grounded feature must carry evidence"
    evidence_ids = {e.id for e in report.evidence}
    assert all(r.evidence_id in evidence_ids for r in refs), "every ref must resolve in the report"


def test_feature_with_invalid_cluster_rank_is_dropped() -> None:
    report = _report()
    # rank 99 has no cluster behind it → no-cite-no-feature.
    chat = _scripted([_draft("hallucinated", 99), _draft("real", 1)])
    spec = build_spec_from_report(_deps(chat), report)
    assert [f.feature_id for f in spec.features] == ["real"]


def test_feature_pointing_at_quoteless_cluster_is_dropped() -> None:
    quoteless = _cluster(1, quotes=[])
    report = _report(clusters=[quoteless])
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), report)
    assert spec.features == []
    assert spec.partial is True
    assert spec.caveat and "stub" in spec.caveat


def test_duplicate_feature_ids_are_deduped() -> None:
    report = _report()
    chat = _scripted([_draft("dup", 1), _draft("dup", 2)])
    spec = build_spec_from_report(_deps(chat), report)
    assert [f.feature_id for f in spec.features] == ["dup"]


def test_features_are_ordered_by_grounded_demand_not_draft_order() -> None:
    # Three demand-ranked clusters; the LLM drafts them OUT of order (3, 1, 2).
    report = _report(
        clusters=[
            _cluster(1, quotes=[_quote("the rank-1 pain", "https://r/x/1", "a1")]),
            _cluster(2, quotes=[_quote("the rank-2 pain", "https://r/x/2", "a2")]),
            _cluster(3, quotes=[_quote("the rank-3 pain", "https://r/x/3", "a3")]),
        ]
    )
    chat = _scripted([_draft("third", 3), _draft("first", 1), _draft("second", 2)])
    spec = build_spec_from_report(_deps(chat), report)
    # Build order follows validated demand (rank 1 first), not the draft order.
    assert [f.feature_id for f in spec.features] == ["first", "second", "third"]
    assert [f.source_cluster_rank for f in spec.features] == [1, 2, 3]
    # features[0] is the spine — the highest-demand feature, to build first.
    assert spec.features[0].feature_id == "first"


def test_demand_order_caps_keep_the_strongest_features() -> None:
    # More grounded drafts than the cap; the survivors must be the highest-demand
    # ones, in order — the cap follows demand, not LLM draft position.
    report = _report(
        clusters=[
            _cluster(r, quotes=[_quote(f"pain {r}", f"https://r/x/{r}", f"a{r}")])
            for r in range(1, 11)
        ]
    )
    drafts = [_draft(f"f{r}", r) for r in (9, 2, 7, 1, 4, 10, 3, 8, 5, 6)]
    spec = build_spec_from_report(_deps(_scripted(drafts)), report)
    ranks = [f.source_cluster_rank for f in spec.features]
    assert ranks == [1, 2, 3, 4, 5, 6, 7, 8], "kept the top-8 by demand, in order"


def test_infra_error_propagates_not_silently_partial() -> None:
    # A 404/auth/network failure must surface as an error, NOT a spec mislabelled
    # "thin demand" — that would launder a broken setup into a fake finding.
    class _BoomChat(FakeChatModel):
        def complete_structured(self, **_kw: Any) -> Any:
            raise RuntimeError("vertex down")

    with pytest.raises(RuntimeError, match="vertex down"):
        build_spec_from_report(_deps(_BoomChat()), _report())


# ── surface pick + feature-grounded screens (the folded-in pillar) ───────────


def test_auto_surface_returns_surface_rationale_and_grounded_screens() -> None:
    report = _report()  # rank-1 (2 quotes) + rank-2 (1 quote)
    chat = _scripted_with_screens(
        features=[_draft("fade", 1), _draft("track", 2)],
        screens=[
            _screen("Fade", ["fade"]),
            _screen("Track", ["track"]),
            _screen("Settings", [], scaffolding=True),
        ],
        chosen_surface="web",
        surface_rationale="consumers want a browsable routine",
    )
    spec = build_spec_from_report(_deps(chat), report, surface="auto")
    # Surface + a one-line rationale come back from the SAME feature call.
    assert spec.surface == "web"
    assert spec.surface_rationale == "consumers want a browsable routine"
    # ≥1 screen per grounded feature (each feature is referenced by some screen).
    served = {fid for s in spec.screens for fid in s.feature_ids}
    assert {f.feature_id for f in spec.features} <= served


def test_screens_reference_real_feature_ids_only() -> None:
    # The LLM maps a screen to a feature id that does NOT exist — it must be dropped,
    # proving screens are grounded in the real feature list, not blind.
    report = _report()
    chat = _scripted_with_screens(
        features=[_draft("fade", 1)],
        screens=[_screen("Ghost", ["fade", "does-not-exist"])],
    )
    spec = build_spec_from_report(_deps(chat), report, surface="auto")
    real_ids = {f.feature_id for f in spec.features}
    for s in spec.screens:
        for fid in s.feature_ids:
            assert fid in real_ids, "a screen must only reference real feature ids"
    ghost = next(s for s in spec.screens if s.name == "Ghost")
    assert ghost.feature_ids == ["fade"]  # the invented id was stripped


def test_screen_validated_when_its_feature_carries_evidence() -> None:
    report = _report()
    chat = _scripted_with_screens(
        features=[_draft("fade", 1)],
        screens=[_screen("Fade", ["fade"]), _screen("Settings", [], scaffolding=True)],
    )
    spec = build_spec_from_report(_deps(chat), report, surface="auto")
    evidence_ids = {e.id for e in report.evidence}
    fade = next(s for s in spec.screens if s.name == "Fade")
    settings = next(s for s in spec.screens if s.name == "Settings")
    assert fade.validated is True
    assert fade.evidence_refs
    assert all(r.evidence_id in evidence_ids for r in fade.evidence_refs)
    # A shell screen carries no feature → scaffolding, not a hypothesis.
    assert settings.scaffolding is True
    assert settings.validated is False
    assert settings.feature_ids == []


def test_pinned_surface_is_honored_and_skips_the_pick() -> None:
    # Pinning a surface must use it verbatim and NOT set a rationale (no auto-pick).
    report = _report()
    chat = _scripted_with_screens(
        features=[_draft("fade", 1)],
        screens=[_screen("Fade", ["fade"])],
        chosen_surface="web",  # the LLM "would" pick web — but we pinned cli.
        surface_rationale="ignored because pinned",
    )
    spec = build_spec_from_report(_deps(chat), report, surface="cli")
    assert spec.surface == "cli"
    assert spec.surface_rationale is None


def test_screens_render_into_spec_md(tmp_path: Path) -> None:
    report = _report()
    chat = _scripted_with_screens(
        features=[_draft("fade", 1)],
        screens=[_screen("Fade", ["fade"]), _screen("Settings", [], scaffolding=True)],
    )
    spec = build_spec_from_report(_deps(chat), report, surface="auto")
    scaffold(spec, report, tmp_path)
    spec_md = (tmp_path / "docs/SPEC.md").read_text(encoding="utf-8")
    assert "## Screens" in spec_md
    assert "Fade" in spec_md and "validated" in spec_md
    assert "scaffolding" in spec_md  # the shell screen is flagged, not a hypothesis


def test_screens_degrade_to_empty_on_screen_call_failure() -> None:
    # Only the feature call is scripted → the screens call raises → no screens,
    # but the rest of the spec still ships (a screens failure is not "thin demand").
    report = _report()
    spec = build_spec_from_report(_deps(_scripted([_draft("fade", 1)])), report, surface="auto")
    assert spec.features  # features survived
    assert spec.screens == []


# ── personas + pricing (copy-through) ────────────────────────────────────────


def test_personas_derived_from_segments_with_resolvable_evidence() -> None:
    seg = AudienceSegment(
        name="Sensitive-skin spender",
        profile=AudienceProfile(),
        preferences=["gentle actives", "no fragrance"],
        demand_score=8.0,
        distinct_author_count=12,
    )
    report = _report(segments=[seg])
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), report)
    assert [p.name for p in spec.personas] == ["Sensitive-skin spender"]
    evidence_ids = {e.id for e in report.evidence}
    assert all(r.evidence_id in evidence_ids for p in spec.personas for r in p.evidence)


def test_no_segments_derives_one_core_persona() -> None:
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), _report())
    assert [p.name for p in spec.personas] == ["Core user"]


def test_pricing_tiers_copy_through_from_price_finding() -> None:
    price = PriceFinding(
        low=9.0,
        high=29.0,
        currency="USD",
        confidence=SignalStrength.MEDIUM,
        evidence=[PriceEvidence(text="I'd pay $9/mo for this", kind="willingness", amount=9.0)],
    )
    report = _report(price=price)
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), report)
    assert [t.name for t in spec.pricing_tiers] == ["Starter", "Pro"]
    assert [t.price for t in spec.pricing_tiers] == [9.0, 29.0]
    evidence_ids = {e.id for e in report.evidence}
    assert all(r.evidence_id in evidence_ids for t in spec.pricing_tiers for r in t.evidence)


def test_no_price_finding_yields_no_tiers() -> None:
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), _report())
    assert spec.pricing_tiers == []


def test_price_with_no_evidence_yields_no_tiers() -> None:
    # No-cite-no-claim for price: low/high set but evidence empty → no tiers ship.
    price = PriceFinding(
        low=9.0, high=29.0, currency="USD", confidence=SignalStrength.LOW, evidence=[]
    )
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), _report(price=price))
    assert spec.pricing_tiers == []


def test_persona_grounds_to_a_later_cluster_when_top_is_quoteless() -> None:
    # Top cluster has no quotes, but a later one does — persona must still be grounded.
    report = _report(
        clusters=[
            _cluster(1, quotes=[]),
            _cluster(2, quotes=[_quote("real voice here", "https://r/x/9", "a9")]),
        ]
    )
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 2)])), report)
    evidence_ids = {e.id for e in report.evidence}
    assert spec.personas, "a persona should be derived from the grounded cluster"
    assert all(r.evidence_id in evidence_ids for p in spec.personas for r in p.evidence)


def test_no_quotes_anywhere_yields_no_personas() -> None:
    report = _report(clusters=[_cluster(1, quotes=[])])
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), report)
    assert spec.personas == []


def test_duplicate_cluster_rank_keeps_first_not_last() -> None:
    # A malformed report with two clusters at rank 1 must not let the later one
    # silently supply a feature's quotes — keep-first.
    first = _cluster(1, quotes=[_quote("the FIRST cluster voice", "https://r/x/1", "a1")])
    dupe = _cluster(1, quotes=[_quote("the SECOND cluster voice", "https://r/x/2", "a2")])
    report = _report(clusters=[first, dupe])
    spec = build_spec_from_report(_deps(_scripted([_draft("f", 1)])), report)
    cited_ids = {r.evidence_id for f in spec.features for r in f.evidence}
    assert first.quotes[0].id in cited_ids
    assert dupe.quotes[0].id not in cited_ids


# ── scaffold writer (deterministic, on-disk) ─────────────────────────────────


def _scaffolded(tmp_path: Path) -> tuple[Path, DemandReport, Any]:
    report = _report()
    spec = build_spec_from_report(_deps(_scripted([_draft("fade-tracker", 1)])), report)
    scaffold(spec, report, tmp_path, base="next-shipfast")
    return tmp_path, report, spec


def test_scaffold_writes_the_full_harness(tmp_path: Path) -> None:
    dest, _report_obj, _spec = _scaffolded(tmp_path)
    for rel in (
        "CLAUDE.md",
        "docs/SPEC.md",
        "docs/EVIDENCE.md",
        ".claude/skills/scaffold-startup/SKILL.md",
        ".claude/skills/spec-from-report/SKILL.md",
        ".claude/skills/cite-or-die/SKILL.md",
        ".claude/scripts/cite_or_die.py",
        ".claude/hooks.json",
        ".mcp.json",
    ):
        assert (dest / rel).is_file(), f"missing {rel}"


def test_scaffold_rejects_spec_report_id_mismatch(tmp_path: Path) -> None:
    report = _report()  # report_id == "rpt-1"
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), report)
    wrong = spec.model_copy(update={"report_id": "different-report"})
    with pytest.raises(ValueError, match="report_id"):
        scaffold(wrong, report, tmp_path)


def test_claude_md_leads_with_cite_or_die(tmp_path: Path) -> None:
    dest, _r, _s = _scaffolded(tmp_path)
    claude = (dest / "CLAUDE.md").read_text(encoding="utf-8")
    assert "cite or die" in claude.lower()
    assert "next-shipfast" in claude  # base overrides the stack hint


def test_spec_md_renders_a_grounded_build_order_with_the_spine_flagged(tmp_path: Path) -> None:
    # rank-2 feature drafted first, rank-1 second → SPEC.md must lead with rank-1.
    report = _report()  # cluster rank 1 (2 quotes) + rank 2 (1 quote)
    spec = build_spec_from_report(_deps(_scripted([_draft("track", 2), _draft("fade", 1)])), report)
    scaffold(spec, report, tmp_path, base="empty")
    spec_md = (tmp_path / "docs/SPEC.md").read_text(encoding="utf-8")
    assert "build in this order" in spec_md.lower()
    assert "spine, build first" in spec_md
    # The rank-1 feature leads (#1) despite being drafted second.
    assert spec_md.index("`fade`") < spec_md.index("`track`")
    assert spec_md.index("### 1. ") < spec_md.index("### 2. ")


def test_evidence_md_is_the_frozen_verbatim_table(tmp_path: Path) -> None:
    dest, report, _s = _scaffolded(tmp_path)
    evidence = (dest / "docs/EVIDENCE.md").read_text(encoding="utf-8")
    # The verbatim quote text and its content-addressed id both appear.
    quote = report.ranked_clusters[0].quotes[0]
    assert quote.text in evidence
    assert quote.id in evidence


def test_spec_md_cites_only_resolvable_evidence(tmp_path: Path) -> None:
    dest, report, _s = _scaffolded(tmp_path)
    spec_md = (dest / "docs/SPEC.md").read_text(encoding="utf-8")
    assert "fade-tracker" in spec_md
    import re

    valid = {e.id for e in report.evidence}
    cited = set(re.findall(r"[qpw]:[0-9a-f]{12}", spec_md))
    assert cited, "spec should cite at least one evidence id"
    assert cited <= valid, "every cited id must resolve in the report"


# ── the generated cite-or-die lint actually runs ─────────────────────────────


def _run_lint(dest: Path, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(dest / ".claude/scripts/cite_or_die.py"), str(dest / target)],
        cwd=dest,
        capture_output=True,
        text=True,
        check=False,
    )


def test_generated_lint_passes_on_clean_spec(tmp_path: Path) -> None:
    dest, _r, _s = _scaffolded(tmp_path)
    result = _run_lint(dest, "docs/SPEC.md")
    assert result.returncode == 0, result.stderr


def test_generated_lint_fails_on_dangling_citation(tmp_path: Path) -> None:
    dest, _r, _s = _scaffolded(tmp_path)
    tampered = dest / "docs/SPEC.md"
    tampered.write_text(
        tampered.read_text(encoding="utf-8") + "\n### Invented  `x`\nbogus  (`q:deadbeefdead`)\n",
        encoding="utf-8",
    )
    result = _run_lint(dest, "docs/SPEC.md")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "deadbeefdead" in result.stderr


def _run_lint_via_hook(dest: Path, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """Invoke the lint the way hooks.json does: no argv, file_path from stdin JSON."""
    return subprocess.run(
        [sys.executable, str(dest / ".claude/scripts/cite_or_die.py")],
        cwd=dest,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def test_lint_hook_path_reads_file_from_stdin(tmp_path: Path) -> None:
    # hooks.json calls the lint with NO argv — the production enforcement path.
    dest, _r, _s = _scaffolded(tmp_path)
    clean = _run_lint_via_hook(dest, {"tool_input": {"file_path": "docs/SPEC.md"}})
    assert clean.returncode == 0, clean.stderr

    spec_md = dest / "docs/SPEC.md"
    spec_md.write_text(
        spec_md.read_text(encoding="utf-8") + "\n### X  `x`\nbogus  (`q:deadbeefdead`)\n",
        encoding="utf-8",
    )
    dangling = _run_lint_via_hook(dest, {"tool_input": {"file_path": "docs/SPEC.md"}})
    assert dangling.returncode == 2, dangling.stdout + dangling.stderr


def test_lint_warns_but_passes_on_uncited_claim(tmp_path: Path) -> None:
    dest, _r, _s = _scaffolded(tmp_path)
    spec_md = dest / "docs/SPEC.md"
    spec_md.write_text(
        spec_md.read_text(encoding="utf-8") + "\n- **Uncited feature** with no citation at all\n",
        encoding="utf-8",
    )
    result = _run_lint(dest, "docs/SPEC.md")
    assert result.returncode == 0, "an uncited claim warns, it does not hard-fail"
    assert "warn:" in result.stderr


# ── render edge cases (partial, single-tier, unresolved) ─────────────────────


def test_partial_spec_render_warns_the_reader(tmp_path: Path) -> None:
    # The honesty surface: a partial spec's SPEC.md must visibly flag itself.
    quoteless = _cluster(1, quotes=[])
    report = _report(clusters=[quoteless])
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), report)
    assert spec.partial is True
    scaffold(spec, report, tmp_path)
    spec_md = (tmp_path / "docs/SPEC.md").read_text(encoding="utf-8")
    assert "Partial spec" in spec_md
    assert "No evidence-grounded features survived" in spec_md


def test_single_tier_when_low_equals_high() -> None:
    price = PriceFinding(
        low=19.0,
        high=19.0,
        currency="USD",
        confidence=SignalStrength.MEDIUM,
        evidence=[PriceEvidence(text="$19/mo feels right", kind="willingness", amount=19.0)],
    )
    spec = build_spec_from_report(_deps(_scripted([_draft("x", 1)])), _report(price=price))
    assert [t.name for t in spec.pricing_tiers] == ["Starter"]


def test_unresolved_evidence_id_renders_as_unresolved(tmp_path: Path) -> None:
    # Defensive branch: a feature carrying an id absent from the report's evidence.
    from metalworks.contract import BuildSpec, EvidenceRef, FeatureSpec

    report = _report()
    spec = BuildSpec(
        spec_id="spec:rpt-1",
        report_id="rpt-1",
        surface="web",
        stack="empty",
        features=[
            FeatureSpec(
                feature_id="ghost",
                title="Ghost",
                rationale="dangling",
                evidence=[EvidenceRef(evidence_id="q:ffffffffffff", kind="quote")],
            )
        ],
    )
    scaffold(spec, report, tmp_path)
    assert "UNRESOLVED" in (tmp_path / "docs/SPEC.md").read_text(encoding="utf-8")
    assert "UNRESOLVED" in (tmp_path / "docs/EVIDENCE.md").read_text(encoding="utf-8")


def test_md_escaping_neutralizes_pipes_in_llm_fields(tmp_path: Path) -> None:
    report = _report()
    chat = FakeChatModel().script(
        _BuildPhrasing,
        _BuildPhrasing(
            features=[
                _FeatureDraft(
                    feature_id="piped",
                    title="A | B title",
                    rationale="row | breaker",
                    source_cluster_rank=1,
                )
            ]
        ),
    )
    spec = build_spec_from_report(_deps(chat), report)
    scaffold(spec, report, tmp_path)
    spec_md = (tmp_path / "docs/SPEC.md").read_text(encoding="utf-8")
    assert "A \\| B title" in spec_md  # the raw pipe is escaped, not table-breaking


# ── MCP tool surface validation ──────────────────────────────────────────────


def test_mcp_build_spec_rejects_unknown_surface() -> None:
    from metalworks.mcp import tools

    result = tools.build_spec("any-report", surface="extension")
    # Envelope must be nested under "error" like every other tool, so a host
    # branching on `"error" in result` sees it as a failure, not a success.
    assert "error" in result
    assert result["error"]["error_code"] == "invalid_argument"
    assert "extension" in result["error"]["message"]
