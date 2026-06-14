"""Pillar F — launch: refusal gate, claim grounding, deterministic channel plan.

Offline. FakeChatModel is scripted per surface (one _AssetPhrasing per call,
consumed FIFO); the DemandReport fixture carries clusters/quotes so claim
grounding and evidence resolution run for real. No network, no keys, no
embeddings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from metalworks.contract import (
    DemandReport,
    Fork,
    InsightCluster,
    QuoteCitation,
    SignalStrength,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.launch import (
    DEFAULT_SURFACES,
    _AssetPhrasing,
    _ClaimDraft,
    build_launch_assets,
    plan_channels,
)
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


def _quote(text: str, permalink: str, author_hash: str = "a1") -> QuoteCitation:
    return QuoteCitation(
        text=text, permalink=permalink, subreddit="SkincareAddiction", author_hash=author_hash
    )


def _cluster(
    rank: int,
    *,
    quotes: list[QuoteCitation],
    signal: SignalStrength = SignalStrength.HIGH,
) -> InsightCluster:
    return InsightCluster(
        rank=rank,
        claim=f"consumers want outcome {rank}",
        demand_score=10.0,
        distinct_author_count=len({q.author_hash for q in quotes}),
        mention_count=len(quotes),
        signal=signal,
        quotes=quotes,
    )


def _report(
    *,
    clusters: list[InsightCluster],
    verdict: str | None = "Strong signal: launch-worthy demand.",
) -> DemandReport:
    now = datetime(2026, 2, 1, tzinfo=UTC)
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
        verdict=verdict,
    )


def _deps(chat: FakeChatModel | None = None) -> ResearchDeps:
    return ResearchDeps(
        chat=chat or FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
    )


def _phrasing(body: str, claims: list[_ClaimDraft]) -> _AssetPhrasing:
    return _AssetPhrasing(
        title="Fade post-acne marks without the burn",
        body=body,
        variants=["The fade that doesn't sting"],
        claims=claims,
    )


def _scripted_chat(phrasings: list[_AssetPhrasing]) -> FakeChatModel:
    chat = FakeChatModel()
    chat.script(_AssetPhrasing, phrasings)
    return chat


# ── refusal gate ─────────────────────────────────────────────────────────────


def test_refuses_on_negative_verdict() -> None:
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("PIE is the worst", "https://r/x/1", "a1")])],
        verdict="Thin signal: not enough demand to act on.",
    )
    # Even with plenty of distinct authors, a negative verdict refuses.
    report.ranked_clusters[0].distinct_author_count = 9
    assets = build_launch_assets(_deps(_scripted_chat([])), report)
    assert assets == []


def test_refuses_when_no_cluster_has_two_distinct_authors() -> None:
    # Positive verdict, but every cluster is a single author → refuse.
    report = _report(
        clusters=[_cluster(1, quotes=[_quote("just me", "https://r/x/1", "a1")])],
    )
    assert report.ranked_clusters[0].distinct_author_count == 1
    assets = build_launch_assets(_deps(_scripted_chat([])), report)
    assert assets == []


def test_price_caveat_in_verdict_does_not_trip_no_go() -> None:
    # Real-world dogfood bug: a STRONG-demand verdict that appends a price caveat
    # ("not enough price signal...") must NOT be read as weak demand. The no-go
    # gate judges only the demand segment (before the first ';').
    report = _two_author_report()
    report.verdict = (
        "Strong demand — 1313 distinct voices; ~1,313 reachable on Reddit, "
        "~131,300 addressable; not enough price signal to recommend a price."
    )
    # Claims are irrelevant here — this test is purely about the no-go gate.
    phrasing = _phrasing("We built the fade that doesn't sting.", [])
    chat = _scripted_chat([phrasing for _ in DEFAULT_SURFACES])
    assets = build_launch_assets(_deps(chat), report)
    assert assets, "strong demand + thin price signal must still launch"


# ── claim grounding ──────────────────────────────────────────────────────────


def _two_author_report() -> DemandReport:
    return _report(
        clusters=[
            _cluster(
                1,
                quotes=[
                    _quote("nothing fades PIE without burning my skin", "https://r/x/1", "a1"),
                    _quote("every cream I tried left me red and raw", "https://r/x/2", "a2"),
                ],
            )
        ],
    )


def test_grounded_claim_produces_resolvable_citation_with_matching_span() -> None:
    report = _two_author_report()
    claim_text = "People say nothing fades PIE without burning"
    body = f"Here's the problem. {claim_text}. We fixed that."
    phrasing = _phrasing(
        body,
        [_ClaimDraft(text=claim_text, supporting_quote="nothing fades PIE without burning")],
    )
    # One phrasing per surface so the FIFO queue isn't exhausted.
    chat = _scripted_chat([phrasing for _ in DEFAULT_SURFACES])
    assets = build_launch_assets(_deps(chat), report)
    assert len(assets) == len(DEFAULT_SURFACES)

    evidence_ids = {e.id for e in report.evidence}
    asset = assets[0]
    assert len(asset.claim_citations) == 1
    cc = asset.claim_citations[0]
    # Span indexes into the body and recovers the claim text exactly.
    assert asset.body[cc.span_start : cc.span_end] == cc.claim_text == claim_text
    # The ref resolves against the report's evidence (the spine).
    assert cc.evidence_ref.kind == "quote"
    assert cc.evidence_ref.evidence_id in evidence_ids


def test_unsupported_claim_is_dropped() -> None:
    report = _two_author_report()
    good = "nothing fades PIE without burning"
    grounded = _ClaimDraft(text=f"They told us {good}", supporting_quote=good)
    invented = _ClaimDraft(
        text="Clinically proven 10x faster than anything else",
        supporting_quote="10x faster, dermatologist approved",  # not in any report quote
    )
    body = f"They told us {good}. Clinically proven 10x faster than anything else."
    phrasing = _phrasing(body, [grounded, invented])
    chat = _scripted_chat([phrasing for _ in DEFAULT_SURFACES])
    assets = build_launch_assets(_deps(chat), report)

    cc = assets[0].claim_citations
    # The invented claim (no resolvable quote) is dropped; the grounded one stays.
    assert len(cc) == 1
    assert cc[0].claim_text == f"They told us {good}"


def test_claim_not_in_body_is_dropped() -> None:
    report = _two_author_report()
    good = "nothing fades PIE without burning"
    # Supporting quote resolves, but the claim text is absent from the body.
    claim = _ClaimDraft(text="This phrase is nowhere in the body", supporting_quote=good)
    phrasing = _phrasing("A clean body with no matching claim text.", [claim])
    chat = _scripted_chat([phrasing for _ in DEFAULT_SURFACES])
    assets = build_launch_assets(_deps(chat), report)
    assert assets[0].claim_citations == []


def test_llm_failure_on_a_surface_skips_only_that_asset() -> None:
    report = _two_author_report()
    good = "nothing fades PIE without burning"
    body = f"They told us {good}."
    phrasing = _phrasing(body, [_ClaimDraft(text=f"They told us {good}", supporting_quote=good)])
    # Only TWO phrasings scripted for THREE surfaces → the third call raises →
    # that surface is skipped, the batch still returns the first two.
    chat = _scripted_chat([phrasing, phrasing])
    assets = build_launch_assets(_deps(chat), report)
    assert len(assets) == len(DEFAULT_SURFACES) - 1


# ── channel plan ─────────────────────────────────────────────────────────────


def test_plan_channels_marks_every_step_human_and_gated() -> None:
    report = _two_author_report()
    plan = plan_channels(report, list(DEFAULT_SURFACES))
    assert plan.report_id == "rpt-1"
    assert len(plan.steps) == len(DEFAULT_SURFACES)
    assert [s.surface for s in plan.steps] == list(DEFAULT_SURFACES)
    for step in plan.steps:
        assert step.requires_human is True
        assert step.posting_gated is True
        assert step.scheduled_offset.startswith("T+")


def test_plan_channels_defaults_to_all_surfaces() -> None:
    plan = plan_channels(_two_author_report())
    assert [s.surface for s in plan.steps] == list(DEFAULT_SURFACES)


def test_short_supporting_quote_does_not_ground_claim() -> None:
    # "PIE" is a real substring of a quote but only 1 word — it must not ground
    # the surrounding claim (no-cite-no-claim against trivial substrings).
    report = _two_author_report()
    claim_text = "PIE is brutal and nothing helps"
    body = f"Real talk. {claim_text}. Until now."
    phrasing = _phrasing(body, [_ClaimDraft(text=claim_text, supporting_quote="PIE")])
    chat = _scripted_chat([phrasing for _ in DEFAULT_SURFACES])
    assets = build_launch_assets(_deps(chat), report)
    assert assets  # asset still ships...
    assert all(a.claim_citations == [] for a in assets)  # ...but the trivial claim is uncited
