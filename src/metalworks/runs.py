"""Persisting a research run to a project's ``runs/`` directory.

When ``Metalworks.research`` runs inside a ``.metalworks/`` project, the result
is written as committed files — ``research.json`` (the structured `Research`
bundle with stable evidence ids) and ``research.md`` (a human-readable summary)
— under ``.metalworks/runs/<report_id>/``, and a `RunRef` is appended to the
project manifest. Artifacts live where both the founder and their coding agent
can read them (files in the repo), not in a database blob.

This module owns the on-disk *shape* of a run. It does not run the pipeline; the
facade calls :func:`write_run` after a run completes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.project import RunRef

if TYPE_CHECKING:
    from metalworks.contract import Research
    from metalworks.contract.research import DemandReport, ReportDiff
    from metalworks.project import Project


def render_run_markdown(research: Research) -> str:
    """A readable Markdown summary of a research run — verdict, demand clusters
    with a representative quote + permalink, and web findings. Every claim that
    has a quote links back to the real source thread."""
    report: DemandReport = research.demand
    lines: list[str] = [f"# Research — {report.query}", ""]
    if report.verdict:
        lines += [f"**Verdict:** {report.verdict}", ""]
    lines += [
        f"- Threads analyzed: {report.total_threads}",
        f"- Distinct authors: {report.total_distinct_authors}",
        f"- Window: {report.date_range_start:%Y-%m-%d} → {report.date_range_end:%Y-%m-%d}",
    ]
    if report.partial:
        suffix = f": {report.caveat}" if report.caveat else ""
        lines.append(f"- ⚠️ Partial result{suffix}")
    lines.append("")

    if report.ranked_clusters:
        lines += ["## Top demand clusters", ""]
        for cluster in report.ranked_clusters[:8]:
            lines.append(f"### {cluster.rank}. {cluster.claim}")
            breadth_str = (
                f"{cluster.distinct_author_count} distinct authors"
                if cluster.breadth_unit == "authors"
                else f"{cluster.breadth_count} {cluster.breadth_unit}"
            )
            lines.append(
                f"_signal: {cluster.signal} · {breadth_str} · {cluster.mention_count} mentions_"
            )
            if cluster.quotes:
                quote = cluster.quotes[0]
                label = quote.source_name or quote.source
                lines += ["", f"> {quote.text}", ">", f"> — [{label}]({quote.source_url})"]
            lines.append("")

    if report.web_findings:
        lines += ["## Web findings", ""]
        lines += [f"- {w.claim} ([{w.source_title}]({w.source_url}))" for w in report.web_findings]
        lines.append("")

    lines += [
        "---",
        f"_report_id `{report.report_id}` · generated {report.generated_at:%Y-%m-%d %H:%M} UTC_",
        "",
    ]
    return "\n".join(lines)


def render_diff_markdown(diff: ReportDiff) -> str:
    """A readable Markdown summary of a refresh — what moved between versions."""
    lines: list[str] = [
        f"# Refresh diff — v{diff.from_version} → v{diff.to_version}",
        "",
        f"**{diff.summary}**",
        "",
        f"- Threads: {diff.total_threads_before} → {diff.total_threads_after} "
        f"({diff.total_threads_delta:+d})",
        f"- Distinct authors: {diff.total_distinct_authors_before} → "
        f"{diff.total_distinct_authors_after} ({diff.total_distinct_authors_delta:+d})",
        f"- Demand themes: {diff.cluster_count_before} → {diff.cluster_count_after}",
        "",
    ]
    if diff.clusters_added:
        lines += ["## New themes", ""] + [f"- {c}" for c in diff.clusters_added] + [""]
    if diff.clusters_dropped:
        lines += ["## Faded themes", ""] + [f"- {c}" for c in diff.clusters_dropped] + [""]
    if diff.clusters_changed:
        lines += ["## Shifted themes", ""]
        for d in diff.clusters_changed:
            lines.append(
                f"- {d.claim_after} — demand {d.demand_score_before:.2f} → "
                f"{d.demand_score_after:.2f} ({d.demand_score_delta:+.2f}), "
                f"authors {d.distinct_authors_delta:+d}"
            )
        lines.append("")
    lines += [
        "---",
        f"_lineage `{diff.lineage_id}` · {diff.from_report_id} → {diff.to_report_id}_",
        "",
    ]
    return "\n".join(lines)


def write_run(
    project: Project, research: Research, *, question: str, diff: ReportDiff | None = None
) -> RunRef:
    """Persist ``research`` under ``.metalworks/runs/<report_id>/`` and record it
    in the project manifest. Returns the `RunRef` that was appended.

    The run directory is keyed on ``report_id`` (unique per run); a re-run mints a
    new id and a new directory, so history is just the set of run dirs (and git).
    When ``diff`` is supplied (a refresh), ``diff.{json,md}`` are written
    alongside so the version-to-version change is a committed, readable artifact.
    """
    report = research.demand
    run_dir = project.runs_dir / report.report_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "research.json").write_text(
        research.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "research.md").write_text(render_run_markdown(research), encoding="utf-8")
    if diff is not None:
        (run_dir / "diff.json").write_text(diff.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (run_dir / "diff.md").write_text(render_diff_markdown(diff), encoding="utf-8")

    ref = RunRef(
        run_id=report.report_id,
        report_id=report.report_id,
        question=question,
        created_at=report.generated_at,
        lineage_id=report.effective_lineage_id,
        version=report.version,
        parent_report_id=report.parent_report_id,
    )
    manifest = project.read_manifest()
    manifest.runs.append(ref)
    project.write_manifest(manifest)
    return ref


__all__ = ["render_run_markdown", "write_run"]
