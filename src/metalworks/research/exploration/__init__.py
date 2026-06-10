"""Three-bucket exploration triage.

The pipeline:

    embed_question + batch_embed_threads
                 │
                 ▼
    triage_by_embedding (hybrid cosine + BM25)
       ├─ top X%    → ACCEPTED
       ├─ bottom Y% → REJECTED
       └─ middle    → classify_middle (cheap LLM)
                            │
                            ▼
                build_exploration_report

Public surface:
- `run_exploration_triage(...)` — the one-call orchestrator most callers want.
- `triage_by_embedding(...)` / `classify_middle(...)` / `build_exploration_report(...)`
  for callers that need to plug in a different stage.
- `ExplorationItem`, `TriageBuckets`, `ClassifierVerdict` from research.types.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from metalworks.contract import ExplorationReport
from metalworks.research.exploration.corpus_shape import build_exploration_report
from metalworks.research.exploration.embedding_triage import triage_by_embedding
from metalworks.research.exploration.llm_classifier import classify_middle
from metalworks.research.types import ClassifierVerdict, ExplorationItem, TriageBuckets

if TYPE_CHECKING:
    from metalworks.contract import TriageThresholds
    from metalworks.research.deps import ResearchDeps

logger = logging.getLogger(__name__)

__all__ = [
    "ClassifierVerdict",
    "ExplorationItem",
    "TriageBuckets",
    "build_exploration_report",
    "classify_middle",
    "run_exploration_triage",
    "triage_by_embedding",
]


def run_exploration_triage(
    deps: ResearchDeps,
    *,
    question: str,
    relevance_rubric: str,
    items: list[ExplorationItem],
    thresholds: TriageThresholds,
) -> tuple[list[int], ExplorationReport]:
    """Run the full three-bucket triage and return (relevant_indices, report).

    `relevant_indices` is the list of `ExplorationItem.idx` values that survived
    triage — accepted by the hybrid score PLUS classifier-confirmed from the
    middle bucket. The orchestrator passes this set to the hydration step so
    only the surviving subset hits storage.

    The `report` is the ExplorationReport contract field, ready to drop into
    `DemandReport.corpus_shape`.
    """
    if not items:
        return [], ExplorationReport(
            threads_pulled=0,
            threads_auto_accepted=0,
            threads_auto_rejected=0,
            threads_classified=0,
            threads_relevant=0,
            threads_synthesized=0,
        )

    logger.info("exploration: triage start, %d items", len(items))
    buckets = triage_by_embedding(deps, question=question, items=items, thresholds=thresholds)
    logger.info(
        "exploration: hybrid triage — %d accepted / %d middle / %d rejected (disagreement=%.1f%%)",
        len(buckets.accepted),
        len(buckets.middle),
        len(buckets.rejected),
        (buckets.band_percentile_disagreement or 0.0) * 100,
    )

    verdicts = classify_middle(
        deps,
        question=question,
        relevance_rubric=relevance_rubric,
        items=items,
        middle_indices=buckets.middle,
    )
    logger.info(
        "exploration: middle classifier — %d/%d relevant",
        sum(1 for v in verdicts.values() if v.relevant),
        len(verdicts),
    )

    relevant_indices = list(buckets.accepted) + [idx for idx, v in verdicts.items() if v.relevant]
    # Preserve cosine-descending order in the output.
    relevant_indices.sort(key=lambda i: buckets.cosines[i], reverse=True)

    report = build_exploration_report(
        n_threads_pulled=len(items),
        buckets=buckets,
        middle_verdicts=verdicts,
    )
    return relevant_indices, report
