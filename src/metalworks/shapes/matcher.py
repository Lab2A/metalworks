"""ShapeMatcher — rank product shapes against a finished research bundle.

Read-only over the report, verdict-reactive over the assessment, never touching
the honesty gates. The scoring metric is embedding-similarity when an
``EmbeddingProvider`` is supplied (reuses the engine's existing embedding infra),
with a deterministic keyword-coverage fallback when it is not, so the matcher
runs on a bare install and is fully offline-testable.

Pipeline::

    research.assessment.decision ?
      NO_GO   -> []                          (the corpus vetoed every shape)
      PIVOT   -> score only the pivot fork's clusters
      None    -> score all clusters (demand-only, reduced confidence)
      GO/...  -> score all clusters
        |
        v
    for each registered ProductShape:
      gate clusters by MatchSignature.min_signal (breadth floor)
      relevance = max sim(signature.cluster_keywords, cluster.claim)
      + surface match bonus, + build-signal bonus
      drop below min_score
        |
        v
    ranked list[ShapeMatch], each cited to the clusters that drove it
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from metalworks.contract.assess import Decision
from metalworks.contract.evidence import EvidenceRef
from metalworks.contract.research import InsightCluster, SignalStrength
from metalworks.contract.shape import ProductShape, ShapeMatch
from metalworks.shapes import all_shapes, get_base_stack

if TYPE_CHECKING:
    from metalworks.contract.assess import Assessment
    from metalworks.contract.build import BuildSpec
    from metalworks.contract.bundle import Research
    from metalworks.contract.surface import SurfaceRecommendation
    from metalworks.embeddings import EmbeddingProvider

_SIGNAL_RANK: dict[SignalStrength, int] = {
    SignalStrength.LOW: 0,
    SignalStrength.MEDIUM: 1,
    SignalStrength.HIGH: 2,
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SURFACE_BONUS = 0.1
_BUILD_BONUS_PER_HIT = 0.03
_BUILD_BONUS_CAP = 0.1
_MAX_REFS = 3


def _tokens(text: str) -> set[str]:
    """Lowercased alphanumeric tokens of length >= 3 (drops noise words)."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 3}


def _keyword_coverage(keyword: str, claim_tokens: set[str]) -> float:
    """Fraction of ``keyword``'s tokens present in the claim (0..1)."""
    kw = _tokens(keyword)
    if not kw:
        return 0.0
    return len(kw & claim_tokens) / len(kw)


def _cosine(u: list[float], v: list[float]) -> float:
    """Cosine similarity of two equal-length vectors, clamped to [0, 1]."""
    dot = sum(a * b for a, b in zip(u, v, strict=True))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    if nu == 0.0 or nv == 0.0:
        return 0.0
    return max(0.0, dot / (nu * nv))


class ShapeMatcher:
    """Ranks registered product shapes against a research bundle.

    ``embedder`` is optional: with one, shape signatures are matched by embedding
    similarity (synonym-robust); without one, by deterministic keyword coverage.
    """

    def __init__(self, *, embedder: EmbeddingProvider | None = None) -> None:
        self._embedder = embedder

    def match(
        self,
        research: Research,
        *,
        surface: SurfaceRecommendation | None = None,
        build_spec: BuildSpec | None = None,
        min_score: float = 0.5,
    ) -> list[ShapeMatch]:
        """Return shapes that fit ``research``, ranked by score (desc).

        Empty when the report is NO-GO, has no clusters, or nothing clears
        ``min_score``. Never raises on a missing assessment / positioning /
        surface / build spec.
        """
        clusters = self._candidate_clusters(research)
        if not clusters:
            return []

        matches: list[ShapeMatch] = []
        for shape in all_shapes():
            match = self._score_shape(shape, clusters, surface, build_spec)
            if match is not None and match.score >= min_score:
                matches.append(match)
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    def _candidate_clusters(self, research: Research) -> list[InsightCluster]:
        """The clusters to score: all of them, the pivot fork's, or none (NO-GO)."""
        report = research.demand
        assessment: Assessment | None = research.assessment
        if assessment is None:
            return list(report.ranked_clusters)
        if assessment.decision == Decision.NO_GO:
            return []
        if assessment.decision == Decision.PIVOT and assessment.pivot_target is not None:
            return self._pivot_clusters(research, assessment)
        return list(report.ranked_clusters)

    def _pivot_clusters(self, research: Research, assessment: Assessment) -> list[InsightCluster]:
        """Restrict to the pivot wedge's clusters; fall back to all if unresolvable."""
        report = research.demand
        target = assessment.pivot_target
        if target is not None and target.kind == "wedge":
            wedge = next((w for w in report.candidate_wedges if w.id == target.target_id), None)
            if wedge is not None and wedge.cluster_ranks:
                ranks = set(wedge.cluster_ranks)
                picked = [c for c in report.ranked_clusters if c.rank in ranks]
                if picked:
                    return picked
        # Segment pivots (and unresolvable wedge ids) have no clean cluster map yet.
        return list(report.ranked_clusters)

    def _score_shape(
        self,
        shape: ProductShape,
        clusters: list[InsightCluster],
        surface: SurfaceRecommendation | None,
        build_spec: BuildSpec | None,
    ) -> ShapeMatch | None:
        """Score one shape against the candidate clusters; None if nothing qualifies."""
        sig = shape.match_signature
        floor = _SIGNAL_RANK[sig.min_signal]
        contributing: list[tuple[InsightCluster, float]] = []
        for cluster in clusters:
            if _SIGNAL_RANK[cluster.signal] < floor:
                continue  # below the breadth floor this shape requires
            rel = self._claim_relevance(sig.cluster_keywords, cluster.claim)
            if rel > 0.0:
                contributing.append((cluster, rel))
        if not contributing:
            return None

        contributing.sort(key=lambda t: t[1], reverse=True)
        score = contributing[0][1]
        if sig.surface is not None and surface is not None:
            score += _SURFACE_BONUS if surface.chosen == sig.surface else -_SURFACE_BONUS
        if build_spec is not None and sig.build_signals:
            titles = " ".join(f.title for f in build_spec.features).lower()
            hits = sum(1 for b in sig.build_signals if b.lower() in titles)
            score += min(_BUILD_BONUS_CAP, _BUILD_BONUS_PER_HIT * hits)
        score = max(0.0, min(1.0, score))

        top = contributing[0][0]
        refs = [
            EvidenceRef(kind="cluster", cluster_rank=c.rank) for c, _ in contributing[:_MAX_REFS]
        ]
        rationale = (
            f"{shape.name}: demand cluster '{top.claim}' matches its signature "
            f"(relevance {contributing[0][1]:.2f})"
        )
        return ShapeMatch(
            shape=shape,
            base_stack=get_base_stack(shape.base_stack),
            score=score,
            rationale=rationale,
            evidence_refs=refs,
        )

    def _claim_relevance(self, keywords: list[str], claim: str) -> float:
        """Max similarity between any signature keyword and the cluster claim (0..1)."""
        if not keywords:
            return 0.0
        if self._embedder is not None:
            vecs = self._embedder.embed([claim, *keywords], task="document")
            claim_vec, kw_vecs = vecs[0], vecs[1:]
            return max(_cosine(claim_vec, kv) for kv in kw_vecs)
        claim_tokens = _tokens(claim)
        return max(_keyword_coverage(kw, claim_tokens) for kw in keywords)


__all__ = ["ShapeMatcher"]
