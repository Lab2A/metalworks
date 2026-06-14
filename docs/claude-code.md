---
title: "Claude Code plugin"
description: "Run the whole metalworks workflow from inside Claude Code with slash commands — validate an idea, get positioning, scaffold a build, draft launch copy, all without leaving your editor."
---

The metalworks plugin brings the full workflow into Claude Code as slash commands. Ask
`/demand-report can I sell a focus supplement to developers?` and you get the same grounded
report you'd get from the library — every claim linked to a real Reddit thread — right in
your chat, then keep going (`/position-wedge`, `/build-spec`, `/launch-kit`) from there.

## Install

```
/plugin marketplace add Lab2A/metalworks
/plugin install metalworks@lab2a
```

You need [uv](https://docs.astral.sh/uv/) on your PATH — the plugin runs the metalworks MCP
server via `uvx`, which installs it into an isolated environment on first launch (give it a
minute the first time). The data commands work with no API key; the research commands use
whatever provider key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY`) is in your
environment.

## The commands

Each command runs one step of the [end-to-end workflow](/docs/walkthrough). Start with
`/demand-report`; the rest build on the report it produces.

**Research**
- `/demand-report <idea>` — is there real demand? A go/no-go plus the needs people voiced, each backed by quotes.
- `/position-wedge` — your positioning: who it's for and why it's different.
- `/competitor-map` — the rivals to beat, each with a real, cited gap.

**Design**
- `/surface-and-ux` — what to build (web, mobile, CLI, …) and the screens you need.
- `/generate-site` — a marketing site whose every line is a verbatim real quote.

**Build**
- `/build-spec` — a feature spec + a project scaffold for Claude Code to build inside.

**Launch**
- `/launch-kit` — Product Hunt / Show HN / X drafts, each claim backed by a quote (it never posts).

**Grow**
- `/content-plan` — a content/SEO plan, one page per real demand cluster.
- `/find-threads <product>` — live Reddit threads worth joining.
- `/draft-reply <thread>` — an honest, disclosed reply, checked for compliance before you post.
- `/subreddit-intel <r/name>` — a community brief before you participate.

## Same engine, your choice of surface

The plugin, the [Python SDK](/docs/python-sdk), the [CLI](/docs/cli), and the
[MCP server](/docs/mcp-tools) all run the same engine and produce the same results — pick
whichever fits how you work. Driving metalworks from your own agent instead of the plugin?
See [using with AI agents](/docs/ai-agents).
