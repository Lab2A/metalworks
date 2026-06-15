---
title: "Quickstart"
description: "Install metalworks with one provider key and get a real demand report — a go/no-go plus the needs people actually voiced, each backed by a real Reddit quote — in about five minutes."
---

## 1. Install + set a key

Install metalworks with a provider SDK, then set **one** key — any provider works:

```bash
pip install "metalworks[research,openai]"     # or [research,google], [research,anthropic]
export OPENAI_API_KEY=...                      # or ANTHROPIC_API_KEY / GOOGLE_API_KEY / OPENROUTER_API_KEY
```

Embeddings need no separate key: a Google or OpenAI key is used when present, otherwise a
small local model (bundled with `[research]`) is downloaded once — so a single chat key,
Anthropic or OpenRouter included, is enough. See [Installation](/docs/installation).

## 2. Your first report

```python
from metalworks import Metalworks

mw = Metalworks()                  # provider inferred from the env key
research = mw.research(
    "an affordable, jitter-free focus supplement for developers",
    subreddits=["Nootropics", "Supplements"],   # omit to let it pick
)
report = research.demand

print(report.verdict)                           # the go / no-go summary
for cluster in report.ranked_clusters:
    print(cluster.claim, "—", cluster.distinct_author_count, "people")
    for quote in cluster.quotes:                # the real comments behind it
        print("  ", quote.source_url, "→", quote.text[:80])
```

Every cluster is a real demand theme, and every quote is a verbatim Reddit comment you can
open — nothing is invented. That report is the input to everything else: positioning, a
marketing site, a build spec, launch copy. See the [end-to-end walkthrough](/docs/walkthrough).

## 3. Or use the CLI / MCP / plugin

The same engine, language-agnostic:

```bash
# CLI
metalworks research run --question "an affordable focus supplement for developers"
metalworks research list                     # the report id every other command takes
metalworks build init <report-id> --dest ./my-startup

# MCP server (Claude Code, Cursor, any MCP host)
metalworks mcp serve                         # stdio; the data tools need no keys
```

Or install the Claude Code plugin and ask in chat:

```
/plugin marketplace add Lab2A/metalworks
/plugin install metalworks@lab2a
```

Then `/demand-report <your idea>`. Requires [uv](https://docs.astral.sh/uv/) on your PATH.

## Next

<CardGroup cols={2}>
  <Card title="Build a startup, end to end" href="/docs/walkthrough" />
  <Card title="Demand research" href="/docs/demand-research" />
  <Card title="Why you can trust the output" href="/docs/how-it-works" />
  <Card title="Configuration" href="/docs/configuration" />
</CardGroup>
