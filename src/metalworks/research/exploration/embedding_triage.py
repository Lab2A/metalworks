"""Hybrid cosine + BM25 triage: three-bucket partition of a thread corpus.

The first stage of the exploration funnel. We score every thread against the
research question along two axes — dense semantic (embeddings, cosine) and
lexical (BM25) — then blend them into one hybrid score that drives bucketing:

    top N% hybrid → ACCEPTED  (skip the LLM, treat as relevant)
    bottom M%     → REJECTED   (skip the LLM, treat as noise)
    middle        → MIDDLE     (LLM classifier decides — see llm_classifier.py)

Hybrid blend:
    cosine_norm = (cosine - min) / (max - min) over the corpus
    bm25_norm   = (bm25   - min) / (max - min) over the corpus
    hybrid      = alpha * cosine_norm + (1 - alpha) * bm25_norm

Default alpha = 0.6 (cosine-weighted). Cosine is robust to vocabulary mismatch
(synonyms, paraphrase); BM25 anchors on exact lexical hits like brand names,
ingredient codes, dosages. The blend recovers the lexical specificity dense
embeddings smooth away.

We still gate on BOTH absolute cosine bands AND the hybrid percentile.
cosine_floor / cosine_ceiling stay cosine-specific — a lexical-only match (high
BM25, near-zero cosine) is usually a false positive (rare-word collisions).
Promotion / demotion to MIDDLE on these overrides is recorded as
band_percentile_disagreement.

DESIGN NOTE: an earlier internal version embedded each item in its
own ThreadPoolExecutor task with a None-tolerant adapter. Here we BATCH-embed
through `deps.embeddings.embed(...)` — one call for all documents, one for the
query. The metalworks embedding adapters never return None (they raise on
failure), so the per-item None branch the source carried is gone; every item
gets a real vector or the whole triage fails loud.
"""

from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING, Any

from metalworks.errors import MissingExtraError
from metalworks.research.embedding_cache import cached_embed
from metalworks.research.types import ExplorationItem, TriageBuckets

if TYPE_CHECKING:
    from metalworks.contract import TriageThresholds
    from metalworks.research.deps import ResearchDeps

logger = logging.getLogger(__name__)

DEFAULT_HYBRID_ALPHA = 0.6


def _cosine(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity. Vectors are typically L2-normed by the
    embedding API, but we still divide by magnitude so a partial vector or
    zero-vector failure mode doesn't NaN downstream code."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization. No stopword removal — BM25's IDF
    naturally down-weights common terms; explicit stopwords add a language
    dependency we don't need."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _bm25okapi() -> Any:
    """Lazy import — rank_bm25 lives in the `[research]` extra. Imported here,
    never at module load, so the package stays import-safe without the extra."""
    try:
        from rank_bm25 import BM25Okapi  # pyright: ignore[reportMissingTypeStubs]
    except ImportError as exc:  # pragma: no cover - exercised via MissingExtra test
        raise MissingExtraError("research", package="rank-bm25") from exc
    return BM25Okapi


def _bm25_scores(question: str, items: list[ExplorationItem]) -> list[float]:
    """Compute one BM25Okapi score per item against the question.

    Empty corpus → empty list. Items tokenizing empty → 0 score (rank_bm25
    handles this without crashing). The corpus IS the items themselves — IDF
    reflects only what's pulled in this run.
    """
    if not items:
        return []
    tokenized_corpus = [_tokenize(it.to_text()) for it in items]
    # rank_bm25 chokes on a corpus of all-empty docs; pad to avoid div-by-zero.
    safe_corpus = [doc if doc else [""] for doc in tokenized_corpus]
    bm25: Any = _bm25okapi()(safe_corpus)
    q_tokens = _tokenize(question)
    if not q_tokens:
        return [0.0] * len(items)
    scores: Any = bm25.get_scores(q_tokens)
    return [float(s) for s in scores]


def _minmax_normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. Constant input → all zeros (avoids NaN).
    Empty input → empty output."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    spread = hi - lo
    if spread <= 0:
        return [0.0] * len(values)
    return [(v - lo) / spread for v in values]


def triage_by_embedding(
    deps: ResearchDeps,
    *,
    question: str,
    items: list[ExplorationItem],
    thresholds: TriageThresholds,
    hybrid_alpha: float = DEFAULT_HYBRID_ALPHA,
) -> TriageBuckets:
    """Embed, BM25-score, blend, and bucket the corpus.

    Args:
        deps: Injected dependencies; uses `deps.embeddings`.
        question: The research question (typically `ResearchBrief.question`).
        items: Threads to triage. Each gets exactly one bucket assignment.
        thresholds: Percentile cutoffs + optional absolute cosine guards.
        hybrid_alpha: Cosine weight in [0,1]. 1.0 = cosine-only (legacy);
            0.0 = BM25-only. Default 0.6 — cosine-leaning.

    Returns: TriageBuckets with disjoint accepted/rejected/middle lists.
    """
    if not items:
        return TriageBuckets(accepted=[], rejected=[], middle=[])

    # Step 1: embed the question. task="query" biases the embedding toward
    # "what would match this query" — the documented retrieval pattern.
    q_vec = deps.embeddings.embed([question], task="query")[0]
    if not q_vec:
        raise RuntimeError("embedding_triage: question embedding failed; cannot triage corpus")

    # Step 2: embed every item (reusing any persisted corpus vectors, keyed on
    # post_id, embedding only the misses in one batch) plus BM25 in-process. The
    # adapter raises on failure, so there is no per-item None to tolerate.
    cache = cached_embed(deps, [(it.post_id, it.to_text()) for it in items], task="document")
    item_vecs = [cache[it.post_id] for it in items]
    bm25_raw = _bm25_scores(question, items)

    # Step 3: cosine each item against the question.
    cosines: list[float] = [_cosine(q_vec, vec) for vec in item_vecs]

    # Step 4: normalize cosine + BM25 to [0,1], blend.
    alpha = max(0.0, min(1.0, hybrid_alpha))
    cosine_norm = _minmax_normalize(cosines)
    bm25_norm = _minmax_normalize(bm25_raw)
    hybrid: list[float] = [
        alpha * c + (1.0 - alpha) * b for c, b in zip(cosine_norm, bm25_norm, strict=False)
    ]
    logger.info(
        "embedding_triage: blend alpha=%.2f · cosine[min=%.3f max=%.3f] · "
        "bm25[min=%.3f max=%.3f] · hybrid[min=%.3f max=%.3f]",
        alpha,
        min(cosines) if cosines else 0,
        max(cosines) if cosines else 0,
        min(bm25_raw) if bm25_raw else 0,
        max(bm25_raw) if bm25_raw else 0,
        min(hybrid) if hybrid else 0,
        max(hybrid) if hybrid else 0,
    )

    # Step 5: percentile-bucket by HYBRID score descending.
    n = len(items)
    indices_sorted_desc = sorted(range(n), key=lambda i: hybrid[i], reverse=True)

    n_accept = round(n * thresholds.auto_accept_pct)
    n_reject = round(n * thresholds.auto_reject_pct)
    # Guard against accept+reject > n (e.g. malformed brief): squeeze middle to 0.
    if n_accept + n_reject > n:
        if n_accept <= n_reject:
            n_reject = n - n_accept
        else:
            n_accept = n - n_reject

    accepted_set: set[int] = set(indices_sorted_desc[:n_accept])
    rejected_set: set[int] = set(indices_sorted_desc[n - n_reject :]) if n_reject else set()
    middle_set: set[int] = set(range(n)) - accepted_set - rejected_set

    # Step 6: absolute-cosine overrides. cosine_floor / cosine_ceiling are kept
    # cosine-specific — a lexical-only match (high BM25, near-zero cosine) is
    # usually a rare-word false positive, demoted to middle for the LLM to check.
    overrides = 0
    if thresholds.cosine_floor is not None:
        for i in list(accepted_set):
            if cosines[i] < thresholds.cosine_floor:
                accepted_set.discard(i)
                middle_set.add(i)
                overrides += 1
    if thresholds.cosine_ceiling is not None:
        for i in list(rejected_set):
            if cosines[i] > thresholds.cosine_ceiling:
                rejected_set.discard(i)
                middle_set.add(i)
                overrides += 1
    disagreement = overrides / n if n else 0.0
    if disagreement > 0.05:
        logger.warning(
            "embedding_triage: band/percentile disagreement %.1f%% (%d of %d items "
            "overridden by cosine_floor/cosine_ceiling).",
            disagreement * 100,
            overrides,
            n,
        )

    # Materialize ordered lists. Sort each bucket by descending hybrid so the
    # orchestrator can show "top N" without re-sorting.
    def _ordered(bucket: set[int]) -> list[int]:
        return sorted(bucket, key=lambda i: hybrid[i], reverse=True)

    return TriageBuckets(
        accepted=_ordered(accepted_set),
        rejected=_ordered(rejected_set),
        middle=_ordered(middle_set),
        cosines=cosines,
        bm25_scores=bm25_raw,
        hybrid_scores=hybrid,
        band_percentile_disagreement=disagreement,
    )
