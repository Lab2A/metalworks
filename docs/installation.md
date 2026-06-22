---
title: "Installation"
description: "Install metalworks, pick the right extras, and set one provider key. Any single LLM key works — embeddings default to a local model, no second key required."
---

metalworks is a Python package (3.11+). The core install is tiny; heavier dependencies
(provider SDKs, the Reddit corpus, the MCP server) live behind **extras**, so you only
install what you use.

## Most people want this

```bash
pip install "metalworks[research,openai]"     # or [research,google], or [research,anthropic]
```

That gives you the demand-research pipeline (the local corpus reader + the triage and
clustering it needs) **and** a provider SDK. The `[research]` extra has no provider SDK on
its own — pair it with `openai`, `google`, or `anthropic`. Then set that one key (next
section) and you're ready.

<Note>
**One key is enough — whichever provider you use.** Embeddings default to a small local
model (no API key, downloaded once), so a single chat key gets you a full run. If you have
an OpenAI or Google key, metalworks uses *its* embeddings automatically (higher quality, no
download). Either way, you never need a second key.
</Note>

## Pick your extras

Install only what your workflow needs — combine them like `"metalworks[research,reddit]"`.

| Extra | Install when you want to… |
| --- | --- |
| `research` | Run demand research and everything built on it (the common case). Bundles the local embedding model. |
| `reddit` | Search Reddit, pull subreddit intel, or post replies (the engagement loop). |
| `arctic` | Read the historical Reddit corpus directly (a subset of `research`). |
| `mcp` | Run the MCP server (`metalworks mcp serve`). |
| `anthropic` / `openai` / `google` | Use that provider's models. Any one is enough (see the note above). |
| `exa` / `tavily` | Add live web search to ground findings against the web. |
| `browser` | An owned headless Chromium for competitor teardowns and design review. **One post-install step:** `metalworks browser install` (downloads Chromium). On a server where Chromium is painful, set `FIRECRAWL_API_KEY` to render without a local browser. |
| `all` | Everything above. |

If you call something without its extra, metalworks tells you exactly what to install
instead of crashing.

## Set a provider key

Set the key for the provider you installed — metalworks resolves the chat provider from
whichever key is present (Anthropic → OpenAI → Google → OpenRouter):

```bash
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY, GOOGLE_API_KEY / GEMINI_API_KEY,
                                 # or OPENROUTER_API_KEY (reaches 200+ models)
```

**Embeddings need no separate key.** The pipeline needs an embeddings model for clustering;
with no Google/OpenAI key it uses a local model (`fastembed`, bundled with `[research]`),
downloaded once on first use:

| Your key | Chat | Embeddings |
| --- | --- | --- |
| OpenAI | OpenAI | OpenAI (no download) |
| Google / Gemini | Google (native web grounding) | Google (no download) |
| Anthropic | Anthropic | **local model** (one-time download) |
| OpenRouter | any model via OpenRouter | **local model** (one-time download) |

Pre-download the local model so your first run isn't blocked on it:

```bash
metalworks models warm
```

Want Google Vertex AI, a local LLM, or any OpenAI-compatible endpoint? See
[Configuration](/docs/configuration). Live web search (optional, improves grounding) reads
`EXA_API_KEY` or `TAVILY_API_KEY` if present. Reddit posting needs `REDDIT_CLIENT_ID` /
`REDDIT_CLIENT_SECRET` — see [Reddit engagement](/docs/reddit-engagement).

## Check your setup

```bash
metalworks doctor
```

Reports installed extras, the keys it found, the **resolved chat and embedding models**, the
store path, connected Reddit accounts, and actionable hints (e.g. "key set but extra missing
→ `pip install …`") — so you know you're ready before you spend a token. `metalworks models
list` shows the same model resolution plus a provider reachability matrix.

Next: run your first real report in the [Quickstart](/docs/quickstart).
