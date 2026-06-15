---
title: "Installation"
description: "Install metalworks, pick the right extras, and set a provider key. Most people want the [research] extra and one LLM key."
---

metalworks is a Python package (3.11+). The core install is tiny; heavier dependencies
(provider SDKs, the Reddit corpus, the MCP server) live behind **extras**, so you only
install what you use.

## Most people want this

```bash
pip install "metalworks[research,openai]"     # or [research,google]
```

That gives you the demand-research pipeline (the local corpus reader + the triage and
clustering it needs) **and** a provider SDK. The `[research]` extra alone has no provider
SDK — pair it with `openai`, `google`, or `anthropic`. Then set the matching key (next
section) and you're ready.

<Note>
Use **OpenAI** or **Google** for the simplest setup: one key covers both the chat model and
the embeddings the pipeline needs. **Anthropic** has no embeddings API, so an Anthropic key
must be paired with a Google or OpenAI key — see [Set a provider key](#set-a-provider-key).
</Note>

## Pick your extras

Install only what your workflow needs — combine them like `"metalworks[research,reddit]"`.

| Extra | Install when you want to… |
| --- | --- |
| `research` | Run demand research and everything built on it (the common case). |
| `reddit` | Search Reddit, pull subreddit intel, or post replies (the engagement loop). |
| `arctic` | Read the historical Reddit corpus directly (a subset of `research`). |
| `mcp` | Run the MCP server (`metalworks mcp serve`). |
| `anthropic` / `openai` / `google` | Use that provider's models. `openai` or `google` cover chat **and** embeddings; `anthropic` is chat-only (pair it with one of the others). |
| `exa` / `tavily` | Add live web search to ground findings against the web. |
| `all` | Everything above. |

If you call something without its extra, metalworks tells you exactly what to install
instead of crashing.

## Set a provider key

The pipeline needs two things: a **chat** model and an **embeddings** model (for the
clustering). metalworks resolves the chat provider from whichever key is present
(Anthropic → OpenAI → Google), and embeddings from a Google or OpenAI key.

The simplest setup is one key that covers both:

```bash
export OPENAI_API_KEY=...        # chat + embeddings
# or
export GOOGLE_API_KEY=...        # chat + embeddings  (GEMINI_API_KEY also works)
```

Using Anthropic for chat? Anthropic has no embeddings API, so set a Google or OpenAI key
**as well** — otherwise `research run` stops with a clear message telling you so:

```bash
export ANTHROPIC_API_KEY=...     # chat
export OPENAI_API_KEY=...        # embeddings (or GOOGLE_API_KEY)
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

Next: run your first real report in the [Quickstart](/docs/quickstart).
