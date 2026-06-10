"""Background research-job runner for the MCP ``research_start`` family.

The research pipeline takes minutes — far longer than an MCP tool-call timeout.
So ``research_start`` spawns a daemon thread, persists status into a
:class:`~metalworks.stores.repos.RunRepo`, and returns a ``run_id`` immediately;
``research_status`` / ``research_result`` poll that store.

Production would use a real queue (a worker pool, a durable broker) rather than
an in-process daemon thread that dies with the server — this is the documented
zero-infra stand-in. State lives in the RunRepo, so a restarted server still
sees finished reports; only in-flight jobs are lost.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from metalworks.contract import RunSummary

if TYPE_CHECKING:
    from metalworks.contract import ResearchBrief
    from metalworks.research.deps import ResearchDeps
    from metalworks.stores.repos import RunRepo


def _now() -> datetime:
    return datetime.now(UTC)


def start_research_job(
    *,
    run_id: str,
    deps: ResearchDeps,
    brief: ResearchBrief,
    runs: RunRepo,
    per_sub_limit: int | None = None,
) -> threading.Thread:
    """Persist a ``queued`` run, spawn a daemon thread to run the pipeline, and
    return the thread (started). The thread updates the run's status to
    ``analyzing_relevant`` while running, then ``complete`` (saving the report)
    or ``failed`` (recording the error)."""
    runs.save_run(
        RunSummary(
            report_id=run_id,
            brief_id=brief.brief_id,
            query=brief.question,
            status="queued",
            created_at=_now(),
        )
    )

    def _run() -> None:
        # Import here so this module imports cleanly without the [research]
        # extra; the thread is only spawned once a real run is requested.
        from metalworks.research import run_research

        runs.save_run(
            RunSummary(
                report_id=run_id,
                brief_id=brief.brief_id,
                query=brief.question,
                status="analyzing_relevant",
                created_at=_now(),
            )
        )
        try:
            report = run_research(deps, brief=brief, per_sub_limit=per_sub_limit)
            runs.save_report(report)
            runs.save_run(
                RunSummary(
                    report_id=run_id,
                    brief_id=brief.brief_id,
                    query=brief.question,
                    status="complete",
                    total_distinct_authors=report.total_distinct_authors,
                    created_at=_now(),
                    generated_at=report.generated_at,
                    ready_at=_now(),
                )
            )
        except Exception as exc:  # the job boundary — surface, never crash
            runs.save_run(
                RunSummary(
                    report_id=run_id,
                    brief_id=brief.brief_id,
                    query=brief.question,
                    status="failed",
                    error=f"{type(exc).__name__}: {str(exc)[:300]}",
                    created_at=_now(),
                )
            )

    thread = threading.Thread(target=_run, name=f"metalworks-research-{run_id}", daemon=True)
    thread.start()
    return thread


__all__ = ["start_research_job"]
