"""Per-stage checkpoint envelopes + the load-or-compute seam for resume.

The research pipeline persists each stage's OUTPUT, keyed by ``run_id``, so a
failed run can re-run from the last incomplete stage instead of from zero. Each
stage gets an EXPLICIT, typed Pydantic envelope (never pickle): serialize via
``model_dump_json``, restore via ``model_validate_json``. Pydantic round-trips
the pipeline's intermediate dataclasses (:class:`ExplorationItem`,
:class:`SynthesisOutput`, :class:`MonthRef`) and the contract models losslessly,
so a resumed stage's output is byte-identical to the original compute.

The two checkpointer flavours enforce the fresh-run-unchanged invariant:

* :class:`NoopCheckpointer` (no ``run_id`` / no store) is a transparent
  pass-through — it calls ``compute()`` and returns its result with NO
  serialization round-trip, so a fresh run with no checkpoint store is
  byte-for-byte identical to today.
* :class:`Checkpointer` loads a stage's envelope if present (skip compute), else
  computes, SAVES the serialized form as a side effect, and returns the same
  in-memory object the compute produced — so a fresh run WITH a store yields the
  identical report (the save is invisible to the result), and only a resume
  reads back the deserialized form.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from metalworks.contract import (
    CorpusRecord,
    CrossReference,
    ExplorationReport,
    InsightCluster,
    SourceSelection,
    TargetSubreddit,
    WebFinding,
)
from metalworks.research.types import ExplorationItem, MonthRef, SynthesisOutput

if TYPE_CHECKING:
    from collections.abc import Callable

    from metalworks.stores.repos import CheckpointRepo

logger = logging.getLogger(__name__)

_E = TypeVar("_E", bound=BaseModel)


# ── Canonical stage order ───────────────────────────────────────────────────
# The 1-based index + total a progress poller renders ("stage 4/6: analyzing").
# Mirrors the ``deps.emit`` names the pipeline already emits, plus ``planning``
# (the non-determinism capture that runs BEFORE the first emit).
PIPELINE_STAGES: tuple[str, ...] = (
    "pulling",
    "triaging",
    "hydrating",
    "analyzing",
    "triangulating",
    "assembling",
)


# ── Per-stage envelopes ─────────────────────────────────────────────────────
# Each mirrors exactly the variables the restructured pipeline threads forward.


class PlanningCheckpoint(BaseModel):
    """The resolved, non-deterministic inputs — captured BEFORE ``pulling``.

    ``pick_target_subreddits`` and ``_maybe_select_sources`` are LLM /
    non-deterministic; checkpointing their RESOLVED outputs means a resume reuses
    the exact same corpus plan instead of re-rolling different subreddits, which
    would corrupt the run."""

    effective_subs: list[TargetSubreddit]
    selection: SourceSelection | None = None
    months: list[MonthRef]


class PullingCheckpoint(BaseModel):
    """The pulled corpus: triage items + the records keyed by id."""

    items: list[ExplorationItem]
    records_by_id: dict[str, CorpusRecord]


class TriagingCheckpoint(BaseModel):
    """The three-bucket triage result."""

    relevant_indices: list[int]
    exploration_report: ExplorationReport


class HydratingCheckpoint(BaseModel):
    """Hydration completion marker + the downstream bits it produced.

    The corpus writes (records + comments) are already durable + idempotent; this
    checkpoint just lets a resume SKIP the expensive per-link comment re-fetch."""

    post_ids: list[str]
    relevant_records: list[CorpusRecord]
    n_comments: int
    any_comment_layer: bool
    unit_source_ids: list[str]
    comments_error: str | None = None
    stage_errors_so_far: list[str]


class AnalyzingCheckpoint(BaseModel):
    """Synthesis ‖ web research (+ the in-place magnitude overlay)."""

    synthesis_out: SynthesisOutput
    web_findings: list[WebFinding]
    web_error: str | None = None
    magnitude_error: str | None = None


class TriangulatingCheckpoint(BaseModel):
    """Cross-stream confidence + must-address resolution."""

    cross_references: list[CrossReference]
    must_address_resolution: dict[str, str]
    ranked_clusters_final: list[InsightCluster]
    triangulation_error: str | None = None


# ── Checkpointer seam ───────────────────────────────────────────────────────


class NoopCheckpointer:
    """Transparent pass-through — no store, no run_id, no serialization.

    Guarantees a fresh run is byte-for-byte identical to the pre-checkpoint
    pipeline: it just runs ``compute()``."""

    def stage(self, name: str, model_cls: type[_E], compute: Callable[[], _E]) -> _E:
        return compute()


class Checkpointer:
    """Load-or-compute against a :class:`CheckpointRepo`, keyed by ``run_id``.

    Loads the stage envelope if present (skip compute); else computes, saves the
    serialized form (best-effort — a save failure degrades to no-checkpoint, never
    aborts the run), and returns the freshly computed object."""

    def __init__(self, repo: CheckpointRepo, run_id: str) -> None:
        self._repo = repo
        self._run_id = run_id

    def stage(self, name: str, model_cls: type[_E], compute: Callable[[], _E]) -> _E:
        raw = self._repo.get_checkpoint(self._run_id, name)
        if raw is not None:
            logger.info("checkpoint hit: run=%s stage=%s (skipping compute)", self._run_id, name)
            return model_cls.model_validate_json(raw)
        result = compute()
        try:
            self._repo.save_checkpoint(self._run_id, name, result.model_dump_json())
        except Exception as exc:  # best-effort: a write failure must not fail the run
            logger.debug("checkpoint save failed: run=%s stage=%s (%s)", self._run_id, name, exc)
        return result


def make_checkpointer(
    checkpoints: CheckpointRepo | None, run_id: str | None
) -> Checkpointer | NoopCheckpointer:
    """A :class:`Checkpointer` when BOTH a store and a run_id are present, else a
    :class:`NoopCheckpointer` (the transparent fresh-run path)."""
    if checkpoints is not None and run_id is not None:
        return Checkpointer(checkpoints, run_id)
    return NoopCheckpointer()


__all__ = [
    "PIPELINE_STAGES",
    "AnalyzingCheckpoint",
    "Checkpointer",
    "HydratingCheckpoint",
    "NoopCheckpointer",
    "PlanningCheckpoint",
    "PullingCheckpoint",
    "TriagingCheckpoint",
    "TriangulatingCheckpoint",
    "make_checkpointer",
]
