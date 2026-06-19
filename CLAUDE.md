# CLAUDE.md — metalworks

Conventions for working on **metalworks** with Claude Code. [CONTRIBUTING.md](CONTRIBUTING.md) is the
full guide; [docs/architecture.md](docs/architecture.md) is the *why*.

## Before opening a PR

Run **`/pr-ready`** — it runs the gate, the contract-drift check CI doesn't, and walks the
parity / docs / changelog checks. The gate (what CI enforces):

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
```

## Non-negotiables

- **Contract-first, four-surface parity.** A primitive lives on the Python facade (`client.py`), the
  CLI (`cli/__init__.py`), the MCP server (`mcp/tools.py` + `server.py` + the `_TOOL_WRAPPERS` tuple),
  and a Claude Code skill (`plugin/skills/`). Change one → change all four, plus the docs.
- **Registry lockstep.** A new `contract` model goes in `scripts/gen_ts_types.py` `MODELS` and
  `contract/__init__.py` `__all__`; regenerate (`python scripts/gen_ts_types.py`) and **commit**
  `ts/contract.ts` + the `contract/schema/*.json`. CI doesn't run `--check` — `/pr-ready` does.
  Additive only below 1.0 (new fields defaulted; old payloads still validate).
- **No-cite-no-claim.** Every claim resolves to a real quote (`EvidenceRef` → `report.evidence`);
  un-grounded output is dropped, never invented.
- **Lean core, lazy extras.** Provider SDKs are lazy-imported inside the function that uses them,
  behind an extra; `import metalworks` stays free. No env reads or client construction at import time.
- **Offline tests.** `pytest-socket` blocks the network; use `FakeChatModel` / `FakeEmbedding` /
  `MemoryStores`. Mark real-network tests `network`.
- **Decisions are deterministic.** Verdicts / severity / demand bands are pure functions; the LLM
  writes only the human-facing rationale.

## House style

Match the surrounding code. Ruff (line length 100) and pyright strict over `src/` are the law; keep
new code green on both. Skills live in `plugin/skills/` (product) and `.claude/skills/` (repo dev
tools like `/pr-ready`).
