"""Intermediate types that flow between research pipeline stages.

These are the dataclasses passed stage-to-stage inside the pipeline — distinct
from `metalworks.contract`, which is the public wire shape. Ported with field
names are kept stable as part of the public contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metalworks.contract import (
    AudienceProfile,
    AudienceSegment,
    CandidateWedge,
    CrossReference,
    InsightCluster,
    MarketSizing,
    PriceFinding,
    SlotPlan,
    SourceMapEntry,
)

# ── Corpus reader ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MonthRef:
    """An immutable year/month reference into the monthly-partitioned corpus."""

    year: int
    month: int

    @property
    def path_segment(self) -> str:
        return f"{self.year:04d}/{self.month:02d}"

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def months_back(n: int, *, anchor: MonthRef) -> list[MonthRef]:
    """`n` months ending at (and including) `anchor`, oldest first."""
    out: list[MonthRef] = []
    y, m = anchor.year, anchor.month
    for _ in range(max(1, n)):
        out.append(MonthRef(y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


# ── Exploration / triage ───────────────────────────────────────────────────


@dataclass
class ExplorationItem:
    """One pulled thread, the triage stage's indexing unit.

    `idx` is the 0-based position in the input list — the indexing contract
    every downstream stage relies on.
    """

    idx: int
    post_id: str
    title: str
    selftext: str | None = None
    subreddit: str | None = None
    score: int | None = None
    num_comments: int | None = None

    def to_text(self) -> str:
        body = self.selftext or ""
        return f"{self.title}\n\n{body}".strip() if body else self.title


@dataclass
class TriageBuckets:
    """Three-bucket split plus the dense per-item score vectors that drove it."""

    accepted: list[int]
    rejected: list[int]
    middle: list[int]
    cosines: list[float] = field(default_factory=list[float])
    bm25_scores: list[float] = field(default_factory=list[float])
    hybrid_scores: list[float] = field(default_factory=list[float])
    band_percentile_disagreement: float | None = None


@dataclass(frozen=True)
class ClassifierVerdict:
    """The middle-bucket LLM classifier's call on one item."""

    relevant: bool
    reason: str


# ── Synthesis loader rows ──────────────────────────────────────────────────


@dataclass
class LoadedPost:
    post_id: str
    subreddit: str
    title: str
    score: int = 0
    num_comments: int = 0
    permalink: str = ""
    # Source-neutral display fields (additive). The Reddit loader fills these
    # alongside the legacy Reddit-specific fields above; downstream consumers
    # may read either, and nothing Reddit-specific leaks for other sources.
    source: str = "reddit"
    source_label: str = ""
    engagement: int = 0
    engagement_unit: str = "upvotes"
    source_url: str = ""


@dataclass
class LoadedComment:
    comment_id: str
    post_id: str
    subreddit: str
    body: str
    upvotes: int = 0
    author_hash: str = ""
    permalink: str = ""
    # Source-neutral display fields (additive) — see LoadedPost.
    source: str = "reddit"
    source_label: str = ""
    engagement: int = 0
    engagement_unit: str = "upvotes"
    source_url: str = ""
    # Open, source-declared demand signals (additive). The loader fills this from
    # the generic `CorpusComment.signals`, or synthesizes `{native_kind: engagement}`
    # for sources not yet emitting a vector. The cluster ranker aggregates and
    # spec-weights it — the de-Reddit'd successor to a lone `upvotes` int.
    signals: dict[str, float] = field(default_factory=dict[str, float])

    @property
    def post_url(self) -> str:
        return self.permalink

    @property
    def text(self) -> str:
        """Source-neutral alias for the comment body."""
        return self.body


# ── Stage outputs ──────────────────────────────────────────────────────────


@dataclass
class HydrationResult:
    """Outcome of a hydration pass.

    `skipped` / `errors` are metalworks additions (the source swallowed
    per-link failures): a run that lost most of the corpus to upstream 5xx
    must be able to flag itself partial.
    """

    requested: int
    fetched: int
    upserted: int
    elapsed_s: float
    source: str
    skipped: int = 0
    errors: list[str] = field(default_factory=list[str])

    def __str__(self) -> str:
        tail = f", skipped {self.skipped}" if self.skipped else ""
        return (
            f"hydrate[{self.source}]: requested {self.requested}, fetched "
            f"{self.fetched}, upserted {self.upserted}{tail} in {self.elapsed_s:.1f}s"
        )


@dataclass
class SynthesisOutput:
    """Everything the synthesis subtree produces for the report."""

    ranked_clusters: list[InsightCluster]
    demand_summary: str
    slot_plan: SlotPlan | None
    audience_profile: AudienceProfile | None
    segments: list[AudienceSegment]
    candidate_wedges: list[CandidateWedge]
    market_sizing: MarketSizing | None
    price_finding: PriceFinding | None
    source_map: list[SourceMapEntry]
    total_distinct_authors: int
    n_synthesized: int
    # Fraction of synthesis units folded together by embed_group near-dup merging
    # (1 - groups/units). Surfaces breadth-collapse onto ExplorationReport
    # (issue #82). None when no units were synthesized.
    dedup_merge_rate: float | None = None


@dataclass
class TriangulationOutput:
    """Cross-stream links + must_address coverage. Empty = degraded stage."""

    cross_references: list[CrossReference] = field(default_factory=list[CrossReference])
    must_address_resolution: dict[str, str] = field(default_factory=dict[str, str])
