"""Static templates for the build-pack that `scaffold()` writes into the user's repo.

These are NOT metalworks' own plugin skills — they are a second skill pack that
LANDS in the scaffolded project so the user's OWN Claude Code knows how to build
from the spec and is held to the cite-or-die rule. Kept as plain string constants
(no f-strings) so the writer stays deterministic and the content is reviewable.
"""

from __future__ import annotations

SKILL_SCAFFOLD_STARTUP = """\
---
name: scaffold-startup
description: Stand up the product in docs/SPEC.md, feature by feature, on the chosen stack.
---

# scaffold-startup

You are building the product metalworks specced from validated Reddit demand.

## Steps

1. Read `docs/SPEC.md` (the build spec) and `docs/EVIDENCE.md` (the proof). Note
   the **Surface** and **Stack hint** at the top of the spec.
2. If the repo is empty, scaffold the chosen stack (e.g. a Next.js app for a web
   surface). metalworks did NOT vendor boilerplate — you pick the starter.
3. Build the features in `docs/SPEC.md`, top to bottom. Each one delivers a
   demand that real users voiced — keep the rationale in view as you build.
4. For every user-facing string you write (headline, value prop, feature blurb,
   price), cite the backing evidence id from `docs/EVIDENCE.md`. The
   `cite-or-die` skill and the PostToolUse hook enforce this.
5. Do NOT invent features or audiences. If the spec is thin (`Partial spec`
   banner), go back to metalworks and re-run the research — see `spec-from-report`.

## What "done" looks like

Every feature in the spec exists, every claim on the page traces to `EVIDENCE.md`,
and nothing on the site asserts demand the report did not find.
"""

SKILL_SPEC_FROM_REPORT = """\
---
name: spec-from-report
description: Re-derive or extend the build spec from the metalworks report via MCP.
---

# spec-from-report

When the spec is thin, stale, or you need more evidence, go back to the source —
do not invent demand in the build repo.

## Steps

1. The metalworks MCP server is wired in `.mcp.json`. Use its research tools to
   load the source report (the `report_id` is at the top of `docs/SPEC.md`).
2. To regenerate the build spec, call the `build_spec` tool with that
   `report_id` (optionally a different `surface` or `stack`). It returns a fresh
   `BuildSpec` — every feature still grounded in a real demand cluster.
3. Re-run the scaffold writer (or apply the new spec by hand) so `docs/SPEC.md`
   and `docs/EVIDENCE.md` move together. EVIDENCE.md must always be the frozen
   ground truth for the claims in SPEC.md.
4. If you need MORE demand than the report holds, that is a research task, not a
   build task — run a new metalworks research pass; do not pad the spec.
"""

SKILL_CITE_OR_DIE = """\
---
name: cite-or-die
description: The no-cite-no-claim rule — every user-facing claim must trace to a frozen evidence id.
---

# cite-or-die

The whole point of a metalworks build is that it never asserts demand nobody
voiced. Enforced at the SPEC / feature / copy level — NOT per line of code.

## The rule

Every feature, persona, headline, value prop, and price in this repo must cite an
evidence id (`q:…` quote, `p:…` price, `w:…` web) that exists in
`docs/EVIDENCE.md`. A claim with no resolvable cite does not ship.

## The lint

`.claude/scripts/cite_or_die.py <file>...` checks a markdown/copy file:
- **Hard fail** (exit 2): a cited id that is NOT in `docs/EVIDENCE.md` (a dangling
  or invented citation).
- **Warning**: a feature/persona/pricing entry with no citation at all.

The PostToolUse hook in `.claude/hooks.json` runs it automatically when you edit
`docs/SPEC.md` or files under `docs/`. Run it yourself before shipping copy:

```bash
python .claude/scripts/cite_or_die.py docs/SPEC.md
```

## When it fails

Do not delete the cite to silence the lint. Either find the real supporting quote
in `docs/EVIDENCE.md`, or drop the claim. If the evidence genuinely isn't there,
the demand wasn't validated — go back to metalworks (`spec-from-report`).
"""

CITE_OR_DIE_LINT = '''\
#!/usr/bin/env python3
"""cite-or-die lint — every claim in a spec/copy file must cite frozen evidence.

Usage:
    python .claude/scripts/cite_or_die.py docs/SPEC.md [more.md ...]

Also runs as a Claude Code PostToolUse hook: with no argv it reads the hook JSON
from stdin and lints the edited file. Exit 2 = hard fail (dangling citation),
exit 0 = clean (uncited claims are warnings, not failures).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ID_RE = re.compile(r"[qpw]:[0-9a-f]{12}")
_CLAIM_RE = re.compile(r"^\\s*(###\\s+|[-*]\\s+\\*\\*)")  # feature headers / bullet claims


def _evidence_ids(root: Path) -> set[str]:
    ev = root / "docs" / "EVIDENCE.md"
    if not ev.exists():
        return set()
    return set(_ID_RE.findall(ev.read_text(encoding="utf-8")))


def _lint(target: Path, valid: set[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    text = target.read_text(encoding="utf-8")
    for cited in set(_ID_RE.findall(text)):
        if cited not in valid:
            errors.append(f"{target}: cites `{cited}` which is not in docs/EVIDENCE.md")
    for i, line in enumerate(text.splitlines(), 1):
        if _CLAIM_RE.match(line) and not _ID_RE.search(line):
            # Header-style claims cite on a following line; only flag inline bullets.
            if line.lstrip().startswith(("-", "*")):
                warnings.append(f"{target}:{i}: claim with no citation — {line.strip()[:80]}")
    return errors, warnings


def _targets_from_stdin() -> list[Path]:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return []
    fp = (payload.get("tool_input") or {}).get("file_path")
    return [Path(fp)] if fp else []


def main() -> int:
    args = [Path(a) for a in sys.argv[1:]] or _targets_from_stdin()
    targets = [p for p in args if p.suffix == ".md" and p.exists()]
    if not targets:
        return 0
    root = Path.cwd()
    valid = _evidence_ids(root)
    errors: list[str] = []
    warnings: list[str] = []
    for t in targets:
        e, w = _lint(t, valid)
        errors += e
        warnings += w
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)
    for e in errors:
        print(f"FAIL: {e}", file=sys.stderr)
    if errors:
        print("cite-or-die: dangling citation(s) — fix or drop the claim.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

HOOKS_JSON = """\
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/scripts/cite_or_die.py"
          }
        ]
      }
    ]
  }
}
"""

MCP_JSON = """\
{
  "mcpServers": {
    "metalworks": {
      "command": "python",
      "args": ["-m", "metalworks.mcp"],
      "description": "metalworks research tools — re-spec or pull evidence in the build."
    }
  }
}
"""
