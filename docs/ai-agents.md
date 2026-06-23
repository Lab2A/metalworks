---
title: "Using with AI agents"
description: "A dense map of metalworks for an LLM or coding agent integrating it — entry points, the MCP tool surface, the async job pattern, and the rules that matter."
---

There are two ways to integrate metalworks, depending on what kind of agent you are:

1. **Call the MCP tools** — if you are an LLM or Claude agent that works by making tool calls, run
   the MCP server (`metalworks mcp serve`) and call its tools. Start with the [MCP tools
   reference](/docs/mcp-tools).
2. **Import the Python SDK** — if you are a coding agent writing Python, import the `Metalworks`
   facade directly. Start with the [Python SDK](/docs/python-sdk).

This page is the dense map for either path: the entry point, the MCP tool surface, the async job
pattern, and the rules that matter. Read it, then skim `llms.txt` (the machine-readable index) and
the reference page for your path above.

## The one entry point

```python
from metalworks import Metalworks
mw = Metalworks()                       # provider inferred from env keys
```

- `mw.research(question, subreddits=[...]) -> Research` — demand research (the `DemandReport` is on `.demand`).
- `mw.reddit.search / subreddit / comments / rules / inbox / post` — Reddit surfaces.
- `mw.discovery.run / filter / generate` — discovery loop + building blocks.

Construction never raises; a `MissingKeyError` (with a `fix` string) surfaces only when a
call needs a key. Every error carries `error_code`, `message`, `fix`, and `docs_url` — relay
the `fix` verbatim.

## MCP tools (the language-agnostic surface)

Run `metalworks mcp serve` (stdio). **31 tools** are registered. The full table — every
tool, its tier, whether it needs a key, its purpose, and params — is the canonical [MCP tools
reference](/docs/mcp-tools); read it there rather than re-deriving the list here. In short:

- **Zero-key** data + deterministic tools (Reddit + Arctic corpus reads, run/report listing,
  `compliance_lint`, `content_plan_from_report`, ...) need no provider key.
- **Key-gated** tools call a model: demand research (`research_start` / `research_status` /
  `research_result`), `research_plan_brief`, the report-derived pillars (`positioning_from_report`,
  `landscape_from_report`, `assess_from_report`, design, `launch_assets_build`, `build_spec`, ...),
  `generate_reply`, `discovery_run`, and the `validate_from_idea` orchestrator.
- **Posting (the security boundary):** `reddit_post_comment` requires a `confirm_token`
  emitted by a `compliance_lint` pass over that exact text **and**
  `METALWORKS_ALLOW_POSTING=1`. There is no override.

## The async job pattern

Research and discovery take minutes. Do not call a blocking tool and wait — use
`research_start` → `research_status` → `research_result`. The synchronous Python
`mw.research(...)` is for scripts, not for tool-call timeouts.

## Rules that matter

1. **Posting is gated and irreversible.** A blocked draft is refused before it reaches
   Reddit; every attempt is logged to `~/.metalworks/post-log.jsonl`. Never try to route
   around the compliance gate.
2. **Authentic engagement only.** No fabricated personas or backstories. The
   `Persona.background` field must be real.
3. **Every claim is backed by a real quote.** Quotes are exact-matched against stored
   comments; web URLs come from citation metadata. Don't present model-authored text as a
   sourced quote.
4. **Pick models by ref.** `Metalworks(model="provider/model")`; point at any
   OpenAI-compatible endpoint with `base_url`. See [Configuration](/docs/configuration).

## Where to look

- [Python SDK](/docs/python-sdk) — the facade surface.
- [Extending metalworks](/docs/extending) — the swappable protocols + functions.
- [Protocols](/docs/protocols) — exact protocol shapes.
- `llms.txt` — the machine-readable index.
