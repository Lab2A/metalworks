"""metalworks.build — Pillar D (Build stage).

Two halves, both evidence-grounded:

- :func:`build_spec_from_report` turns a finished report (+ positioning + surface)
  into a :class:`~metalworks.contract.build.BuildSpec`. Each feature is mapped to a
  real demand cluster and carries that cluster's verbatim quotes; an un-grounded
  feature is dropped (no-cite-no-feature).
- :func:`scaffold` writes a deterministic build harness (CLAUDE.md cite-or-die
  rule, docs/SPEC.md, frozen docs/EVIDENCE.md, the build-pack skills, the MCP
  wiring) the user's OWN coding agent then works inside. metalworks specs and
  scaffolds; it does not write product code.
"""

from metalworks.build.scaffold import (
    render_claude_md,
    render_evidence_md,
    render_spec_md,
    scaffold,
)
from metalworks.build.spec import build_spec_from_report

__all__ = [
    "build_spec_from_report",
    "render_claude_md",
    "render_evidence_md",
    "render_spec_md",
    "scaffold",
]
