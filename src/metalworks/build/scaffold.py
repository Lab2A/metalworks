"""Pillar D — the deterministic scaffold writer (the on-disk half).

``scaffold(spec, report, dest, *, base) -> list[Path]`` writes a build harness
the user's OWN coding agent then works inside — metalworks stops here, it does
not write product code. The harness is pure templating (no LLM, fully
reproducible) and carries the evidence forward so the downstream agent cannot
drift from the validated demand:

    dest/
      CLAUDE.md                      cite-or-die top rule + how to build
      docs/SPEC.md                   features / personas / pricing, each cited
      docs/EVIDENCE.md               frozen quote + permalink table (the spine)
      .claude/skills/                the build-pack (scaffold-startup, spec, cite-or-die)
      .claude/scripts/cite_or_die.py the lint that enforces no-cite-no-claim
      .claude/hooks.json             PostToolUse hook wiring the lint in
      .mcp.json                      points the agent back at metalworks' MCP server

``base`` is a stack HINT recorded in the SPEC (e.g. ``next-shipfast`` / ``empty``);
metalworks does NOT vendor boilerplate — the downstream agent picks the starter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.build._templates import (
    CITE_OR_DIE_LINT,
    HOOKS_JSON,
    MCP_JSON,
    SKILL_CITE_OR_DIE,
    SKILL_SCAFFOLD_STARTUP,
    SKILL_SPEC_FROM_REPORT,
)

if TYPE_CHECKING:
    from pathlib import Path

    from metalworks.contract import BuildSpec, DemandReport, EvidenceRecord


def _evidence_index(report: DemandReport) -> dict[str, EvidenceRecord]:
    return {rec.id: rec for rec in report.evidence}


def _cite_line(idx: dict[str, EvidenceRecord], evidence_id: str) -> str:
    rec = idx.get(evidence_id)
    if rec is None:
        return f"`{evidence_id}` (UNRESOLVED)"
    url = f" — <{rec.url}>" if rec.url else ""
    return f"`{evidence_id}`{url}"


def _md(text: str) -> str:
    """Neutralize LLM-derived text for inline markdown: no pipes, no newlines."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


# ── markdown renderers (deterministic) ───────────────────────────────────────


def render_evidence_md(spec: BuildSpec, report: DemandReport) -> str:
    """The frozen evidence table — every id the SPEC cites, with its verbatim text."""
    idx = _evidence_index(report)
    cited: list[str] = []
    seen: set[str] = set()
    for refs in (
        [r.evidence_id for f in spec.features for r in f.evidence],
        [r.evidence_id for p in spec.personas for r in p.evidence],
        [r.evidence_id for t in spec.pricing_tiers for r in t.evidence],
    ):
        for eid in refs:
            if eid not in seen:
                seen.add(eid)
                cited.append(eid)

    lines = [
        "# Evidence",
        "",
        "Every claim in `SPEC.md` traces to one of these verbatim Reddit voices.",
        "This table is FROZEN — do not edit it; it is the ground truth the build",
        f"must not drift from. Source report: `{report.report_id}` ({report.query}).",
        "",
        "| id | kind | verbatim | source |",
        "| --- | --- | --- | --- |",
    ]
    for eid in cited:
        rec = idx.get(eid)
        if rec is None:
            lines.append(f"| `{eid}` | ? | **UNRESOLVED** | — |")
            continue
        text = rec.text.replace("|", "\\|").replace("\n", " ").strip()
        if len(text) > 280:
            text = text[:277] + "…"
        url = f"[link]({rec.url})" if rec.url else "—"
        lines.append(f"| `{eid}` | {rec.kind} | {text} | {url} |")
    if not cited:
        lines.append("| — | — | _no cited evidence (partial spec)_ | — |")
    lines.append("")
    return "\n".join(lines)


def render_spec_md(spec: BuildSpec, report: DemandReport) -> str:
    """The build spec — features, personas, pricing, each carrying its citations."""
    idx = _evidence_index(report)
    lines = [
        f"# Build spec — {report.query}",
        "",
        f"- **Spec:** `{spec.spec_id}`  ·  **Report:** `{spec.report_id}`",
        f"- **Surface:** {spec.surface}  ·  **Stack hint:** {spec.stack}",
    ]
    if spec.partial:
        lines += ["", f"> ⚠️ **Partial spec.** {spec.caveat or 'Grounding was thin.'}"]
    lines += ["", "## Features — build in this order", ""]
    if spec.features:
        lines += [
            "Ordered by validated demand (strongest first). **Build #1 first — it is the "
            "spine the rest hangs off.** The order is grounded, not arbitrary: each number is "
            "the rank of the demand cluster behind the feature.",
            "",
        ]
        for i, f in enumerate(spec.features, start=1):
            cites = ", ".join(_cite_line(idx, r.evidence_id) for r in f.evidence) or "_(uncited)_"
            rank = (
                f"demand cluster #{f.source_cluster_rank}"
                if f.source_cluster_rank > 0
                else "demand rank unknown"
            )
            spine = " — the spine, build first" if i == 1 else ""
            lines += [
                f"### {i}. {_md(f.title)}  `{_md(f.feature_id)}`{spine}",
                "",
                _md(f.rationale),
                "",
                f"Why this rank: {rank}.  Evidence: {cites}",
                "",
            ]
    else:
        lines += [
            "_No evidence-grounded features survived. Do not build from this spec as-is._",
            "",
        ]
    lines += ["## Personas", ""]
    if spec.personas:
        for p in spec.personas:
            cites = ", ".join(_cite_line(idx, r.evidence_id) for r in p.evidence) or "_(uncited)_"
            lines += [f"- **{_md(p.name)}** — {_md(p.description)}  ({cites})"]
        lines.append("")
    else:
        lines += ["_No personas derived._", ""]
    lines += ["## Pricing", ""]
    if spec.pricing_tiers:
        for t in spec.pricing_tiers:
            price = f"{t.currency} {t.price:.0f}/mo" if t.price is not None else "unpriced"
            cites = ", ".join(_cite_line(idx, r.evidence_id) for r in t.evidence) or "_(uncited)_"
            lines += [f"- **{_md(t.name)}** — {price}. {_md(t.rationale)}  ({cites})"]
        lines.append("")
    else:
        lines += ["_No pricing evidence in the report — price this manually, do not guess._", ""]
    return "\n".join(lines)


def render_claude_md(spec: BuildSpec, report: DemandReport) -> str:
    """The downstream agent's top-level rule file — cite-or-die comes first."""
    return "\n".join(
        [
            f"# {report.query} — build harness",
            "",
            "This repo was scaffolded by **metalworks** from a validated Reddit demand",
            f"report (`{report.report_id}`). metalworks researched and specced; YOU build.",
            "",
            "## Rule 0 — cite or die",
            "",
            "Every feature, persona, and pricing claim in `docs/SPEC.md` traces to a",
            "verbatim Reddit voice in `docs/EVIDENCE.md`. When you add or change a",
            "user-facing claim (a feature, a headline, a price, a value prop), it MUST",
            "cite an evidence id from `docs/EVIDENCE.md`. No cite → do not ship the claim.",
            "`.claude/scripts/cite_or_die.py` enforces this on edited spec/copy files.",
            "This is enforced at the SPEC/feature/copy level — NOT per line of code.",
            "",
            "## How to build",
            "",
            "1. Read `docs/SPEC.md` (what to build) and `docs/EVIDENCE.md` (why — the proof).",
            f"2. Pick the `{spec.stack}` starter and stand up the {spec.surface} surface.",
            "3. Build the features in `SPEC.md` in the order given — it is the build order,",
            "   strongest validated demand first. Start with #1, the spine the rest hangs off.",
            "4. Keep `EVIDENCE.md` frozen. To add a feature, go back to metalworks and",
            "   re-run the research — do not invent demand here.",
            "",
            "The metalworks MCP server (`.mcp.json`) gives you the research tools to",
            "re-spec or pull more evidence without leaving the build.",
            "",
        ]
    )


# ── the writer ───────────────────────────────────────────────────────────────


def scaffold(
    spec: BuildSpec,
    report: DemandReport,
    dest: Path,
    *,
    base: str = "empty",
) -> list[Path]:
    """Write the build harness under ``dest``; return the paths written, in order.

    Deterministic and idempotent — re-running overwrites the generated files in
    place. ``base`` overrides the stack hint recorded in the harness docs.

    Raises ``ValueError`` if ``spec`` was not built from ``report`` (FK mismatch)
    — otherwise the frozen EVIDENCE.md would render the spec's refs against the
    wrong report and silently fill with UNRESOLVED rows.
    """
    if spec.report_id != report.report_id:
        raise ValueError(
            f"spec.report_id {spec.report_id!r} != report.report_id {report.report_id!r}; "
            "scaffold a spec only against the report it was built from."
        )
    if base and base != spec.stack:
        spec = spec.model_copy(update={"stack": base})

    files: dict[str, str] = {
        "CLAUDE.md": render_claude_md(spec, report),
        "docs/SPEC.md": render_spec_md(spec, report),
        "docs/EVIDENCE.md": render_evidence_md(spec, report),
        ".claude/skills/scaffold-startup/SKILL.md": SKILL_SCAFFOLD_STARTUP,
        ".claude/skills/spec-from-report/SKILL.md": SKILL_SPEC_FROM_REPORT,
        ".claude/skills/cite-or-die/SKILL.md": SKILL_CITE_OR_DIE,
        ".claude/scripts/cite_or_die.py": CITE_OR_DIE_LINT,
        ".claude/hooks.json": HOOKS_JSON,
        ".mcp.json": MCP_JSON,
    }
    written: list[Path] = []
    for rel, content in files.items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = content if content.endswith("\n") else content + "\n"
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
