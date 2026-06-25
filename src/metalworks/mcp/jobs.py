"""Background research-job runner for the MCP ``research_start`` family.

The research pipeline takes minutes — far longer than an MCP tool-call timeout.
So ``research_start`` spawns a daemon thread, persists status into a
:class:`~metalworks.stores.repos.RunRepo`, and returns a ``run_id`` immediately;
``research_status`` / ``research_result`` poll that store.

Production would use a real queue (a worker pool, a durable broker) rather than
an in-process daemon thread that dies with the server — this is the documented
zero-infra stand-in. State lives in the RunRepo, so a restarted server still
sees finished reports; only in-flight jobs are lost.

Progress + resume:

* Each pipeline stage re-saves the run's :class:`RunSummary` with a fine-grained
  ``stage`` / ``stage_index`` / ``updated_at`` heartbeat (the coarse ``status``
  stays a running state), so a poller can tell grinding from hung.
* The pipeline checkpoints each stage's output keyed by ``run_id``; on failure the
  checkpoints are KEPT (so :func:`resume_research_job` re-runs from the last
  incomplete stage), and on completion they are cleared to free space.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from metalworks.contract import RunSummary
from metalworks.research.checkpoints import PIPELINE_STAGES

if TYPE_CHECKING:
    from metalworks.contract import ResearchBrief
    from metalworks.research.deps import ResearchDeps
    from metalworks.stores.repos import BriefRepo, CheckpointRepo, RunRepo


def _now() -> datetime:
    return datetime.now(UTC)


def _make_emit(
    *, run_id: str, brief: ResearchBrief, runs: RunRepo, created_at: datetime
) -> Callable[[str], None]:
    """A cheap, never-raising emit sink: re-save the run with a stage heartbeat.

    Keeps the coarse running ``status`` (``analyzing_relevant``) and overlays the
    fine-grained ``stage`` / ``stage_index`` / ``stage_total`` / ``updated_at``
    detail. Swallows any save error — a heartbeat must never break a real run."""
    total = len(PIPELINE_STAGES)

    def _emit(stage: str) -> None:
        try:
            idx = PIPELINE_STAGES.index(stage) + 1 if stage in PIPELINE_STAGES else None
            runs.save_run(
                RunSummary(
                    report_id=run_id,
                    brief_id=brief.brief_id,
                    query=brief.question,
                    status="analyzing_relevant",
                    stage=stage,
                    stage_index=idx,
                    stage_total=total,
                    created_at=created_at,
                    updated_at=_now(),
                )
            )
        except Exception:  # a heartbeat is best-effort — never raise into the pipeline
            return None

    return _emit


def _run_pipeline(
    *,
    run_id: str,
    deps: ResearchDeps,
    brief: ResearchBrief,
    runs: RunRepo,
    per_sub_limit: int | None,
    created_at: datetime,
) -> None:
    """The thread body shared by start + resume: run the pipeline keyed off
    ``run_id`` with checkpointing, updating the run's status as it goes.

    On success: save the report, mark ``complete``, and clear the run's
    checkpoints. On failure: mark ``failed`` and KEEP the checkpoints so a resume
    can pick up from the last incomplete stage."""
    from metalworks.research import run_research

    checkpoints = cast("CheckpointRepo", runs)
    deps.emit = _make_emit(run_id=run_id, brief=brief, runs=runs, created_at=created_at)
    runs.save_run(
        RunSummary(
            report_id=run_id,
            brief_id=brief.brief_id,
            query=brief.question,
            status="analyzing_relevant",
            stage_total=len(PIPELINE_STAGES),
            created_at=created_at,
            updated_at=_now(),
        )
    )
    try:
        report = run_research(
            deps,
            brief=brief,
            run_id=run_id,
            checkpoints=checkpoints,
            per_sub_limit=per_sub_limit,
        )
        runs.save_report(report)
        runs.save_run(
            RunSummary(
                report_id=run_id,
                brief_id=brief.brief_id,
                query=brief.question,
                status="complete",
                stage="assembling",
                stage_index=len(PIPELINE_STAGES),
                stage_total=len(PIPELINE_STAGES),
                total_distinct_authors=report.total_distinct_authors,
                created_at=created_at,
                generated_at=report.generated_at,
                ready_at=_now(),
                updated_at=_now(),
            )
        )
        # Free the per-stage checkpoint space — the run is done.
        with contextlib.suppress(Exception):
            checkpoints.clear_checkpoints(run_id)
    except Exception as exc:  # the job boundary — surface, never crash
        # Keep the checkpoints (do NOT clear) so resume can re-run from the last
        # incomplete stage rather than from zero.
        runs.save_run(
            RunSummary(
                report_id=run_id,
                brief_id=brief.brief_id,
                query=brief.question,
                status="failed",
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
                created_at=created_at,
                updated_at=_now(),
            )
        )


def start_research_job(
    *,
    run_id: str,
    deps: ResearchDeps,
    brief: ResearchBrief,
    runs: RunRepo,
    per_sub_limit: int | None = None,
) -> threading.Thread:
    """Persist a ``queued`` run + the brief, spawn a daemon thread to run the
    pipeline, and return the thread (started). The thread checkpoints each stage
    keyed by ``run_id`` and updates the run's status to ``analyzing_relevant``
    while running, then ``complete`` (saving the report) or ``failed``."""
    created_at = _now()
    # Persist the brief — resume needs it to rebuild the run.
    with contextlib.suppress(Exception):
        cast("BriefRepo", runs).save_brief(brief)
    runs.save_run(
        RunSummary(
            report_id=run_id,
            brief_id=brief.brief_id,
            query=brief.question,
            status="queued",
            stage_total=len(PIPELINE_STAGES),
            created_at=created_at,
        )
    )

    def _run() -> None:
        _run_pipeline(
            run_id=run_id,
            deps=deps,
            brief=brief,
            runs=runs,
            per_sub_limit=per_sub_limit,
            created_at=created_at,
        )

    thread = threading.Thread(target=_run, name=f"metalworks-research-{run_id}", daemon=True)
    thread.start()
    return thread


def resume_research_job(
    *,
    run_id: str,
    deps: ResearchDeps,
    brief: ResearchBrief,
    runs: RunRepo,
    per_sub_limit: int | None = None,
) -> threading.Thread:
    """Re-spawn the pipeline for an existing ``run_id``, reusing its checkpoints.

    Identical to :func:`start_research_job` except it does NOT reset ``created_at``
    (it preserves the original run's creation time) — the per-stage checkpoints in
    the store make the pipeline skip every already-completed stage."""
    existing = runs.get_run(run_id)
    created_at = existing.created_at if existing is not None else _now()
    with contextlib.suppress(Exception):
        cast("BriefRepo", runs).save_brief(brief)

    def _run() -> None:
        _run_pipeline(
            run_id=run_id,
            deps=deps,
            brief=brief,
            runs=runs,
            per_sub_limit=per_sub_limit,
            created_at=created_at,
        )

    thread = threading.Thread(target=_run, name=f"metalworks-research-resume-{run_id}", daemon=True)
    thread.start()
    return thread


__all__ = ["resume_research_job", "start_research_job"]
