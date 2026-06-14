---
title: "Installation"
description: "Install metalworks, pick the right extras, and set a provider key. Most people want the [research] extra and one LLM key."
---

metalworks is a Python package (3.11+). The core install is tiny; heavier dependencies
(provider SDKs, the Reddit corpus, the MCP server) live behind **extras**, so you only
install what you use.

## Most people want this

```bash
pip install "metalworks[research]"
```

That gives you the full demand-research pipeline (the local corpus reader + the triage and
clustering it needs). Then set one provider key (next section) and you're ready.

## Pick your extras

Install only what your workflow needs — combine them like `"metalworks[research,reddit]"`.

| Extra | Install when you want to… |
| --- | --- |
| `research` | Run demand research and everything built on it (the common case). |
| `reddit` | Search Reddit, pull subreddit intel, or post replies (the engagement loop). |
| `arctic` | Read the historical Reddit corpus directly (a subset of `research`). |
| `mcp` | Run the MCP server (`metalworks mcp serve`). |
| `anthropic` / `openai` / `google` | Use that provider's models. (Any one is enough.) |
| `exa` / `tavily` | Add live web search to ground findings against the web. |
| `all` | Everything above. |

If you call something without its extra, metalworks tells you exactly what to install
instead of crashing.

## Set a provider key

The real pipeline needs one LLM provider. metalworks picks the provider automatically from
whichever key is in your environment (Anthropic → OpenAI → Google):

```bash
export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY, or GOOGLE_API_KEY / GEMINI_API_KEY
```

Want to use Google Vertex AI, a local model, or an OpenAI-compatible endpoint instead? See
[Configuration](/docs/configuration).

Live web search (optional, improves grounding) reads `EXA_API_KEY` or `TAVILY_API_KEY` if
present. Reddit posting needs `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — see
[Reddit engagement](/docs/reddit-engagement).

## Check your setup

```bash
metalworks doctor
```

This reports which extras are installed, which keys it found, where your data is stored,
and any connected Reddit accounts — so you know you're ready before you spend a token.

## No keys yet? Try the offline demo

```bash
metalworks quickstart
```

Runs the whole pipeline on a small bundled corpus with fake models — zero keys, zero
network — so you can see the output shape first. Needs the `[research]` extra. Next:
[Quickstart](/docs/quickstart).
