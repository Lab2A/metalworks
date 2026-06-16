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
tool, whether it needs a key, its purpose, and params — is the [MCP tools
reference](/docs/mcp-tools). The split by key requirement:

- **Zero-key:** the data + deterministic tools — `compliance_lint`, `reddit_search_posts`,
  `reddit_get_post_comments`, `reddit_subreddit_info`, `reddit_subreddit_rules`,
  `arctic_list_months`, `arctic_pull_threads`, `corpus_stats`, `research_list_runs`,
  `research_get_report`, `channel_plan_build`, `content_plan_from_report`. No provider key
  needed (`[reddit]`/`[arctic]` extras where noted).
- **Key-gated:** anything that calls a model — `research_plan_brief`, `research_start` /
  `research_status` / `research_result`, `generate_reply`, `discovery_run`, and the
  synchronous report-derived tools (run after a stored report exists):
  `positioning_from_report`, `competitor_map_from_report`, `landscape_from_report`,
  `ideate_from_idea`, `ideate_from_report`, `assess_from_report`, `surface_recommend`,
  `ux_skeleton_build`, `site_render`, `launch_assets_build`, `build_spec`. The validation-loop
  orchestrator `validate_from_idea` also calls a model and runs a demand pull (slower).
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
