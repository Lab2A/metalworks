---
name: pr-ready
description: Pre-PR readiness check for the metalworks repo. Runs the full gate (ruff, ruff format --check, pyright, pytest) plus the contract-drift check CI does NOT run (gen_ts_types --check), then walks the can't-be-automated checks — surface parity (facade / CLI / MCP / skill), docs updated, CHANGELOG entry, additive contract — and reports a ✓/✗/? checklist with what's left. Use before opening a PR, or when the user asks "is this ready to ship", "pre-PR check", "/pr-ready", "check before PR", or "is everything in order".
---

# /pr-ready — pre-PR readiness check

You are checking whether the current branch is ready to open a PR against metalworks. Run the
automatable gates, inspect the diff for what CI can't check, and report a clean ✓ / ✗ / ? checklist
with what's left. metalworks is contract-first with four-surface parity (see `docs/architecture.md`) —
that's what most of these checks protect, so name the principle when something's off.

First, see what changed:

```bash
git fetch origin main -q
git diff --stat origin/main...HEAD    # committed changes; add `git status -s` for uncommitted
```

## 1. The gate — run each, report pass/fail with the failing output

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

These are exactly what CI runs (matrix py3.11–3.13 × bare/all; you're running one interpreter, which
is enough to catch real failures). A failure here blocks the PR — show the output and the fix.

## 2. Contract drift — the gate CI does NOT run

```bash
uv run python scripts/gen_ts_types.py --check
```

If it reports drift, the committed `ts/contract.ts` or `src/metalworks/contract/schema/*.json` are
stale. Run `uv run python scripts/gen_ts_types.py` and tell the contributor to commit the regenerated
files. This is the one gate CI misses, so it's the most common silent break.

## 3. Surface parity — inspect the diff (judgment, not a command)

If the diff adds or changes a **primitive** (a research verb / a user-facing capability), confirm it
moved on all four surfaces and flag any missing one:

- **Facade** — a method on `Metalworks` in `src/metalworks/client.py`.
- **CLI** — a `@research_app.command(...)` in `src/metalworks/cli/__init__.py` (+ a `_print_*` renderer).
- **MCP** — a body in `src/metalworks/mcp/tools.py`, an async wrapper in `src/metalworks/mcp/server.py`,
  **and** an entry in that file's `_TOOL_WRAPPERS` tuple (forgetting the tuple = the tool isn't registered).
- **Skill** — a `plugin/skills/<name>/SKILL.md`.

A new contract model also means: it's in `scripts/gen_ts_types.py` `MODELS` (+ `_SCHEMAS` if a
snapshot root) and exported from `src/metalworks/contract/__init__.py` + `__all__`. Removing a surface
is the same rule in reverse — all four gone, plus every doc reference.

Skip this item if the change is internal-only (no new/changed surface).

## 4. Docs + changelog parity

If a surface or a public contract field changed: is the relevant `docs/` page updated
(`cli.md` / `mcp-tools.md` / `python-sdk.md` / the capability page), and is there a `CHANGELOG.md`
entry under Added / Changed / Removed? Grep the diff'd surface name across `docs/` to catch stale
references.

## 5. Additive contract

New contract fields are defaulted (an old payload still validates — see the round-trip pattern in
`tests/test_contract_forks.py`); no public field removed or renamed without a deprecation note.

## 6. Release — only if this PR bumps the version

The three version sites agree — `pyproject.toml`, `src/metalworks/__init__.py` (`__version__`), and
`plugin/.claude-plugin/plugin.json` — and there's a `CHANGELOG.md` entry. (Tag `vX.Y.Z` after merge;
`release.yml` publishes to PyPI.)

## Report

Emit a tidy checklist:

- **✓** passed (gate, drift)
- **✗** failed — with the one-line fix
- **?** needs the contributor's eyes — parity, docs, additive-ness

End with one line: "ready to open the PR" or "N items left," and a `git diff --stat` recap. Don't
re-explain a principle when an item passes; only name it (and link `docs/architecture.md`) when
something's off.
