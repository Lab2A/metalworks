---
title: "Quickstart"
description: "Run the zero-key offline demo, then a real report with a provider key, then the same thing from the CLI or MCP server."
---

## Install

```bash
pip install metalworks
```

Core stays lean (pydantic, httpx, typer, rich). Everything that pulls a provider
SDK or duckdb lives behind an extra, so you install only what you use.

## 1. The offline demo (no keys, no network)

```bash
pip install "metalworks[arctic]"      # duckdb, for the bundled local corpus
```

```python
from metalworks import Metalworks

report = Metalworks.demo().research(
    "Is there demand for a focus supplement?",
    subreddits=["Supplements"],
)
print(report.verdict)      # the synthesized go / no-go summary (or None)
for cluster in report.ranked_clusters:
    print(cluster.signal, cluster.distinct_author_count, cluster.claim)
```

`Metalworks.demo()` wires fake models and a small bundled Reddit corpus, so the
whole pipeline runs in seconds with **zero API keys and zero network**. It shows
you the output shape before you plug in a provider.

## 2. A real report

Set one provider key — metalworks infers the provider from whichever key is
present:

```bash
pip install "metalworks[google,research]"
export GOOGLE_API_KEY=...      # or ANTHROPIC_API_KEY / OPENAI_API_KEY
```

```python
from metalworks import Metalworks

mw = Metalworks()                       # provider inferred from the env key
report = mw.research(
    "Is there demand for a focus supplement aimed at developers?",
    subreddits=["Nootropics", "Supplements"],
)
for cluster in report.ranked_clusters:
    print(cluster.claim, "—", cluster.distinct_author_count, "distinct authors")
    for quote in cluster.quotes:
        print("  ", quote.permalink, "→", quote.text[:80])
```

Submissions come from the Hugging Face Arctic mirror; comments come from the live
Arctic Shift API. Set `HF_TOKEN` for windows longer than a few months. See
[Use your own corpus](/docs/how-to-custom-corpus) to run without Arctic Shift.

## 3. The same thing, language-agnostic

Not in Python? Every surface is also a CLI command and an MCP tool.

**CLI:**

```bash
metalworks quickstart                       # the offline demo
metalworks reddit search "focus supplement" --subreddit Supplements
metalworks research run brief.json
```

**MCP server** (for Claude Code, Cursor, or any MCP host):

```bash
metalworks mcp serve                        # stdio; zero-key tools need no keys
```

Or install the Claude Code plugin and just ask:

```
/plugin marketplace add Lab2A/metalworks
/plugin install metalworks@lab2a
```

Then `/demand-report <your idea>`. The data tools run with no API key; the
pipeline tools use whatever provider key is in your environment. Requires
[uv](https://docs.astral.sh/uv/) on your PATH.

## Next

<CardGroup cols={2}>
  <Card title="Core concepts" href="/docs/concepts" />
  <Card title="Building blocks" href="/docs/building-blocks" />
  <Card title="Demand Research guide" href="/docs/guide-demand-research" />
  <Card title="Model configuration" href="/docs/model-configuration" />
</CardGroup>
